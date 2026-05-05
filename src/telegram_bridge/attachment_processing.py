import logging
import os
import re
import subprocess
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

from telegram_bridge.channel_adapter import ChannelAdapter
from telegram_bridge.handler_models import DocumentPayload
from telegram_bridge.media import TelegramFileDownloadSpec, download_telegram_file_to_temp
from telegram_bridge.runtime_profile import is_whatsapp_channel
from telegram_bridge.state_store import State
from telegram_bridge.structured_logging import emit_event

def download_photo_to_temp(
    client: ChannelAdapter,
    config,
    photo_file_id: str,
) -> str:
    spec = TelegramFileDownloadSpec(
        file_id=photo_file_id,
        max_bytes=config.max_image_bytes,
        size_label="Image",
        temp_prefix="telegram-bridge-photo-",
        default_suffix=".jpg",
        too_large_label="Image",
    )
    tmp_path, _ = download_telegram_file_to_temp(client, spec)
    return tmp_path

def download_voice_to_temp(
    client: ChannelAdapter,
    config,
    voice_file_id: str,
) -> str:
    spec = TelegramFileDownloadSpec(
        file_id=voice_file_id,
        max_bytes=config.max_voice_bytes,
        size_label="Voice file",
        temp_prefix="telegram-bridge-voice-",
        default_suffix=".ogg",
        too_large_label="Voice file",
    )
    tmp_path, _ = download_telegram_file_to_temp(client, spec)
    return tmp_path

def download_document_to_temp(
    client: ChannelAdapter,
    config,
    document: DocumentPayload,
) -> tuple[str, int]:
    spec = TelegramFileDownloadSpec(
        file_id=document.file_id,
        max_bytes=config.max_document_bytes,
        size_label="File",
        temp_prefix="telegram-bridge-file-",
        default_suffix=".bin",
        too_large_label="File",
        suffix_hint=document.file_name,
    )
    return download_telegram_file_to_temp(client, spec)

def build_document_analysis_context(
    document_path: str,
    document: DocumentPayload,
    size_bytes: int,
) -> str:
    return (
        "Attached file context:\n"
        f"- Local path: {document_path}\n"
        f"- Original filename: {document.file_name}\n"
        f"- MIME type: {document.mime_type}\n"
        f"- Size bytes: {size_bytes}\n\n"
        "Read and analyze the file from the local path."
    )

def build_archived_attachment_summary_context(media_label: str, summary: str) -> str:
    clean_summary = (summary or "").strip()
    if not clean_summary:
        return ""
    return (
        f"Archived {media_label} context:\n"
        f"- Fresh {media_label} bytes are no longer available.\n"
        f"- Prior analysis summary: {clean_summary}"
    )

def archive_media_path(
    attachment_store,
    *,
    channel_name: str,
    file_id: str,
    media_kind: str,
    source_path: str,
    file_name: str = "",
    mime_type: str = "",
) -> Optional[str]:
    if attachment_store is None:
        return None
    try:
        record = attachment_store.remember_file(
            channel=channel_name,
            file_id=file_id,
            media_kind=media_kind,
            source_path=source_path,
            file_name=file_name,
            mime_type=mime_type,
        )
    except Exception:
        logging.exception(
            "Failed to archive inbound %s for channel=%s file_id=%s",
            media_kind,
            channel_name,
            file_id,
        )
        return None
    return record.local_path

def resolve_attachment_binary_or_summary(
    attachment_store,
    *,
    channel_name: str,
    file_id: str,
    media_label: str,
) -> tuple[Optional[str], str]:
    if attachment_store is None:
        return None, ""
    record = attachment_store.get_record(channel_name, file_id)
    if record is not None:
        return record.local_path, ""
    summary = attachment_store.get_summary(channel_name, file_id)
    if not summary:
        return None, ""
    return None, build_archived_attachment_summary_context(media_label, summary)

def build_voice_transcribe_command(cmd_template: List[str], voice_path: str) -> List[str]:
    cmd: List[str] = []
    used_placeholder = False
    for arg in cmd_template:
        if "{file}" in arg:
            cmd.append(arg.replace("{file}", voice_path))
            used_placeholder = True
        else:
            cmd.append(arg)
    if not used_placeholder:
        cmd.append(voice_path)
    return cmd

def parse_voice_confidence(stderr_text: str) -> Optional[float]:
    matches = re.findall(r"VOICE_CONFIDENCE=([0-9]*\.?[0-9]+)", stderr_text or "")
    if not matches:
        return None
    try:
        value = float(matches[-1])
    except ValueError:
        return None
    return max(0.0, min(1.0, value))

def apply_voice_alias_replacements(
    transcript: str,
    replacements: List[Tuple[str, str]],
) -> Tuple[str, bool]:
    if not replacements:
        return transcript, False

    updated = transcript
    changed = False
    for source, target in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
        source_value = source.strip()
        target_value = target.strip()
        if not source_value or not target_value:
            continue
        pattern = rf"(?<!\w){re.escape(source_value)}(?!\w)"
        replaced = re.sub(pattern, target_value, updated, flags=re.IGNORECASE)
        if replaced != updated:
            updated = replaced
            changed = True
    return updated, changed

def build_active_voice_alias_replacements(
    config,
    state: Optional[State] = None,
) -> List[Tuple[str, str]]:
    merged: Dict[str, Tuple[str, str]] = {}
    for source, target in getattr(config, "voice_alias_replacements", []):
        source_value = source.strip()
        target_value = target.strip()
        if not source_value or not target_value:
            continue
        merged[source_value.casefold()] = (source_value, target_value)

    if state is not None:
        learning_store = getattr(state, "voice_alias_learning_store", None)
        if learning_store is not None:
            try:
                approved = learning_store.get_approved_replacements()
            except Exception:
                logging.exception("Failed to load approved learned voice aliases")
                approved = []
            for source, target in approved:
                source_value = source.strip()
                target_value = target.strip()
                if not source_value or not target_value:
                    continue
                merged[source_value.casefold()] = (source_value, target_value)
    return list(merged.values())

def build_low_confidence_voice_message(
    config,
    transcript: str,
    confidence: float,
) -> str:
    _ = transcript
    _ = confidence
    message = getattr(config, "voice_low_confidence_message", "")
    return (message or "Voice transcript confidence is low, resend").strip()

def build_voice_alias_suggestions_message(suggestions: List[object]) -> Optional[str]:
    if not suggestions:
        return None
    lines = [
        "Voice correction learning suggestion(s):",
    ]
    for suggestion in suggestions:
        suggestion_id = getattr(suggestion, "suggestion_id", None)
        source = str(getattr(suggestion, "source", "")).strip()
        target = str(getattr(suggestion, "target", "")).strip()
        count = getattr(suggestion, "count", None)
        if not isinstance(suggestion_id, int) or not source or not target:
            continue
        count_text = f" (seen {count}x)" if isinstance(count, int) else ""
        lines.append(f"- #{suggestion_id}: `{source}` => `{target}`{count_text}")
    if len(lines) == 1:
        return None
    lines.append("Approve with: `/voice-alias approve <id>`")
    lines.append("Reject with: `/voice-alias reject <id>`")
    return "\n".join(lines)

def suggest_required_prefix_alias_candidate(
    transcript: str,
    required_prefixes: List[str],
    *,
    ignore_case: bool,
    min_similarity: float = 0.5,
) -> Optional[Tuple[str, str, float]]:
    words = transcript.strip().split()
    if not words or not required_prefixes:
        return None

    best_source = ""
    best_target = ""
    best_similarity = 0.0
    for required_prefix in required_prefixes:
        normalized_prefix = " ".join(required_prefix.strip().split())
        if not normalized_prefix:
            continue
        prefix_words = normalized_prefix.split()
        if len(words) < len(prefix_words):
            continue
        source_candidate = " ".join(words[: len(prefix_words)])
        source_probe = source_candidate.casefold() if ignore_case else source_candidate
        target_probe = normalized_prefix.casefold() if ignore_case else normalized_prefix
        if source_probe == target_probe:
            continue
        similarity = SequenceMatcher(None, source_probe, target_probe).ratio()
        if similarity > best_similarity:
            best_source = source_candidate
            best_target = normalized_prefix
            best_similarity = similarity

    if not best_source:
        return None
    if best_similarity < min_similarity:
        return None
    return best_source, best_target, best_similarity

def maybe_suggest_voice_prefix_alias(
    state: State,
    config,
    client: ChannelAdapter,
    chat_id: int,
    message_id: Optional[int],
    transcript: str,
) -> None:
    if not is_whatsapp_channel(client):
        return
    learning_store = getattr(state, "voice_alias_learning_store", None)
    if learning_store is None or not hasattr(learning_store, "observe_pair"):
        return

    candidate = suggest_required_prefix_alias_candidate(
        transcript,
        list(getattr(config, "required_prefixes", [])),
        ignore_case=bool(getattr(config, "required_prefix_ignore_case", True)),
    )
    if candidate is None:
        return
    source, target, similarity = candidate

    for active_source, active_target in build_active_voice_alias_replacements(config, state):
        if source.casefold() == active_source.casefold() and target.casefold() == active_target.casefold():
            return

    try:
        created = learning_store.observe_pair(source=source, target=target)
    except Exception:
        logging.exception(
            "Failed to register prefix alias suggestion for chat_id=%s source=%r target=%r",
            chat_id,
            source,
            target,
        )
        return

    emit_event(
        "bridge.voice_alias_prefix_observed",
        fields={
            "chat_id": chat_id,
            "message_id": message_id,
            "source": source,
            "target": target,
            "similarity": round(similarity, 3),
            "suggestions_created": len(created),
        },
    )
    suggestion_text = build_voice_alias_suggestions_message(created)
    if suggestion_text:
        client.send_message(
            chat_id,
            suggestion_text,
            reply_to_message_id=message_id,
        )

def transcribe_voice(config, voice_path: str) -> Tuple[str, Optional[float]]:
    if not config.voice_transcribe_cmd:
        raise RuntimeError("Voice transcription is not configured")

    cmd = build_voice_transcribe_command(config.voice_transcribe_cmd, voice_path)
    logging.info("Running voice transcription command: %s", cmd)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=config.voice_transcribe_timeout_seconds,
        check=False,
    )
    if result.returncode != 0:
        logging.error(
            "Voice transcription failed returncode=%s stderr=%r",
            result.returncode,
            (result.stderr or "")[-1000:],
        )
        raise RuntimeError("Voice transcription failed")

    transcript = (result.stdout or "").strip()
    if not transcript:
        raise ValueError("Voice transcription output was empty")
    return transcript, parse_voice_confidence(result.stderr or "")
