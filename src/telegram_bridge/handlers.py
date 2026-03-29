import logging
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import datetime as dt
import copy
from difflib import SequenceMatcher
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

try:
    from .auth_state import refresh_runtime_auth_fingerprint
    from .conversation_scope import (
        ConversationScope,
        build_telegram_scope_key,
        parse_telegram_scope_key,
        scope_from_message,
    )
    from .executor import (
        ExecutorCancelledError,
        ExecutorProgressEvent,
        parse_executor_output,
        should_reset_thread_after_resume_failure,
    )
    from .channel_adapter import ChannelAdapter
    from .diary_store import (
        DiaryEntry,
        DiaryPhoto,
        append_day_entry,
        copy_photo_to_day_assets,
        diary_day_docx_path,
        diary_day_remote_docx_path,
        diary_mode_enabled,
        diary_nextcloud_enabled,
        diary_timezone,
        read_day_entries,
        upload_to_nextcloud,
    )
    from .engine_adapter import CodexEngineAdapter, EngineAdapter
    from .media import TelegramFileDownloadSpec, download_telegram_file_to_temp
    from .memory_engine import (
        MemoryEngine,
        TurnContext,
        build_memory_help_lines,
        handle_memory_command,
        handle_natural_language_memory_query,
    )
    from .memory_scope import (
        resolve_memory_conversation_key,
        resolve_shared_memory_archive_key,
    )
    from .runtime_profile import (
        BROWSER_BRAIN_KEYWORD_HELP_MESSAGE,
        HA_KEYWORD_HELP_MESSAGE,
        HELP_COMMAND_ALIASES,
        NEXTCLOUD_KEYWORD_HELP_MESSAGE,
        PREFIX_HELP_MESSAGE,
        RETRY_WITH_NEW_SESSION_PHASE,
        SERVER3_KEYWORD_HELP_MESSAGE,
        WHATSAPP_REPLY_PREFIX,
        WHATSAPP_REPLY_PREFIX_RE,
        apply_outbound_reply_prefix,
        assistant_label,
        build_repo_root,
        build_browser_brain_keyword_prompt,
        build_browser_brain_routing_script_allowlist,
        build_ha_keyword_prompt,
        build_ha_routing_script_allowlist,
        build_nextcloud_keyword_prompt,
        build_nextcloud_routing_script_allowlist,
        build_server3_keyword_prompt,
        build_server3_routing_script_allowlist,
        command_bypasses_required_prefix,
        extract_browser_brain_keyword_request,
        extract_ha_keyword_request,
        extract_nextcloud_keyword_request,
        extract_server3_keyword_request,
        is_signal_channel,
        is_whatsapp_channel,
        resume_retry_phase,
        start_command_message,
    )
    from .runtime_routing import apply_priority_keyword_routing, apply_required_prefix_gate
    from .session_manager import (
        ensure_chat_worker_session,
        finalize_chat_work,
        is_rate_limited,
        mark_busy,
        request_safe_restart,
        trigger_restart_async,
    )
    from .state_store import PendingDiaryBatch, State, StateRepository
    from .structured_logging import emit_event
    from .transport import TELEGRAM_CAPTION_LIMIT, TELEGRAM_LIMIT
except ImportError:
    from auth_state import refresh_runtime_auth_fingerprint
    from conversation_scope import (
        ConversationScope,
        build_telegram_scope_key,
        parse_telegram_scope_key,
        scope_from_message,
    )
    from executor import (
        ExecutorCancelledError,
        ExecutorProgressEvent,
        parse_executor_output,
        should_reset_thread_after_resume_failure,
    )
    from channel_adapter import ChannelAdapter
    from diary_store import (
        DiaryEntry,
        DiaryPhoto,
        append_day_entry,
        copy_photo_to_day_assets,
        diary_day_docx_path,
        diary_day_remote_docx_path,
        diary_mode_enabled,
        diary_nextcloud_enabled,
        diary_timezone,
        read_day_entries,
        upload_to_nextcloud,
    )
    from engine_adapter import CodexEngineAdapter, EngineAdapter
    from media import TelegramFileDownloadSpec, download_telegram_file_to_temp
    from memory_engine import (
        MemoryEngine,
        TurnContext,
        build_memory_help_lines,
        handle_memory_command,
        handle_natural_language_memory_query,
    )
    from memory_scope import (
        resolve_memory_conversation_key,
        resolve_shared_memory_archive_key,
    )
    from runtime_profile import (
        BROWSER_BRAIN_KEYWORD_HELP_MESSAGE,
        HA_KEYWORD_HELP_MESSAGE,
        HELP_COMMAND_ALIASES,
        NEXTCLOUD_KEYWORD_HELP_MESSAGE,
        PREFIX_HELP_MESSAGE,
        RETRY_WITH_NEW_SESSION_PHASE,
        SERVER3_KEYWORD_HELP_MESSAGE,
        WHATSAPP_REPLY_PREFIX,
        WHATSAPP_REPLY_PREFIX_RE,
        apply_outbound_reply_prefix,
        assistant_label,
        build_repo_root,
        build_browser_brain_keyword_prompt,
        build_browser_brain_routing_script_allowlist,
        build_ha_keyword_prompt,
        build_ha_routing_script_allowlist,
        build_nextcloud_keyword_prompt,
        build_nextcloud_routing_script_allowlist,
        build_server3_keyword_prompt,
        build_server3_routing_script_allowlist,
        command_bypasses_required_prefix,
        extract_browser_brain_keyword_request,
        extract_ha_keyword_request,
        extract_nextcloud_keyword_request,
        extract_server3_keyword_request,
        is_signal_channel,
        is_whatsapp_channel,
        resume_retry_phase,
        start_command_message,
    )
    from runtime_routing import apply_priority_keyword_routing, apply_required_prefix_gate
    from session_manager import (
        ensure_chat_worker_session,
        finalize_chat_work,
        is_rate_limited,
        mark_busy,
        request_safe_restart,
        trigger_restart_async,
    )
    from state_store import PendingDiaryBatch, State, StateRepository
    from structured_logging import emit_event
    from transport import TELEGRAM_CAPTION_LIMIT, TELEGRAM_LIMIT

PROGRESS_TYPING_INTERVAL_SECONDS = 4
PROGRESS_EDIT_MIN_INTERVAL_SECONDS = 6
PROGRESS_HEARTBEAT_EDIT_SECONDS = 30
MEDIA_DIRECTIVE_TAG_RE = re.compile(r"\[\[\s*media\s*:\s*(?P<value>.+?)\s*\]\]", re.IGNORECASE)
MEDIA_DIRECTIVE_LINE_RE = re.compile(r"(?im)^\s*media\s*:\s*(?P<value>.+?)\s*$")
AUDIO_AS_VOICE_TAG_RE = re.compile(r"\[\[\s*audio_as_voice\s*\]\]", re.IGNORECASE)
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
AUDIO_EXTENSIONS = {".ogg", ".oga", ".opus", ".mp3", ".m4a", ".aac", ".wav", ".flac"}
VOICE_COMPATIBLE_EXTENSIONS = {".ogg", ".oga", ".opus", ".mp3", ".m4a"}

RATE_LIMIT_MESSAGE = "Rate limit exceeded. Please wait a minute and retry."
RETRY_FAILED_MESSAGE = "Execution failed after an automatic retry. Please resend your request."
CANCEL_REQUESTED_MESSAGE = "Cancel requested. Stopping current request."
CANCEL_ALREADY_REQUESTED_MESSAGE = (
    "Cancel is already in progress. Waiting for current request to stop."
)
CANCEL_NO_ACTIVE_MESSAGE = "No active request to cancel."
REQUEST_CANCELED_MESSAGE = "Request canceled."
YOUTUBE_ANALYZER_TIMEOUT_SECONDS = 1800
YOUTUBE_INLINE_TRANSCRIPT_LIMIT = 12000


@dataclass
class DocumentPayload:
    file_id: str
    file_name: str
    mime_type: str


@dataclass
class PreparedPromptInput:
    prompt_text: str
    image_path: Optional[str] = None
    image_paths: List[str] = field(default_factory=list)
    document_path: Optional[str] = None
    cleanup_paths: List[str] = field(default_factory=list)
    attachment_file_ids: List[str] = field(default_factory=list)


@dataclass
class OutboundMediaDirective:
    media_ref: str
    as_voice: bool
def normalize_command(text: str) -> Optional[str]:
    stripped = text.strip()
    head: Optional[str] = None
    if stripped.startswith("/"):
        head = stripped.split(maxsplit=1)[0]
    else:
        parts = stripped.split(maxsplit=1)
        if len(parts) == 2 and parts[0].startswith("@"):
            candidate = parts[1].lstrip()
            if candidate.startswith("/"):
                head = candidate.split(maxsplit=1)[0]
    if not head:
        return None
    return head.split("@", maxsplit=1)[0]


def strip_required_prefix(
    text: str,
    prefixes: List[str],
    ignore_case: bool,
) -> tuple[bool, str]:
    allowed_punctuation_separators = (":", "-", ",", ".")

    def strip_prefix_separators(value: str) -> str:
        index = 0
        while index < len(value):
            current = value[index]
            if current.isspace() or current in allowed_punctuation_separators:
                index += 1
                continue
            break
        return value[index:]

    stripped = text.strip()
    if not stripped:
        return False, ""
    probe = stripped.casefold() if ignore_case else stripped
    for prefix in prefixes:
        normalized_prefix = prefix.strip()
        if not normalized_prefix:
            continue
        normalized_probe = normalized_prefix.casefold() if ignore_case else normalized_prefix
        if probe == normalized_probe:
            return True, ""
        if not probe.startswith(normalized_probe):
            continue
        remainder = stripped[len(normalized_prefix):]
        if remainder and not (
            remainder[0].isspace() or remainder[0] in allowed_punctuation_separators
        ):
            continue
        return True, strip_prefix_separators(remainder)
    return False, stripped


def trim_output(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    marker = "\n\n[output truncated]"
    return text[: max(0, limit - len(marker))] + marker


def parse_outbound_media_directive(output: str) -> tuple[str, Optional[OutboundMediaDirective]]:
    text = output or ""
    as_voice = bool(AUDIO_AS_VOICE_TAG_RE.search(text))
    text = AUDIO_AS_VOICE_TAG_RE.sub("", text)

    media_match = MEDIA_DIRECTIVE_TAG_RE.search(text)
    if media_match is None:
        media_match = MEDIA_DIRECTIVE_LINE_RE.search(text)
    if media_match is None:
        return text.strip(), None

    media_ref = media_match.group("value").strip().strip('"').strip("'")
    without_directive = f"{text[:media_match.start()]}{text[media_match.end():]}".strip()
    if not media_ref:
        return without_directive, None
    return without_directive, OutboundMediaDirective(media_ref=media_ref, as_voice=as_voice)


def parse_structured_outbound_payload(
    output: str,
) -> tuple[Optional[tuple[str, Optional[OutboundMediaDirective]]], Optional[str]]:
    text = (output or "").strip()
    if not text or '"telegram_outbound"' not in text:
        return None, None

    try:
        decoded = json.loads(text)
    except Exception as exc:
        return None, f"invalid_json:{type(exc).__name__}"

    if not isinstance(decoded, dict) or "telegram_outbound" not in decoded:
        return None, None

    payload = decoded.get("telegram_outbound")
    if not isinstance(payload, dict):
        return None, "invalid_schema:telegram_outbound_not_object"

    payload_text = payload.get("text", "")
    if payload_text is None:
        payload_text = ""
    if not isinstance(payload_text, str):
        return None, "invalid_schema:text_not_string"

    media_ref = payload.get("media_ref", "")
    if media_ref is None:
        media_ref = ""
    if not isinstance(media_ref, str):
        return None, "invalid_schema:media_ref_not_string"
    media_ref = media_ref.strip()

    as_voice = payload.get("as_voice", False)
    if not isinstance(as_voice, bool):
        return None, "invalid_schema:as_voice_not_bool"

    if not payload_text.strip() and not media_ref:
        return None, "invalid_schema:empty_payload"

    directive = None
    if media_ref:
        directive = OutboundMediaDirective(media_ref=media_ref, as_voice=as_voice)
    return (payload_text.strip(), directive), None


def output_contains_control_directive(output: str) -> bool:
    text = output or ""
    if not text:
        return False
    return (
        bool(MEDIA_DIRECTIVE_TAG_RE.search(text))
        or bool(MEDIA_DIRECTIVE_LINE_RE.search(text))
        or '"telegram_outbound"' in text
    )


def media_extension(media_ref: str) -> str:
    ref = media_ref.strip()
    if not ref:
        return ""
    parsed = urlparse(ref)
    if parsed.scheme and parsed.path:
        return Path(parsed.path).suffix.lower()
    return Path(ref).suffix.lower()


def infer_media_kind(media_ref: str) -> str:
    extension = media_extension(media_ref)
    if extension in PHOTO_EXTENSIONS:
        return "photo"
    if extension in AUDIO_EXTENSIONS:
        return "audio"
    return "document"


def is_voice_compatible_media(media_ref: str) -> bool:
    return media_extension(media_ref) in VOICE_COMPATIBLE_EXTENSIONS


def is_voice_messages_forbidden_error(exc: Exception) -> bool:
    return "VOICE_MESSAGES_FORBIDDEN" in str(exc).upper()


def send_chat_action_safe(
    client: ChannelAdapter,
    chat_id: int,
    action: str,
    message_thread_id: Optional[int] = None,
) -> None:
    try:
        client.send_chat_action(chat_id, action=action, message_thread_id=message_thread_id)
    except Exception:
        logging.debug("Failed to send %s action for chat_id=%s", action, chat_id)


def send_executor_output(
    client: ChannelAdapter,
    chat_id: int,
    message_id: Optional[int],
    output: str,
) -> str:
    payload_format = "plain_text"
    structured_payload, parse_error = parse_structured_outbound_payload(output)
    if parse_error is not None:
        emit_event(
            "bridge.outbound_payload_parse_failed",
            level=logging.WARNING,
            fields={
                "chat_id": chat_id,
                "message_id": message_id,
                "reason": parse_error,
            },
        )
        fallback_text = apply_outbound_reply_prefix(client, output or "")
        client.send_message(chat_id, fallback_text, reply_to_message_id=message_id)
        return fallback_text

    if structured_payload is not None:
        rendered_text, directive = structured_payload
        payload_format = "json_envelope"
    else:
        rendered_text, directive = parse_outbound_media_directive(output)
        if directive is not None:
            payload_format = "legacy_directive"

    emit_event(
        "bridge.outbound_payload_parsed",
        fields={
            "chat_id": chat_id,
            "message_id": message_id,
            "payload_format": payload_format,
            "has_media_directive": directive is not None,
        },
    )

    if directive is None:
        rendered_text = apply_outbound_reply_prefix(client, rendered_text)
        client.send_message(chat_id, rendered_text, reply_to_message_id=message_id)
        return rendered_text

    caption = apply_outbound_reply_prefix(client, rendered_text) if rendered_text else None
    follow_up_text: Optional[str] = None
    if caption and len(caption) > TELEGRAM_CAPTION_LIMIT:
        follow_up_text = caption
        caption = None

    try:
        media_kind = infer_media_kind(directive.media_ref)
        emit_event(
            "bridge.outbound_delivery_attempt",
            fields={
                "chat_id": chat_id,
                "message_id": message_id,
                "media_kind": media_kind,
                "as_voice_requested": directive.as_voice,
            },
        )
        if media_kind == "photo":
            send_chat_action_safe(client, chat_id, "upload_photo")
            client.send_photo(
                chat_id=chat_id,
                photo=directive.media_ref,
                caption=caption,
                reply_to_message_id=message_id,
            )
            emit_event(
                "bridge.outbound_delivery_succeeded",
                fields={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "media_kind": media_kind,
                    "send_method": "sendPhoto",
                    "fallback_used": False,
                },
            )
        elif media_kind == "audio":
            if directive.as_voice and is_voice_compatible_media(directive.media_ref):
                send_chat_action_safe(client, chat_id, "record_voice")
                send_chat_action_safe(client, chat_id, "upload_voice")
                try:
                    client.send_voice(
                        chat_id=chat_id,
                        voice=directive.media_ref,
                        caption=caption,
                        reply_to_message_id=message_id,
                    )
                    emit_event(
                        "bridge.outbound_delivery_succeeded",
                        fields={
                            "chat_id": chat_id,
                            "message_id": message_id,
                            "media_kind": media_kind,
                            "send_method": "sendVoice",
                            "fallback_used": False,
                        },
                    )
                except Exception as exc:
                    if not is_voice_messages_forbidden_error(exc):
                        raise
                    logging.warning(
                        "sendVoice forbidden for chat_id=%s; falling back to sendAudio",
                        chat_id,
                    )
                    emit_event(
                        "bridge.outbound_delivery_fallback",
                        level=logging.WARNING,
                        fields={
                            "chat_id": chat_id,
                            "message_id": message_id,
                            "media_kind": media_kind,
                            "from_method": "sendVoice",
                            "to_method": "sendAudio",
                            "reason": "VOICE_MESSAGES_FORBIDDEN",
                        },
                    )
                    send_chat_action_safe(client, chat_id, "upload_audio")
                    client.send_audio(
                        chat_id=chat_id,
                        audio=directive.media_ref,
                        caption=caption,
                        reply_to_message_id=message_id,
                    )
                    emit_event(
                        "bridge.outbound_delivery_succeeded",
                        fields={
                            "chat_id": chat_id,
                            "message_id": message_id,
                            "media_kind": media_kind,
                            "send_method": "sendAudio",
                            "fallback_used": True,
                        },
                    )
            else:
                send_chat_action_safe(client, chat_id, "upload_audio")
                client.send_audio(
                    chat_id=chat_id,
                    audio=directive.media_ref,
                    caption=caption,
                    reply_to_message_id=message_id,
                )
                emit_event(
                    "bridge.outbound_delivery_succeeded",
                    fields={
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "media_kind": media_kind,
                        "send_method": "sendAudio",
                        "fallback_used": False,
                    },
                )
        else:
            send_chat_action_safe(client, chat_id, "upload_document")
            client.send_document(
                chat_id=chat_id,
                document=directive.media_ref,
                caption=caption,
                reply_to_message_id=message_id,
            )
            emit_event(
                "bridge.outbound_delivery_succeeded",
                fields={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "media_kind": media_kind,
                    "send_method": "sendDocument",
                    "fallback_used": False,
                },
            )
    except Exception as exc:
        logging.exception(
            "Failed to send outbound media for chat_id=%s; falling back to text",
            chat_id,
        )
        emit_event(
            "bridge.outbound_delivery_failed",
            level=logging.ERROR,
            fields={
                "chat_id": chat_id,
                "message_id": message_id,
                "media_kind": infer_media_kind(directive.media_ref),
                "error_type": type(exc).__name__,
                "fallback_to_text": True,
            },
        )
        fallback_text = apply_outbound_reply_prefix(client, rendered_text or output)
        client.send_message(chat_id, fallback_text, reply_to_message_id=message_id)
        return fallback_text

    if follow_up_text:
        client.send_message(chat_id, follow_up_text, reply_to_message_id=message_id)
        return follow_up_text
    if caption:
        return caption
    if rendered_text:
        return rendered_text
    return f"[media sent: {directive.media_ref}]"


def compact_progress_text(text: str, max_chars: int = 120) -> str:
    cleaned = " ".join(text.replace("\n", " ").split())
    cleaned = cleaned.replace("**", "").replace("`", "")
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 3].rstrip() + "..."


def send_input_too_long(
    client: ChannelAdapter,
    chat_id: int,
    message_id: Optional[int],
    actual_length: int,
    max_input_chars: int,
) -> None:
    client.send_message(
        chat_id,
        f"Input too long ({actual_length} chars). Max is {max_input_chars}.",
        reply_to_message_id=message_id,
    )


EXECUTOR_USAGE_LIMIT_RE = re.compile(r"\bhit your usage limit\b", re.IGNORECASE)
EXECUTOR_RETRY_AT_RE = re.compile(r"\btry again at ([0-9]{1,2}:\d{2}\s*[AP]M)\b", re.IGNORECASE)


def normalize_known_executor_failure_message(message: str) -> Optional[str]:
    cleaned = " ".join((message or "").split())
    if not cleaned:
        return None
    if EXECUTOR_USAGE_LIMIT_RE.search(cleaned):
        retry_at_match = EXECUTOR_RETRY_AT_RE.search(cleaned)
        if retry_at_match:
            retry_at = " ".join(retry_at_match.group(1).upper().split())
            return f"The runtime has hit its usage limit. Try again after {retry_at}."
        return "The runtime has hit its usage limit. Try again later."
    return None


def extract_executor_failure_message(stdout: str, stderr: str) -> Optional[str]:
    candidates: List[str] = []
    for stream in (stdout or "", stderr or ""):
        for raw_line in stream.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            payload: Optional[Dict[str, object]] = None
            if line.startswith("{"):
                try:
                    decoded = json.loads(line)
                except json.JSONDecodeError:
                    decoded = None
                if isinstance(decoded, dict):
                    payload = decoded
            if payload is not None:
                payload_message = payload.get("message")
                if isinstance(payload_message, str):
                    candidates.append(payload_message)
                payload_error = payload.get("error")
                if isinstance(payload_error, dict):
                    error_message = payload_error.get("message")
                    if isinstance(error_message, str):
                        candidates.append(error_message)
                continue
            candidates.append(line)
    for candidate in candidates:
        normalized = normalize_known_executor_failure_message(candidate)
        if normalized:
            return normalized
    return None


def send_executor_failure_message(
    client: ChannelAdapter,
    config,
    chat_id: int,
    message_id: Optional[int],
    allow_automatic_retry: bool,
    failure_message: Optional[str] = None,
    message_thread_id: Optional[int] = None,
) -> None:
    if failure_message:
        client.send_message(
            chat_id,
            failure_message,
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return
    if allow_automatic_retry:
        client.send_message(
            chat_id,
            RETRY_FAILED_MESSAGE,
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return
    client.send_message(
        chat_id,
        config.generic_error_message,
        reply_to_message_id=message_id,
        message_thread_id=message_thread_id,
    )


def register_cancel_event(state: State, scope_key: str) -> threading.Event:
    cancel_event = threading.Event()
    with state.lock:
        state.cancel_events[scope_key] = cancel_event
    return cancel_event


def clear_cancel_event(
    state: State,
    scope_key: str,
    expected_event: Optional[threading.Event] = None,
) -> None:
    with state.lock:
        current = state.cancel_events.get(scope_key)
        if current is None:
            return
        if expected_event is not None and current is not expected_event:
            return
        del state.cancel_events[scope_key]


def request_chat_cancel(state: State, scope_key: str) -> str:
    try:
        parsed_scope = parse_telegram_scope_key(scope_key)
    except ValueError:
        parsed_scope = None
    legacy_alias = (
        parsed_scope.chat_id
        if parsed_scope is not None and parsed_scope.message_thread_id is None
        else None
    )
    with state.lock:
        is_busy = scope_key in state.busy_chats or (
            legacy_alias is not None and legacy_alias in state.busy_chats
        )
        cancel_event = state.cancel_events.get(scope_key)
        if cancel_event is None and legacy_alias is not None:
            cancel_event = state.cancel_events.get(legacy_alias)
            if cancel_event is not None:
                state.cancel_events[scope_key] = cancel_event
                del state.cancel_events[legacy_alias]
        if not is_busy:
            if cancel_event is not None:
                del state.cancel_events[scope_key]
            return "idle"
        if cancel_event is None:
            return "unavailable"
        if cancel_event.is_set():
            return "already_requested"
        cancel_event.set()
        return "requested"


def extract_chat_context(
    update: Dict[str, object],
) -> tuple[Optional[Dict[str, object]], Optional[ConversationScope], Optional[int]]:
    message = update.get("message")
    if not isinstance(message, dict):
        return None, None, None

    scope = scope_from_message(message)
    if scope is None:
        return None, None, None

    message_id = message.get("message_id")
    if not isinstance(message_id, int):
        message_id = None
    return message, scope, message_id


class ProgressReporter:
    def __init__(
        self,
        client: ChannelAdapter,
        chat_id: int,
        reply_to_message_id: Optional[int],
        message_thread_id: Optional[int],
        assistant_name: str,
        progress_label: str = "",
        compact_elapsed_prefix: str = "Already",
        compact_elapsed_suffix: str = "s",
    ) -> None:
        self.client = client
        self.chat_id = chat_id
        self.reply_to_message_id = reply_to_message_id
        self.message_thread_id = message_thread_id
        self.assistant_name = assistant_name
        self.progress_label = progress_label.strip()
        if compact_elapsed_prefix is None:
            self.compact_elapsed_prefix = "Already"
        else:
            self.compact_elapsed_prefix = compact_elapsed_prefix.strip()
        if compact_elapsed_suffix is None:
            self.compact_elapsed_suffix = "s"
        else:
            self.compact_elapsed_suffix = compact_elapsed_suffix
        self.started_at = time.time()
        self.progress_message_id: Optional[int] = None
        self.phase = ""
        self.commands_started = 0
        self.commands_completed = 0
        self.pending_update = True
        self.last_edit_at = 0.0
        self.last_rendered_text = ""
        self._is_compact_progress = bool(self.progress_label)
        self._edit_min_interval_seconds = (
            1.0 if self._is_compact_progress else PROGRESS_EDIT_MIN_INTERVAL_SECONDS
        )
        self._heartbeat_edit_seconds = (
            1.0 if self._is_compact_progress else PROGRESS_HEARTBEAT_EDIT_SECONDS
        )
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self.edit_attempts = 0
        self.edit_successes = 0
        self.edit_failures_400 = 0
        self.edit_failures_other = 0

    def start(self) -> None:
        text = self._render_progress_text()
        try:
            self.progress_message_id = self.client.send_message_get_id(
                self.chat_id,
                text,
                reply_to_message_id=self.reply_to_message_id,
                message_thread_id=self.message_thread_id,
            )
        except Exception:
            logging.exception("Failed to send initial progress message for chat_id=%s", self.chat_id)
            self.progress_message_id = None

        self.last_rendered_text = text
        self.last_edit_at = time.time()
        self._worker = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._worker.start()

    def close(self) -> None:
        self._stop_event.set()
        if self._worker:
            self._worker.join(timeout=2.0)
        self._maybe_edit(force=True)
        emit_event(
            "bridge.progress_edit_stats",
            fields={
                "chat_id": self.chat_id,
                "reply_to_message_id": self.reply_to_message_id,
                "progress_message_id": self.progress_message_id,
                "edit_attempts": self.edit_attempts,
                "edit_successes": self.edit_successes,
                "edit_failures_400": self.edit_failures_400,
                "edit_failures_other": self.edit_failures_other,
            },
        )

    def mark_success(self) -> None:
        self.set_phase("Finalizing response.", immediate=True)

    def mark_failure(self, detail: str) -> None:
        self.set_phase(detail, immediate=True)

    def set_phase(self, phase: str, immediate: bool = False) -> None:
        with self._lock:
            self.phase = phase
            self.pending_update = True
        if immediate:
            self._maybe_edit(force=True)

    def handle_executor_event(self, event: ExecutorProgressEvent) -> None:
        if event.kind == "turn_started":
            self.set_phase(f"{self.assistant_name} started reasoning.", immediate=False)
            return
        if event.kind == "reasoning":
            detail = (
                compact_progress_text(event.detail)
                if event.detail
                else f"{self.assistant_name} is reasoning."
            )
            self.set_phase(detail, immediate=False)
            return
        if event.kind == "agent_message":
            self.set_phase(f"{self.assistant_name} is preparing the reply.", immediate=False)
            return
        if event.kind == "command_started":
            with self._lock:
                self.commands_started += 1
            command_text = compact_progress_text(event.detail) if event.detail else "shell command"
            self.set_phase(f"Running command: {command_text}", immediate=False)
            return
        if event.kind == "command_completed":
            with self._lock:
                self.commands_completed += 1
            if event.exit_code is None:
                self.set_phase("A command finished.", immediate=False)
            elif event.exit_code == 0:
                self.set_phase("A command finished successfully.", immediate=False)
            else:
                self.set_phase(
                    f"A command finished with exit code {event.exit_code}.",
                    immediate=False,
                )

    def _heartbeat_loop(self) -> None:
        next_typing_at = 0.0
        next_progress_at = 0.0
        while not self._stop_event.is_set():
            now = time.time()
            if now >= next_typing_at:
                self._send_typing()
                next_typing_at = now + PROGRESS_TYPING_INTERVAL_SECONDS
            self._maybe_edit(force=False)
            if now >= next_progress_at:
                self._maybe_edit(force=True)
                next_progress_at = now + self._heartbeat_edit_seconds
            self._stop_event.wait(1.0)

    def _send_typing(self) -> None:
        try:
            self.client.send_chat_action(
                self.chat_id,
                action="typing",
                message_thread_id=self.message_thread_id,
            )
        except Exception:
            logging.debug("Failed to send typing action for chat_id=%s", self.chat_id)

    def _render_progress_text(self) -> str:
        elapsed = max(1, int(time.time() - self.started_at))
        with self._lock:
            phase = self.phase
            started = self.commands_started
            completed = self.commands_completed
        label = self.progress_label or f"{self.assistant_name} is working"
        if self._is_compact_progress:
            if not self.compact_elapsed_prefix and not self.compact_elapsed_suffix:
                text = f"{label}..."
            else:
                elapsed_prefix = (
                    f"{self.compact_elapsed_prefix} " if self.compact_elapsed_prefix else ""
                )
                text = f"{label}... {elapsed_prefix}{elapsed}{self.compact_elapsed_suffix}"
            return trim_output(text, TELEGRAM_LIMIT)

        text = f"{label}... {elapsed}s elapsed."
        if phase:
            text += f"\n{phase}"
        if started > 0:
            text += f"\nCommands done: {completed}/{started}"
        return trim_output(text, TELEGRAM_LIMIT)

    def _maybe_edit(self, force: bool = False) -> None:
        message_id = self.progress_message_id
        if message_id is None:
            return
        if not getattr(self.client, "supports_message_edits", True):
            return

        with self._lock:
            pending_update = self.pending_update
        if not force and not pending_update:
            return

        now = time.time()
        if not force and now - self.last_edit_at < self._edit_min_interval_seconds:
            return

        text = self._render_progress_text()
        if not force and text == self.last_rendered_text:
            with self._lock:
                self.pending_update = False
            return

        self.edit_attempts += 1
        try:
            self.client.edit_message(self.chat_id, message_id, text)
        except RuntimeError as exc:
            if "message is not modified" in str(exc).lower():
                self.edit_failures_400 += 1
                with self._lock:
                    self.pending_update = False
                return
            self.edit_failures_other += 1
            if getattr(self.client, "channel_name", "") in {"whatsapp", "signal"}:
                # WhatsApp edit failures can create visible noise if retried aggressively.
                self.progress_message_id = None
            logging.debug("Failed to edit progress message for chat_id=%s: %s", self.chat_id, exc)
            return
        except Exception:
            self.edit_failures_other += 1
            if getattr(self.client, "channel_name", "") in {"whatsapp", "signal"}:
                self.progress_message_id = None
            logging.debug("Failed to edit progress message for chat_id=%s", self.chat_id)
            return

        self.edit_successes += 1
        self.last_rendered_text = text
        self.last_edit_at = now
        with self._lock:
            self.pending_update = False


def pick_largest_photo_file_id(photo_items: List[object]) -> Optional[str]:
    best_file_id: Optional[str] = None
    best_size = -1
    for item in photo_items:
        if not isinstance(item, dict):
            continue
        file_id = item.get("file_id")
        if not isinstance(file_id, str) or not file_id.strip():
            continue
        file_size = item.get("file_size")
        size_score = file_size if isinstance(file_size, int) else 0
        if size_score >= best_size:
            best_size = size_score
            best_file_id = file_id.strip()
    return best_file_id


def extract_discrete_photo_file_ids(photo_items: List[object]) -> List[str]:
    has_transport_descriptors = any(
        isinstance(item, dict) and isinstance(item.get("mime_type"), str) and item.get("mime_type", "").strip()
        for item in photo_items
    )
    if not has_transport_descriptors:
        return []

    photo_file_ids: List[str] = []
    for item in photo_items:
        if not isinstance(item, dict):
            continue
        file_id = item.get("file_id")
        if not isinstance(file_id, str):
            continue
        normalized = file_id.strip()
        if not normalized or normalized in photo_file_ids:
            continue
        photo_file_ids.append(normalized)
    return photo_file_ids


def normalize_optional_text(value: object) -> Optional[str]:
    if not isinstance(value, str):
        return None
    return value.strip()


def iter_media_group_messages(message: Dict[str, object]) -> List[Dict[str, object]]:
    grouped = message.get("media_group_messages")
    if isinstance(grouped, list):
        messages = [item for item in grouped if isinstance(item, dict)]
        if messages:
            return messages
    return [message]


def collapse_media_group_updates(updates: List[Dict[str, object]]) -> List[Dict[str, object]]:
    collapsed: List[Dict[str, object]] = []
    index = 0
    while index < len(updates):
        update = updates[index]
        message = update.get("message")
        if not isinstance(message, dict):
            collapsed.append(update)
            index += 1
            continue

        media_group_id = message.get("media_group_id")
        chat = message.get("chat")
        chat_id = chat.get("id") if isinstance(chat, dict) else None
        if not isinstance(media_group_id, str) or not media_group_id.strip() or not isinstance(chat_id, int):
            collapsed.append(update)
            index += 1
            continue

        grouped_updates = [update]
        next_index = index + 1
        while next_index < len(updates):
            candidate_update = updates[next_index]
            candidate_message = candidate_update.get("message")
            if not isinstance(candidate_message, dict):
                break
            candidate_group_id = candidate_message.get("media_group_id")
            candidate_chat = candidate_message.get("chat")
            candidate_chat_id = candidate_chat.get("id") if isinstance(candidate_chat, dict) else None
            if candidate_group_id != media_group_id or candidate_chat_id != chat_id:
                break
            grouped_updates.append(candidate_update)
            next_index += 1

        if len(grouped_updates) == 1:
            collapsed.append(update)
            index = next_index
            continue

        grouped_messages = [
            candidate_update["message"]
            for candidate_update in grouped_updates
            if isinstance(candidate_update.get("message"), dict)
        ]
        combined_update = dict(update)
        combined_message = dict(message)
        combined_message["media_group_messages"] = grouped_messages
        for field_name in ("caption", "text"):
            if normalize_optional_text(combined_message.get(field_name)):
                continue
            for grouped_message in grouped_messages:
                candidate_text = normalize_optional_text(grouped_message.get(field_name))
                if candidate_text:
                    combined_message[field_name] = candidate_text
                    break
        combined_update["message"] = combined_message
        collapsed.append(combined_update)
        index = next_index

    return collapsed


def build_reply_context_prompt(message: Dict[str, object]) -> str:
    reply_to = message.get("reply_to_message")
    if not isinstance(reply_to, dict):
        return ""

    reply_text = normalize_optional_text(reply_to.get("text"))
    reply_caption = normalize_optional_text(reply_to.get("caption"))
    quoted_text = reply_text or reply_caption or ""
    media_context = describe_message_media(reply_to)
    if not quoted_text and not media_context:
        return ""

    sender_name = extract_sender_name(reply_to)
    sender_line = ""
    if sender_name != "Telegram User":
        sender_line = f"Original Message Author: {sender_name}\n"

    body_parts: List[str] = []
    if quoted_text:
        body_parts.append(
            "Message User Replied To:\n"
            f"{quoted_text}"
        )
    if media_context:
        body_parts.append(media_context)

    return "Reply Context:\n" + sender_line + "\n\n".join(body_parts)


def select_media_prompt(text: Optional[str], caption: Optional[str], default_prompt: str) -> str:
    text_value = text or ""
    caption_value = caption or ""
    if caption_value and text_value and caption_value != text_value:
        return f"{caption_value}\n\n{text_value}"
    if caption_value:
        return caption_value
    if text_value:
        return text_value
    return default_prompt


def extract_document_payload(message: Dict[str, object]) -> Optional[DocumentPayload]:
    document = message.get("document")
    if not isinstance(document, dict):
        return None

    file_id = document.get("file_id")
    if not isinstance(file_id, str) or not file_id.strip():
        return None

    file_name = document.get("file_name")
    mime_type = document.get("mime_type")
    return DocumentPayload(
        file_id=file_id.strip(),
        file_name=file_name.strip() if isinstance(file_name, str) and file_name.strip() else "unnamed",
        mime_type=mime_type.strip() if isinstance(mime_type, str) and mime_type.strip() else "unknown",
    )


def extract_message_media_payload(
    message: Dict[str, object]
) -> tuple[Optional[str], Optional[str], Optional[DocumentPayload]]:
    photo_file_ids = extract_message_photo_file_ids(message)
    if photo_file_ids:
        return photo_file_ids[0], None, None

    for candidate in iter_media_group_messages(message):
        voice = candidate.get("voice")
        if isinstance(voice, dict):
            voice_file_id = voice.get("file_id")
            if isinstance(voice_file_id, str) and voice_file_id.strip():
                return None, voice_file_id.strip(), None

        document = extract_document_payload(candidate)
        if document is not None:
            return None, None, document

    return None, None, None


def extract_message_photo_file_ids(message: Dict[str, object]) -> List[str]:
    photo_file_ids: List[str] = []
    for candidate in iter_media_group_messages(message):
        photo_items = candidate.get("photo")
        if not isinstance(photo_items, list) or not photo_items:
            continue
        discrete_photo_file_ids = extract_discrete_photo_file_ids(photo_items)
        if discrete_photo_file_ids:
            for file_id in discrete_photo_file_ids:
                if file_id not in photo_file_ids:
                    photo_file_ids.append(file_id)
            continue
        file_id = pick_largest_photo_file_id(photo_items)
        if not file_id or file_id in photo_file_ids:
            continue
        photo_file_ids.append(file_id)
    return photo_file_ids


def describe_message_media(message: Dict[str, object]) -> str:
    photo_file_ids = extract_message_photo_file_ids(message)
    _, voice_file_id, document = extract_message_media_payload(message)
    if photo_file_ids:
        if len(photo_file_ids) > 1:
            return "В исходном сообщении были изображения."
        return "В исходном сообщении было изображение."
    if voice_file_id:
        return "В исходном сообщении было голосовое сообщение."
    if document is not None:
        if document.file_name and document.file_name != "unnamed":
            return f"В исходном сообщении был файл: {document.file_name}."
        return "В исходном сообщении был файл."
    return ""


def extract_prompt_and_media(
    message: Dict[str, object]
) -> tuple[Optional[str], List[str], Optional[str], Optional[DocumentPayload]]:
    text = normalize_optional_text(message.get("text"))
    caption = normalize_optional_text(message.get("caption"))

    photo_file_ids = extract_message_photo_file_ids(message)
    _, voice_file_id, document = extract_message_media_payload(message)
    if photo_file_ids:
        default_prompt = "Please analyze these images." if len(photo_file_ids) > 1 else "Please analyze this image."
        prompt = select_media_prompt(text, caption, default_prompt)
        return prompt, photo_file_ids, None, None
    if voice_file_id:
        prompt = select_media_prompt(text, caption, "")
        return prompt, [], voice_file_id, None
    if document is not None:
        prompt = select_media_prompt(text, caption, "Please analyze this file.")
        return prompt, [], None, document

    reply_to = message.get("reply_to_message")
    if isinstance(reply_to, dict):
        reply_photo_file_ids = extract_message_photo_file_ids(reply_to)
        _, reply_voice_file_id, reply_document = extract_message_media_payload(reply_to)
        if reply_photo_file_ids:
            default_prompt = (
                "Please analyze the referenced images."
                if len(reply_photo_file_ids) > 1
                else "Please analyze the referenced image."
            )
            prompt = select_media_prompt(text, caption, default_prompt)
            return prompt, reply_photo_file_ids, None, None
        if reply_voice_file_id:
            prompt = select_media_prompt(
                text,
                caption,
                "Please transcribe the referenced voice message.",
            )
            return prompt, [], reply_voice_file_id, None
        if reply_document is not None:
            prompt = select_media_prompt(text, caption, "Please analyze the referenced file.")
            return prompt, [], None, reply_document

    if text is not None:
        return text, [], None, None

    return None, [], None, None


def extract_sender_name(message: Dict[str, object]) -> str:
    sender = message.get("from")
    if isinstance(sender, dict):
        first = sender.get("first_name")
        last = sender.get("last_name")
        username = sender.get("username")
        parts: List[str] = []
        if isinstance(first, str) and first.strip():
            parts.append(first.strip())
        if isinstance(last, str) and last.strip():
            parts.append(last.strip())
        if parts:
            return " ".join(parts)
        if isinstance(username, str) and username.strip():
            return username.strip()
    return "Telegram User"


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


def transcribe_voice_for_chat(
    state: State,
    config,
    client: ChannelAdapter,
    chat_id: int,
    message_id: Optional[int],
    voice_file_id: str,
    echo_transcript: bool = True,
) -> Optional[str]:
    if not config.voice_transcribe_cmd:
        client.send_message(
            chat_id,
            config.voice_not_configured_message,
            reply_to_message_id=message_id,
        )
        return None

    voice_path: Optional[str] = None
    try:
        try:
            voice_path = download_voice_to_temp(client, config, voice_file_id)
        except ValueError as exc:
            logging.warning("Voice rejected for chat_id=%s: %s", chat_id, exc)
            client.send_message(chat_id, str(exc), reply_to_message_id=message_id)
            return None
        except Exception:
            logging.exception("Voice download failed for chat_id=%s", chat_id)
            client.send_message(
                chat_id,
                config.voice_download_error_message,
                reply_to_message_id=message_id,
            )
            return None

        try:
            transcript, confidence = transcribe_voice(config, voice_path)
        except subprocess.TimeoutExpired:
            logging.warning("Voice transcription timeout for chat_id=%s", chat_id)
            client.send_message(
                chat_id,
                config.timeout_message,
                reply_to_message_id=message_id,
            )
            return None
        except ValueError:
            logging.warning("Voice transcription was empty for chat_id=%s", chat_id)
            client.send_message(
                chat_id,
                config.voice_transcribe_empty_message,
                reply_to_message_id=message_id,
            )
            return None
        except RuntimeError:
            client.send_message(
                chat_id,
                config.voice_transcribe_error_message,
                reply_to_message_id=message_id,
            )
            return None
        except Exception:
            logging.exception("Unexpected voice transcription error for chat_id=%s", chat_id)
            client.send_message(
                chat_id,
                config.voice_transcribe_error_message,
                reply_to_message_id=message_id,
            )
            return None

        transcript, aliases_applied = apply_voice_alias_replacements(
            transcript,
            build_active_voice_alias_replacements(config, state),
        )
        if aliases_applied:
            logging.info("Applied voice alias corrections chat_id=%s", chat_id)

        if (
            getattr(config, "voice_low_confidence_confirmation_enabled", False)
            and confidence is not None
            and confidence < float(getattr(config, "voice_low_confidence_threshold", 0.0))
        ):
            learning_store = getattr(state, "voice_alias_learning_store", None)
            if learning_store is not None:
                try:
                    learning_store.register_low_confidence_transcript(
                        chat_id=chat_id,
                        transcript=transcript,
                        confidence=confidence,
                    )
                except Exception:
                    logging.exception("Failed to register low-confidence transcript for learning")
            client.send_message(
                chat_id,
                build_low_confidence_voice_message(config, transcript, confidence),
                reply_to_message_id=message_id,
            )
            return None

        if echo_transcript:
            try:
                heading = "Voice transcript:"
                if confidence is not None:
                    heading = f"Voice transcript (confidence {confidence:.2f}):"
                client.send_message(
                    chat_id,
                    f"{heading}\n{transcript}",
                    reply_to_message_id=message_id,
                )
            except Exception:
                logging.exception("Failed to send voice transcript echo for chat_id=%s", chat_id)
        return transcript
    finally:
        if voice_path:
            try:
                os.remove(voice_path)
            except OSError:
                logging.warning("Failed to remove temp voice file: %s", voice_path)


def build_youtube_analyzer_command(youtube_url: str, request_text: str) -> List[str]:
    analyzer_path = os.path.join(build_repo_root(), "ops", "youtube", "analyze_youtube.py")
    return [
        sys.executable,
        analyzer_path,
        "--url",
        youtube_url,
        "--request-text",
        request_text,
    ]


def run_youtube_analyzer(youtube_url: str, request_text: str) -> Dict[str, object]:
    cmd = build_youtube_analyzer_command(youtube_url, request_text)
    logging.info("Running YouTube analyzer command: %s", cmd)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=YOUTUBE_ANALYZER_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode != 0:
        logging.error(
            "YouTube analyzer failed returncode=%s stderr=%r",
            result.returncode,
            (result.stderr or "")[-2000:],
        )
        raise RuntimeError("YouTube analysis failed")
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("YouTube analysis returned invalid JSON") from exc
    if not isinstance(payload, dict) or not payload.get("ok", False):
        raise RuntimeError("YouTube analysis did not complete successfully")
    return payload


def build_youtube_summary_prompt(request_text: str, analysis: Dict[str, object]) -> str:
    title = str(analysis.get("title") or "").strip()
    channel = str(analysis.get("channel") or "").strip()
    duration_seconds = analysis.get("duration_seconds")
    duration_line = ""
    if isinstance(duration_seconds, int) and duration_seconds > 0:
        duration_line = f"Duration seconds: {duration_seconds}\n"
    transcript_source = str(analysis.get("transcript_source") or "unknown").strip()
    transcript_language = str(analysis.get("transcript_language") or "").strip()
    transcript_text = str(analysis.get("transcript_text") or "").strip()
    description = str(analysis.get("description") or "").strip()
    chapters = analysis.get("chapters") if isinstance(analysis.get("chapters"), list) else []
    chapter_lines: List[str] = []
    for item in chapters[:20]:
        if not isinstance(item, dict):
            continue
        start_time = item.get("start_time")
        chapter_title = str(item.get("title") or "").strip()
        if not chapter_title:
            continue
        if isinstance(start_time, (int, float)):
            chapter_lines.append(f"- {int(start_time)}s: {chapter_title}")
        else:
            chapter_lines.append(f"- {chapter_title}")
    chapter_block = "\n".join(chapter_lines)
    return (
        "You are answering a chat message about a YouTube video.\n"
        "Use the transcript below as the primary source of truth for what the video actually says.\n"
        "Do not mention backend tools, yt-dlp, Browser Brain, JSON, or implementation details.\n"
        "If the user only pasted the link, default to a concise content summary.\n"
        "If the transcript comes from automatic captions or transcription, mention that briefly only if it materially affects confidence.\n"
        "Do not invent details that are not supported by the transcript.\n\n"
        f"Original user message:\n{request_text.strip()}\n\n"
        f"Video title: {title}\n"
        f"Channel: {channel}\n"
        f"{duration_line}"
        f"Transcript source: {transcript_source}\n"
        f"Transcript language: {transcript_language or 'unknown'}\n\n"
        f"Description:\n{description or '(no description)'}\n\n"
        f"Chapters:\n{chapter_block or '(no chapters)'}\n\n"
        f"Transcript:\n{transcript_text}\n"
    )


def build_youtube_unavailable_message(analysis: Dict[str, object]) -> str:
    title = str(analysis.get("title") or "").strip()
    channel = str(analysis.get("channel") or "").strip()
    reason = str(analysis.get("transcript_error") or "").strip()
    parts = [
        "I could not obtain captions or a usable transcription for this video, so I cannot provide a reliable content summary."
    ]
    if title:
        parts.append(f"Title: {title}.")
    if channel:
        parts.append(f"Channel: {channel}.")
    if reason:
        parts.append(f"Reason: {reason}.")
    return " ".join(parts)


def build_youtube_transcript_output(
    config,
    analysis: Dict[str, object],
    cleanup_paths: List[str],
) -> str:
    title = str(analysis.get("title") or "YouTube video").strip()
    transcript_source = str(analysis.get("transcript_source") or "unknown").strip()
    transcript_language = str(analysis.get("transcript_language") or "unknown").strip()
    transcript_text = str(analysis.get("transcript_text") or "").strip()
    payload = (
        f"Full transcript for: {title}\n"
        f"Source: {transcript_source}\n"
        f"Language: {transcript_language}\n\n"
        f"{transcript_text}"
    )
    inline_limit = min(getattr(config, "max_output_chars", TELEGRAM_LIMIT), YOUTUBE_INLINE_TRANSCRIPT_LIMIT)
    if len(payload) <= inline_limit:
        return payload

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as handle:
        handle.write(payload)
        transcript_path = handle.name
    cleanup_paths.append(transcript_path)
    return json.dumps(
        {
            "telegram_outbound": {
                "text": f"Full transcript attached for: {title}",
                "media_ref": transcript_path,
                "as_voice": False,
            }
        }
    )


def build_help_text(config) -> str:
    minimal = (
        "Available commands:\n"
        "/start - verify bridge connectivity\n"
        "/help or /h - show this message\n"
        "/status - show bridge status and context\n"
        "/reset - clear saved context for this chat\n"
        "/cancel - cancel current in-flight request for this chat\n"
        "/restart - queue a safe bridge restart\n"
        "/voice-alias add <source> => <target> - add approved alias manually"
    )
    if getattr(config, "channel_plugin", "telegram") in {"whatsapp", "signal"}:
        return minimal

    name = assistant_label(config)
    base = (
        minimal
        + "\n"
        "/voice-alias list - show pending learned voice corrections\n"
        "/voice-alias approve <id> - approve one learned correction\n"
        "browser_brain_ctl.sh status - show browser brain API/runtime state (local shell command)\n"
        "server3-tv-start - start TV desktop mode (local shell command)\n"
        "server3-tv-stop - stop TV desktop mode and return to CLI (local shell command)\n\n"
        f"Send text, images, voice notes, or files and {name} will process them.\n"
        + (
            ""
            if not getattr(config, "keyword_routing_enabled", True)
            else (
                "Use `HA ...` or `Home Assistant ...` to force Home Assistant script routing.\n"
                "Use `Server3 Browser ...` or `Browser Brain ...` for Server3 browser-brain automation.\n"
                "Use `Server3 TV ...` for Server3 desktop/browser/UI operations.\n"
                "Use `Nextcloud ...` for Nextcloud files/calendar operations.\n"
                "Use `SRO ...` for Server3 Runtime Observer status, summaries, snapshot collection, and test alerts."
            )
        )
    )
    return base + "\n\n" + "\n".join(build_memory_help_lines())


def build_status_text(
    state: State,
    config,
    chat_id: Optional[int] = None,
    scope_key: Optional[str] = None,
    message_thread_id: Optional[int] = None,
) -> str:
    if scope_key is None and chat_id is not None:
        scope_key = build_telegram_scope_key(chat_id, message_thread_id=message_thread_id)
    with state.lock:
        busy_count = len(state.busy_chats)
        restart_requested = state.restart_requested
        restart_in_progress = state.restart_in_progress
        if state.canonical_sessions_enabled:
            thread_count = sum(
                1 for session in state.chat_sessions.values() if session.thread_id.strip()
            )
            worker_count = sum(
                1
                for session in state.chat_sessions.values()
                if session.worker_created_at is not None and session.worker_last_used_at is not None
            )
            has_thread = False
            has_worker = False
            if scope_key is not None:
                session = state.chat_sessions.get(scope_key)
                if session is not None:
                    has_thread = bool(session.thread_id.strip())
                    has_worker = (
                        session.worker_created_at is not None
                        and session.worker_last_used_at is not None
                    )
        else:
            thread_count = len(state.chat_threads)
            worker_count = len(state.worker_sessions)
            has_thread = scope_key in state.chat_threads if scope_key is not None else False
            has_worker = scope_key in state.worker_sessions if scope_key is not None else False

    lines = [
        "Bridge status: online",
        f"Allowed chats: {len(config.allowed_chat_ids)}",
        f"Required prefixes: {', '.join(config.required_prefixes) if config.required_prefixes else '(none)'}",
        f"Busy chats: {busy_count}",
        f"Saved contexts: {thread_count}",
        (
            "Persistent workers: "
            f"enabled={config.persistent_workers_enabled} "
            f"active={worker_count}/{config.persistent_workers_max} "
            f"idle_timeout={config.persistent_workers_idle_timeout_seconds}s"
        ),
        f"Safe restart queued: {restart_requested}",
        f"Safe restart in progress: {restart_in_progress}",
    ]

    if scope_key is not None:
        lines.append(f"This chat has saved context: {has_thread}")
        lines.append(f"This chat has worker session: {has_worker}")
        memory_engine = state.memory_engine
        if isinstance(memory_engine, MemoryEngine):
            memory_channel = getattr(config, "channel_plugin", "telegram")
            try:
                memory_status = memory_engine.get_status(
                    resolve_memory_conversation_key(config, memory_channel, scope_key)
                )
            except Exception:
                logging.exception("Failed to query memory status for scope_key=%s", scope_key)
            else:
                lines.append(f"Memory mode: {memory_status.mode}")
                lines.append(f"Memory facts: {memory_status.active_fact_count}")
                lines.append(f"Memory summaries: {memory_status.summary_count}")
                lines.append(f"Memory session active: {memory_status.session_active}")

    return "\n".join(lines)


def prepare_prompt_input(
    state: State,
    config,
    client: ChannelAdapter,
    chat_id: int,
    message_id: Optional[int],
    prompt: str,
    photo_file_id: Optional[str],
    voice_file_id: Optional[str],
    document: Optional[DocumentPayload],
    progress: ProgressReporter,
    photo_file_ids: Optional[List[str]] = None,
    enforce_voice_prefix_from_transcript: bool = False,
) -> Optional[PreparedPromptInput]:
    channel_name = getattr(client, "channel_name", "telegram")
    attachment_store = getattr(state, "attachment_store", None)
    prompt_text = prompt.strip()
    image_path: Optional[str] = None
    image_paths: List[str] = []
    document_path: Optional[str] = None
    cleanup_paths: List[str] = []
    attachment_file_ids: List[str] = []

    normalized_photo_file_ids = list(photo_file_ids or [])
    if photo_file_id and photo_file_id not in normalized_photo_file_ids:
        normalized_photo_file_ids.insert(0, photo_file_id)

    if normalized_photo_file_ids:
        progress.set_phase(
            "Downloading images from Telegram." if len(normalized_photo_file_ids) > 1 else "Downloading image from Telegram."
        )
        for current_photo_file_id in normalized_photo_file_ids:
            attachment_file_ids.append(current_photo_file_id)
            resolved_image_path, archived_summary_context = resolve_attachment_binary_or_summary(
                attachment_store,
                channel_name=channel_name,
                file_id=current_photo_file_id,
                media_label="image",
            )
            if resolved_image_path is None:
                try:
                    downloaded_image_path = download_photo_to_temp(client, config, current_photo_file_id)
                    archived_image_path = archive_media_path(
                        attachment_store,
                        channel_name=channel_name,
                        file_id=current_photo_file_id,
                        media_kind="photo",
                        source_path=downloaded_image_path,
                    )
                    if archived_image_path:
                        resolved_image_path = archived_image_path
                        try:
                            os.remove(downloaded_image_path)
                        except OSError:
                            logging.warning(
                                "Failed to remove temporary image after archiving: %s",
                                downloaded_image_path,
                            )
                    else:
                        resolved_image_path = downloaded_image_path
                        cleanup_paths.append(downloaded_image_path)
                except ValueError as exc:
                    if archived_summary_context:
                        if prompt_text:
                            prompt_text = f"{prompt_text}\n\n{archived_summary_context}"
                        else:
                            prompt_text = archived_summary_context
                    else:
                        logging.warning("Photo rejected for chat_id=%s: %s", chat_id, exc)
                        progress.mark_failure("Image request rejected.")
                        client.send_message(chat_id, str(exc), reply_to_message_id=message_id)
                        return None
                except Exception:
                    if archived_summary_context:
                        logging.warning(
                            "Photo redownload failed for chat_id=%s; using archived summary fallback.",
                            chat_id,
                        )
                        if prompt_text:
                            prompt_text = f"{prompt_text}\n\n{archived_summary_context}"
                        else:
                            prompt_text = archived_summary_context
                    else:
                        logging.exception("Photo download failed for chat_id=%s", chat_id)
                        progress.mark_failure("Image download failed.")
                        client.send_message(
                            chat_id,
                            config.image_download_error_message,
                            reply_to_message_id=message_id,
                        )
                        return None
            if resolved_image_path is not None:
                image_paths.append(resolved_image_path)

        if image_paths:
            image_path = image_paths[0]

    if voice_file_id:
        progress.set_phase("Transcribing voice message.")
        transcript = transcribe_voice_for_chat(
            state=state,
            config=config,
            client=client,
            chat_id=chat_id,
            message_id=message_id,
            voice_file_id=voice_file_id,
            echo_transcript=True,
        )
        if transcript is None:
            progress.mark_failure("Voice transcription failed.")
            return None
        if enforce_voice_prefix_from_transcript and config.required_prefixes:
            has_required_prefix, stripped_transcript = strip_required_prefix(
                transcript,
                config.required_prefixes,
                config.required_prefix_ignore_case,
            )
            if not has_required_prefix:
                maybe_suggest_voice_prefix_alias(
                    state=state,
                    config=config,
                    client=client,
                    chat_id=chat_id,
                    message_id=message_id,
                    transcript=transcript,
                )
                emit_event(
                    "bridge.request_ignored",
                    fields={
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "reason": "prefix_required_transcript",
                    },
                )
                progress.mark_failure("Voice transcript missing required prefix.")
                if not is_whatsapp_channel(client):
                    client.send_message(
                        chat_id,
                        PREFIX_HELP_MESSAGE,
                        reply_to_message_id=message_id,
                    )
                return None
            transcript = stripped_transcript
            if not transcript.strip():
                emit_event(
                    "bridge.request_rejected",
                    level=logging.WARNING,
                    fields={
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "reason": "prefix_missing_action",
                    },
                )
                progress.mark_failure("Voice transcript prefix missing action.")
                if not is_whatsapp_channel(client):
                    client.send_message(
                        chat_id,
                        PREFIX_HELP_MESSAGE,
                        reply_to_message_id=message_id,
                    )
                return None
        if prompt_text:
            prompt_text = f"{prompt_text}\n\nVoice transcript:\n{transcript}"
        else:
            prompt_text = transcript

    if document:
        attachment_file_ids.append(document.file_id)
        archived_document_summary = ""
        if attachment_store is not None:
            archived_document_summary = build_archived_attachment_summary_context(
                "file",
                attachment_store.get_summary(channel_name, document.file_id),
            )
        document_record_path, _ = resolve_attachment_binary_or_summary(
            attachment_store,
            channel_name=channel_name,
            file_id=document.file_id,
            media_label="file",
        )
        if document_record_path is not None:
            document_path = document_record_path
            file_size = os.path.getsize(document_path)
            context = build_document_analysis_context(document_path, document, file_size)
            if prompt_text:
                prompt_text = f"{prompt_text}\n\n{context}"
            else:
                prompt_text = context
        else:
            progress.set_phase("Downloading file from Telegram.")
            try:
                downloaded_document_path, file_size = download_document_to_temp(client, config, document)
                archived_document_path = archive_media_path(
                    attachment_store,
                    channel_name=channel_name,
                    file_id=document.file_id,
                    media_kind="document",
                    source_path=downloaded_document_path,
                    file_name=document.file_name,
                    mime_type=document.mime_type,
                )
                if archived_document_path:
                    document_path = archived_document_path
                    try:
                        os.remove(downloaded_document_path)
                    except OSError:
                        logging.warning(
                            "Failed to remove temporary document after archiving: %s",
                            downloaded_document_path,
                        )
                    file_size = os.path.getsize(document_path)
                else:
                    document_path = downloaded_document_path
                    cleanup_paths.append(downloaded_document_path)
                context = build_document_analysis_context(document_path, document, file_size)
                if prompt_text:
                    prompt_text = f"{prompt_text}\n\n{context}"
                else:
                    prompt_text = context
            except ValueError as exc:
                if archived_document_summary:
                    if prompt_text:
                        prompt_text = f"{prompt_text}\n\n{archived_document_summary}"
                    else:
                        prompt_text = archived_document_summary
                else:
                    logging.warning("Document rejected for chat_id=%s: %s", chat_id, exc)
                    progress.mark_failure("File request rejected.")
                    client.send_message(chat_id, str(exc), reply_to_message_id=message_id)
                    return None
            except Exception:
                if archived_document_summary:
                    logging.warning(
                        "Document redownload failed for chat_id=%s; using archived summary fallback.",
                        chat_id,
                    )
                    if prompt_text:
                        prompt_text = f"{prompt_text}\n\n{archived_document_summary}"
                    else:
                        prompt_text = archived_document_summary
                else:
                    logging.exception("Document download failed for chat_id=%s", chat_id)
                    progress.mark_failure("File download failed.")
                    client.send_message(
                        chat_id,
                        config.document_download_error_message,
                        reply_to_message_id=message_id,
                    )
                    return None

    if not prompt_text:
        progress.mark_failure("No prompt content to execute.")
        return None

    if len(prompt_text) > config.max_input_chars:
        progress.mark_failure("Input rejected as too long.")
        send_input_too_long(
            client=client,
            chat_id=chat_id,
            message_id=message_id,
            actual_length=len(prompt_text),
            max_input_chars=config.max_input_chars,
        )
        return None

    return PreparedPromptInput(
        prompt_text=prompt_text,
        image_path=image_path,
        image_paths=image_paths,
        document_path=document_path,
        cleanup_paths=cleanup_paths,
        attachment_file_ids=attachment_file_ids,
    )


def prewarm_attachment_archive_for_message(
    state: State,
    config,
    client: ChannelAdapter,
    chat_id: int,
    message: Dict[str, object],
) -> None:
    attachment_store = getattr(state, "attachment_store", None)
    if attachment_store is None:
        return
    channel_name = getattr(client, "channel_name", "telegram")

    photo_file_ids = extract_message_photo_file_ids(message)
    _, _, document = extract_message_media_payload(message)
    for photo_file_id in photo_file_ids:
        record, _ = resolve_attachment_binary_or_summary(
            attachment_store,
            channel_name=channel_name,
            file_id=photo_file_id,
            media_label="image",
        )
        if record is None:
            try:
                temp_path = download_photo_to_temp(client, config, photo_file_id)
                archived_path = archive_media_path(
                    attachment_store,
                    channel_name=channel_name,
                    file_id=photo_file_id,
                    media_kind="photo",
                    source_path=temp_path,
                )
                if archived_path:
                    os.remove(temp_path)
            except Exception:
                logging.warning(
                    "Failed to prewarm attachment archive for chat_id=%s photo_file_id=%s",
                    chat_id,
                    photo_file_id,
                    exc_info=True,
                )

    if document is not None:
        record, _ = resolve_attachment_binary_or_summary(
            attachment_store,
            channel_name=channel_name,
            file_id=document.file_id,
            media_label="file",
        )
        if record is None:
            try:
                temp_path, _ = download_document_to_temp(client, config, document)
                archived_path = archive_media_path(
                    attachment_store,
                    channel_name=channel_name,
                    file_id=document.file_id,
                    media_kind="document",
                    source_path=temp_path,
                    file_name=document.file_name,
                    mime_type=document.mime_type,
                )
                if archived_path:
                    os.remove(temp_path)
            except Exception:
                logging.warning(
                    "Failed to prewarm attachment archive for chat_id=%s document_file_id=%s",
                    chat_id,
                    document.file_id,
                    exc_info=True,
                )


def execute_prompt_with_retry(
    state_repo: StateRepository,
    config,
    client: ChannelAdapter,
    engine: EngineAdapter,
    chat_id: int,
    prompt_text: str,
    previous_thread_id: Optional[str],
    progress: ProgressReporter,
    message_thread_id: Optional[int] = None,
    message_id: Optional[int] = None,
    scope_key: Optional[str] = None,
    image_path: Optional[str] = None,
    image_paths: Optional[List[str]] = None,
    actor_user_id: Optional[int] = None,
    cancel_event: Optional[threading.Event] = None,
    session_continuity_enabled: bool = True,
) -> Optional[subprocess.CompletedProcess[str]]:
    if scope_key is None:
        scope_key = build_telegram_scope_key(chat_id, message_thread_id=message_thread_id)
    allow_automatic_retry = config.persistent_workers_enabled
    retry_attempted = False
    attempt_thread_id: Optional[str] = previous_thread_id
    attempt = 0
    normalized_image_paths = list(image_paths or [])
    if image_path and image_path not in normalized_image_paths:
        normalized_image_paths.insert(0, image_path)

    while True:
        if cancel_event is not None and cancel_event.is_set():
            emit_event(
                "bridge.request_cancelled",
                fields={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "phase": "before_executor_attempt",
                    "attempt": attempt + 1,
                },
            )
            progress.mark_failure("Execution canceled.")
            client.send_message(
                chat_id,
                REQUEST_CANCELED_MESSAGE,
                reply_to_message_id=message_id,
                message_thread_id=message_thread_id,
            )
            return None

        attempt += 1
        emit_event(
            "bridge.executor_attempt",
            fields={
                "chat_id": chat_id,
                "message_id": message_id,
                "attempt": attempt,
                "resume_mode": bool(attempt_thread_id),
                "automatic_retry_enabled": allow_automatic_retry,
            },
        )
        engine_started_at = time.monotonic()
        try:
            try:
                result = engine.run(
                    config=config,
                    prompt=prompt_text,
                    thread_id=attempt_thread_id,
                    session_key=scope_key,
                    channel_name=getattr(client, "channel_name", "telegram"),
                    actor_chat_id=chat_id,
                    actor_user_id=actor_user_id,
                    image_paths=normalized_image_paths,
                    progress_callback=progress.handle_executor_event,
                    cancel_event=cancel_event,
                )
                emit_phase_timing(
                    chat_id=chat_id,
                    message_id=message_id,
                    phase="engine_run",
                    started_at_monotonic=engine_started_at,
                    attempt=attempt,
                    success=True,
                    returncode=result.returncode,
                )
            except TypeError as exc:
                exc_text = str(exc)
                if not any(
                    token in exc_text
                    for token in (
                        "unexpected keyword argument 'session_key'",
                        "unexpected keyword argument 'channel_name'",
                        "unexpected keyword argument 'actor_chat_id'",
                        "unexpected keyword argument 'actor_user_id'",
                        "unexpected keyword argument 'image_paths'",
                    )
                ):
                    raise
                result = engine.run(
                    config=config,
                    prompt=prompt_text,
                    thread_id=attempt_thread_id,
                    image_path=normalized_image_paths[0] if normalized_image_paths else None,
                    progress_callback=progress.handle_executor_event,
                    cancel_event=cancel_event,
                )
                emit_phase_timing(
                    chat_id=chat_id,
                    message_id=message_id,
                    phase="engine_run",
                    started_at_monotonic=engine_started_at,
                    attempt=attempt,
                    success=True,
                    returncode=result.returncode,
                    fallback_signature=True,
                )
        except ExecutorCancelledError:
            emit_phase_timing(
                chat_id=chat_id,
                message_id=message_id,
                phase="engine_run",
                started_at_monotonic=engine_started_at,
                attempt=attempt,
                success=False,
                error_type="ExecutorCancelledError",
            )
            logging.info("Executor canceled for chat_id=%s", chat_id)
            emit_event(
                "bridge.request_cancelled",
                fields={"chat_id": chat_id, "message_id": message_id, "attempt": attempt},
            )
            progress.mark_failure("Execution canceled.")
            client.send_message(
                chat_id,
                REQUEST_CANCELED_MESSAGE,
                reply_to_message_id=message_id,
                message_thread_id=message_thread_id,
            )
            return None
        except subprocess.TimeoutExpired:
            emit_phase_timing(
                chat_id=chat_id,
                message_id=message_id,
                phase="engine_run",
                started_at_monotonic=engine_started_at,
                attempt=attempt,
                success=False,
                error_type="TimeoutExpired",
            )
            logging.warning("Executor timeout for chat_id=%s", chat_id)
            emit_event(
                "bridge.request_timeout",
                level=logging.WARNING,
                fields={"chat_id": chat_id, "message_id": message_id, "attempt": attempt},
            )
            progress.mark_failure("Execution timed out.")
            client.send_message(
                chat_id,
                config.timeout_message,
                reply_to_message_id=message_id,
                message_thread_id=message_thread_id,
            )
            return None
        except FileNotFoundError:
            emit_phase_timing(
                chat_id=chat_id,
                message_id=message_id,
                phase="engine_run",
                started_at_monotonic=engine_started_at,
                attempt=attempt,
                success=False,
                error_type="FileNotFoundError",
            )
            logging.exception("Executor command not found: %s", config.executor_cmd)
            emit_event(
                "bridge.executor_missing",
                level=logging.ERROR,
                fields={"chat_id": chat_id, "message_id": message_id},
            )
            progress.mark_failure("Executor command not found.")
            client.send_message(
                chat_id,
                config.generic_error_message,
                reply_to_message_id=message_id,
                message_thread_id=message_thread_id,
            )
            return None
        except Exception:
            emit_phase_timing(
                chat_id=chat_id,
                message_id=message_id,
                phase="engine_run",
                started_at_monotonic=engine_started_at,
                attempt=attempt,
                success=False,
                error_type="Exception",
            )
            logging.exception("Unexpected executor error for chat_id=%s", chat_id)
            emit_event(
                "bridge.executor_exception",
                level=logging.WARNING,
                fields={"chat_id": chat_id, "message_id": message_id, "attempt": attempt},
            )
            if allow_automatic_retry and not retry_attempted:
                retry_attempted = True
                if session_continuity_enabled:
                    state_repo.clear_thread_id(scope_key)
                attempt_thread_id = None
                progress.set_phase(RETRY_WITH_NEW_SESSION_PHASE)
                emit_event(
                    "bridge.request_retry_scheduled",
                    level=logging.WARNING,
                    fields={
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "attempt": attempt,
                        "reason": "executor_exception",
                    },
                )
                continue
            progress.mark_failure("Execution failed before completion.")
            send_executor_failure_message(
                client=client,
                config=config,
                chat_id=chat_id,
                message_id=message_id,
                allow_automatic_retry=allow_automatic_retry,
                message_thread_id=message_thread_id,
            )
            return None

        if result.returncode == 0:
            emit_event(
                "bridge.executor_completed",
                fields={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "attempt": attempt,
                },
            )
            return result

        reset_and_retry_new = False
        failure_message = extract_executor_failure_message(result.stdout or "", result.stderr or "")
        if attempt_thread_id and should_reset_thread_after_resume_failure(
            result.stderr or "",
            result.stdout or "",
        ):
            logging.warning(
                "Executor failed for chat_id=%s on resume due to invalid thread; "
                "clearing thread and retrying as new. stderr=%r",
                chat_id,
                (result.stderr or "")[-1000:],
            )
            reset_and_retry_new = True
            progress.set_phase(resume_retry_phase(config))
            emit_event(
                "bridge.request_retry_scheduled",
                level=logging.WARNING,
                fields={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "attempt": attempt,
                    "reason": "invalid_resume_thread",
                },
            )
        elif failure_message:
            logging.warning(
                "Executor failed for chat_id=%s with surfaced failure=%r",
                chat_id,
                failure_message,
            )
        elif allow_automatic_retry and not retry_attempted:
            logging.warning(
                "Executor failed for chat_id=%s; retrying once as new. returncode=%s stderr=%r",
                chat_id,
                result.returncode,
                (result.stderr or "")[-1000:],
            )
            reset_and_retry_new = True
            retry_attempted = True
            progress.set_phase(RETRY_WITH_NEW_SESSION_PHASE)
            emit_event(
                "bridge.request_retry_scheduled",
                level=logging.WARNING,
                fields={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "attempt": attempt,
                    "reason": "nonzero_exit",
                    "returncode": result.returncode,
                },
            )

        if reset_and_retry_new:
            if session_continuity_enabled:
                state_repo.clear_thread_id(scope_key)
            attempt_thread_id = None
            retry_attempted = True
            continue

        logging.error(
            "Executor failed for chat_id=%s returncode=%s stderr=%r",
            chat_id,
            result.returncode,
            (result.stderr or "")[-1000:],
        )
        emit_event(
            "bridge.request_failed",
            level=logging.WARNING,
            fields={
                "chat_id": chat_id,
                "message_id": message_id,
                "attempt": attempt,
                "returncode": result.returncode,
            },
        )
        progress.mark_failure("Execution failed.")
        send_executor_failure_message(
            client=client,
            config=config,
            chat_id=chat_id,
            message_id=message_id,
            allow_automatic_retry=allow_automatic_retry,
            failure_message=failure_message,
            message_thread_id=message_thread_id,
        )
        return None


def finalize_prompt_success(
    state_repo: StateRepository,
    config,
    client: ChannelAdapter,
    chat_id: int,
    message_id: Optional[int],
    result: subprocess.CompletedProcess[str],
    progress: ProgressReporter,
    scope_key: Optional[str] = None,
    message_thread_id: Optional[int] = None,
) -> tuple[Optional[str], str]:
    if scope_key is None:
        scope_key = build_telegram_scope_key(chat_id, message_thread_id=message_thread_id)
    new_thread_id, output = parse_executor_output(result.stdout or "")
    if new_thread_id:
        state_repo.set_thread_id(scope_key, new_thread_id)
    if not output:
        output = config.empty_output_message
    if not output_contains_control_directive(output):
        output = trim_output(output, config.max_output_chars)
    progress.mark_success()
    delivered_output = send_executor_output(
        client=client,
        chat_id=chat_id,
        message_id=message_id,
        output=output,
    )
    emit_event(
        "bridge.request_succeeded",
        fields={
            "chat_id": chat_id,
            "message_id": message_id,
            "new_thread_id": bool(new_thread_id),
            "output_chars": len(delivered_output),
        },
    )
    return new_thread_id, delivered_output


def begin_memory_turn(
    memory_engine: Optional[MemoryEngine],
    state_repo: StateRepository,
    config,
    channel_name: str,
    scope_key: str,
    prompt_text: str,
    sender_name: str,
    stateless: bool,
    chat_id: int,
) -> tuple[str, Optional[str], Optional[TurnContext]]:
    if memory_engine is None:
        return prompt_text, (None if stateless else state_repo.get_thread_id(scope_key)), None
    try:
        turn_context = memory_engine.begin_turn(
            conversation_key=resolve_memory_conversation_key(config, channel_name, scope_key),
            channel=channel_name,
            sender_name=sender_name,
            user_input=prompt_text,
            stateless=stateless,
            background_conversation_key=resolve_shared_memory_archive_key(
                config,
                channel_name,
            ),
        )
        return turn_context.prompt_text, turn_context.thread_id, turn_context
    except Exception:
        logging.exception("Failed to prepare shared memory turn for chat_id=%s", chat_id)
        return prompt_text, (None if stateless else state_repo.get_thread_id(scope_key)), None


def begin_affective_turn(
    affective_runtime,
    prompt_text: str,
    *,
    chat_id: int,
    message_id: Optional[int],
) -> tuple[str, bool]:
    if affective_runtime is None:
        return prompt_text, False
    affective_turn_started = False
    try:
        affective_runtime.begin_turn(prompt_text)
        affective_turn_started = True
        affective_prefix = (affective_runtime.prompt_prefix() or "").strip()
        if affective_prefix:
            prompt_text = f"{affective_prefix}\n\nUser request:\n{prompt_text}"
            emit_event(
                "bridge.affective_prompt_applied",
                fields={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "prefix_chars": len(affective_prefix),
                },
            )
        return prompt_text, True
    except Exception:
        logging.exception(
            "Affective runtime begin_turn failed for chat_id=%s; continuing without prefix.",
            chat_id,
        )
        if affective_turn_started:
            try:
                affective_runtime.finish_turn(success=False)
            except Exception:
                logging.exception(
                    "Affective runtime rollback failed after begin_turn error for chat_id=%s",
                    chat_id,
                )
        return prompt_text, False


def emit_request_processing_started(
    *,
    chat_id: int,
    message_id: Optional[int],
    prompt: str,
    photo_file_ids: Optional[List[str]],
    photo_file_id: Optional[str],
    voice_file_id: Optional[str],
    document: Optional[DocumentPayload],
    previous_thread_id: Optional[str],
) -> None:
    emit_event(
        "bridge.request_processing_started",
        fields={
            "chat_id": chat_id,
            "message_id": message_id,
            "prompt_chars": len(prompt or ""),
            "has_photo": bool(photo_file_ids or photo_file_id),
            "has_voice": bool(voice_file_id),
            "has_document": document is not None,
            "has_previous_thread": bool(previous_thread_id),
        },
    )


def emit_phase_timing(
    *,
    chat_id: int,
    message_id: Optional[int],
    phase: str,
    started_at_monotonic: float,
    **extra_fields,
) -> None:
    fields = {
        "chat_id": chat_id,
        "message_id": message_id,
        "phase": phase,
        "duration_ms": int(max(0.0, (time.monotonic() - started_at_monotonic) * 1000.0)),
    }
    for key, value in extra_fields.items():
        if value is not None:
            fields[key] = value
    emit_event("bridge.request_phase_timing", fields=fields)


def process_prompt(
    state: State,
    config,
    client: ChannelAdapter,
    engine: Optional[EngineAdapter],
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    prompt: str,
    photo_file_id: Optional[str],
    voice_file_id: Optional[str],
    document: Optional[DocumentPayload],
    cancel_event: Optional[threading.Event] = None,
    stateless: bool = False,
    sender_name: str = "Telegram User",
    photo_file_ids: Optional[List[str]] = None,
    actor_user_id: Optional[int] = None,
    enforce_voice_prefix_from_transcript: bool = False,
) -> None:
    total_started_at = time.monotonic()
    channel_name = getattr(client, "channel_name", "telegram")
    active_engine = engine or CodexEngineAdapter()
    assistant_name_label = assistant_label(config)
    state_repo = StateRepository(state)
    memory_engine = state.memory_engine if isinstance(state.memory_engine, MemoryEngine) else None
    previous_thread_id: Optional[str] = None
    turn_context: Optional[TurnContext] = None
    image_path: Optional[str] = None
    image_paths: List[str] = []
    document_path: Optional[str] = None
    cleanup_paths: List[str] = []
    attachment_file_ids: List[str] = []
    attachment_store = getattr(state, "attachment_store", None)
    affective_runtime = getattr(state, "affective_runtime", None)
    affective_turn_started = False
    affective_turn_finished = False
    progress = ProgressReporter(
        client,
        chat_id,
        message_id,
        message_thread_id,
        assistant_name_label,
        getattr(config, "progress_label", ""),
        getattr(config, "progress_elapsed_prefix", "Already"),
        getattr(config, "progress_elapsed_suffix", "s"),
    )
    try:
        progress.start()
        auth_reset_result = refresh_runtime_auth_fingerprint(state)
        if auth_reset_result["applied"]:
            counts = auth_reset_result["counts"]
            logging.warning(
                "Auth fingerprint changed mid-runtime; cleared stored thread state for %s "
                "(threads=%s worker_sessions=%s canonical_sessions=%s memory_sessions=%s).",
                assistant_name_label,
                counts["threads"],
                counts["worker_sessions"],
                counts["canonical_sessions"],
                counts["memory_sessions"],
            )
            emit_event(
                "bridge.thread_state_reset_for_auth_change",
                level=logging.WARNING,
                fields={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "thread_count": counts["threads"],
                    "worker_session_count": counts["worker_sessions"],
                    "canonical_session_count": counts["canonical_sessions"],
                    "memory_session_count": counts["memory_sessions"],
                },
            )
        prepare_started_at = time.monotonic()
        prepared = prepare_prompt_input(
            state=state,
            config=config,
            client=client,
            chat_id=chat_id,
            message_id=message_id,
            prompt=prompt,
            photo_file_id=photo_file_id,
            photo_file_ids=photo_file_ids,
            voice_file_id=voice_file_id,
            document=document,
            progress=progress,
            enforce_voice_prefix_from_transcript=enforce_voice_prefix_from_transcript,
        )
        emit_phase_timing(
            chat_id=chat_id,
            message_id=message_id,
            phase="prepare_prompt_input",
            started_at_monotonic=prepare_started_at,
            has_prepared_prompt=prepared is not None,
        )
        if prepared is None:
            return
        image_path = prepared.image_path
        image_paths = list(prepared.image_paths)
        document_path = prepared.document_path
        cleanup_paths = list(prepared.cleanup_paths)
        attachment_file_ids = list(prepared.attachment_file_ids)
        prompt_text = prepared.prompt_text
        memory_started_at = time.monotonic()
        prompt_text, previous_thread_id, turn_context = begin_memory_turn(
            memory_engine=memory_engine,
            state_repo=state_repo,
            config=config,
            channel_name=channel_name,
            scope_key=scope_key,
            prompt_text=prompt_text,
            sender_name=sender_name,
            stateless=stateless,
            chat_id=chat_id,
        )
        emit_phase_timing(
            chat_id=chat_id,
            message_id=message_id,
            phase="begin_memory_turn",
            started_at_monotonic=memory_started_at,
            memory_enabled=memory_engine is not None,
            stateless=stateless,
            reused_thread=bool(previous_thread_id),
        )
        affective_started_at = time.monotonic()
        prompt_text, affective_turn_started = begin_affective_turn(
            affective_runtime,
            prompt_text,
            chat_id=chat_id,
            message_id=message_id,
        )
        emit_phase_timing(
            chat_id=chat_id,
            message_id=message_id,
            phase="begin_affective_turn",
            started_at_monotonic=affective_started_at,
            affective_enabled=affective_runtime is not None,
            affective_applied=affective_turn_started,
        )
        emit_request_processing_started(
            chat_id=chat_id,
            message_id=message_id,
            prompt=prompt,
            photo_file_ids=photo_file_ids,
            photo_file_id=photo_file_id,
            voice_file_id=voice_file_id,
            document=document,
            previous_thread_id=previous_thread_id,
        )
        progress.set_phase(f"Sending request to {assistant_name_label}.")
        execute_started_at = time.monotonic()
        result = execute_prompt_with_retry(
            state_repo=state_repo,
            config=config,
            client=client,
            engine=active_engine,
            scope_key=scope_key,
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            message_id=message_id,
            prompt_text=prompt_text,
            previous_thread_id=previous_thread_id,
            image_path=image_path,
            image_paths=image_paths or ([image_path] if image_path else []),
            actor_user_id=actor_user_id,
            progress=progress,
            cancel_event=cancel_event,
            session_continuity_enabled=not stateless,
        )
        emit_phase_timing(
            chat_id=chat_id,
            message_id=message_id,
            phase="execute_prompt_with_retry",
            started_at_monotonic=execute_started_at,
            success=result is not None,
        )
        if result is None:
            return
        finalize_started_at = time.monotonic()
        new_thread_id, output = finalize_prompt_success(
            state_repo=state_repo,
            config=config,
            client=client,
            scope_key=scope_key,
            chat_id=chat_id,
            message_id=message_id,
            result=result,
            progress=progress,
        )
        emit_phase_timing(
            chat_id=chat_id,
            message_id=message_id,
            phase="finalize_prompt_success",
            started_at_monotonic=finalize_started_at,
            new_thread_id=bool(new_thread_id),
            output_chars=len(output),
        )
        if stateless:
            state_repo.clear_thread_id(scope_key)
        if attachment_store is not None:
            for attachment_file_id in attachment_file_ids:
                try:
                    attachment_store.update_summary(channel_name, attachment_file_id, output)
                except Exception:
                    logging.exception(
                        "Failed to persist attachment summary for channel=%s file_id=%s",
                        channel_name,
                        attachment_file_id,
                    )
        if affective_turn_started:
            try:
                affective_runtime.finish_turn(success=True)
                affective_turn_finished = True
            except Exception:
                logging.exception(
                    "Affective runtime finish_turn(success=True) failed for chat_id=%s",
                    chat_id,
                )
        if memory_engine is not None and turn_context is not None:
            if stateless:
                state_repo.clear_thread_id(scope_key)
            try:
                memory_engine.finish_turn(
                    turn_context,
                    channel=channel_name,
                    assistant_text=output,
                    new_thread_id=new_thread_id,
                    assistant_name=assistant_name_label,
                )
            except Exception:
                logging.exception("Failed to finish shared memory turn for chat_id=%s", chat_id)
    finally:
        if affective_turn_started and not affective_turn_finished and affective_runtime is not None:
            try:
                affective_runtime.finish_turn(success=False)
            except Exception:
                logging.exception(
                    "Affective runtime finish_turn(success=False) failed for chat_id=%s",
                    chat_id,
                )
        progress.close()
        clear_cancel_event(state, scope_key, expected_event=cancel_event)
        for cleanup_path in cleanup_paths:
            try:
                os.remove(cleanup_path)
            except OSError:
                logging.warning("Failed to remove temp file: %s", cleanup_path)
        finalize_chat_work(state, client, chat_id=chat_id, scope_key=scope_key)
        emit_phase_timing(
            chat_id=chat_id,
            message_id=message_id,
            phase="process_prompt_total",
            started_at_monotonic=total_started_at,
        )
        emit_event(
            "bridge.request_processing_finished",
            fields={"chat_id": chat_id, "message_id": message_id},
        )


def process_message_worker(
    state: State,
    config,
    client: ChannelAdapter,
    engine: Optional[EngineAdapter],
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    prompt: str,
    photo_file_id: Optional[str],
    voice_file_id: Optional[str],
    document: Optional[DocumentPayload],
    cancel_event: Optional[threading.Event] = None,
    stateless: bool = False,
    sender_name: str = "Telegram User",
    photo_file_ids: Optional[List[str]] = None,
    actor_user_id: Optional[int] = None,
    enforce_voice_prefix_from_transcript: bool = False,
) -> None:
    try:
        process_prompt(
            state,
            config,
            client,
            engine,
            scope_key,
            chat_id,
            message_thread_id,
            message_id,
            prompt,
            photo_file_id,
            voice_file_id,
            document,
            cancel_event,
            stateless=stateless,
            sender_name=sender_name,
            photo_file_ids=photo_file_ids,
            actor_user_id=actor_user_id,
            enforce_voice_prefix_from_transcript=enforce_voice_prefix_from_transcript,
        )
    except Exception:
        logging.exception("Unexpected message worker error for chat_id=%s", chat_id)
        emit_event(
            "bridge.request_worker_exception",
            level=logging.ERROR,
            fields={"chat_id": chat_id, "message_id": message_id},
        )
        try:
            client.send_message(
                chat_id,
                config.generic_error_message,
                reply_to_message_id=message_id,
            )
        except Exception:
            logging.exception("Failed to send worker error response for chat_id=%s", chat_id)


def process_youtube_request(
    state: State,
    config,
    client: ChannelAdapter,
    engine: Optional[EngineAdapter],
    chat_id: int,
    request_text: str,
    youtube_url: str,
    message_thread_id: Optional[int] = None,
    message_id: Optional[int] = None,
    scope_key: Optional[str] = None,
    actor_user_id: Optional[int] = None,
    cancel_event: Optional[threading.Event] = None,
) -> None:
    if scope_key is None:
        scope_key = build_telegram_scope_key(chat_id, message_thread_id=message_thread_id)
    active_engine = engine or CodexEngineAdapter()
    state_repo = StateRepository(state)
    cleanup_paths: List[str] = []
    progress = ProgressReporter(
        client,
        chat_id,
        message_id,
        message_thread_id,
        assistant_label(config),
        getattr(config, "progress_label", ""),
        getattr(config, "progress_elapsed_prefix", "Already"),
        getattr(config, "progress_elapsed_suffix", "s"),
    )
    try:
        progress.start()
        if cancel_event is not None and cancel_event.is_set():
            progress.mark_failure("Execution canceled.")
            client.send_message(
                chat_id,
                REQUEST_CANCELED_MESSAGE,
                reply_to_message_id=message_id,
                message_thread_id=message_thread_id,
            )
            return

        progress.set_phase("Fetching YouTube metadata and transcript.")
        analysis = run_youtube_analyzer(youtube_url, request_text)

        if cancel_event is not None and cancel_event.is_set():
            progress.mark_failure("Execution canceled.")
            client.send_message(
                chat_id,
                REQUEST_CANCELED_MESSAGE,
                reply_to_message_id=message_id,
                message_thread_id=message_thread_id,
            )
            return

        request_mode = str(analysis.get("request_mode") or "summary").strip().lower()
        transcript_text = str(analysis.get("transcript_text") or "").strip()

        if request_mode == "transcript" and transcript_text:
            output = build_youtube_transcript_output(config, analysis, cleanup_paths)
            progress.mark_success()
            delivered_output = send_executor_output(
                client=client,
                chat_id=chat_id,
                message_id=message_id,
                output=output,
            )
            emit_event(
                "bridge.request_succeeded",
                fields={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "new_thread_id": False,
                    "output_chars": len(delivered_output),
                },
            )
            return

        if not transcript_text:
            output = build_youtube_unavailable_message(analysis)
            progress.mark_success()
            delivered_output = send_executor_output(
                client=client,
                chat_id=chat_id,
                message_id=message_id,
                output=output,
            )
            emit_event(
                "bridge.request_succeeded",
                fields={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "new_thread_id": False,
                    "output_chars": len(delivered_output),
                },
            )
            return

        progress.set_phase("Summarizing the YouTube transcript.")
        result = execute_prompt_with_retry(
            state_repo=state_repo,
            config=config,
            client=client,
            engine=active_engine,
            scope_key=scope_key,
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            message_id=message_id,
            prompt_text=build_youtube_summary_prompt(request_text, analysis),
            previous_thread_id=None,
            image_path=None,
            actor_user_id=actor_user_id,
            progress=progress,
            cancel_event=cancel_event,
            session_continuity_enabled=False,
        )
        if result is None:
            return
        finalize_prompt_success(
            state_repo=state_repo,
            config=config,
            client=client,
            scope_key=scope_key,
            chat_id=chat_id,
            message_id=message_id,
            result=result,
            progress=progress,
        )
    finally:
        progress.close()
        clear_cancel_event(state, scope_key, expected_event=cancel_event)
        for cleanup_path in cleanup_paths:
            try:
                os.remove(cleanup_path)
            except OSError:
                logging.warning("Failed to remove temp file: %s", cleanup_path)
        finalize_chat_work(state, client, chat_id=chat_id, scope_key=scope_key)
        emit_event(
            "bridge.request_processing_finished",
            fields={"chat_id": chat_id, "message_id": message_id},
        )


def process_youtube_worker(
    state: State,
    config,
    client: ChannelAdapter,
    engine: Optional[EngineAdapter],
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    request_text: str,
    youtube_url: str,
    actor_user_id: Optional[int] = None,
    cancel_event: Optional[threading.Event] = None,
) -> None:
    try:
        process_youtube_request(
            state=state,
            config=config,
            client=client,
            engine=engine,
            scope_key=scope_key,
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            message_id=message_id,
            request_text=request_text,
            youtube_url=youtube_url,
            actor_user_id=actor_user_id,
            cancel_event=cancel_event,
        )
    except subprocess.TimeoutExpired:
        logging.warning("YouTube analysis timed out for chat_id=%s", chat_id)
        emit_event(
            "bridge.request_timeout",
            level=logging.WARNING,
            fields={"chat_id": chat_id, "message_id": message_id, "phase": "youtube_analysis"},
        )
        try:
            client.send_message(
                chat_id,
                config.timeout_message,
                reply_to_message_id=message_id,
                message_thread_id=message_thread_id,
            )
        except Exception:
            logging.exception("Failed to send YouTube timeout response for chat_id=%s", chat_id)
    except Exception:
        logging.exception("Unexpected YouTube worker error for chat_id=%s", chat_id)
        emit_event(
            "bridge.request_worker_exception",
            level=logging.ERROR,
            fields={"chat_id": chat_id, "message_id": message_id, "phase": "youtube_analysis"},
        )
        try:
            client.send_message(
                chat_id,
                config.generic_error_message,
                reply_to_message_id=message_id,
                message_thread_id=message_thread_id,
            )
        except Exception:
            logging.exception("Failed to send YouTube worker error response for chat_id=%s", chat_id)


def start_youtube_worker(
    state: State,
    config,
    client: ChannelAdapter,
    engine: Optional[EngineAdapter],
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    request_text: str,
    youtube_url: str,
    actor_user_id: Optional[int] = None,
    cancel_event: Optional[threading.Event] = None,
) -> None:
    worker = threading.Thread(
        target=process_youtube_worker,
        args=(
            state,
            config,
            client,
            engine,
            scope_key,
            chat_id,
            message_thread_id,
            message_id,
            request_text,
            youtube_url,
            actor_user_id,
            cancel_event,
        ),
        daemon=True,
    )
    worker.start()


def handle_reset_command(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
) -> None:
    state_repo = StateRepository(state)
    removed_thread = state_repo.clear_thread_id(scope_key)
    removed_worker = state_repo.clear_worker_session(scope_key) if config.persistent_workers_enabled else False
    memory_engine = state.memory_engine if isinstance(state.memory_engine, MemoryEngine) else None
    if memory_engine is not None:
        memory_channel = getattr(client, "channel_name", "telegram")
        try:
            memory_engine.clear_session(resolve_memory_conversation_key(config, memory_channel, scope_key))
        except Exception:
            logging.exception("Failed to clear shared memory session for scope=%s", scope_key)
    if removed_thread or removed_worker:
        client.send_message(
            chat_id,
            "Context reset. Your next message starts a new conversation.",
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return
    client.send_message(
        chat_id,
        "No saved context was found for this chat.",
        reply_to_message_id=message_id,
        message_thread_id=message_thread_id,
    )


def handle_restart_command(
    state: State,
    client: ChannelAdapter,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
) -> None:
    status, busy_count = request_safe_restart(state, chat_id, message_thread_id, message_id)
    emit_event(
        "bridge.restart_requested",
        fields={
            "chat_id": chat_id,
            "message_id": message_id,
            "status": status,
            "busy_count": busy_count,
        },
    )
    if status == "in_progress":
        client.send_message(
            chat_id,
            "Restart is already in progress.",
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return
    if status == "already_queued":
        client.send_message(
            chat_id,
            "Restart is already queued and will run after current work completes.",
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return
    if status == "queued":
        client.send_message(
            chat_id,
            f"Safe restart queued. Waiting for {busy_count} active request(s) to finish.",
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return

    client.send_message(
        chat_id,
        "No active request. Restarting bridge now.",
        reply_to_message_id=message_id,
        message_thread_id=message_thread_id,
    )
    trigger_restart_async(state, client, chat_id, message_thread_id, message_id)


def handle_cancel_command(
    state: State,
    client: ChannelAdapter,
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
) -> None:
    status = request_chat_cancel(state, scope_key)
    emit_event(
        "bridge.cancel_requested",
        fields={"chat_id": chat_id, "message_id": message_id, "status": status},
    )
    if status == "requested":
        client.send_message(
            chat_id,
            CANCEL_REQUESTED_MESSAGE,
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return
    if status == "already_requested":
        client.send_message(
            chat_id,
            CANCEL_ALREADY_REQUESTED_MESSAGE,
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return
    if status == "unavailable":
        client.send_message(
            chat_id,
            "Active request cannot be canceled at this stage. Please wait a few seconds and retry.",
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return
    client.send_message(
        chat_id,
        CANCEL_NO_ACTIVE_MESSAGE,
        reply_to_message_id=message_id,
        message_thread_id=message_thread_id,
    )


def build_voice_alias_help_text() -> str:
    return (
        "Voice alias learning commands:\n"
        "/voice-alias list - show pending learned corrections\n"
        "/voice-alias approve <id> - approve one suggestion\n"
        "/voice-alias reject <id> - reject one suggestion\n"
        "/voice-alias add <source> => <target> - add approved alias manually"
    )


def parse_voice_alias_suggestion_id(tail: str, action: str) -> Optional[int]:
    prefix = f"{action} "
    if not tail.lower().startswith(prefix):
        return None
    value = tail[len(prefix):].strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def handle_voice_alias_command(
    state: State,
    config,
    client: ChannelAdapter,
    chat_id: int,
    message_id: Optional[int],
    raw_text: str,
) -> bool:
    learning_store = getattr(state, "voice_alias_learning_store", None)
    if learning_store is None:
        client.send_message(
            chat_id,
            "Voice alias learning is disabled.",
            reply_to_message_id=message_id,
        )
        return True

    pieces = raw_text.strip().split(maxsplit=1)
    tail = pieces[1].strip() if len(pieces) > 1 else ""
    if not tail or tail.lower() == "help":
        client.send_message(
            chat_id,
            build_voice_alias_help_text(),
            reply_to_message_id=message_id,
        )
        return True

    if tail.lower() == "list":
        pending = learning_store.list_pending()
        if not pending:
            client.send_message(
                chat_id,
                "No pending learned voice alias suggestions.",
                reply_to_message_id=message_id,
            )
            return True
        lines = ["Pending voice alias suggestions:"]
        for suggestion in pending:
            lines.append(
                f"- #{suggestion.suggestion_id}: `{suggestion.source}` => `{suggestion.target}` (seen {suggestion.count}x)"
            )
        lines.append("Approve with: `/voice-alias approve <id>`")
        lines.append("Reject with: `/voice-alias reject <id>`")
        client.send_message(chat_id, "\n".join(lines), reply_to_message_id=message_id)
        return True

    approve_id = parse_voice_alias_suggestion_id(tail, "approve")
    if approve_id is not None:
        approved = learning_store.approve(approve_id)
        if approved is None:
            client.send_message(
                chat_id,
                f"No pending suggestion with id {approve_id}.",
                reply_to_message_id=message_id,
            )
            return True
        client.send_message(
            chat_id,
            f"Approved voice alias #{approve_id}: `{approved.source}` => `{approved.target}`",
            reply_to_message_id=message_id,
        )
        return True

    reject_id = parse_voice_alias_suggestion_id(tail, "reject")
    if reject_id is not None:
        rejected = learning_store.reject(reject_id)
        if rejected is None:
            client.send_message(
                chat_id,
                f"No pending suggestion with id {reject_id}.",
                reply_to_message_id=message_id,
            )
            return True
        client.send_message(
            chat_id,
            f"Rejected voice alias #{reject_id}: `{rejected.source}` => `{rejected.target}`",
            reply_to_message_id=message_id,
        )
        return True

    if tail.lower().startswith("add "):
        payload = tail[4:].strip()
        if "=>" not in payload:
            client.send_message(
                chat_id,
                "Usage: /voice-alias add <source> => <target>",
                reply_to_message_id=message_id,
            )
            return True
        source, target = payload.split("=>", 1)
        source = source.strip()
        target = target.strip()
        if not source or not target:
            client.send_message(
                chat_id,
                "Usage: /voice-alias add <source> => <target>",
                reply_to_message_id=message_id,
            )
            return True
        try:
            added_source, added_target = learning_store.add_manual(source, target)
        except ValueError:
            client.send_message(
                chat_id,
                "Usage: /voice-alias add <source> => <target>",
                reply_to_message_id=message_id,
            )
            return True
        client.send_message(
            chat_id,
            f"Added manual voice alias: `{added_source}` => `{added_target}`",
            reply_to_message_id=message_id,
        )
        return True

    client.send_message(
        chat_id,
        build_voice_alias_help_text(),
        reply_to_message_id=message_id,
    )
    return True


def maybe_process_voice_alias_learning_confirmation(
    state: State,
    config,
    client: ChannelAdapter,
    chat_id: int,
    message_id: Optional[int],
    prompt_input: str,
    command: Optional[str],
    priority_keyword_mode: bool,
    photo_file_id: Optional[str],
    voice_file_id: Optional[str],
    document: Optional[DocumentPayload],
    photo_file_ids: Optional[List[str]] = None,
) -> None:
    if not prompt_input.strip():
        return
    if command is not None:
        return
    if priority_keyword_mode:
        return
    if photo_file_id or photo_file_ids or voice_file_id or document is not None:
        return

    learning_store = getattr(state, "voice_alias_learning_store", None)
    if learning_store is None:
        return

    try:
        result = learning_store.consume_confirmation(
            chat_id=chat_id,
            confirmed_text=prompt_input,
            active_replacements=build_active_voice_alias_replacements(config, state),
        )
    except Exception:
        logging.exception("Failed to process voice alias learning confirmation")
        return

    if not result.suggestion_created:
        return

    message = build_voice_alias_suggestions_message(result.suggestion_created)
    if not message:
        return
    client.send_message(
        chat_id,
        message,
        reply_to_message_id=message_id,
    )


def diary_control_command(command: Optional[str]) -> bool:
    return command in {"/today", "/queue"}


def build_diary_entry_title(
    text_blocks: List[str],
    voice_transcripts: List[str],
    photo_count: int,
) -> str:
    for candidate in [*text_blocks, *voice_transcripts]:
        cleaned = " ".join(candidate.split()).strip()
        if not cleaned:
            continue
        words = cleaned.split()
        snippet = " ".join(words[:6]).strip(" .,:;!-")
        if snippet:
            return snippet[:72]
    if photo_count > 0:
        return "Photo entry"
    if voice_transcripts:
        return "Voice note"
    return "Diary entry"


def build_diary_photo_caption(message: Dict[str, object], photo_index: int) -> str:
    caption = normalize_optional_text(message.get("caption"))
    if caption:
        return caption
    return f"Photo {photo_index}"


def build_diary_queue_status(state: State, scope_key: str) -> str:
    with state.lock:
        open_batch = state.pending_diary_batches.get(scope_key)
        queued_batches = list(state.queued_diary_batches.get(scope_key, []))
        processing = scope_key in state.diary_queue_processing_scopes or scope_key in state.busy_chats
    lines = []
    lines.append(f"Processing active: {processing}")
    lines.append(f"Queued closed batches: {len(queued_batches)}")
    if open_batch is not None:
        lines.append(f"Open capture batch messages: {len(open_batch.messages)}")
    else:
        lines.append("Open capture batch messages: 0")
    if queued_batches:
        ahead = queued_batches[0]
        lines.append(f"Next queued batch messages: {len(ahead.messages)}")
    return "\n".join(lines)


def build_diary_today_status(state: State, config, scope_key: str) -> str:
    now = dt.datetime.now(diary_timezone(config))
    entries = read_day_entries(config, now.date())
    docx_path = diary_day_docx_path(config, now.date())
    remote_path = diary_day_remote_docx_path(config, now.date()) or ""
    lines = [
        f"Today: {now.date().isoformat()}",
        f"Entries saved: {len(entries)}",
        f"Local document: {docx_path}",
    ]
    if diary_nextcloud_enabled(config):
        lines.append(f"Nextcloud document: {remote_path}")
    if entries:
        latest = entries[-1]
        lines.append(f"Latest entry: {latest.time_label} - {latest.title}")
    lines.append(build_diary_queue_status(state, scope_key))
    return "\n".join(lines)


def transcribe_voice_for_diary_batch(
    config,
    client: ChannelAdapter,
    voice_file_id: str,
) -> tuple[Optional[str], Optional[str]]:
    voice_path: Optional[str] = None
    try:
        voice_path = download_voice_to_temp(client, config, voice_file_id)
        transcript, _ = transcribe_voice(config, voice_path)
        return transcript, None
    except ValueError:
        return None, config.voice_transcribe_empty_message
    except subprocess.TimeoutExpired:
        return None, config.timeout_message
    except Exception:
        return None, config.voice_transcribe_error_message
    finally:
        if voice_path:
            try:
                os.remove(voice_path)
            except OSError:
                logging.warning("Failed to remove temp diary voice file: %s", voice_path)


def process_diary_batch(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
    pending: PendingDiaryBatch,
) -> None:
    progress = ProgressReporter(
        client,
        pending.chat_id,
        pending.latest_message_id,
        pending.message_thread_id,
        assistant_label(config),
        getattr(config, "progress_label", ""),
        getattr(config, "progress_elapsed_prefix", "Already"),
        getattr(config, "progress_elapsed_suffix", "s"),
    )
    cleanup_paths: List[str] = []
    state_repo = StateRepository(state)
    cancel_event = register_cancel_event(state, scope_key)
    state_repo.mark_in_flight_request(scope_key, pending.latest_message_id)
    try:
        progress.start()
        progress.set_phase("Preparing diary entry.")
        messages = sorted(
            pending.messages,
            key=lambda item: (
                item.get("date") if isinstance(item.get("date"), int) else 0,
                item.get("message_id") if isinstance(item.get("message_id"), int) else 0,
            ),
        )
        tz = diary_timezone(config)
        timestamp_value = messages[-1].get("date") if messages else None
        if not isinstance(timestamp_value, int):
            timestamp_value = int(time.time())
        entry_dt = dt.datetime.fromtimestamp(timestamp_value, tz)
        entry_id = entry_dt.strftime("%Y%m%dT%H%M%S")
        text_blocks: List[str] = []
        voice_transcripts: List[str] = []
        notes: List[str] = []
        photos: List[DiaryPhoto] = []
        photo_index = 0

        for message in messages:
            text = normalize_optional_text(message.get("text"))
            caption = normalize_optional_text(message.get("caption"))
            if text:
                text_blocks.append(text)
            elif caption and not extract_message_photo_file_ids(message):
                text_blocks.append(caption)

            photo_file_ids = extract_message_photo_file_ids(message)
            if photo_file_ids:
                progress.set_phase(
                    "Saving diary photos." if len(photo_file_ids) > 1 else "Saving diary photo."
                )
            for photo_file_id in photo_file_ids:
                photo_index += 1
                downloaded_photo_path: Optional[str] = None
                try:
                    downloaded_photo_path = download_photo_to_temp(client, config, photo_file_id)
                    relative_path = copy_photo_to_day_assets(
                        config=config,
                        day=entry_dt.date(),
                        source_path=downloaded_photo_path,
                        entry_id=entry_id,
                        index=photo_index,
                    )
                    photos.append(
                        DiaryPhoto(
                            relative_path=relative_path,
                            caption=build_diary_photo_caption(message, photo_index),
                        )
                    )
                finally:
                    if downloaded_photo_path:
                        try:
                            os.remove(downloaded_photo_path)
                        except OSError:
                            logging.warning(
                                "Failed to remove temporary diary photo file: %s",
                                downloaded_photo_path,
                            )

            _, voice_file_id, _ = extract_message_media_payload(message)
            if voice_file_id:
                progress.set_phase("Transcribing diary voice note.")
                transcript, error_message = transcribe_voice_for_diary_batch(
                    config=config,
                    client=client,
                    voice_file_id=voice_file_id,
                )
                if transcript:
                    voice_transcripts.append(transcript)
                elif error_message:
                    notes.append(f"Voice note was received but not transcribed: {error_message}")

        if not text_blocks and not voice_transcripts and not photos:
            progress.mark_failure("No diary content to save.")
            client.send_message(
                pending.chat_id,
                "Nothing to save from that batch.",
                reply_to_message_id=pending.latest_message_id,
            )
            return

        entry = DiaryEntry(
            entry_id=entry_id,
            created_at=entry_dt.isoformat(),
            time_label=entry_dt.strftime("%I:%M %p").lstrip("0"),
            title=build_diary_entry_title(text_blocks, voice_transcripts, len(photos)),
            text_blocks=text_blocks,
            voice_transcripts=voice_transcripts,
            notes=notes,
            photos=photos,
        )

        progress.set_phase("Writing diary document.")
        docx_path = append_day_entry(config, entry_dt.date(), entry)
        remote_path = diary_day_remote_docx_path(config, entry_dt.date()) or ""
        if diary_nextcloud_enabled(config):
            progress.set_phase("Uploading diary document to Nextcloud.")
            upload_to_nextcloud(config, docx_path, remote_path)

        progress.mark_success()
        counts = []
        if text_blocks:
            counts.append(f"{len(text_blocks)} text")
        if voice_transcripts:
            counts.append(f"{len(voice_transcripts)} voice")
        if photos:
            counts.append(f"{len(photos)} photo{'s' if len(photos) != 1 else ''}")
        count_summary = ", ".join(counts) if counts else "no content"
        message = (
            f"Saved {entry.time_label} - {entry.title}.\n"
            f"Included: {count_summary}.\n"
            f"Local file: {docx_path}"
        )
        if diary_nextcloud_enabled(config):
            message += f"\nNextcloud file: {remote_path}"
        client.send_message(
            pending.chat_id,
            message,
            reply_to_message_id=pending.latest_message_id,
        )
        emit_event(
            "bridge.diary_batch_saved",
            fields={
                "chat_id": pending.chat_id,
                "message_id": pending.latest_message_id,
                "scope_key": scope_key,
                "entry_id": entry.entry_id,
                "photo_count": len(photos),
                "voice_count": len(voice_transcripts),
                "text_count": len(text_blocks),
            },
        )
    except Exception:
        logging.exception("Diary batch save failed for chat_id=%s", pending.chat_id)
        progress.mark_failure("Diary save failed.")
        client.send_message(
            pending.chat_id,
            config.generic_error_message,
            reply_to_message_id=pending.latest_message_id,
        )
    finally:
        progress.close()
        clear_cancel_event(state, scope_key, expected_event=cancel_event)
        for cleanup_path in cleanup_paths:
            try:
                os.remove(cleanup_path)
            except OSError:
                logging.warning("Failed to remove temp file: %s", cleanup_path)
        finalize_chat_work(state, client, chat_id=pending.chat_id, scope_key=scope_key)
        emit_event(
            "bridge.diary_batch_finished",
            fields={"chat_id": pending.chat_id, "message_id": pending.latest_message_id},
        )


def ensure_diary_queue_processor(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
) -> None:
    should_start_worker = False
    with state.lock:
        if scope_key not in state.diary_queue_processing_scopes:
            state.diary_queue_processing_scopes.add(scope_key)
            should_start_worker = True
    if not should_start_worker:
        return
    worker = threading.Thread(
        target=diary_queue_worker,
        args=(state, config, client, scope_key),
        daemon=True,
    )
    worker.start()


def diary_capture_batch_worker(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
) -> None:
    while True:
        with state.lock:
            pending = state.pending_diary_batches.get(scope_key)
            if pending is None:
                return
            quiet_window = float(getattr(config, "diary_capture_quiet_window_seconds", 75))
            remaining = quiet_window - (time.time() - pending.last_seen_at)
        if remaining > 0:
            time.sleep(min(1.0, remaining))
            continue
        with state.lock:
            pending = state.pending_diary_batches.pop(scope_key, None)
            if pending is not None:
                queue = state.queued_diary_batches.setdefault(scope_key, [])
                queue.append(pending)
                queue_depth = len(queue)
            else:
                queue_depth = 0
        if pending is None:
            return
        emit_event(
            "bridge.diary_batch_enqueued",
            fields={
                "chat_id": pending.chat_id,
                "message_id": pending.latest_message_id,
                "scope_key": scope_key,
                "queue_depth": queue_depth,
            },
        )
        if queue_depth > 1:
            client.send_message(
                pending.chat_id,
                f"Queued. {queue_depth - 1} batch{'es' if queue_depth - 1 != 1 else ''} ahead.",
                reply_to_message_id=pending.latest_message_id,
            )
        ensure_diary_queue_processor(state, config, client, scope_key)
        return


def diary_queue_worker(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
) -> None:
    try:
        while True:
            with state.lock:
                queue = state.queued_diary_batches.get(scope_key, [])
                pending = queue[0] if queue else None
            if pending is None:
                return
            if not mark_busy(state, scope_key):
                time.sleep(0.5)
                continue
            with state.lock:
                queue = state.queued_diary_batches.get(scope_key, [])
                pending = queue.pop(0) if queue else None
                if not queue:
                    state.queued_diary_batches.pop(scope_key, None)
            if pending is None:
                finalize_chat_work(state, client, chat_id=0, scope_key=scope_key)
                continue
            process_diary_batch(
                state=state,
                config=config,
                client=client,
                scope_key=scope_key,
                pending=pending,
            )
    finally:
        with state.lock:
            state.diary_queue_processing_scopes.discard(scope_key)
            has_more = bool(state.queued_diary_batches.get(scope_key))
        if has_more:
            ensure_diary_queue_processor(state, config, client, scope_key)


def queue_diary_capture(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    sender_name: str,
    actor_user_id: Optional[int],
    message: Dict[str, object],
) -> None:
    should_start_capture_worker = False
    buffered_message_count = 0
    with state.lock:
        pending = state.pending_diary_batches.get(scope_key)
        if pending is None:
            pending = PendingDiaryBatch(
                scope_key=scope_key,
                chat_id=chat_id,
                message_thread_id=message_thread_id,
                latest_message_id=message_id,
                sender_name=sender_name,
                actor_user_id=actor_user_id,
            )
            state.pending_diary_batches[scope_key] = pending
        pending.messages.append(copy.deepcopy(message))
        pending.last_seen_at = time.time()
        pending.latest_message_id = message_id
        buffered_message_count = len(pending.messages)
        if not pending.worker_started:
            pending.worker_started = True
            should_start_capture_worker = True
    emit_event(
        "bridge.diary_batch_buffered",
        fields={
            "chat_id": chat_id,
            "message_id": message_id,
            "scope_key": scope_key,
            "buffered_message_count": buffered_message_count,
        },
    )
    if should_start_capture_worker:
        worker = threading.Thread(
            target=diary_capture_batch_worker,
            args=(state, config, client, scope_key),
            daemon=True,
        )
        worker.start()


def handle_known_command(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    command: Optional[str],
    raw_text: str,
) -> bool:
    if command == "/start":
        client.send_message(
            chat_id,
            start_command_message(config),
            reply_to_message_id=message_id,
        )
        return True
    if command in HELP_COMMAND_ALIASES:
        client.send_message(
            chat_id,
            build_help_text(config),
            reply_to_message_id=message_id,
        )
        return True
    if command == "/status":
        client.send_message(
            chat_id,
            build_status_text(state, config, chat_id=chat_id, scope_key=scope_key),
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return True
    if command == "/restart":
        handle_restart_command(state, client, chat_id, message_thread_id, message_id)
        return True
    if command == "/cancel":
        handle_cancel_command(state, client, scope_key, chat_id, message_thread_id, message_id)
        return True
    if command == "/reset":
        handle_reset_command(state, config, client, scope_key, chat_id, message_thread_id, message_id)
        return True
    if command == "/voice-alias":
        return handle_voice_alias_command(
            state=state,
            config=config,
            client=client,
            chat_id=chat_id,
            message_id=message_id,
            raw_text=raw_text,
        )
    if diary_mode_enabled(config) and command == "/today":
        client.send_message(
            chat_id,
            build_diary_today_status(state, config, scope_key),
            reply_to_message_id=message_id,
        )
        return True
    if diary_mode_enabled(config) and command == "/queue":
        client.send_message(
            chat_id,
            build_diary_queue_status(state, scope_key),
            reply_to_message_id=message_id,
        )
        return True
    return False


def start_message_worker(
    state: State,
    config,
    client: ChannelAdapter,
    engine: Optional[EngineAdapter],
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    prompt: str,
    photo_file_id: Optional[str],
    voice_file_id: Optional[str],
    document: Optional[DocumentPayload],
    cancel_event: Optional[threading.Event] = None,
    stateless: bool = False,
    sender_name: str = "Telegram User",
    photo_file_ids: Optional[List[str]] = None,
    actor_user_id: Optional[int] = None,
    enforce_voice_prefix_from_transcript: bool = False,
) -> None:
    worker = threading.Thread(
        target=process_message_worker,
        args=(
            state,
            config,
            client,
            engine,
            scope_key,
            chat_id,
            message_thread_id,
            message_id,
            prompt,
            photo_file_id,
            voice_file_id,
            document,
            cancel_event,
            stateless,
            sender_name,
            photo_file_ids,
            actor_user_id,
            enforce_voice_prefix_from_transcript,
        ),
        daemon=True,
    )
    worker.start()


def handle_update(
    state: State,
    config,
    client: ChannelAdapter,
    update: Dict[str, object],
    engine: Optional[EngineAdapter] = None,
) -> None:
    handle_update_started_at = time.monotonic()
    message, conversation_scope, message_id = extract_chat_context(update)
    if message is None or conversation_scope is None:
        return
    chat_id = conversation_scope.chat_id
    message_thread_id = conversation_scope.message_thread_id
    scope_key = conversation_scope.scope_key
    from_obj = message.get("from")
    actor_user_id = from_obj.get("id") if isinstance(from_obj, dict) and isinstance(from_obj.get("id"), int) else None
    update_id = update.get("update_id")
    update_id_int = update_id if isinstance(update_id, int) else None
    emit_event(
        "bridge.update_received",
        fields={
            "chat_id": chat_id,
            "message_id": message_id,
            "scope_key": scope_key,
            "update_id": update_id_int,
        },
    )

    chat_obj = message.get("chat")
    chat_type = chat_obj.get("type") if isinstance(chat_obj, dict) else None
    is_private_chat = isinstance(chat_type, str) and chat_type == "private"
    allow_private_unlisted = bool(getattr(config, "allow_private_chats_unlisted", False))
    allow_group_unlisted = bool(getattr(config, "allow_group_chats_unlisted", False))

    if chat_id not in config.allowed_chat_ids and not (
        (allow_private_unlisted and is_private_chat) or (allow_group_unlisted and not is_private_chat)
    ):
        logging.warning("Denied non-allowlisted chat_id=%s", chat_id)
        emit_event(
            "bridge.request_denied",
            level=logging.WARNING,
            fields={"chat_id": chat_id, "message_id": message_id, "reason": "chat_not_allowlisted"},
        )
        # For WhatsApp-plugin ingress, silent-deny avoids leaking policy to
        # unrelated groups while preserving denial telemetry.
        if config.channel_plugin != "whatsapp":
            client.send_message(chat_id, config.denied_message, reply_to_message_id=message_id)
        return

    prompt_input, photo_file_ids, voice_file_id, document = extract_prompt_and_media(message)
    if prompt_input is None and not photo_file_ids and voice_file_id is None and document is None:
        return

    prewarm_attachment_archive_for_message(
        state=state,
        config=config,
        client=client,
        chat_id=chat_id,
        message=message,
    )

    reply_context_prompt = build_reply_context_prompt(message)

    prefix_result = apply_required_prefix_gate(
        client=client,
        config=config,
        prompt_input=prompt_input,
        has_reply_context=bool(reply_context_prompt),
        voice_file_id=voice_file_id,
        document=document,
        is_private_chat=is_private_chat,
        normalize_command=normalize_command,
        strip_required_prefix=strip_required_prefix,
    )
    enforce_voice_prefix_from_transcript = prefix_result.enforce_voice_prefix_from_transcript
    prompt_input = prefix_result.prompt_input
    if prefix_result.ignored:
        emit_event(
            "bridge.request_ignored",
            fields={"chat_id": chat_id, "message_id": message_id, "reason": prefix_result.rejection_reason},
        )
        return
    if prefix_result.rejection_reason:
        emit_event(
            "bridge.request_rejected",
            level=logging.WARNING,
            fields={"chat_id": chat_id, "message_id": message_id, "reason": prefix_result.rejection_reason},
        )
        client.send_message(
            chat_id,
            prefix_result.rejection_message or PREFIX_HELP_MESSAGE,
            reply_to_message_id=message_id,
        )
        return

    sender_name = extract_sender_name(message)
    stateless = False
    command = normalize_command(prompt_input or "")

    if diary_mode_enabled(config):
        if handle_known_command(
            state,
            config,
            client,
            scope_key,
            chat_id,
            message_thread_id,
            message_id,
            command,
            prompt_input or "",
        ):
            emit_event(
                "bridge.command_handled",
                fields={"chat_id": chat_id, "message_id": message_id, "command": command or ""},
            )
            return
        queue_diary_capture(
            state=state,
            config=config,
            client=client,
            scope_key=scope_key,
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            message_id=message_id,
            sender_name=sender_name,
            actor_user_id=actor_user_id,
            message=message,
        )
        return

    priority_keyword_mode = False
    youtube_route_url: Optional[str] = None
    keyword_result = apply_priority_keyword_routing(
        config=config,
        prompt_input=prompt_input,
        command=command,
        chat_id=chat_id,
    )
    if keyword_result.rejection_reason:
        emit_event(
            "bridge.request_rejected",
            level=logging.WARNING,
            fields={"chat_id": chat_id, "message_id": message_id, "reason": keyword_result.rejection_reason},
        )
        client.send_message(
            chat_id,
            keyword_result.rejection_message or PREFIX_HELP_MESSAGE,
            reply_to_message_id=message_id,
        )
        return
    prompt_input = keyword_result.prompt_input
    command = keyword_result.command
    if keyword_result.priority_keyword_mode:
        stateless = keyword_result.stateless
        priority_keyword_mode = True
        if keyword_result.route_kind == "youtube_link":
            youtube_route_url = keyword_result.route_value
        emit_event(
            keyword_result.routed_event or "bridge.keyword_routed",
            fields={"chat_id": chat_id, "message_id": message_id},
        )

    if prompt_input:
        maybe_process_voice_alias_learning_confirmation(
            state=state,
            config=config,
            client=client,
            chat_id=chat_id,
            message_id=message_id,
            prompt_input=prompt_input,
            command=command,
            priority_keyword_mode=priority_keyword_mode,
            photo_file_id=photo_file_ids[0] if photo_file_ids else None,
            photo_file_ids=photo_file_ids,
            voice_file_id=voice_file_id,
            document=document,
        )

    memory_engine = state.memory_engine if isinstance(state.memory_engine, MemoryEngine) else None
    if memory_engine is not None and prompt_input and not priority_keyword_mode:
        memory_channel = getattr(client, "channel_name", "telegram")
        cmd_result = handle_memory_command(
            engine=memory_engine,
            conversation_key=resolve_memory_conversation_key(config, memory_channel, scope_key),
            text=prompt_input,
        )
        if cmd_result.handled:
            if cmd_result.response:
                client.send_message(
                    chat_id,
                    cmd_result.response,
                    reply_to_message_id=message_id,
                )
            if cmd_result.run_prompt is None:
                emit_event(
                    "bridge.command_handled",
                    fields={"chat_id": chat_id, "message_id": message_id, "command": command or ""},
                )
                return
            prompt_input = cmd_result.run_prompt
            stateless = cmd_result.stateless
            command = None

    if handle_known_command(
        state,
        config,
        client,
        scope_key,
        chat_id,
        message_thread_id,
        message_id,
        command,
        prompt_input or "",
    ):
        emit_event(
            "bridge.command_handled",
            fields={"chat_id": chat_id, "message_id": message_id, "command": command or ""},
        )
        return

    if memory_engine is not None and prompt_input and not priority_keyword_mode and not stateless:
        recall_response = handle_natural_language_memory_query(
            memory_engine,
            resolve_memory_conversation_key(config, memory_channel, scope_key),
            prompt_input,
        )
        if recall_response:
            client.send_message(
                chat_id,
                recall_response,
                reply_to_message_id=message_id,
            )
            emit_event(
                "bridge.command_handled",
                fields={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "command": "natural_language_memory_recall",
                },
            )
            return

    prompt = (prompt_input or "").strip()
    if reply_context_prompt:
        if prompt:
            prompt = (
                f"{reply_context_prompt}\n\n"
                "Current User Message:\n"
                f"{prompt}"
            )
        else:
            prompt = reply_context_prompt
    if not prompt and not voice_file_id and document is None:
        return

    if prompt and len(prompt) > config.max_input_chars:
        emit_event(
            "bridge.request_rejected",
            level=logging.WARNING,
            fields={"chat_id": chat_id, "message_id": message_id, "reason": "input_too_long"},
        )
        send_input_too_long(
            client=client,
            chat_id=chat_id,
            message_id=message_id,
            actual_length=len(prompt),
            max_input_chars=config.max_input_chars,
        )
        return

    if is_rate_limited(state, config, scope_key):
        emit_event(
            "bridge.request_rejected",
            level=logging.WARNING,
            fields={"chat_id": chat_id, "message_id": message_id, "reason": "rate_limited"},
        )
        client.send_message(
            chat_id,
            RATE_LIMIT_MESSAGE,
            reply_to_message_id=message_id,
        )
        return

    if not stateless:
        if not ensure_chat_worker_session(
            state,
            config,
            client,
            scope_key,
            chat_id,
            message_thread_id,
            message_id,
        ):
            emit_event(
                "bridge.request_rejected",
                level=logging.WARNING,
                fields={"chat_id": chat_id, "message_id": message_id, "reason": "worker_capacity"},
            )
            return

    if not mark_busy(state, scope_key):
        emit_event(
            "bridge.request_rejected",
            level=logging.WARNING,
            fields={"chat_id": chat_id, "message_id": message_id, "reason": "chat_busy"},
        )
        client.send_message(
            chat_id,
            config.busy_message,
            reply_to_message_id=message_id,
        )
        return
    cancel_event = register_cancel_event(state, scope_key)
    state_repo = StateRepository(state)
    state_repo.mark_in_flight_request(scope_key, message_id)
    emit_event(
        "bridge.request_accepted",
        fields={
            "chat_id": chat_id,
            "message_id": message_id,
            "scope_key": scope_key,
            "has_photo": bool(photo_file_ids),
            "has_voice": bool(voice_file_id),
            "has_document": document is not None,
            "stateless": stateless,
        },
    )
    if youtube_route_url:
        start_youtube_worker(
            state=state,
            config=config,
            client=client,
            engine=engine,
            scope_key=scope_key,
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            message_id=message_id,
            request_text=prompt,
            youtube_url=youtube_route_url,
            actor_user_id=actor_user_id,
            cancel_event=cancel_event,
        )
    else:
        start_message_worker(
            state=state,
            config=config,
            client=client,
            engine=engine,
            scope_key=scope_key,
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            message_id=message_id,
            prompt=prompt,
            photo_file_id=photo_file_ids[0] if photo_file_ids else None,
            photo_file_ids=photo_file_ids,
            voice_file_id=voice_file_id,
            document=document,
            cancel_event=cancel_event,
            stateless=stateless,
            sender_name=sender_name,
            enforce_voice_prefix_from_transcript=enforce_voice_prefix_from_transcript,
            actor_user_id=actor_user_id,
        )
    emit_event(
        "bridge.worker_started",
        fields={"chat_id": chat_id, "message_id": message_id},
    )
    emit_phase_timing(
        chat_id=chat_id,
        message_id=message_id,
        phase="handle_update_pre_worker",
        started_at_monotonic=handle_update_started_at,
        routed_youtube=bool(youtube_route_url),
        stateless=stateless,
    )
    return
