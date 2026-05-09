import json
import logging
import os
import re
import shutil
import threading
from dataclasses import dataclass
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

@dataclass(frozen=True)
class ParsedOutboundPayload:
    rendered_text: str
    directive: Optional[OutboundMediaDirective]
    payload_format: str


@dataclass(frozen=True)
class OutboundDeliveryContext:
    client: ChannelAdapter
    chat_id: int
    message_id: Optional[int]
    message_thread_id: Optional[int]
    output: str


@dataclass(frozen=True)
class OutboundRenderPlan:
    rendered_text: str
    directive: OutboundMediaDirective
    media_kind: str
    caption: Optional[str]
    follow_up_text: Optional[str]


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
    context = OutboundDeliveryContext(
        client=client,
        chat_id=chat_id,
        message_id=message_id,
        message_thread_id=message_thread_id,
        output=output,
    )
    parsed_payload = _parse_outbound_payload(context)
    if parsed_payload is None:
        return _send_raw_text_fallback(context, output or "")

    emit_event(
        "bridge.outbound_payload_parsed",
        fields={
            "chat_id": chat_id,
            "message_id": message_id,
            "payload_format": parsed_payload.payload_format,
            "has_media_directive": parsed_payload.directive is not None,
        },
    )

    if parsed_payload.directive is None:
        return _send_plain_text(context, parsed_payload.rendered_text)

    delivery_plan = _build_outbound_render_plan(context, parsed_payload)
    return _deliver_outbound_media(context, delivery_plan)

def _parse_outbound_payload(context: OutboundDeliveryContext) -> Optional[ParsedOutboundPayload]:
    structured_payload, parse_error = parse_structured_outbound_payload(context.output)
    if parse_error is not None:
        emit_event(
            "bridge.outbound_payload_parse_failed",
            level=logging.WARNING,
            fields={
                "chat_id": context.chat_id,
                "message_id": context.message_id,
                "reason": parse_error,
            },
        )
        return None

    if structured_payload is not None:
        rendered_text, directive = structured_payload
        return ParsedOutboundPayload(
            rendered_text=rendered_text,
            directive=directive,
            payload_format="json_envelope",
        )
    rendered_text, directive = parse_outbound_media_directive(context.output)
    return ParsedOutboundPayload(
        rendered_text=rendered_text,
        directive=directive,
        payload_format="legacy_directive" if directive is not None else "plain_text",
    )


def _send_raw_text_fallback(context: OutboundDeliveryContext, text: str) -> str:
    fallback_text = apply_outbound_reply_prefix(context.client, text)
    context.client.send_message(
        context.chat_id,
        fallback_text,
        reply_to_message_id=context.message_id,
        message_thread_id=context.message_thread_id,
    )
    return fallback_text


def _send_plain_text(context: OutboundDeliveryContext, rendered_text: str) -> str:
    return _send_raw_text_fallback(context, rendered_text)


def _build_outbound_render_plan(
    context: OutboundDeliveryContext,
    parsed_payload: ParsedOutboundPayload,
) -> OutboundRenderPlan:
    caption = (
        apply_outbound_reply_prefix(context.client, parsed_payload.rendered_text)
        if parsed_payload.rendered_text
        else None
    )
    follow_up_text = None
    if caption and len(caption) > TELEGRAM_CAPTION_LIMIT:
        follow_up_text = caption
        caption = None
    return OutboundRenderPlan(
        rendered_text=parsed_payload.rendered_text,
        directive=parsed_payload.directive,
        media_kind=infer_media_kind(parsed_payload.directive.media_ref),
        caption=caption,
        follow_up_text=follow_up_text,
    )


def _send_photo(context: OutboundDeliveryContext, plan: OutboundRenderPlan) -> None:
    send_chat_action_safe(context.client, context.chat_id, "upload_photo", context.message_thread_id)
    context.client.send_photo(
        chat_id=context.chat_id,
        photo=plan.directive.media_ref,
        caption=plan.caption,
        reply_to_message_id=context.message_id,
        message_thread_id=context.message_thread_id,
    )
    emit_event(
        "bridge.outbound_delivery_succeeded",
        fields={
            "chat_id": context.chat_id,
            "message_id": context.message_id,
            "media_kind": plan.media_kind,
            "send_method": "sendPhoto",
            "fallback_used": False,
        },
    )


def _send_audio(context: OutboundDeliveryContext, plan: OutboundRenderPlan) -> None:
    send_chat_action_safe(context.client, context.chat_id, "upload_audio", context.message_thread_id)
    context.client.send_audio(
        chat_id=context.chat_id,
        audio=plan.directive.media_ref,
        caption=plan.caption,
        reply_to_message_id=context.message_id,
        message_thread_id=context.message_thread_id,
    )
    emit_event(
        "bridge.outbound_delivery_succeeded",
        fields={
            "chat_id": context.chat_id,
            "message_id": context.message_id,
            "media_kind": plan.media_kind,
            "send_method": "sendAudio",
            "fallback_used": False,
        },
    )


def _send_voice_with_audio_fallback(context: OutboundDeliveryContext, plan: OutboundRenderPlan) -> None:
    send_chat_action_safe(context.client, context.chat_id, "record_voice", context.message_thread_id)
    send_chat_action_safe(context.client, context.chat_id, "upload_voice", context.message_thread_id)
    try:
        context.client.send_voice(
            chat_id=context.chat_id,
            voice=plan.directive.media_ref,
            caption=plan.caption,
            reply_to_message_id=context.message_id,
            message_thread_id=context.message_thread_id,
        )
        emit_event(
            "bridge.outbound_delivery_succeeded",
            fields={
                "chat_id": context.chat_id,
                "message_id": context.message_id,
                "media_kind": plan.media_kind,
                "send_method": "sendVoice",
                "fallback_used": False,
            },
        )
    except Exception as exc:
        if not is_voice_messages_forbidden_error(exc):
            raise
        logging.warning(
            "sendVoice forbidden for chat_id=%s; falling back to sendAudio",
            context.chat_id,
        )
        emit_event(
            "bridge.outbound_delivery_fallback",
            level=logging.WARNING,
            fields={
                "chat_id": context.chat_id,
                "message_id": context.message_id,
                "media_kind": plan.media_kind,
                "from_method": "sendVoice",
                "to_method": "sendAudio",
                "reason": "VOICE_MESSAGES_FORBIDDEN",
            },
        )
        send_chat_action_safe(context.client, context.chat_id, "upload_audio", context.message_thread_id)
        context.client.send_audio(
            chat_id=context.chat_id,
            audio=plan.directive.media_ref,
            caption=plan.caption,
            reply_to_message_id=context.message_id,
            message_thread_id=context.message_thread_id,
        )
        emit_event(
            "bridge.outbound_delivery_succeeded",
            fields={
                "chat_id": context.chat_id,
                "message_id": context.message_id,
                "media_kind": plan.media_kind,
                "send_method": "sendAudio",
                "fallback_used": True,
            },
        )


def _send_document(context: OutboundDeliveryContext, plan: OutboundRenderPlan) -> None:
    send_chat_action_safe(context.client, context.chat_id, "upload_document", context.message_thread_id)
    context.client.send_document(
        chat_id=context.chat_id,
        document=plan.directive.media_ref,
        caption=plan.caption,
        reply_to_message_id=context.message_id,
        message_thread_id=context.message_thread_id,
    )
    emit_event(
        "bridge.outbound_delivery_succeeded",
        fields={
            "chat_id": context.chat_id,
            "message_id": context.message_id,
            "media_kind": plan.media_kind,
            "send_method": "sendDocument",
            "fallback_used": False,
        },
    )


def _execute_media_delivery(context: OutboundDeliveryContext, plan: OutboundRenderPlan) -> None:
    if plan.media_kind == "photo":
        _send_photo(context, plan)
        return
    if plan.media_kind == "audio":
        if plan.directive.as_voice and is_voice_compatible_media(plan.directive.media_ref):
            _send_voice_with_audio_fallback(context, plan)
            return
        _send_audio(context, plan)
        return
    _send_document(context, plan)


def _finalize_media_delivery(context: OutboundDeliveryContext, plan: OutboundRenderPlan) -> str:
    if plan.follow_up_text:
        context.client.send_message(
            context.chat_id,
            plan.follow_up_text,
            reply_to_message_id=context.message_id,
            message_thread_id=context.message_thread_id,
        )
        return plan.follow_up_text
    if plan.caption:
        return plan.caption
    if plan.rendered_text:
        return plan.rendered_text
    return f"[media sent: {plan.directive.media_ref}]"


def _deliver_outbound_media(context: OutboundDeliveryContext, plan: OutboundRenderPlan) -> str:
    try:
        emit_event(
            "bridge.outbound_delivery_attempt",
            fields={
                "chat_id": context.chat_id,
                "message_id": context.message_id,
                "media_kind": plan.media_kind,
                "as_voice_requested": plan.directive.as_voice,
            },
        )
        _execute_media_delivery(context, plan)
    except Exception as exc:
        logging.exception(
            "Failed to send outbound media for chat_id=%s; falling back to text",
            context.chat_id,
        )
        emit_event(
            "bridge.outbound_delivery_failed",
            level=logging.ERROR,
            fields={
                "chat_id": context.chat_id,
                "message_id": context.message_id,
                "media_kind": plan.media_kind,
                "error_type": type(exc).__name__,
                "fallback_to_text": True,
            },
        )
        return _send_raw_text_fallback(context, plan.rendered_text or context.output)

    return _finalize_media_delivery(context, plan)

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
