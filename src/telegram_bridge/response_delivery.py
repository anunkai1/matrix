import json
import logging
import os
import re
import shutil
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

from telegram_bridge.background_tasks import start_daemon_thread
from telegram_bridge.channel_adapter import ChannelAdapter
from telegram_bridge.conversation_scope import parse_telegram_scope_key
from telegram_bridge.handler_models import OutboundMediaDirective
from telegram_bridge.runtime_profile import apply_outbound_reply_prefix
from telegram_bridge.session_manager import finalize_chat_work
from telegram_bridge.state_store import State
from telegram_bridge.structured_logging import emit_event
from telegram_bridge.transport import TELEGRAM_CAPTION_LIMIT

MEDIA_DIRECTIVE_TAG_RE = re.compile(r"\[\[\s*media\s*:\s*(?P<value>.+?)\s*\]\]", re.IGNORECASE)
MEDIA_DIRECTIVE_LINE_RE = re.compile(r"(?im)^\s*media\s*:\s*(?P<value>.+?)\s*$")
AUDIO_AS_VOICE_TAG_RE = re.compile(r"\[\[\s*audio_as_voice\s*\]\]", re.IGNORECASE)
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
AUDIO_EXTENSIONS = {".ogg", ".oga", ".opus", ".mp3", ".m4a", ".aac", ".wav", ".flac"}
VOICE_COMPATIBLE_EXTENSIONS = {".ogg", ".oga", ".opus", ".mp3", ".m4a"}

RETRY_FAILED_MESSAGE = "Execution failed after an automatic retry. Please resend your request."
REQUEST_CANCELED_MESSAGE = "Request canceled."

EXECUTOR_USAGE_LIMIT_RE = re.compile(r"\bhit your usage limit\b", re.IGNORECASE)
EXECUTOR_RETRY_AT_RE = re.compile(r"\btry again at ([0-9]{1,2}:\d{2}\s*[AP]M)\b", re.IGNORECASE)

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
    message_thread_id: Optional[int] = None,
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
        client.send_message(
            chat_id,
            fallback_text,
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
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
        client.send_message(
            chat_id,
            rendered_text,
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
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
            send_chat_action_safe(client, chat_id, "upload_photo", message_thread_id)
            client.send_photo(
                chat_id=chat_id,
                photo=directive.media_ref,
                caption=caption,
                reply_to_message_id=message_id,
                message_thread_id=message_thread_id,
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
                send_chat_action_safe(client, chat_id, "record_voice", message_thread_id)
                send_chat_action_safe(client, chat_id, "upload_voice", message_thread_id)
                try:
                    client.send_voice(
                        chat_id=chat_id,
                        voice=directive.media_ref,
                        caption=caption,
                        reply_to_message_id=message_id,
                        message_thread_id=message_thread_id,
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
                    send_chat_action_safe(client, chat_id, "upload_audio", message_thread_id)
                    client.send_audio(
                        chat_id=chat_id,
                        audio=directive.media_ref,
                        caption=caption,
                        reply_to_message_id=message_id,
                        message_thread_id=message_thread_id,
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
                send_chat_action_safe(client, chat_id, "upload_audio", message_thread_id)
                client.send_audio(
                    chat_id=chat_id,
                    audio=directive.media_ref,
                    caption=caption,
                    reply_to_message_id=message_id,
                    message_thread_id=message_thread_id,
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
            send_chat_action_safe(client, chat_id, "upload_document", message_thread_id)
            client.send_document(
                chat_id=chat_id,
                document=directive.media_ref,
                caption=caption,
                reply_to_message_id=message_id,
                message_thread_id=message_thread_id,
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
        client.send_message(
            chat_id,
            fallback_text,
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return fallback_text

    if follow_up_text:
        client.send_message(
            chat_id,
            follow_up_text,
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
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

def send_canceled_response(
    client: ChannelAdapter,
    chat_id: int,
    message_id: Optional[int],
    message_thread_id: Optional[int] = None,
) -> None:
    client.send_message(
        chat_id,
        REQUEST_CANCELED_MESSAGE,
        reply_to_message_id=message_id,
        message_thread_id=message_thread_id,
    )

def send_generic_worker_error_response(
    client: ChannelAdapter,
    config,
    chat_id: int,
    message_id: Optional[int],
    message_thread_id: Optional[int] = None,
) -> None:
    client.send_message(
        chat_id,
        config.generic_error_message,
        reply_to_message_id=message_id,
        message_thread_id=message_thread_id,
    )

def send_timeout_response(
    client: ChannelAdapter,
    config,
    chat_id: int,
    message_id: Optional[int],
    message_thread_id: Optional[int] = None,
) -> None:
    client.send_message(
        chat_id,
        config.timeout_message,
        reply_to_message_id=message_id,
        message_thread_id=message_thread_id,
    )

def emit_worker_exception_and_reply(
    *,
    log_message: str,
    failure_log_message: str,
    event_fields: Dict[str, object],
    client: ChannelAdapter,
    config,
    chat_id: int,
    message_id: Optional[int],
    message_thread_id: Optional[int] = None,
) -> None:
    logging.exception(log_message, chat_id)
    emit_event(
        "bridge.request_worker_exception",
        level=logging.ERROR,
        fields=event_fields,
    )
    try:
        send_generic_worker_error_response(
            client,
            config,
            chat_id,
            message_id,
            message_thread_id,
        )
    except Exception:
        logging.exception(failure_log_message, chat_id)

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

def cleanup_temp_files(paths: List[str]) -> None:
    for cleanup_path in paths:
        try:
            os.remove(cleanup_path)
        except OSError:
            logging.warning("Failed to remove temp file: %s", cleanup_path)

def cleanup_temp_dirs(paths: List[str]) -> None:
    for cleanup_dir in paths:
        shutil.rmtree(cleanup_dir, ignore_errors=True)

def finalize_request_progress(
    *,
    progress: Any,
    state: State,
    client: ChannelAdapter,
    scope_key: str,
    chat_id: int,
    message_id: Optional[int],
    cancel_event: Optional[threading.Event],
    cleanup_paths: Optional[List[str]] = None,
    cleanup_dirs: Optional[List[str]] = None,
    finish_event_name: str = "bridge.request_processing_finished",
    finish_event_fields: Optional[Dict[str, object]] = None,
) -> None:
    progress.close()
    clear_cancel_event(state, scope_key, expected_event=cancel_event)
    cleanup_temp_files(list(cleanup_paths or []))
    cleanup_temp_dirs(list(cleanup_dirs or []))
    finalize_chat_work(state, client, chat_id=chat_id, scope_key=scope_key)
    fields: Dict[str, object] = {"chat_id": chat_id, "message_id": message_id}
    if finish_event_fields:
        fields.update(finish_event_fields)
    emit_event(finish_event_name, fields=fields)

def start_background_worker(target: Callable[..., None], *args: object) -> None:
    start_daemon_thread(target, *args)

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
