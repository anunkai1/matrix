import logging
import json
import os
import re
import shlex
import shutil
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
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from urllib import error as urllib_error
from urllib import request as urllib_request
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
    from .memory_merge import merge_conversation_keys
    from .plugin_registry import build_default_plugin_registry
    from .runtime_profile import (
        BROWSER_BRAIN_KEYWORD_HELP_MESSAGE,
        HA_KEYWORD_HELP_MESSAGE,
        HELP_COMMAND_ALIASES,
        CANCEL_COMMAND_ALIASES,
        NEXTCLOUD_KEYWORD_HELP_MESSAGE,
        PREFIX_HELP_MESSAGE,
        RETRY_WITH_NEW_SESSION_PHASE,
        SERVER3_KEYWORD_HELP_MESSAGE,
        WHATSAPP_REPLY_PREFIX,
        WHATSAPP_REPLY_PREFIX_RE,
        apply_outbound_reply_prefix,
        assistant_label,
        build_engine_progress_context_label,
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
    from .state_store import PendingDiaryBatch, RecentPhotoSelection, State, StateRepository
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
    from memory_merge import merge_conversation_keys
    from plugin_registry import build_default_plugin_registry
    from runtime_profile import (
        BROWSER_BRAIN_KEYWORD_HELP_MESSAGE,
        HA_KEYWORD_HELP_MESSAGE,
        HELP_COMMAND_ALIASES,
        CANCEL_COMMAND_ALIASES,
        NEXTCLOUD_KEYWORD_HELP_MESSAGE,
        PREFIX_HELP_MESSAGE,
        RETRY_WITH_NEW_SESSION_PHASE,
        SERVER3_KEYWORD_HELP_MESSAGE,
        WHATSAPP_REPLY_PREFIX,
        WHATSAPP_REPLY_PREFIX_RE,
        apply_outbound_reply_prefix,
        assistant_label,
        build_engine_progress_context_label,
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
    from state_store import PendingDiaryBatch, RecentPhotoSelection, State, StateRepository
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
GEMMA_HEALTH_TIMEOUT_SECONDS = 6
GEMMA_HEALTH_CURL_TIMEOUT_SECONDS = 5
DISHFRAMED_REPO_ROOT = Path(
    os.getenv("DISHFRAMED_REPO_ROOT", "/home/architect/dishframed")
).expanduser()
DISHFRAMED_PYTHON_BIN = Path(
    os.getenv("DISHFRAMED_PYTHON_BIN", str(DISHFRAMED_REPO_ROOT / ".venv/bin/python"))
).expanduser()
DISHFRAMED_USAGE_MESSAGE = (
    "Send `/dishframed` with a menu photo, or reply `/dishframed` to a menu photo."
)


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


@dataclass(frozen=True)
class KnownCommandContext:
    state: State
    config: Any
    client: ChannelAdapter
    scope_key: str
    chat_id: int
    message_thread_id: Optional[int]
    message_id: Optional[int]
    raw_text: str


KnownCommandHandler = Callable[[KnownCommandContext], bool]


@dataclass(frozen=True)
class CallbackActionContext:
    state: State
    config: Any
    client: ChannelAdapter
    scope_key: str
    chat_id: int
    message_thread_id: Optional[int]
    message_id: Optional[int]
    callback_query_id: str
    kind: str
    engine_name: str
    action: str
    value: str


@dataclass(frozen=True)
class CallbackActionResult:
    text: str
    reply_markup: Optional[Dict[str, object]] = None
    toast_text: str = "Updated."


CallbackActionHandler = Callable[[CallbackActionContext], CallbackActionResult]


@dataclass(frozen=True)
class PromptRequest:
    state: State
    config: Any
    client: ChannelAdapter
    engine: Optional[EngineAdapter]
    scope_key: str
    chat_id: int
    message_thread_id: Optional[int]
    message_id: Optional[int]
    prompt: str
    photo_file_id: Optional[str]
    voice_file_id: Optional[str]
    document: Optional[DocumentPayload]
    cancel_event: Optional[threading.Event] = None
    stateless: bool = False
    sender_name: str = "Telegram User"
    photo_file_ids: Optional[List[str]] = None
    actor_user_id: Optional[int] = None
    enforce_voice_prefix_from_transcript: bool = False


@dataclass(frozen=True)
class YoutubeRequest:
    state: State
    config: Any
    client: ChannelAdapter
    engine: Optional[EngineAdapter]
    scope_key: str
    chat_id: int
    message_thread_id: Optional[int]
    message_id: Optional[int]
    request_text: str
    youtube_url: str
    actor_user_id: Optional[int] = None
    cancel_event: Optional[threading.Event] = None


@dataclass(frozen=True)
class DishframedRequest:
    state: State
    config: Any
    client: ChannelAdapter
    scope_key: str
    chat_id: int
    message_thread_id: Optional[int]
    message_id: Optional[int]
    photo_file_ids: List[str]
    cancel_event: Optional[threading.Event] = None


@dataclass(frozen=True)
class UpdateDispatchRequest:
    state: State
    config: Any
    client: ChannelAdapter
    engine: Optional[EngineAdapter]
    scope_key: str
    chat_id: int
    message_thread_id: Optional[int]
    message_id: Optional[int]
    prompt: str
    raw_prompt: str
    photo_file_ids: List[str]
    voice_file_id: Optional[str]
    document: Optional[DocumentPayload]
    actor_user_id: Optional[int]
    sender_name: str
    stateless: bool
    enforce_voice_prefix_from_transcript: bool
    youtube_route_url: Optional[str] = None
    handle_update_started_at: Optional[float] = None


@dataclass(frozen=True)
class IncomingUpdateContext:
    update: Dict[str, object]
    message: Dict[str, object]
    chat_id: int
    message_thread_id: Optional[int]
    scope_key: str
    message_id: Optional[int]
    actor_user_id: Optional[int]
    is_private_chat: bool
    update_id: Optional[int]


@dataclass(frozen=True)
class PreparedUpdateRequest:
    ctx: IncomingUpdateContext
    prompt_input: Optional[str]
    photo_file_ids: List[str]
    voice_file_id: Optional[str]
    document: Optional[DocumentPayload]
    reply_context_prompt: str
    telegram_context_prompt: str
    enforce_voice_prefix_from_transcript: bool
    sender_name: str
    command: Optional[str]


@dataclass
class UpdateFlowState:
    state: State
    config: Any
    client: ChannelAdapter
    engine: Optional[EngineAdapter]
    ctx: IncomingUpdateContext
    prompt_input: Optional[str]
    photo_file_ids: List[str]
    voice_file_id: Optional[str]
    document: Optional[DocumentPayload]
    reply_context_prompt: str
    telegram_context_prompt: str
    enforce_voice_prefix_from_transcript: bool
    sender_name: str
    command: Optional[str]
    stateless: bool = False
    priority_keyword_mode: bool = False
    youtube_route_url: Optional[str] = None


def build_youtube_request(
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
) -> YoutubeRequest:
    return YoutubeRequest(
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


def build_dishframed_request(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    photo_file_ids: List[str],
    cancel_event: Optional[threading.Event] = None,
) -> DishframedRequest:
    return DishframedRequest(
        state=state,
        config=config,
        client=client,
        scope_key=scope_key,
        chat_id=chat_id,
        message_thread_id=message_thread_id,
        message_id=message_id,
        photo_file_ids=list(photo_file_ids),
        cancel_event=cancel_event,
    )


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
    progress: "ProgressReporter",
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
    worker = threading.Thread(
        target=target,
        args=args,
        daemon=True,
    )
    worker.start()


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


def extract_callback_query_context(
    update: Dict[str, object],
) -> tuple[Optional[Dict[str, object]], Optional[ConversationScope], Optional[int], str, str]:
    callback_query = update.get("callback_query")
    if not isinstance(callback_query, dict):
        return None, None, None, "", ""
    message = callback_query.get("message")
    if not isinstance(message, dict):
        return None, None, None, "", ""
    scope = scope_from_message(message)
    if scope is None:
        return None, None, None, "", ""
    callback_query_id = str(callback_query.get("id", "") or "").strip()
    callback_data = str(callback_query.get("data", "") or "").strip()
    message_id = message.get("message_id")
    if not isinstance(message_id, int):
        message_id = None
    return message, scope, message_id, callback_query_id, callback_data


class ProgressReporter:
    def __init__(
        self,
        client: ChannelAdapter,
        chat_id: int,
        reply_to_message_id: Optional[int],
        message_thread_id: Optional[int],
        assistant_name: str,
        progress_label: str = "",
        progress_context_label: str = "",
        compact_elapsed_prefix: str = "Already",
        compact_elapsed_suffix: str = "s",
    ) -> None:
        self.client = client
        self.chat_id = chat_id
        self.reply_to_message_id = reply_to_message_id
        self.message_thread_id = message_thread_id
        self.assistant_name = assistant_name
        self.progress_label = progress_label.strip()
        self.progress_context_label = progress_context_label.strip()
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
        if self.progress_label:
            label = self.progress_label
        elif self.progress_context_label:
            label = f"{self.assistant_name} {self.progress_context_label} is working"
        else:
            label = f"{self.assistant_name} is working"
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
    reply_message_id = reply_to.get("message_id")
    if isinstance(reply_message_id, int):
        body_parts.append(f"Original Telegram Message ID: {reply_message_id}")
    if quoted_text:
        body_parts.append(
            "Message User Replied To:\n"
            f"{quoted_text}"
        )
    if media_context:
        body_parts.append(media_context)

    return "Reply Context:\n" + sender_line + "\n\n".join(body_parts)


TELEGRAM_CONTEXT_TARGET_HINT_RE = re.compile(
    r"(?i)\b("
    r"message[_ ]id|reply[_ ]to[_ ]message[_ ]id|"
    r"use this message id|this message|reply here|reply to this|"
    r"to this chat message|reply to this chat"
    r")\b"
)


def should_include_telegram_context_prompt(
    prompt_input: Optional[str],
    reply_context_prompt: str,
    channel_name: str = "telegram",
) -> bool:
    if reply_context_prompt.strip():
        return True
    prompt_text = (prompt_input or "").strip()
    if not prompt_text:
        return False
    if (channel_name or "telegram").strip().lower() == "telegram":
        return True
    return TELEGRAM_CONTEXT_TARGET_HINT_RE.search(prompt_text) is not None


def build_telegram_context_prompt(
    chat_id: int,
    message_thread_id: Optional[int],
    scope_key: str,
    message_id: Optional[int],
    message: Dict[str, object],
) -> str:
    lines = ["Current Telegram Context:"]
    lines.append(f"- Chat ID: {chat_id}")
    if message_thread_id is not None:
        lines.append(f"- Topic ID: {message_thread_id}")
    if isinstance(message_id, int):
        lines.append(f"- Current Message ID: {message_id}")
    lines.append(f"- Scope Key: {scope_key}")

    reply_to = message.get("reply_to_message")
    if isinstance(reply_to, dict):
        reply_message_id = reply_to.get("message_id")
        if isinstance(reply_message_id, int):
            lines.append(f"- Replied-To Message ID: {reply_message_id}")

    lines.append(
        '- If the user asks to reply "here" or "to this message", '
        "default to Current Message ID unless they specify another numeric target."
    )
    lines.append(
        "- For Telegram replies, files, photos, documents, or attachments, treat this "
        "current chat/topic as authoritative. Do not infer a different chat from logs, "
        "session databases, allowlists, or recent activity."
    )
    lines.append(
        "- If the current Telegram target is missing or ambiguous, ask the user for the "
        "destination before sending. Never fall back to a different chat ID."
    )
    return "\n".join(lines)


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


RECENT_SCOPE_PHOTO_TTL_SECONDS = 600


def remember_recent_scope_photos(
    state: State,
    scope_key: str,
    message_id: int,
    photo_file_ids: List[str],
) -> None:
    if not photo_file_ids:
        return
    now = time.time()
    scope_candidates = {scope_key}
    try:
        conversation_scope = parse_telegram_scope_key(scope_key)
    except ValueError:
        conversation_scope = None
    if conversation_scope is not None:
        scope_candidates.add(build_telegram_scope_key(conversation_scope.chat_id))
    selection = RecentPhotoSelection(
        photo_file_ids=list(photo_file_ids),
        message_id=message_id,
        captured_at=now,
    )
    with state.lock:
        for candidate in scope_candidates:
            state.recent_scope_photos[candidate] = selection
        expired_scope_keys = [
            candidate
            for candidate, candidate_selection in state.recent_scope_photos.items()
            if now - candidate_selection.captured_at > RECENT_SCOPE_PHOTO_TTL_SECONDS
        ]
        for candidate in expired_scope_keys:
            state.recent_scope_photos.pop(candidate, None)


def get_recent_scope_photos(state: State, scope_key: str) -> List[str]:
    now = time.time()
    scope_candidates = [scope_key]
    try:
        conversation_scope = parse_telegram_scope_key(scope_key)
    except ValueError:
        conversation_scope = None
    if conversation_scope is not None:
        base_scope_key = build_telegram_scope_key(conversation_scope.chat_id)
        if base_scope_key not in scope_candidates:
            scope_candidates.append(base_scope_key)
    with state.lock:
        for candidate in scope_candidates:
            selection = state.recent_scope_photos.get(candidate)
            if selection is None:
                continue
            if now - selection.captured_at > RECENT_SCOPE_PHOTO_TTL_SECONDS:
                state.recent_scope_photos.pop(candidate, None)
                continue
            return list(selection.photo_file_ids)
    return []


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
    selectable = selectable_engine_plugins(config)
    engine_help_choices = ["status", *selectable, "reset"]
    minimal = (
        "Available commands:\n"
        "/start - verify bridge connectivity\n"
        "/help or /h - show this message\n"
        "/status - show bridge status and context\n"
        f"/engine {'|'.join(engine_help_choices)} - show or select this chat's engine\n"
        "/model - show this chat's current model for the active engine\n"
        "/model list - list model choices/help for the active engine\n"
        "/model <name> - set this chat's model for the active engine\n"
        "/model reset - clear this chat's model override for the active engine\n"
        "/effort - show this chat's current Codex reasoning effort\n"
        "/effort list - list effort choices/help for the active model\n"
        "/effort <low|medium|high|xhigh> - set this chat's Codex reasoning effort\n"
        "/effort reset - clear this chat's Codex reasoning effort override\n"
        "/pi - show Pi provider/model status for this chat\n"
        "/pi providers - list available Pi providers\n"
        "/pi provider <name> - set this chat's Pi provider\n"
        "/pi reset - clear this chat's Pi provider and model overrides\n"
        "/dishframed - turn a menu photo into a DishFramed preview\n"
        "/reset - clear saved context for this chat\n"
        "/cancel or /c - cancel current in-flight request for this chat\n"
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
                "Mention `server2` or `staker2` in your request to target the Server2 LAN host over SSH.\n"
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
        f"Default engine: {getattr(config, 'engine_plugin', 'codex')}",
        f"Selectable engines: {', '.join(getattr(config, 'selectable_engine_plugins', [])) or '(none)'}",
        f"Busy chats: {busy_count}",
        f"Saved Codex threads: {thread_count}",
        (
            "Persistent workers: "
            f"enabled={config.persistent_workers_enabled} "
            f"active={worker_count}/{config.persistent_workers_max} "
            f"idle_expiry=disabled"
        ),
        f"Safe restart queued: {restart_requested}",
        f"Safe restart in progress: {restart_in_progress}",
    ]

    if scope_key is not None:
        selected_engine = StateRepository(state).get_chat_engine(scope_key)
        lines.append(f"This chat has Codex thread: {has_thread}")
        lines.append(f"This chat has worker session: {has_worker}")
        lines.append(f"This chat engine: {selected_engine or getattr(config, 'engine_plugin', 'codex')}")
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
                lines.append(f"Memory messages: {memory_status.message_count}")
                lines.append(f"Memory session active: {memory_status.session_active}")

    return "\n".join(lines)


def _prepare_prompt_input_request(
    request: PromptRequest,
    progress: ProgressReporter,
) -> Optional[PreparedPromptInput]:
    state = request.state
    config = request.config
    client = request.client
    chat_id = request.chat_id
    message_id = request.message_id
    prompt = request.prompt
    photo_file_id = request.photo_file_id
    voice_file_id = request.voice_file_id
    document = request.document
    photo_file_ids = request.photo_file_ids
    enforce_voice_prefix_from_transcript = request.enforce_voice_prefix_from_transcript
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
    return _prepare_prompt_input_request(
        PromptRequest(
            state=state,
            config=config,
            client=client,
            engine=None,
            scope_key="",
            chat_id=chat_id,
            message_thread_id=None,
            message_id=message_id,
            prompt=prompt,
            photo_file_id=photo_file_id,
            voice_file_id=voice_file_id,
            document=document,
            photo_file_ids=photo_file_ids,
            enforce_voice_prefix_from_transcript=enforce_voice_prefix_from_transcript,
        ),
        progress,
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
            send_canceled_response(client, chat_id, message_id, message_thread_id)
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
            send_canceled_response(client, chat_id, message_id, message_thread_id)
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
    delivered_output = deliver_output_and_emit_success(
        client=client,
        chat_id=chat_id,
        message_id=message_id,
        output=output,
        message_thread_id=message_thread_id,
        new_thread_id=bool(new_thread_id),
    )
    return new_thread_id, delivered_output


def deliver_output_and_emit_success(
    client: ChannelAdapter,
    chat_id: int,
    message_id: Optional[int],
    output: str,
    message_thread_id: Optional[int] = None,
    new_thread_id: bool = False,
) -> str:
    delivered_output = send_executor_output(
        client=client,
        chat_id=chat_id,
        message_id=message_id,
        output=output,
        message_thread_id=message_thread_id,
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
    return delivered_output


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
    conversation_key = resolve_memory_conversation_key(config, channel_name, scope_key)
    persisted_thread_id = None if stateless else state_repo.get_thread_id(scope_key)
    if not stateless:
        try:
            if persisted_thread_id:
                memory_engine.set_session_thread_id(conversation_key, persisted_thread_id)
            else:
                memory_engine.clear_session_thread_id(conversation_key)
        except Exception:
            logging.exception(
                "Failed to sync shared memory thread state for chat_id=%s",
                chat_id,
            )
    try:
        turn_context = memory_engine.begin_turn(
            conversation_key=conversation_key,
            channel=channel_name,
            sender_name=sender_name,
            user_input=prompt_text,
            stateless=stateless,
            background_conversation_key=resolve_shared_memory_archive_key(
                config,
                channel_name,
            ),
            thread_id_override=persisted_thread_id,
        )
        return turn_context.prompt_text, persisted_thread_id, turn_context
    except Exception:
        logging.exception("Failed to prepare shared memory turn for chat_id=%s", chat_id)
        return prompt_text, persisted_thread_id, None


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


def build_progress_reporter(
    client: ChannelAdapter,
    config,
    chat_id: int,
    message_id: Optional[int],
    message_thread_id: Optional[int],
    progress_context_label: str,
) -> ProgressReporter:
    return ProgressReporter(
        client,
        chat_id,
        message_id,
        message_thread_id,
        assistant_label(config),
        getattr(config, "progress_label", ""),
        progress_context_label,
        getattr(config, "progress_elapsed_prefix", "Already"),
        getattr(config, "progress_elapsed_suffix", "s"),
    )


def _build_prompt_progress_reporter(
    request: PromptRequest,
    active_engine: EngineAdapter,
) -> ProgressReporter:
    engine_config = build_engine_runtime_config(
        request.state,
        request.config,
        request.scope_key,
        getattr(active_engine, "engine_name", ""),
    )
    return build_progress_reporter(
        request.client,
        request.config,
        request.chat_id,
        request.message_id,
        request.message_thread_id,
        build_engine_progress_context_label(
            engine_config,
            getattr(active_engine, "engine_name", ""),
        ),
    )


def _process_prompt_request(request: PromptRequest) -> None:
    state = request.state
    config = request.config
    client = request.client
    engine = request.engine
    scope_key = request.scope_key
    chat_id = request.chat_id
    message_thread_id = request.message_thread_id
    message_id = request.message_id
    prompt = request.prompt
    photo_file_id = request.photo_file_id
    voice_file_id = request.voice_file_id
    document = request.document
    cancel_event = request.cancel_event
    stateless = request.stateless
    sender_name = request.sender_name
    photo_file_ids = request.photo_file_ids
    actor_user_id = request.actor_user_id
    enforce_voice_prefix_from_transcript = request.enforce_voice_prefix_from_transcript
    total_started_at = time.monotonic()
    channel_name = getattr(client, "channel_name", "telegram")
    active_engine = engine or CodexEngineAdapter()
    assistant_name_label = assistant_label(config)
    state_repo = StateRepository(state)
    memory_engine = state.memory_engine if isinstance(state.memory_engine, MemoryEngine) else None
    engine_config = build_engine_runtime_config(
        state,
        config,
        scope_key,
        getattr(active_engine, "engine_name", ""),
    )
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
    progress = _build_prompt_progress_reporter(request, active_engine)
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
        prepared = _prepare_prompt_input_request(request, progress)
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
            config=engine_config,
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
        finalize_request_progress(
            progress=progress,
            state=state,
            client=client,
            scope_key=scope_key,
            chat_id=chat_id,
            message_id=message_id,
            cancel_event=cancel_event,
            cleanup_paths=cleanup_paths,
        )
        emit_phase_timing(
            chat_id=chat_id,
            message_id=message_id,
            phase="process_prompt_total",
            started_at_monotonic=total_started_at,
        )


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
    _process_prompt_request(
        PromptRequest(
            state=state,
            config=config,
            client=client,
            engine=engine,
            scope_key=scope_key,
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            message_id=message_id,
            prompt=prompt,
            photo_file_id=photo_file_id,
            voice_file_id=voice_file_id,
            document=document,
            cancel_event=cancel_event,
            stateless=stateless,
            sender_name=sender_name,
            photo_file_ids=photo_file_ids,
            actor_user_id=actor_user_id,
            enforce_voice_prefix_from_transcript=enforce_voice_prefix_from_transcript,
        )
    )


def _process_message_worker_request(request: PromptRequest) -> None:
    try:
        _process_prompt_request(request)
    except Exception:
        emit_worker_exception_and_reply(
            log_message="Unexpected message worker error for chat_id=%s",
            failure_log_message="Failed to send worker error response for chat_id=%s",
            event_fields={"chat_id": request.chat_id, "message_id": request.message_id},
            client=request.client,
            config=request.config,
            chat_id=request.chat_id,
            message_id=request.message_id,
            message_thread_id=request.message_thread_id,
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
    _process_message_worker_request(
        PromptRequest(
            state=state,
            config=config,
            client=client,
            engine=engine,
            scope_key=scope_key,
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            message_id=message_id,
            prompt=prompt,
            photo_file_id=photo_file_id,
            voice_file_id=voice_file_id,
            document=document,
            cancel_event=cancel_event,
            stateless=stateless,
            sender_name=sender_name,
            photo_file_ids=photo_file_ids,
            actor_user_id=actor_user_id,
            enforce_voice_prefix_from_transcript=enforce_voice_prefix_from_transcript,
        )
    )


def _process_youtube_request(request: YoutubeRequest) -> None:
    active_engine = request.engine or CodexEngineAdapter()
    state_repo = StateRepository(request.state)
    cleanup_paths: List[str] = []
    progress = build_progress_reporter(
        request.client,
        request.config,
        request.chat_id,
        request.message_id,
        request.message_thread_id,
        build_engine_progress_context_label(
            request.config,
            getattr(active_engine, "engine_name", ""),
        ),
    )
    try:
        progress.start()
        if request.cancel_event is not None and request.cancel_event.is_set():
            progress.mark_failure("Execution canceled.")
            send_canceled_response(
                request.client,
                request.chat_id,
                request.message_id,
                request.message_thread_id,
            )
            return

        progress.set_phase("Fetching YouTube metadata and transcript.")
        analysis = run_youtube_analyzer(request.youtube_url, request.request_text)

        if request.cancel_event is not None and request.cancel_event.is_set():
            progress.mark_failure("Execution canceled.")
            send_canceled_response(
                request.client,
                request.chat_id,
                request.message_id,
                request.message_thread_id,
            )
            return

        request_mode = str(analysis.get("request_mode") or "summary").strip().lower()
        transcript_text = str(analysis.get("transcript_text") or "").strip()

        if request_mode == "transcript" and transcript_text:
            output = build_youtube_transcript_output(request.config, analysis, cleanup_paths)
            progress.mark_success()
            deliver_output_and_emit_success(
                client=request.client,
                chat_id=request.chat_id,
                message_id=request.message_id,
                output=output,
                message_thread_id=request.message_thread_id,
            )
            return

        if not transcript_text:
            output = build_youtube_unavailable_message(analysis)
            progress.mark_success()
            deliver_output_and_emit_success(
                client=request.client,
                chat_id=request.chat_id,
                message_id=request.message_id,
                output=output,
                message_thread_id=request.message_thread_id,
            )
            return

        progress.set_phase("Summarizing the YouTube transcript.")
        result = execute_prompt_with_retry(
            state_repo=state_repo,
            config=request.config,
            client=request.client,
            engine=active_engine,
            scope_key=request.scope_key,
            chat_id=request.chat_id,
            message_thread_id=request.message_thread_id,
            message_id=request.message_id,
            prompt_text=build_youtube_summary_prompt(request.request_text, analysis),
            previous_thread_id=None,
            image_path=None,
            actor_user_id=request.actor_user_id,
            progress=progress,
            cancel_event=request.cancel_event,
            session_continuity_enabled=False,
        )
        if result is None:
            return
        finalize_prompt_success(
            state_repo=state_repo,
            config=request.config,
            client=request.client,
            scope_key=request.scope_key,
            chat_id=request.chat_id,
            message_id=request.message_id,
            result=result,
            progress=progress,
        )
    finally:
        finalize_request_progress(
            progress=progress,
            state=request.state,
            client=request.client,
            scope_key=request.scope_key,
            chat_id=request.chat_id,
            message_id=request.message_id,
            cancel_event=request.cancel_event,
            cleanup_paths=cleanup_paths,
        )


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
    _process_youtube_request(
        build_youtube_request(
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
    )


def _process_youtube_worker_request(request: YoutubeRequest) -> None:
    try:
        _process_youtube_request(request)
    except subprocess.TimeoutExpired:
        logging.warning("YouTube analysis timed out for chat_id=%s", request.chat_id)
        emit_event(
            "bridge.request_timeout",
            level=logging.WARNING,
            fields={
                "chat_id": request.chat_id,
                "message_id": request.message_id,
                "phase": "youtube_analysis",
            },
        )
        try:
            send_timeout_response(
                request.client,
                request.config,
                request.chat_id,
                request.message_id,
                request.message_thread_id,
            )
        except Exception:
            logging.exception(
                "Failed to send YouTube timeout response for chat_id=%s",
                request.chat_id,
            )
    except Exception:
        emit_worker_exception_and_reply(
            log_message="Unexpected YouTube worker error for chat_id=%s",
            failure_log_message="Failed to send YouTube worker error response for chat_id=%s",
            event_fields={
                "chat_id": request.chat_id,
                "message_id": request.message_id,
                "phase": "youtube_analysis",
            },
            client=request.client,
            config=request.config,
            chat_id=request.chat_id,
            message_id=request.message_id,
            message_thread_id=request.message_thread_id,
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
    _process_youtube_worker_request(
        build_youtube_request(
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
    )


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
    start_background_worker(
        _process_youtube_worker_request,
        build_youtube_request(
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
        ),
    )


def build_dishframed_command(image_paths: List[str], output_dir: str) -> List[str]:
    cmd = [
        str(DISHFRAMED_PYTHON_BIN),
        "-m",
        "dishframed",
        "frame",
        "--extractor",
        "auto",
        "--output-dir",
        output_dir,
    ]
    for image_path in image_paths:
        cmd.extend(["--image", image_path])
    return cmd


def parse_dishframed_cli_output(stdout: str) -> tuple[Optional[str], str]:
    output_path: Optional[str] = None
    preview_text = ""
    for raw_line in (stdout or "").splitlines():
        line = raw_line.strip()
        if line.startswith("Output:"):
            candidate = line.split(":", 1)[1].strip()
            if candidate:
                output_path = candidate
            continue
        if line:
            preview_text = line
    return output_path, preview_text


def run_dishframed_cli(
    *,
    image_paths: List[str],
    output_dir: str,
    timeout_seconds: int,
    cancel_event: Optional[threading.Event] = None,
) -> tuple[str, str]:
    if not DISHFRAMED_REPO_ROOT.is_dir():
        raise RuntimeError(f"DishFramed repo not found: {DISHFRAMED_REPO_ROOT}")
    if not DISHFRAMED_PYTHON_BIN.is_file():
        raise RuntimeError(f"DishFramed Python not found: {DISHFRAMED_PYTHON_BIN}")

    cmd = build_dishframed_command(image_paths, output_dir)
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(DISHFRAMED_REPO_ROOT),
    )
    stdout = ""
    stderr = ""
    started_at = time.monotonic()
    while True:
        if cancel_event is not None and cancel_event.is_set():
            process.kill()
            process.wait(timeout=5)
            raise ExecutorCancelledError("DishFramed request canceled by user.")
        if (time.monotonic() - started_at) >= float(timeout_seconds):
            process.kill()
            process.wait(timeout=5)
            raise subprocess.TimeoutExpired(cmd, timeout_seconds)
        try:
            stdout, stderr = process.communicate(timeout=0.2)
            break
        except subprocess.TimeoutExpired:
            continue

    if process.returncode != 0:
        raise RuntimeError((stderr or stdout or "DishFramed command failed.").strip())

    output_path, preview_text = parse_dishframed_cli_output(stdout)
    if not output_path:
        raise RuntimeError("DishFramed command did not report an output path.")
    return output_path, preview_text


def _process_dishframed_request(request: DishframedRequest) -> None:
    cleanup_paths: List[str] = []
    cleanup_dirs: List[str] = []
    progress = build_progress_reporter(
        request.client,
        request.config,
        request.chat_id,
        request.message_id,
        request.message_thread_id,
        "DishFramed",
    )
    try:
        progress.start()
        prepared = prepare_prompt_input(
            state=request.state,
            config=request.config,
            client=request.client,
            chat_id=request.chat_id,
            message_id=request.message_id,
            prompt="Render a DishFramed preview from these menu images.",
            photo_file_id=request.photo_file_ids[0] if request.photo_file_ids else None,
            photo_file_ids=request.photo_file_ids,
            voice_file_id=None,
            document=None,
            progress=progress,
        )
        if prepared is None:
            return
        cleanup_paths = list(prepared.cleanup_paths)
        image_paths = list(prepared.image_paths)
        if not image_paths:
            request.client.send_message(
                request.chat_id,
                DISHFRAMED_USAGE_MESSAGE,
                reply_to_message_id=request.message_id,
                message_thread_id=request.message_thread_id,
            )
            return

        output_dir = tempfile.mkdtemp(prefix="dishframed-telegram-")
        cleanup_dirs.append(output_dir)
        progress.set_phase("Rendering DishFramed preview.")
        output_path, preview_text = run_dishframed_cli(
            image_paths=image_paths,
            output_dir=output_dir,
            timeout_seconds=request.config.exec_timeout_seconds,
            cancel_event=request.cancel_event,
        )
        caption = (preview_text or "DishFramed preview attached.").strip()
        if len(caption) > TELEGRAM_CAPTION_LIMIT:
            caption = caption[: TELEGRAM_CAPTION_LIMIT - 1].rstrip() + "…"
        if infer_media_kind(output_path) == "photo":
            send_chat_action_safe(
                request.client,
                request.chat_id,
                "upload_photo",
                request.message_thread_id,
            )
            request.client.send_photo(
                chat_id=request.chat_id,
                photo=output_path,
                caption=caption,
                reply_to_message_id=request.message_id,
                message_thread_id=request.message_thread_id,
            )
        else:
            send_chat_action_safe(
                request.client,
                request.chat_id,
                "upload_document",
                request.message_thread_id,
            )
            request.client.send_document(
                chat_id=request.chat_id,
                document=output_path,
                caption=caption,
                reply_to_message_id=request.message_id,
                message_thread_id=request.message_thread_id,
            )
        progress.mark_success()
    finally:
        finalize_request_progress(
            progress=progress,
            state=request.state,
            client=request.client,
            scope_key=request.scope_key,
            chat_id=request.chat_id,
            message_id=request.message_id,
            cancel_event=request.cancel_event,
            cleanup_paths=cleanup_paths,
            cleanup_dirs=cleanup_dirs,
            finish_event_fields={"phase": "dishframed"},
        )


def process_dishframed_request(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    photo_file_ids: List[str],
    cancel_event: Optional[threading.Event] = None,
) -> None:
    _process_dishframed_request(
        build_dishframed_request(
            state=state,
            config=config,
            client=client,
            scope_key=scope_key,
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            message_id=message_id,
            photo_file_ids=photo_file_ids,
            cancel_event=cancel_event,
        )
    )


def _process_dishframed_worker_request(request: DishframedRequest) -> None:
    try:
        _process_dishframed_request(request)
    except subprocess.TimeoutExpired:
        logging.warning("DishFramed timed out for chat_id=%s", request.chat_id)
        try:
            send_timeout_response(
                request.client,
                request.config,
                request.chat_id,
                request.message_id,
                request.message_thread_id,
            )
        except Exception:
            logging.exception(
                "Failed to send DishFramed timeout response for chat_id=%s",
                request.chat_id,
            )
    except ExecutorCancelledError:
        try:
            send_canceled_response(
                request.client,
                request.chat_id,
                request.message_id,
                request.message_thread_id,
            )
        except Exception:
            logging.exception(
                "Failed to send DishFramed cancel response for chat_id=%s",
                request.chat_id,
            )
    except Exception:
        emit_worker_exception_and_reply(
            log_message="Unexpected DishFramed worker error for chat_id=%s",
            failure_log_message="Failed to send DishFramed worker error response for chat_id=%s",
            event_fields={
                "chat_id": request.chat_id,
                "message_id": request.message_id,
                "phase": "dishframed",
            },
            client=request.client,
            config=request.config,
            chat_id=request.chat_id,
            message_id=request.message_id,
            message_thread_id=request.message_thread_id,
        )


def process_dishframed_worker(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    photo_file_ids: List[str],
    cancel_event: Optional[threading.Event] = None,
) -> None:
    _process_dishframed_worker_request(
        build_dishframed_request(
            state=state,
            config=config,
            client=client,
            scope_key=scope_key,
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            message_id=message_id,
            photo_file_ids=photo_file_ids,
            cancel_event=cancel_event,
        )
    )


def start_dishframed_worker(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    photo_file_ids: List[str],
    cancel_event: Optional[threading.Event] = None,
) -> None:
    start_background_worker(
        _process_dishframed_worker_request,
        build_dishframed_request(
            state=state,
            config=config,
            client=client,
            scope_key=scope_key,
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            message_id=message_id,
            photo_file_ids=photo_file_ids,
            cancel_event=cancel_event,
        ),
    )


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
        conversation_key = resolve_memory_conversation_key(config, memory_channel, scope_key)
        shared_archive_key = resolve_shared_memory_archive_key(config, memory_channel)
        try:
            if shared_archive_key and shared_archive_key != conversation_key:
                merge_conversation_keys(
                    db_path=memory_engine.db_path,
                    source_keys=[conversation_key],
                    target_key=shared_archive_key,
                    allow_existing_target=True,
                    force_summarize_target=True,
                    min_message_score=0.75,
                )
                memory_engine.compact_summarized_messages(shared_archive_key)
            memory_engine.clear_session(conversation_key)
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


ENGINE_NAME_ALIASES = {
    "chatgpt_web": "chatgptweb",
}

PI_PROVIDER_ALIASES = {
    "ollama_ssh": "ollama",
    "ssh": "ollama",
}

PI_PROVIDER_CHOICES = (
    ("ollama", "local Ollama or SSH-tunneled Ollama"),
    ("venice", "Venice API models"),
    ("deepseek", "DeepSeek API models"),
)


def normalize_engine_name(engine_name: str) -> str:
    normalized = str(engine_name or "").strip().lower()
    return ENGINE_NAME_ALIASES.get(normalized, normalized)


def configured_default_engine(config) -> str:
    return normalize_engine_name(getattr(config, "engine_plugin", "codex") or "codex")


def selectable_engine_plugins(config) -> List[str]:
    configured: List[str] = []
    for value in getattr(config, "selectable_engine_plugins", ["codex", "gemma", "pi"]):
        normalized = normalize_engine_name(str(value))
        if normalized and normalized not in configured:
            configured.append(normalized)
    default_engine = configured_default_engine(config)
    if default_engine not in configured:
        configured.insert(0, default_engine)
    return configured


def configured_pi_provider(config) -> str:
    provider = str(getattr(config, "pi_provider", "ollama") or "ollama").strip().lower()
    return PI_PROVIDER_ALIASES.get(provider, provider) or "ollama"


def normalize_pi_provider_name(provider_name: str) -> str:
    provider = str(provider_name or "").strip().lower()
    return PI_PROVIDER_ALIASES.get(provider, provider)


def configured_pi_model(config) -> str:
    return str(getattr(config, "pi_model", "qwen3-coder:30b") or "qwen3-coder:30b").strip() or "qwen3-coder:30b"


def pi_provider_uses_ollama_tunnel(config) -> bool:
    return configured_pi_provider(config) == "ollama"


def configured_codex_model(config) -> str:
    return str(getattr(config, "codex_model", "") or "").strip()


def configured_codex_reasoning_effort(config) -> str:
    return str(getattr(config, "codex_reasoning_effort", "") or "").strip().lower()


def _codex_models_cache_path() -> Path:
    codex_home = str(os.getenv("CODEX_HOME", "") or "").strip()
    if codex_home:
        return Path(codex_home).expanduser() / "models_cache.json"
    return Path.home() / ".codex" / "models_cache.json"


def _load_codex_model_catalog() -> List[Dict[str, object]]:
    cache_path = _codex_models_cache_path()
    if not cache_path.exists():
        return []
    data = json.loads(cache_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return []
    models = data.get("models")
    if not isinstance(models, list):
        return []
    catalog: List[Dict[str, object]] = []
    seen: Set[str] = set()
    for item in models:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("slug", "") or "").strip()
        if not slug:
            continue
        visibility = str(item.get("visibility", "") or "").strip().lower()
        if visibility and visibility != "list":
            continue
        key = slug.casefold()
        if key in seen:
            continue
        seen.add(key)
        display_name = str(item.get("display_name", "") or "").strip() or slug
        efforts: List[str] = []
        raw_efforts = item.get("supported_reasoning_levels")
        if isinstance(raw_efforts, list):
            for raw_effort in raw_efforts:
                if not isinstance(raw_effort, dict):
                    continue
                effort = str(raw_effort.get("effort", "") or "").strip().lower()
                if effort and effort not in efforts:
                    efforts.append(effort)
        catalog.append(
            {
                "slug": slug,
                "display_name": display_name,
                "supported_efforts": efforts,
            }
        )
    return catalog


def _load_codex_model_choices() -> List[Tuple[str, str]]:
    choices: List[Tuple[str, str]] = []
    for item in _load_codex_model_catalog():
        slug = str(item.get("slug", "") or "").strip()
        if not slug:
            continue
        display_name = str(item.get("display_name", "") or "").strip() or slug
        choices.append((slug, display_name))
    return choices


def _supported_codex_efforts_for_model(model_name: str) -> List[str]:
    normalized_model = str(model_name or "").strip()
    default_efforts = ["low", "medium", "high", "xhigh"]
    if not normalized_model:
        return default_efforts
    folded = normalized_model.casefold()
    for item in _load_codex_model_catalog():
        slug = str(item.get("slug", "") or "").strip()
        display_name = str(item.get("display_name", "") or "").strip()
        if slug.casefold() != folded and display_name.casefold() != folded:
            continue
        efforts = [
            str(value).strip().lower()
            for value in item.get("supported_efforts", [])
            if str(value).strip()
        ]
        return efforts or default_efforts
    return default_efforts


def _resolve_codex_effort_candidate(model_name: str, requested_effort: str) -> Optional[str]:
    normalized_effort = str(requested_effort or "").strip().lower()
    if not normalized_effort:
        return None
    for effort in _supported_codex_efforts_for_model(model_name):
        if effort == normalized_effort:
            return effort
    return None


def _resolve_codex_model_candidate(requested_model: str) -> str:
    requested = str(requested_model or "").strip()
    if not requested:
        return ""
    folded = requested.casefold()
    for slug, display_name in _load_codex_model_choices():
        if slug.casefold() == folded or display_name.casefold() == folded:
            return slug
    return requested


def build_engine_runtime_config(state, config, scope_key: str, engine_name: str):
    runtime_config = copy.copy(config)
    normalized_engine = normalize_engine_name(engine_name)
    if normalized_engine == "codex":
        override_model = StateRepository(state).get_chat_codex_model(scope_key)
        override_effort = StateRepository(state).get_chat_codex_effort(scope_key)
        if not override_model and not override_effort:
            return config
        if override_model:
            runtime_config.codex_model = override_model
        if override_effort:
            runtime_config.codex_reasoning_effort = override_effort
        return runtime_config
    if normalized_engine != "pi":
        return config
    override_provider = StateRepository(state).get_chat_pi_provider(scope_key)
    override_model = StateRepository(state).get_chat_pi_model(scope_key)
    if not override_provider and not override_model:
        return config
    if override_provider:
        runtime_config.pi_provider = override_provider
    if override_model:
        runtime_config.pi_model = override_model
    return runtime_config


def _build_codex_model_source_text(state: State, scope_key: str) -> str:
    if StateRepository(state).get_chat_codex_model(scope_key):
        return "chat override"
    return "global default"


def _build_codex_effort_source_text(state: State, scope_key: str) -> str:
    if StateRepository(state).get_chat_codex_effort(scope_key):
        return "chat override"
    return "global default"


def _build_pi_provider_source_text(state: State, scope_key: str) -> str:
    if StateRepository(state).get_chat_pi_provider(scope_key):
        return "chat override"
    return "global default"


def _build_pi_model_source_text(state: State, scope_key: str) -> str:
    if StateRepository(state).get_chat_pi_model(scope_key):
        return "chat override"
    return "global default"


def _pi_provider_choice_lines(current_provider: str) -> List[str]:
    lines: List[str] = []
    for provider, description in PI_PROVIDER_CHOICES:
        marker = " (current)" if provider == current_provider else ""
        lines.append(f"- {provider}{marker} - {description}")
    return lines


def _pi_provider_description(provider_name: str) -> str:
    normalized = normalize_pi_provider_name(provider_name)
    for provider, description in PI_PROVIDER_CHOICES:
        if provider == normalized:
            return description
    return "custom Pi provider"


def _pi_provider_sort_key(provider_name: str) -> Tuple[int, str]:
    normalized = normalize_pi_provider_name(provider_name)
    for index, (provider, _description) in enumerate(PI_PROVIDER_CHOICES):
        if provider == normalized:
            return (index, normalized)
    return (len(PI_PROVIDER_CHOICES), normalized)


def _pi_available_provider_names(config) -> List[str]:
    names = {
        normalize_pi_provider_name(row_provider)
        for row_provider, row_model in _pi_model_rows(config)
        if str(row_provider).strip() and str(row_model).strip()
    }
    if not names:
        return []
    return sorted(names, key=_pi_provider_sort_key)


def build_pi_providers_text(state: State, config, scope_key: str) -> str:
    display_config = build_engine_runtime_config(state, config, scope_key, "pi")
    provider = configured_pi_provider(display_config)
    try:
        available_providers = _pi_available_provider_names(display_config)
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        available_providers = []
    lines = [
        f"Pi provider: {provider}",
        f"Pi provider source: {_build_pi_provider_source_text(state, scope_key)}",
        "Available Pi providers:",
    ]
    if available_providers:
        for provider_name in available_providers:
            marker = " (current)" if provider_name == provider else ""
            lines.append(f"- {provider_name}{marker} - {_pi_provider_description(provider_name)}")
    else:
        lines.extend(_pi_provider_choice_lines(provider))
    lines.append("Use /pi provider <name> to switch this chat.")
    return "\n".join(lines)


def _pi_provider_model_names(config) -> List[str]:
    provider = configured_pi_provider(config)
    model_names = [
        row_model
        for row_provider, row_model in _pi_model_rows(config)
        if row_provider.strip().lower() == provider
    ]
    return sorted(dict.fromkeys(model_names), key=str.casefold)


def _resolve_pi_model_candidate(available_models: List[str], requested_model: str) -> Optional[str]:
    requested = requested_model.strip()
    if not requested:
        return None
    for available in available_models:
        if available == requested:
            return available
    folded = requested.casefold()
    matches = [available for available in available_models if available.casefold() == folded]
    if len(matches) == 1:
        return matches[0]
    return None


def build_pi_models_text(state: State, config, scope_key: str) -> str:
    display_config = build_engine_runtime_config(state, config, scope_key, "pi")
    provider = configured_pi_provider(display_config)
    current_model = configured_pi_model(display_config)
    provider_source = _build_pi_provider_source_text(state, scope_key)
    source_text = _build_pi_model_source_text(state, scope_key)
    model_names = _pi_provider_model_names(display_config)
    if not model_names:
        return "\n".join(
            [
                f"Pi provider: {provider}",
                f"Pi provider source: {provider_source}",
                "No Pi models were reported for this provider.",
                "Use /engine status to check Pi health.",
            ]
        )
    lines = [
        f"Pi provider: {provider}",
        f"Pi provider source: {provider_source}",
        f"Current Pi model: {current_model} ({source_text})",
        "Available Pi models:",
    ]
    lines.extend(f"- {model_name}" for model_name in model_names)
    return "\n".join(lines)


def _run_pi_command(config, command: str) -> subprocess.CompletedProcess[str]:
    pi_bin = str(getattr(config, "pi_bin", "pi") or "pi").strip() or "pi"
    argv = shlex.split(command)
    if argv and argv[0] == "pi":
        argv[0] = pi_bin
    command_text = shlex.join(argv) if argv else shlex.quote(pi_bin)
    runner = str(getattr(config, "pi_runner", "ssh") or "ssh").strip().lower()
    timeout = GEMMA_HEALTH_TIMEOUT_SECONDS + 4
    if runner in {"local", "server3"}:
        env = None
        if pi_provider_uses_ollama_tunnel(config):
            tunnel_port = int(getattr(config, "pi_ollama_tunnel_local_port", 11435))
            env = os.environ.copy()
            env.setdefault("OLLAMA_HOST", f"http://127.0.0.1:{tunnel_port}")
        return subprocess.run(
            argv or [pi_bin],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(getattr(config, "pi_local_cwd", "") or "").strip() or None,
            env=env,
        )
    host = str(getattr(config, "pi_ssh_host", "server4-beast") or "").strip() or "server4-beast"
    return subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={GEMMA_HEALTH_TIMEOUT_SECONDS}",
            host,
            f"command -v {shlex.quote(pi_bin)} >/dev/null && {command_text}",
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _pi_model_rows(config) -> List[Tuple[str, str]]:
    completed = _run_pi_command(config, "pi --list-models")
    if completed.returncode != 0:
        raise RuntimeError(
            completed.stderr.strip()
            or completed.stdout.strip()
            or f"ssh exited {completed.returncode}"
        )
    payload = completed.stdout.strip() or completed.stderr.strip()
    return _parse_pi_model_rows(payload)


def build_pi_status_text(state: State, config, scope_key: str) -> str:
    display_config = build_engine_runtime_config(state, config, scope_key, "pi")
    provider = configured_pi_provider(display_config)
    runner = str(getattr(display_config, "pi_runner", "ssh") or "ssh").strip().lower()
    lines = [
        f"Pi provider: {provider}",
        f"Pi provider source: {_build_pi_provider_source_text(state, scope_key)}",
        f"Pi model: {configured_pi_model(display_config)}",
        f"Pi model source: {_build_pi_model_source_text(state, scope_key)}",
        f"Pi runner: {getattr(display_config, 'pi_runner', 'ssh')}",
        f"Pi session mode: {getattr(display_config, 'pi_session_mode', 'none')}",
        f"Pi tools mode: {getattr(display_config, 'pi_tools_mode', 'default')}",
        "Use /engine status to check health and availability.",
    ]
    if runner in {"local", "server3"}:
        lines.insert(4, f"Pi local cwd: {getattr(display_config, 'pi_local_cwd', '')}")
    else:
        lines.insert(4, f"Pi host: {getattr(display_config, 'pi_ssh_host', 'server4-beast')}")
    lines.append("Use /pi providers or /pi provider <name> to manage Pi providers.")
    lines.append("Use /model list and /model <name> to view or change the Pi model.")
    return "\n".join(lines)


def _brief_health_error(error: object, limit: int = 180) -> str:
    text = str(error).strip().replace("\n", " ")
    if not text:
        return "unknown error"
    if len(text) > limit:
        return text[: limit - 3].rstrip() + "..."
    return text


def _parse_ollama_tags(payload: str) -> List[str]:
    data = json.loads(payload)
    models = data.get("models", [])
    if not isinstance(models, list):
        return []
    names: List[str] = []
    for item in models:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if name:
            names.append(name)
    return names


def _parse_venice_model_ids(payload: str) -> List[str]:
    data = json.loads(payload)
    models = data.get("data", [])
    if not isinstance(models, list):
        return []
    names: List[str] = []
    for item in models:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id", "")).strip()
        if model_id:
            names.append(model_id)
    return names


def check_gemma_health(config) -> Dict[str, object]:
    provider = (
        str(getattr(config, "gemma_provider", "ollama_ssh") or "ollama_ssh")
        .strip()
        .lower()
    )
    model = str(getattr(config, "gemma_model", "gemma4:26b") or "gemma4:26b").strip()
    started = time.monotonic()
    try:
        if provider == "ollama_http":
            base_url = str(
                getattr(config, "gemma_base_url", "http://127.0.0.1:11434") or ""
            ).rstrip("/")
            if not base_url:
                raise ValueError("GEMMA_BASE_URL is empty")
            with urllib_request.urlopen(
                f"{base_url}/api/tags",
                timeout=GEMMA_HEALTH_TIMEOUT_SECONDS,
            ) as response:
                payload = response.read().decode("utf-8", errors="replace")
        elif provider == "ollama_ssh":
            host = str(getattr(config, "gemma_ssh_host", "server4-beast") or "").strip()
            if not host:
                raise ValueError("GEMMA_SSH_HOST is empty")
            remote_cmd = (
                "curl -sS "
                f"--max-time {GEMMA_HEALTH_CURL_TIMEOUT_SECONDS} "
                "http://127.0.0.1:11434/api/tags"
            )
            completed = subprocess.run(
                [
                    "ssh",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    f"ConnectTimeout={GEMMA_HEALTH_TIMEOUT_SECONDS}",
                    host,
                    remote_cmd,
                ],
                capture_output=True,
                text=True,
                timeout=GEMMA_HEALTH_TIMEOUT_SECONDS + 2,
            )
            if completed.returncode != 0:
                raise RuntimeError(
                    completed.stderr.strip()
                    or completed.stdout.strip()
                    or f"ssh exited {completed.returncode}"
                )
            payload = completed.stdout
        else:
            raise ValueError(f"unsupported provider {provider!r}")
        elapsed_ms = int((time.monotonic() - started) * 1000)
        model_names = _parse_ollama_tags(payload)
        return {
            "ok": True,
            "response_ms": elapsed_ms,
            "model_available": model in model_names,
            "error": "",
        }
    except (
        OSError,
        RuntimeError,
        ValueError,
        json.JSONDecodeError,
        subprocess.TimeoutExpired,
        urllib_error.URLError,
    ) as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return {
            "ok": False,
            "response_ms": elapsed_ms,
            "model_available": False,
            "error": _brief_health_error(exc),
        }


def check_venice_health(config) -> Dict[str, object]:
    api_key = str(getattr(config, "venice_api_key", "") or "").strip()
    base_url = str(getattr(config, "venice_base_url", "https://api.venice.ai/api/v1") or "").strip().rstrip("/")
    model = str(getattr(config, "venice_model", "mistral-31-24b") or "mistral-31-24b").strip()
    if not api_key:
        return {
            "ok": False,
            "response_ms": 0,
            "model_available": False,
            "error": "VENICE_API_KEY is missing",
        }
    if not base_url:
        return {
            "ok": False,
            "response_ms": 0,
            "model_available": False,
            "error": "VENICE_BASE_URL is empty",
        }
    started = time.monotonic()
    try:
        request = urllib_request.Request(
            f"{base_url}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            method="GET",
        )
        with urllib_request.urlopen(request, timeout=GEMMA_HEALTH_TIMEOUT_SECONDS) as response:
            payload = response.read().decode("utf-8")
        elapsed_ms = int((time.monotonic() - started) * 1000)
        model_names = _parse_venice_model_ids(payload)
        return {
            "ok": True,
            "response_ms": elapsed_ms,
            "model_available": model in model_names,
            "error": "",
        }
    except (OSError, RuntimeError, json.JSONDecodeError, subprocess.TimeoutExpired, urllib_error.URLError) as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return {
            "ok": False,
            "response_ms": elapsed_ms,
            "model_available": False,
            "error": _brief_health_error(exc),
        }


def _parse_pi_model_rows(payload: str) -> List[Tuple[str, str]]:
    rows: List[Tuple[str, str]] = []
    for raw_line in str(payload or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.lower().startswith("provider"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        rows.append((parts[0], parts[1]))
    return rows


def check_pi_health(config) -> Dict[str, object]:
    provider = configured_pi_provider(config)
    model = str(getattr(config, "pi_model", "qwen3-coder:30b") or "qwen3-coder:30b").strip()
    runner = str(getattr(config, "pi_runner", "ssh") or "ssh").strip().lower()
    host = str(getattr(config, "pi_ssh_host", "server4-beast") or "").strip()
    if runner not in {"local", "server3"} and not host:
        return {
            "ok": False,
            "response_ms": 0,
            "version": "",
            "model_available": False,
            "error": "PI_SSH_HOST is empty",
    }
    started = time.monotonic()
    try:
        version_completed = _run_pi_command(config, "pi --version")
        models_completed = _run_pi_command(config, "pi --list-models")
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if version_completed.returncode != 0:
            raise RuntimeError(
                version_completed.stderr.strip()
                or version_completed.stdout.strip()
                or f"ssh exited {version_completed.returncode}"
            )
        if models_completed.returncode != 0:
            raise RuntimeError(
                models_completed.stderr.strip()
                or models_completed.stdout.strip()
                or f"ssh exited {models_completed.returncode}"
            )
        version_output = (version_completed.stdout.strip() or version_completed.stderr.strip()).strip()
        version_lines = version_output.splitlines()
        version = version_lines[0].strip() if version_lines else ""
        models_stdout = models_completed.stdout.strip() or models_completed.stderr.strip()
        model_available = any(
            row_provider == provider and row_model == model
            for row_provider, row_model in _parse_pi_model_rows(models_stdout)
        )
        return {
            "ok": True,
            "response_ms": elapsed_ms,
            "version": version,
            "model_available": model_available if model else False,
            "error": "",
        }
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return {
            "ok": False,
            "response_ms": elapsed_ms,
            "version": "",
            "model_available": False,
            "error": _brief_health_error(exc),
        }


def check_chatgpt_web_health(config) -> Dict[str, object]:
    script = str(
        getattr(
            config,
            "chatgpt_web_bridge_script",
            str(Path(__file__).resolve().parents[2] / "ops" / "chatgpt_web_bridge.py"),
        )
        or ""
    ).strip()
    if not script:
        return {
            "ok": False,
            "response_ms": 0,
            "running": False,
            "chatgpt_tab": False,
            "error": "CHATGPT_WEB_BRIDGE_SCRIPT is empty",
        }
    cmd = [
        str(getattr(config, "chatgpt_web_python_bin", "python3") or "python3"),
        script,
        "--base-url",
        str(getattr(config, "chatgpt_web_browser_brain_url", "http://127.0.0.1:47831") or "http://127.0.0.1:47831"),
        "--service-name",
        str(getattr(config, "chatgpt_web_browser_brain_service", "server3-browser-brain.service") or "server3-browser-brain.service"),
        "--request-timeout",
        str(int(getattr(config, "chatgpt_web_request_timeout_seconds", 30) or 30)),
        "status",
    ]
    started = time.monotonic()
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=int(getattr(config, "chatgpt_web_request_timeout_seconds", 30) or 30) + 5,
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if completed.returncode != 0:
            raise RuntimeError(
                completed.stderr.strip()
                or completed.stdout.strip()
                or f"chatgpt web status exited {completed.returncode}"
            )
        payload = json.loads(completed.stdout or "{}")
        tabs = payload.get("tabs", [])
        if not isinstance(tabs, list):
            tabs = []
        chatgpt_tab = any(
            isinstance(tab, dict) and "chatgpt.com" in str(tab.get("url") or "")
            for tab in tabs
        )
        return {
            "ok": True,
            "response_ms": elapsed_ms,
            "running": bool(payload.get("running")),
            "chatgpt_tab": chatgpt_tab,
            "error": "",
        }
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return {
            "ok": False,
            "response_ms": elapsed_ms,
            "running": False,
            "chatgpt_tab": False,
            "error": _brief_health_error(exc),
        }


def build_engine_status_text(state: State, config, scope_key: str) -> str:
    selected = StateRepository(state).get_chat_engine(scope_key)
    effective = normalize_engine_name(selected or configured_default_engine(config))
    display_config = build_engine_runtime_config(state, config, scope_key, effective)
    lines = [
        f"Default engine: {configured_default_engine(config)}",
        f"This chat engine: {effective}",
        f"Selectable engines: {', '.join(selectable_engine_plugins(config))}",
        "Use /engine <name> or tap the buttons below to switch this chat.",
        "Use /engine reset to clear the chat override.",
    ]
    if effective == "codex":
        codex_model = str(getattr(display_config, "codex_model", "") or "").strip()
        lines.append(f"Codex model: {codex_model or '(default)'}")
        lines.append(
            f"Codex effort: {configured_codex_reasoning_effort(display_config) or '(default)'}"
        )
    if effective == "gemma":
        lines.append(f"Gemma provider: {getattr(config, 'gemma_provider', 'ollama_ssh')}")
        lines.append(f"Gemma model: {getattr(config, 'gemma_model', 'gemma4:26b')}")
        lines.append(f"Gemma host: {getattr(config, 'gemma_ssh_host', 'server4-beast')}")
        health = check_gemma_health(config)
        lines.append(f"Gemma health: {'ok' if health['ok'] else 'error'}")
        lines.append(f"Gemma response time: {health['response_ms']}ms")
        lines.append(f"Gemma model available: {'yes' if health['model_available'] else 'no'}")
        lines.append(f"Gemma last check error: {health['error'] or '(none)'}")
    if effective == "venice":
        lines.append(f"Venice base URL: {getattr(display_config, 'venice_base_url', 'https://api.venice.ai/api/v1')}")
        lines.append(f"Venice model: {getattr(display_config, 'venice_model', 'mistral-31-24b')}")
        lines.append(f"Venice temperature: {getattr(display_config, 'venice_temperature', 0.2)}")
        health = check_venice_health(config)
        lines.append(f"Venice health: {'ok' if health['ok'] else 'error'}")
        lines.append(f"Venice response time: {health['response_ms']}ms")
        lines.append(f"Venice model available: {'yes' if health['model_available'] else 'no'}")
        lines.append(f"Venice last check error: {health['error'] or '(none)'}")
    if effective == "pi":
        lines.append(f"Pi provider: {getattr(display_config, 'pi_provider', 'ollama')}")
        lines.append(f"Pi provider source: {_build_pi_provider_source_text(state, scope_key)}")
        lines.append(f"Pi model: {getattr(display_config, 'pi_model', 'qwen3-coder:30b')}")
        lines.append(f"Pi model source: {_build_pi_model_source_text(state, scope_key)}")
        lines.append(f"Pi runner: {getattr(display_config, 'pi_runner', 'ssh')}")
        if str(getattr(display_config, "pi_runner", "ssh") or "ssh").strip().lower() in {"local", "server3"}:
            lines.append(f"Pi local cwd: {getattr(display_config, 'pi_local_cwd', '')}")
            if pi_provider_uses_ollama_tunnel(display_config):
                if bool(getattr(display_config, "pi_ollama_tunnel_enabled", True)):
                    lines.append(
                        f"Pi Ollama tunnel: 127.0.0.1:{getattr(display_config, 'pi_ollama_tunnel_local_port', 11435)}"
                    )
                else:
                    lines.append("Pi Ollama tunnel: disabled")
            else:
                lines.append("Pi Ollama tunnel: not used for this provider")
        else:
            lines.append(f"Pi host: {getattr(display_config, 'pi_ssh_host', 'server4-beast')}")
        lines.append(f"Pi session mode: {getattr(display_config, 'pi_session_mode', 'none')}")
        lines.append(f"Pi tools mode: {getattr(display_config, 'pi_tools_mode', 'default')}")
        health = check_pi_health(display_config)
        lines.append(f"Pi health: {'ok' if health['ok'] else 'error'}")
        lines.append(f"Pi response time: {health['response_ms']}ms")
        lines.append(f"Pi version: {health['version'] or '(unknown)'}")
        lines.append(f"Pi model available: {'yes' if health['model_available'] else 'no'}")
        lines.append(f"Pi last check error: {health['error'] or '(none)'}")
        lines.append("Pi selectability: /pi providers, /pi provider <name>, /model list, /model <name>")
    if effective == "chatgptweb":
        lines.append(f"ChatGPT web URL: {getattr(display_config, 'chatgpt_web_url', 'https://chatgpt.com/')}")
        lines.append(f"ChatGPT web bridge: {getattr(display_config, 'chatgpt_web_bridge_script', '')}")
        lines.append(f"ChatGPT web Browser Brain: {getattr(display_config, 'chatgpt_web_browser_brain_url', 'http://127.0.0.1:47831')}")
        lines.append("ChatGPT web mode: experimental brittle browser bridge")
        health = check_chatgpt_web_health(display_config)
        lines.append(f"ChatGPT web health: {'ok' if health['ok'] else 'error'}")
        lines.append(f"ChatGPT web response time: {health['response_ms']}ms")
        lines.append(f"ChatGPT web Browser Brain running: {'yes' if health['running'] else 'no'}")
        lines.append(f"ChatGPT web tab visible: {'yes' if health['chatgpt_tab'] else 'no'}")
        lines.append(f"ChatGPT web last check error: {health['error'] or '(none)'}")
    return "\n".join(lines)


def _engine_callback_data(engine_name: str, action: str) -> str:
    return f"cfg|engine|{engine_name}|{action}"


def _build_engine_picker_markup(state: State, config, scope_key: str) -> Optional[Dict[str, object]]:
    current_engine = _model_active_engine_name(state, config, scope_key)
    buttons: List[Tuple[str, str]] = []
    for engine_name in selectable_engine_plugins(config):
        label = f"{engine_name} *" if engine_name == current_engine else engine_name
        buttons.append((label, _engine_callback_data(engine_name, "set")))
    if current_engine == "codex":
        buttons.append(("Model", _model_callback_data(current_engine, "menu")))
    elif current_engine == "pi":
        buttons.append(("Provider", _provider_callback_data("menu")))
        buttons.append(("Model", _model_callback_data(current_engine, "menu")))
    buttons.append(("Reset", _engine_callback_data("default", "reset")))
    markup = _compact_inline_keyboard(buttons, columns=2)
    return markup if markup.get("inline_keyboard") else None


def _set_engine_for_scope(state: State, config, scope_key: str, engine_name: str) -> str:
    normalized_engine = normalize_engine_name(engine_name)
    if normalized_engine == "venice" and not str(getattr(config, "venice_api_key", "") or "").strip():
        return "Venice engine is configured in the bridge, but VENICE_API_KEY is missing."
    allowed = selectable_engine_plugins(config)
    if normalized_engine not in allowed:
        return f"Unknown or unavailable engine: {normalized_engine}\nSelectable engines: {', '.join(allowed)}"
    StateRepository(state).set_chat_engine(scope_key, normalized_engine)
    return f"This chat now uses engine: {normalized_engine}"


def _reset_engine_for_scope(state: State, config, scope_key: str) -> str:
    removed = StateRepository(state).clear_chat_engine(scope_key)
    suffix = "removed" if removed else "already using default"
    return f"Engine override {suffix}. This chat now uses {configured_default_engine(config)}."


def handle_engine_command(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    raw_text: str,
) -> bool:
    pieces = raw_text.strip().split(maxsplit=1)
    tail = pieces[1].strip().lower() if len(pieces) > 1 else "status"
    tail = normalize_engine_name(tail)
    reply_markup: Optional[Dict[str, object]] = None
    if tail in {"", "status"}:
        text = build_engine_status_text(state, config, scope_key)
        reply_markup = _build_engine_picker_markup(state, config, scope_key)
    elif tail == "reset":
        text = _reset_engine_for_scope(state, config, scope_key)
        reply_markup = _build_engine_picker_markup(state, config, scope_key)
    else:
        text = _set_engine_for_scope(state, config, scope_key, tail)
        reply_markup = _build_engine_picker_markup(state, config, scope_key)
    client.send_message(
        chat_id,
        text,
        reply_to_message_id=message_id,
        message_thread_id=message_thread_id,
        reply_markup=reply_markup,
    )
    return True


def handle_pi_command(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    raw_text: str,
) -> bool:
    pieces = raw_text.strip().split(maxsplit=1)
    raw_tail = pieces[1].strip() if len(pieces) > 1 else "status"
    tail = raw_tail.lower()
    state_repo = StateRepository(state)
    display_config = build_engine_runtime_config(state, config, scope_key, "pi")

    if tail in {"", "status"}:
        client.send_message(
            chat_id,
            build_pi_status_text(state, config, scope_key),
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return True
    if tail == "providers":
        client.send_message(
            chat_id,
            build_pi_providers_text(state, config, scope_key),
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
            reply_markup=_build_provider_picker_markup(state, config, scope_key),
        )
        return True
    if tail == "models":
        try:
            text = build_pi_models_text(state, config, scope_key)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            text = "Failed to list Pi models.\n" f"Error: {_brief_health_error(exc)}"
        else:
            text += (
                "\n\nDeprecated alias: `/pi models` still works for compatibility, "
                "but `/model list` is the canonical command."
            )
        client.send_message(
            chat_id,
            text,
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return True
    if tail == "reset":
        removed_provider = state_repo.clear_chat_pi_provider(scope_key)
        removed_model = state_repo.clear_chat_pi_model(scope_key)
        effective_config = build_engine_runtime_config(state, config, scope_key, "pi")
        if removed_provider or removed_model:
            source_text = "chat overrides cleared"
        else:
            source_text = "no chat overrides were set"
        client.send_message(
            chat_id,
            (
                f"{source_text}. "
                f"Pi provider is now {configured_pi_provider(effective_config)} "
                f"({_build_pi_provider_source_text(state, scope_key)}). "
                f"Pi model is now {configured_pi_model(effective_config)} "
                f"({_build_pi_model_source_text(state, scope_key)})."
            ),
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return True
    if tail.startswith("provider"):
        provider_name = raw_tail[8:].strip() if len(raw_tail) >= 8 else ""
        if not provider_name:
            client.send_message(
                chat_id,
                "Usage: /pi provider <name>\nUse /pi providers to list available Pi providers.",
                reply_to_message_id=message_id,
                message_thread_id=message_thread_id,
            )
            return True
        try:
            text = _set_pi_provider_for_scope(state, config, scope_key, provider_name)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            client.send_message(
                chat_id,
                "Failed to validate Pi provider.\n"
                f"Error: {_brief_health_error(exc)}",
                reply_to_message_id=message_id,
                message_thread_id=message_thread_id,
            )
            return True
        client.send_message(
            chat_id,
            text,
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return True
    if tail.startswith("model"):
        model_name = raw_tail[5:].strip() if len(raw_tail) >= 5 else ""
        if not model_name:
            client.send_message(
                chat_id,
                "Usage: /model <name>\nUse /model list to list available models for the current Pi provider.",
                reply_to_message_id=message_id,
                message_thread_id=message_thread_id,
            )
            return True
        try:
            available_models = _pi_provider_model_names(display_config)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            client.send_message(
                chat_id,
                "Failed to validate Pi models.\n"
                f"Error: {_brief_health_error(exc)}",
                reply_to_message_id=message_id,
                message_thread_id=message_thread_id,
            )
            return True
        resolved_model = _resolve_pi_model_candidate(available_models, model_name)
        if resolved_model is None:
            provider = configured_pi_provider(display_config)
            client.send_message(
                chat_id,
                (
                    f"Model not available for Pi provider `{provider}`: `{model_name}`\n"
                    "Use /model list to see the allowed model names."
                ),
                reply_to_message_id=message_id,
                message_thread_id=message_thread_id,
            )
            return True
        state_repo.set_chat_pi_model(scope_key, resolved_model)
        updated_config = build_engine_runtime_config(state, config, scope_key, "pi")
        client.send_message(
            chat_id,
            (
                f"Pi model for this chat is now {configured_pi_model(updated_config)} "
                f"({_build_pi_model_source_text(state, scope_key)}).\n"
                "Deprecated alias: `/pi model` still works for compatibility, "
                "but `/model <name>` is the canonical command."
            ),
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return True
    client.send_message(
        chat_id,
        "Unknown /pi command. Use /pi, /pi providers, /pi provider <name>, or /pi reset. Use /model list and /model <name> for Pi model selection.",
        reply_to_message_id=message_id,
        message_thread_id=message_thread_id,
    )
    return True


def _model_active_engine_name(state: State, config, scope_key: str) -> str:
    selected = StateRepository(state).get_chat_engine(scope_key)
    return normalize_engine_name(selected or configured_default_engine(config))


def _telegram_inline_buttons_supported(client: ChannelAdapter) -> bool:
    return getattr(client, "channel_name", "telegram") == "telegram"


def _compact_inline_keyboard(
    buttons: List[Tuple[str, str]],
    *,
    columns: int = 2,
) -> Dict[str, object]:
    rows: List[List[Dict[str, str]]] = []
    current_row: List[Dict[str, str]] = []
    for label, callback_data in buttons:
        if len(callback_data.encode("utf-8")) > 64:
            continue
        current_row.append({"text": label, "callback_data": callback_data})
        if len(current_row) >= max(columns, 1):
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)
    return {"inline_keyboard": rows}


PI_MODEL_PICKER_PAGE_SIZE = 16


def _model_callback_data(engine_name: str, action: str, value: str = "") -> str:
    if action == "reset":
        return f"cfg|model|{engine_name}|reset"
    if action == "menu":
        return f"cfg|model|{engine_name}|menu|{value}" if value else f"cfg|model|{engine_name}|menu"
    if action == "page":
        return f"cfg|model|{engine_name}|page|{value}"
    return f"cfg|model|{engine_name}|set|{value}"


def _provider_callback_data(action: str, value: str = "") -> str:
    if action == "menu":
        return "cfg|provider|pi|menu"
    if action == "set":
        return f"cfg|provider|pi|set|{value}"
    return f"cfg|provider|pi|{action}"


def _effort_callback_data(action: str, value: str = "") -> str:
    if action == "reset":
        return "cfg|effort|codex|reset"
    if action == "menu":
        return "cfg|effort|codex|menu"
    return f"cfg|effort|codex|set|{value}"


def _pi_model_page_for_selection(model_names: List[str], current_model: str, page_size: int) -> int:
    if not model_names or page_size <= 0:
        return 0
    try:
        index = model_names.index(current_model)
    except ValueError:
        return 0
    return max(index // page_size, 0)


def _clamp_page_index(page_index: Optional[int], total_items: int, page_size: int) -> int:
    if total_items <= 0 or page_size <= 0:
        return 0
    last_page = max(((total_items - 1) // page_size), 0)
    if page_index is None:
        return 0
    return min(max(page_index, 0), last_page)


def _build_model_picker_markup(
    state: State,
    config,
    scope_key: str,
    *,
    page_index: Optional[int] = None,
) -> Optional[Dict[str, object]]:
    active_engine = _model_active_engine_name(state, config, scope_key)
    display_config = build_engine_runtime_config(state, config, scope_key, active_engine)
    buttons: List[Tuple[str, str]] = []
    if active_engine == "codex":
        current_model = configured_codex_model(display_config) or "(default)"
        for slug, display_name in _load_codex_model_choices():
            label = slug
            if slug == current_model:
                label = f"{slug} *"
            elif display_name != slug:
                label = display_name
            buttons.append((label, _model_callback_data("codex", "set", slug)))
        buttons.append(("Reset", _model_callback_data("codex", "reset")))
        buttons.append(("Effort", "cfg|effort|codex|menu"))
        buttons.append(("Back to Engine", _engine_callback_data("codex", "menu")))
    elif active_engine == "pi":
        try:
            model_names = _pi_provider_model_names(display_config)
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            return None
        current_model = configured_pi_model(display_config)
        current_page = _clamp_page_index(
            page_index if page_index is not None else _pi_model_page_for_selection(
                model_names,
                current_model,
                PI_MODEL_PICKER_PAGE_SIZE,
            ),
            len(model_names),
            PI_MODEL_PICKER_PAGE_SIZE,
        )
        start = current_page * PI_MODEL_PICKER_PAGE_SIZE
        end = start + PI_MODEL_PICKER_PAGE_SIZE
        for model_name in model_names[start:end]:
            label = f"{model_name} *" if model_name == current_model else model_name
            buttons.append((label, _model_callback_data("pi", "set", model_name)))
        rows = _compact_inline_keyboard(buttons, columns=2).get("inline_keyboard", [])
        total_pages = max(((len(model_names) - 1) // PI_MODEL_PICKER_PAGE_SIZE) + 1, 1) if model_names else 1
        if total_pages > 1:
            nav_row: List[Dict[str, str]] = []
            if current_page > 0:
                nav_row.append({"text": "Prev", "callback_data": _model_callback_data("pi", "page", str(current_page - 1))})
            nav_row.append(
                {
                    "text": f"{current_page + 1}/{total_pages}",
                    "callback_data": _model_callback_data("pi", "page", str(current_page)),
                }
            )
            if current_page < total_pages - 1:
                nav_row.append({"text": "Next", "callback_data": _model_callback_data("pi", "page", str(current_page + 1))})
            rows.append(nav_row)
        rows.append(
            [
                {"text": "Reset", "callback_data": _model_callback_data("pi", "reset")},
                {"text": "Back to Engine", "callback_data": _engine_callback_data("pi", "menu")},
            ]
        )
        return {"inline_keyboard": rows} if rows else None
    else:
        return None
    markup = _compact_inline_keyboard(buttons, columns=2)
    return markup if markup.get("inline_keyboard") else None


def _build_provider_picker_markup(state: State, config, scope_key: str) -> Optional[Dict[str, object]]:
    display_config = build_engine_runtime_config(state, config, scope_key, "pi")
    current_provider = configured_pi_provider(display_config)
    try:
        provider_names = _pi_available_provider_names(display_config)
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        provider_names = []
    if not provider_names:
        provider_names = [provider for provider, _description in PI_PROVIDER_CHOICES]
    buttons: List[Tuple[str, str]] = []
    for provider_name in provider_names:
        label = f"{provider_name} *" if provider_name == current_provider else provider_name
        buttons.append((label, _provider_callback_data("set", provider_name)))
    rows = _compact_inline_keyboard(buttons, columns=2).get("inline_keyboard", [])
    rows.append(
        [
            {"text": "Back to Engine", "callback_data": _engine_callback_data("pi", "menu")},
        ]
    )
    return {"inline_keyboard": rows} if rows else None


def _build_effort_picker_markup(state: State, config, scope_key: str) -> Optional[Dict[str, object]]:
    active_engine = _model_active_engine_name(state, config, scope_key)
    if active_engine != "codex":
        return None
    display_config = build_engine_runtime_config(state, config, scope_key, "codex")
    current_model = configured_codex_model(display_config)
    current_effort = configured_codex_reasoning_effort(display_config) or "(default)"
    buttons: List[Tuple[str, str]] = []
    for effort in _supported_codex_efforts_for_model(current_model):
        label = f"{effort} *" if effort == current_effort else effort
        buttons.append((label, _effort_callback_data("set", effort)))
    buttons.append(("Reset", _effort_callback_data("reset")))
    buttons.append(("Back to Models", "cfg|model|codex|menu"))
    markup = _compact_inline_keyboard(buttons, columns=2)
    return markup if markup.get("inline_keyboard") else None


def build_model_status_text(state: State, config, scope_key: str) -> str:
    active_engine = _model_active_engine_name(state, config, scope_key)
    display_config = build_engine_runtime_config(state, config, scope_key, active_engine)
    if active_engine == "codex":
        lines = [
            "Active engine: codex",
            f"Codex model: {configured_codex_model(display_config) or '(default)'}",
            f"Codex model source: {_build_codex_model_source_text(state, scope_key)}",
            f"Codex effort: {configured_codex_reasoning_effort(display_config) or '(default)'}",
            f"Codex effort source: {_build_codex_effort_source_text(state, scope_key)}",
            "Use /model <name> to set this chat's Codex model or tap the buttons below.",
            "Use /model reset to clear the chat override.",
        ]
        return "\n".join(lines)
    if active_engine == "pi":
        lines = [
            "Active engine: pi",
            f"Pi provider: {configured_pi_provider(display_config)}",
            f"Pi model: {configured_pi_model(display_config)}",
            f"Pi model source: {_build_pi_model_source_text(state, scope_key)}",
            "Use /model list to see available Pi models for the current provider.",
            "Use /pi provider <name> to switch Pi provider for this chat.",
        ]
        return "\n".join(lines)
    return (
        f"Active engine: {active_engine}\n"
        "Model switching is currently supported for `codex` and `pi`.\n"
        "Use `/engine codex` or `/engine pi` first."
    )


def build_effort_status_text(state: State, config, scope_key: str) -> str:
    active_engine = _model_active_engine_name(state, config, scope_key)
    if active_engine != "codex":
        return (
            f"Active engine: {active_engine}\n"
            "Reasoning effort switching is currently supported for `codex`.\n"
            "Use `/engine codex` first."
        )
    display_config = build_engine_runtime_config(state, config, scope_key, "codex")
    current_model = configured_codex_model(display_config) or "(default)"
    current_effort = configured_codex_reasoning_effort(display_config) or "(default)"
    return "\n".join(
        [
            "Active engine: codex",
            f"Codex model: {current_model}",
            f"Codex effort: {current_effort}",
            f"Codex effort source: {_build_codex_effort_source_text(state, scope_key)}",
            "Use /effort <low|medium|high|xhigh> or tap the buttons below.",
            "Use /effort reset to clear the chat override.",
        ]
    )


def build_effort_list_text(state: State, config, scope_key: str) -> str:
    active_engine = _model_active_engine_name(state, config, scope_key)
    if active_engine != "codex":
        return (
            f"Active engine: {active_engine}\n"
            "Reasoning effort listing is currently supported for `codex`.\n"
            "Use `/engine codex` first."
        )
    display_config = build_engine_runtime_config(state, config, scope_key, "codex")
    current_model = configured_codex_model(display_config) or "(default)"
    current_effort = configured_codex_reasoning_effort(display_config) or "(default)"
    lines = [
        "Active engine: codex",
        f"Current Codex model: {current_model}",
        f"Current Codex effort: {current_effort}",
        "Available Codex reasoning efforts for this model:",
    ]
    for effort in _supported_codex_efforts_for_model(current_model):
        marker = " (current)" if effort == current_effort else ""
        lines.append(f"- {effort}{marker}")
    return "\n".join(lines)


def _set_codex_model_for_scope(state: State, config, scope_key: str, model_name: str) -> str:
    state_repo = StateRepository(state)
    resolved_model = _resolve_codex_model_candidate(model_name)
    state_repo.set_chat_codex_model(scope_key, resolved_model)
    updated_config = build_engine_runtime_config(state, config, scope_key, "codex")
    current_effort = configured_codex_reasoning_effort(updated_config)
    if current_effort and _resolve_codex_effort_candidate(resolved_model, current_effort) is None:
        supported_efforts = _supported_codex_efforts_for_model(resolved_model)
        if supported_efforts:
            state_repo.set_chat_codex_effort(scope_key, supported_efforts[0])
            updated_config = build_engine_runtime_config(state, config, scope_key, "codex")
    return (
        f"Codex model for this chat is now {configured_codex_model(updated_config) or '(default)'} "
        f"({_build_codex_model_source_text(state, scope_key)})."
    )


def _reset_model_for_scope(state: State, config, scope_key: str, active_engine: str) -> str:
    state_repo = StateRepository(state)
    if active_engine == "codex":
        removed = state_repo.clear_chat_codex_model(scope_key)
        updated_config = build_engine_runtime_config(state, config, scope_key, "codex")
        source = "chat override cleared" if removed else "no chat override was set"
        return (
            f"{source}. Codex model is now {configured_codex_model(updated_config) or '(default)'} "
            f"({_build_codex_model_source_text(state, scope_key)})."
        )
    if active_engine == "pi":
        removed = state_repo.clear_chat_pi_model(scope_key)
        updated_config = build_engine_runtime_config(state, config, scope_key, "pi")
        source = "chat override cleared" if removed else "no chat override was set"
        return (
            f"{source}. Pi model is now {configured_pi_model(updated_config)} "
            f"({_build_pi_model_source_text(state, scope_key)})."
        )
    return build_model_status_text(state, config, scope_key)


def _set_pi_provider_for_scope(state: State, config, scope_key: str, provider_name: str) -> str:
    normalized_provider = normalize_pi_provider_name(provider_name)
    temp_config = copy.copy(config)
    temp_config.pi_provider = normalized_provider
    available_models = _pi_provider_model_names(temp_config)
    if not available_models:
        return (
            f"Provider `{normalized_provider}` did not report any models.\n"
            "Pi provider was not changed."
        )
    state_repo = StateRepository(state)
    current_model = state_repo.get_chat_pi_model(scope_key)
    resolved_model = _resolve_pi_model_candidate(available_models, current_model or "")
    if resolved_model is None:
        resolved_model = available_models[0]
    state_repo.set_chat_pi_provider(scope_key, normalized_provider)
    state_repo.set_chat_pi_model(scope_key, resolved_model)
    return (
        f"Pi provider for this chat is now {normalized_provider}. "
        f"Pi model is now {resolved_model}."
    )


def _set_pi_model_for_scope(state: State, config, scope_key: str, model_name: str) -> str:
    display_config = build_engine_runtime_config(state, config, scope_key, "pi")
    available_models = _pi_provider_model_names(display_config)
    resolved_model = _resolve_pi_model_candidate(available_models, model_name)
    if resolved_model is None:
        provider = configured_pi_provider(display_config)
        return (
            f"Model not available for Pi provider `{provider}`: `{model_name}`\n"
            "Use /model list to see the allowed model names."
        )
    StateRepository(state).set_chat_pi_model(scope_key, resolved_model)
    updated_config = build_engine_runtime_config(state, config, scope_key, "pi")
    return (
        f"Pi model for this chat is now {configured_pi_model(updated_config)} "
        f"({_build_pi_model_source_text(state, scope_key)})."
    )


def _set_codex_effort_for_scope(state: State, config, scope_key: str, effort_name: str) -> str:
    display_config = build_engine_runtime_config(state, config, scope_key, "codex")
    current_model = configured_codex_model(display_config)
    resolved_effort = _resolve_codex_effort_candidate(current_model, effort_name)
    if resolved_effort is None:
        return (
            f"Reasoning effort not supported for Codex model `{current_model or '(default)'}`: "
            f"`{effort_name}`\nUse /effort list to see the allowed effort names."
        )
    StateRepository(state).set_chat_codex_effort(scope_key, resolved_effort)
    updated_config = build_engine_runtime_config(state, config, scope_key, "codex")
    return (
        f"Codex reasoning effort for this chat is now "
        f"{configured_codex_reasoning_effort(updated_config) or '(default)'} "
        f"({_build_codex_effort_source_text(state, scope_key)})."
    )


def _reset_codex_effort_for_scope(state: State, config, scope_key: str) -> str:
    removed = StateRepository(state).clear_chat_codex_effort(scope_key)
    updated_config = build_engine_runtime_config(state, config, scope_key, "codex")
    source = "chat override cleared" if removed else "no chat override was set"
    return (
        f"{source}. Codex reasoning effort is now "
        f"{configured_codex_reasoning_effort(updated_config) or '(default)'} "
        f"({_build_codex_effort_source_text(state, scope_key)})."
    )


def _parse_page_index(raw_value: str) -> Optional[int]:
    value = str(raw_value or "").strip()
    if not value:
        return None
    try:
        page_index = int(value)
    except ValueError:
        return None
    return page_index if page_index >= 0 else None


def build_model_list_text(state: State, config, scope_key: str) -> str:
    active_engine = _model_active_engine_name(state, config, scope_key)
    display_config = build_engine_runtime_config(state, config, scope_key, active_engine)
    if active_engine == "codex":
        current_model = configured_codex_model(display_config) or "(default)"
        default_model = configured_codex_model(config) or "(default)"
        lines = [
            "Active engine: codex",
            f"Current Codex model: {current_model}",
            f"Bridge default Codex model: {default_model}",
        ]
        choices = _load_codex_model_choices()
        if choices:
            lines.append("Available Codex models:")
            for slug, display_name in choices:
                marker = " (current)" if slug == current_model else ""
                if display_name != slug:
                    lines.append(f"- {slug}{marker} - {display_name}")
                else:
                    lines.append(f"- {slug}{marker}")
            lines.append("Use /model <name> with either the slug or display name.")
        else:
            lines.append("No local Codex model cache was found for a fuller list.")
            lines.append("Set any Codex model name with /model <name>.")
        return "\n".join(lines)
    if active_engine == "pi":
        return build_pi_models_text(state, config, scope_key)
    return (
        f"Active engine: {active_engine}\n"
        "Model listing is currently supported for `codex` and `pi`.\n"
        "Use `/engine codex` or `/engine pi` first."
    )


def handle_model_command(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    raw_text: str,
) -> bool:
    pieces = raw_text.strip().split(maxsplit=1)
    raw_tail = pieces[1].strip() if len(pieces) > 1 else "status"
    tail = raw_tail.lower()
    active_engine = _model_active_engine_name(state, config, scope_key)
    display_config = build_engine_runtime_config(state, config, scope_key, active_engine)
    reply_markup: Optional[Dict[str, object]] = None

    if tail in {"", "status"}:
        text = build_model_status_text(state, config, scope_key)
        reply_markup = _build_model_picker_markup(state, config, scope_key)
    elif tail == "list":
        try:
            text = build_model_list_text(state, config, scope_key)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            text = "Failed to list models.\n" f"Error: {_brief_health_error(exc)}"
    elif tail == "reset":
        text = _reset_model_for_scope(state, config, scope_key, active_engine)
        reply_markup = _build_model_picker_markup(state, config, scope_key)
    else:
        if active_engine == "codex":
            text = _set_codex_model_for_scope(state, config, scope_key, raw_tail)
            reply_markup = _build_model_picker_markup(state, config, scope_key)
        elif active_engine == "pi":
            try:
                text = _set_pi_model_for_scope(state, config, scope_key, raw_tail)
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                text = "Failed to validate Pi models.\n" f"Error: {_brief_health_error(exc)}"
            reply_markup = _build_model_picker_markup(state, config, scope_key)
        else:
            text = build_model_status_text(state, config, scope_key)

    client.send_message(
        chat_id,
        text,
        reply_to_message_id=message_id,
        message_thread_id=message_thread_id,
        reply_markup=reply_markup,
    )
    return True


def handle_effort_command(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    raw_text: str,
) -> bool:
    pieces = raw_text.strip().split(maxsplit=1)
    raw_tail = pieces[1].strip() if len(pieces) > 1 else "status"
    tail = raw_tail.lower()
    active_engine = _model_active_engine_name(state, config, scope_key)
    reply_markup: Optional[Dict[str, object]] = None

    if tail in {"", "status"}:
        text = build_effort_status_text(state, config, scope_key)
        reply_markup = _build_effort_picker_markup(state, config, scope_key)
    elif tail == "list":
        text = build_effort_list_text(state, config, scope_key)
    elif tail == "reset":
        text = _reset_codex_effort_for_scope(state, config, scope_key)
        reply_markup = _build_effort_picker_markup(state, config, scope_key)
    elif active_engine != "codex":
        text = build_effort_status_text(state, config, scope_key)
    else:
        text = _set_codex_effort_for_scope(state, config, scope_key, raw_tail)
        reply_markup = _build_effort_picker_markup(state, config, scope_key)

    client.send_message(
        chat_id,
        text,
        reply_to_message_id=message_id,
        message_thread_id=message_thread_id,
        reply_markup=reply_markup,
    )
    return True


def _handle_engine_callback_action(ctx: CallbackActionContext) -> CallbackActionResult:
    if ctx.action == "reset":
        text = _reset_engine_for_scope(ctx.state, ctx.config, ctx.scope_key)
    elif ctx.action == "set":
        text = _set_engine_for_scope(ctx.state, ctx.config, ctx.scope_key, ctx.engine_name)
    else:
        text = build_engine_status_text(ctx.state, ctx.config, ctx.scope_key)
    return CallbackActionResult(
        text=text,
        reply_markup=_build_engine_picker_markup(ctx.state, ctx.config, ctx.scope_key),
    )


def _handle_pi_provider_callback_action(ctx: CallbackActionContext) -> CallbackActionResult:
    if ctx.action == "set":
        text = _set_pi_provider_for_scope(ctx.state, ctx.config, ctx.scope_key, ctx.value)
        reply_markup = _build_engine_picker_markup(ctx.state, ctx.config, ctx.scope_key)
    else:
        text = build_pi_providers_text(ctx.state, ctx.config, ctx.scope_key)
        reply_markup = _build_provider_picker_markup(ctx.state, ctx.config, ctx.scope_key)
    return CallbackActionResult(text=text, reply_markup=reply_markup)


def _handle_model_callback_action(ctx: CallbackActionContext) -> CallbackActionResult:
    requested_page = _parse_page_index(ctx.value)
    if ctx.action == "reset":
        text = _reset_model_for_scope(ctx.state, ctx.config, ctx.scope_key, ctx.engine_name)
    elif ctx.action == "set":
        if ctx.engine_name == "codex":
            text = _set_codex_model_for_scope(ctx.state, ctx.config, ctx.scope_key, ctx.value)
        elif ctx.engine_name == "pi":
            text = _set_pi_model_for_scope(ctx.state, ctx.config, ctx.scope_key, ctx.value)
        else:
            text = build_model_status_text(ctx.state, ctx.config, ctx.scope_key)
    else:
        text = build_model_status_text(ctx.state, ctx.config, ctx.scope_key)
    return CallbackActionResult(
        text=text,
        reply_markup=_build_model_picker_markup(
            ctx.state,
            ctx.config,
            ctx.scope_key,
            page_index=requested_page,
        ),
    )


def _handle_codex_effort_callback_action(ctx: CallbackActionContext) -> CallbackActionResult:
    if ctx.action == "reset":
        text = _reset_codex_effort_for_scope(ctx.state, ctx.config, ctx.scope_key)
    elif ctx.action == "set":
        text = _set_codex_effort_for_scope(ctx.state, ctx.config, ctx.scope_key, ctx.value)
    else:
        text = build_effort_status_text(ctx.state, ctx.config, ctx.scope_key)
    return CallbackActionResult(
        text=text,
        reply_markup=_build_effort_picker_markup(ctx.state, ctx.config, ctx.scope_key),
    )


CALLBACK_ACTION_HANDLERS: Dict[Tuple[str, Optional[str]], CallbackActionHandler] = {
    ("engine", None): _handle_engine_callback_action,
    ("provider", "pi"): _handle_pi_provider_callback_action,
    ("model", None): _handle_model_callback_action,
    ("effort", "codex"): _handle_codex_effort_callback_action,
}


def _resolve_callback_action_handler(
    kind: str,
    engine_name: str,
) -> Optional[CallbackActionHandler]:
    return CALLBACK_ACTION_HANDLERS.get((kind, engine_name)) or CALLBACK_ACTION_HANDLERS.get((kind, None))


def handle_callback_query(
    state: State,
    config,
    client: ChannelAdapter,
    update: Dict[str, object],
) -> bool:
    message, conversation_scope, message_id, callback_query_id, callback_data = extract_callback_query_context(update)
    if message is None or conversation_scope is None or not callback_query_id or not callback_data:
        return False
    chat_id = conversation_scope.chat_id
    message_thread_id = conversation_scope.message_thread_id
    scope_key = conversation_scope.scope_key
    chat_obj = message.get("chat")
    chat_type = chat_obj.get("type") if isinstance(chat_obj, dict) else None
    is_private_chat = isinstance(chat_type, str) and chat_type == "private"
    allow_private_unlisted = bool(getattr(config, "allow_private_chats_unlisted", False))
    allow_group_unlisted = bool(getattr(config, "allow_group_chats_unlisted", False))
    if chat_id not in config.allowed_chat_ids and not (
        (allow_private_unlisted and is_private_chat) or (allow_group_unlisted and not is_private_chat)
    ):
        client.answer_callback_query(callback_query_id, text="Access denied.")
        return True

    parts = callback_data.split("|", 4)
    if len(parts) < 4 or parts[0] != "cfg":
        client.answer_callback_query(callback_query_id, text="Unknown action.")
        return True
    kind = parts[1]
    engine_name = parts[2]
    action = parts[3]
    value = parts[4] if len(parts) > 4 else ""
    ctx = CallbackActionContext(
        state=state,
        config=config,
        client=client,
        scope_key=scope_key,
        chat_id=chat_id,
        message_thread_id=message_thread_id,
        message_id=message_id,
        callback_query_id=callback_query_id,
        kind=kind,
        engine_name=engine_name,
        action=action,
        value=value,
    )
    handler = _resolve_callback_action_handler(kind, engine_name)

    try:
        if handler is not None:
            result = handler(ctx)
        else:
            result = CallbackActionResult(
                text="Unsupported action.",
                toast_text="Unsupported action.",
            )
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        result = CallbackActionResult(
            text=f"Action failed.\nError: {_brief_health_error(exc)}",
            toast_text="Action failed.",
        )

    client.answer_callback_query(callback_query_id, text=result.toast_text)
    if isinstance(message_id, int):
        try:
            client.edit_message(chat_id, message_id, result.text, reply_markup=result.reply_markup)
            return True
        except Exception:
            logging.exception("Failed to edit callback menu message for chat_id=%s", chat_id)
    client.send_message(
        chat_id,
        result.text,
        reply_to_message_id=message_id,
        message_thread_id=message_thread_id,
        reply_markup=result.reply_markup,
    )
    return True


def resolve_engine_for_scope(
    state: State,
    config,
    scope_key: str,
    default_engine: Optional[EngineAdapter],
) -> EngineAdapter:
    selected = StateRepository(state).get_chat_engine(scope_key)
    if not selected:
        if default_engine is not None:
            return default_engine
        return build_default_plugin_registry().build_engine(configured_default_engine(config))
    engine_name = normalize_engine_name(selected)
    if default_engine is not None and getattr(default_engine, "engine_name", "") == engine_name:
        return default_engine
    registry = build_default_plugin_registry()
    return registry.build_engine(engine_name)


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


def build_diary_progress_context_label(state: State, config, scope_key: str) -> str:
    selected_engine = StateRepository(state).get_chat_engine(scope_key)
    engine_name = selected_engine or configured_default_engine(config)
    display_config = build_engine_runtime_config(state, config, scope_key, engine_name)
    return build_engine_progress_context_label(display_config, selected_engine)


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
    progress = build_progress_reporter(
        client,
        config,
        pending.chat_id,
        pending.latest_message_id,
        pending.message_thread_id,
        build_diary_progress_context_label(state, config, scope_key),
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
        send_generic_worker_error_response(
            client,
            config,
            pending.chat_id,
            pending.latest_message_id,
        )
    finally:
        finalize_request_progress(
            progress=progress,
            state=state,
            client=client,
            scope_key=scope_key,
            chat_id=pending.chat_id,
            message_id=pending.latest_message_id,
            cancel_event=cancel_event,
            cleanup_paths=cleanup_paths,
            finish_event_name="bridge.diary_batch_finished",
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
    start_background_worker(diary_queue_worker, state, config, client, scope_key)


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
        start_background_worker(diary_capture_batch_worker, state, config, client, scope_key)


def _handle_start_known_command(ctx: KnownCommandContext) -> bool:
    ctx.client.send_message(
        ctx.chat_id,
        start_command_message(ctx.config),
        reply_to_message_id=ctx.message_id,
    )
    return True


def _handle_help_known_command(ctx: KnownCommandContext) -> bool:
    ctx.client.send_message(
        ctx.chat_id,
        build_help_text(ctx.config),
        reply_to_message_id=ctx.message_id,
    )
    return True


def _handle_status_known_command(ctx: KnownCommandContext) -> bool:
    ctx.client.send_message(
        ctx.chat_id,
        build_status_text(ctx.state, ctx.config, chat_id=ctx.chat_id, scope_key=ctx.scope_key),
        reply_to_message_id=ctx.message_id,
        message_thread_id=ctx.message_thread_id,
    )
    return True


def _handle_restart_known_command(ctx: KnownCommandContext) -> bool:
    handle_restart_command(
        ctx.state,
        ctx.client,
        ctx.chat_id,
        ctx.message_thread_id,
        ctx.message_id,
    )
    return True


def _handle_cancel_known_command(ctx: KnownCommandContext) -> bool:
    handle_cancel_command(
        ctx.state,
        ctx.client,
        ctx.scope_key,
        ctx.chat_id,
        ctx.message_thread_id,
        ctx.message_id,
    )
    return True


def _handle_engine_known_command(ctx: KnownCommandContext) -> bool:
    return handle_engine_command(
        state=ctx.state,
        config=ctx.config,
        client=ctx.client,
        scope_key=ctx.scope_key,
        chat_id=ctx.chat_id,
        message_thread_id=ctx.message_thread_id,
        message_id=ctx.message_id,
        raw_text=ctx.raw_text,
    )


def _handle_model_known_command(ctx: KnownCommandContext) -> bool:
    return handle_model_command(
        state=ctx.state,
        config=ctx.config,
        client=ctx.client,
        scope_key=ctx.scope_key,
        chat_id=ctx.chat_id,
        message_thread_id=ctx.message_thread_id,
        message_id=ctx.message_id,
        raw_text=ctx.raw_text,
    )


def _handle_effort_known_command(ctx: KnownCommandContext) -> bool:
    return handle_effort_command(
        state=ctx.state,
        config=ctx.config,
        client=ctx.client,
        scope_key=ctx.scope_key,
        chat_id=ctx.chat_id,
        message_thread_id=ctx.message_thread_id,
        message_id=ctx.message_id,
        raw_text=ctx.raw_text,
    )


def _handle_pi_known_command(ctx: KnownCommandContext) -> bool:
    return handle_pi_command(
        state=ctx.state,
        config=ctx.config,
        client=ctx.client,
        scope_key=ctx.scope_key,
        chat_id=ctx.chat_id,
        message_thread_id=ctx.message_thread_id,
        message_id=ctx.message_id,
        raw_text=ctx.raw_text,
    )


def _handle_reset_known_command(ctx: KnownCommandContext) -> bool:
    handle_reset_command(
        ctx.state,
        ctx.config,
        ctx.client,
        ctx.scope_key,
        ctx.chat_id,
        ctx.message_thread_id,
        ctx.message_id,
    )
    return True


def _handle_voice_alias_known_command(ctx: KnownCommandContext) -> bool:
    return handle_voice_alias_command(
        state=ctx.state,
        config=ctx.config,
        client=ctx.client,
        chat_id=ctx.chat_id,
        message_id=ctx.message_id,
        raw_text=ctx.raw_text,
    )


def _handle_diary_today_known_command(ctx: KnownCommandContext) -> bool:
    ctx.client.send_message(
        ctx.chat_id,
        build_diary_today_status(ctx.state, ctx.config, ctx.scope_key),
        reply_to_message_id=ctx.message_id,
    )
    return True


def _handle_diary_queue_known_command(ctx: KnownCommandContext) -> bool:
    ctx.client.send_message(
        ctx.chat_id,
        build_diary_queue_status(ctx.state, ctx.scope_key),
        reply_to_message_id=ctx.message_id,
    )
    return True


KNOWN_COMMAND_HANDLERS: Dict[str, KnownCommandHandler] = {
    "/start": _handle_start_known_command,
    "/status": _handle_status_known_command,
    "/restart": _handle_restart_known_command,
    "/engine": _handle_engine_known_command,
    "/model": _handle_model_known_command,
    "/effort": _handle_effort_known_command,
    "/pi": _handle_pi_known_command,
    "/reset": _handle_reset_known_command,
    "/voice-alias": _handle_voice_alias_known_command,
}

DIARY_COMMAND_HANDLERS: Dict[str, KnownCommandHandler] = {
    "/today": _handle_diary_today_known_command,
    "/queue": _handle_diary_queue_known_command,
}


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
    if command is None:
        return False

    ctx = KnownCommandContext(
        state=state,
        config=config,
        client=client,
        scope_key=scope_key,
        chat_id=chat_id,
        message_thread_id=message_thread_id,
        message_id=message_id,
        raw_text=raw_text,
    )

    if command in HELP_COMMAND_ALIASES:
        return _handle_help_known_command(ctx)
    if command in CANCEL_COMMAND_ALIASES:
        return _handle_cancel_known_command(ctx)

    handler = KNOWN_COMMAND_HANDLERS.get(command)
    if handler is not None:
        return handler(ctx)

    if diary_mode_enabled(config):
        diary_handler = DIARY_COMMAND_HANDLERS.get(command)
        if diary_handler is not None:
            return diary_handler(ctx)

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
    request = PromptRequest(
        state=state,
        config=config,
        client=client,
        engine=engine,
        scope_key=scope_key,
        chat_id=chat_id,
        message_thread_id=message_thread_id,
        message_id=message_id,
        prompt=prompt,
        photo_file_id=photo_file_id,
        voice_file_id=voice_file_id,
        document=document,
        cancel_event=cancel_event,
        stateless=stateless,
        sender_name=sender_name,
        photo_file_ids=photo_file_ids,
        actor_user_id=actor_user_id,
        enforce_voice_prefix_from_transcript=enforce_voice_prefix_from_transcript,
    )
    start_background_worker(_process_message_worker_request, request)


def start_dishframed_dispatch(request: UpdateDispatchRequest) -> bool:
    photo_file_ids = list(request.photo_file_ids)
    if not photo_file_ids:
        photo_file_ids = get_recent_scope_photos(request.state, request.scope_key)
    if not photo_file_ids:
        request.client.send_message(
            request.chat_id,
            DISHFRAMED_USAGE_MESSAGE,
            reply_to_message_id=request.message_id,
            message_thread_id=request.message_thread_id,
        )
        return False
    if not mark_busy(request.state, request.scope_key):
        emit_event(
            "bridge.request_rejected",
            level=logging.WARNING,
            fields={
                "chat_id": request.chat_id,
                "message_id": request.message_id,
                "reason": "chat_busy",
            },
        )
        request.client.send_message(
            request.chat_id,
            request.config.busy_message,
            reply_to_message_id=request.message_id,
            message_thread_id=request.message_thread_id,
        )
        return False
    cancel_event = register_cancel_event(request.state, request.scope_key)
    StateRepository(request.state).mark_in_flight_request(request.scope_key, request.message_id)
    emit_event(
        "bridge.request_accepted",
        fields={
            "chat_id": request.chat_id,
            "message_id": request.message_id,
            "scope_key": request.scope_key,
            "has_photo": True,
            "has_voice": False,
            "has_document": False,
            "stateless": True,
            "route": "dishframed",
        },
    )
    start_dishframed_worker(
        state=request.state,
        config=request.config,
        client=request.client,
        scope_key=request.scope_key,
        chat_id=request.chat_id,
        message_thread_id=request.message_thread_id,
        message_id=request.message_id,
        photo_file_ids=photo_file_ids,
        cancel_event=cancel_event,
    )
    emit_event(
        "bridge.worker_started",
        fields={"chat_id": request.chat_id, "message_id": request.message_id, "route": "dishframed"},
    )
    return True


def start_standard_dispatch(request: UpdateDispatchRequest) -> bool:
    try:
        active_engine = resolve_engine_for_scope(
            request.state,
            request.config,
            request.scope_key,
            request.engine,
        )
    except Exception as exc:
        logging.exception("Failed to resolve engine for scope=%s", request.scope_key)
        request.client.send_message(
            request.chat_id,
            f"Engine selection failed: {exc}",
            reply_to_message_id=request.message_id,
            message_thread_id=request.message_thread_id,
        )
        return False

    if not request.stateless:
        if not ensure_chat_worker_session(
            request.state,
            request.config,
            request.client,
            request.scope_key,
            request.chat_id,
            request.message_thread_id,
            request.message_id,
        ):
            emit_event(
                "bridge.request_rejected",
                level=logging.WARNING,
                fields={
                    "chat_id": request.chat_id,
                    "message_id": request.message_id,
                    "reason": "worker_capacity",
                },
            )
            return False

    if not mark_busy(request.state, request.scope_key):
        emit_event(
            "bridge.request_rejected",
            level=logging.WARNING,
            fields={
                "chat_id": request.chat_id,
                "message_id": request.message_id,
                "reason": "chat_busy",
            },
        )
        request.client.send_message(
            request.chat_id,
            request.config.busy_message,
            reply_to_message_id=request.message_id,
        )
        return False

    cancel_event = register_cancel_event(request.state, request.scope_key)
    state_repo = StateRepository(request.state)
    state_repo.mark_in_flight_request(request.scope_key, request.message_id)
    emit_event(
        "bridge.request_accepted",
        fields={
            "chat_id": request.chat_id,
            "message_id": request.message_id,
            "scope_key": request.scope_key,
            "has_photo": bool(request.photo_file_ids),
            "has_voice": bool(request.voice_file_id),
            "has_document": request.document is not None,
            "stateless": request.stateless,
        },
    )
    if request.youtube_route_url:
        start_youtube_worker(
            state=request.state,
            config=request.config,
            client=request.client,
            engine=active_engine,
            scope_key=request.scope_key,
            chat_id=request.chat_id,
            message_thread_id=request.message_thread_id,
            message_id=request.message_id,
            request_text=request.raw_prompt,
            youtube_url=request.youtube_route_url,
            actor_user_id=request.actor_user_id,
            cancel_event=cancel_event,
        )
    else:
        start_message_worker(
            state=request.state,
            config=request.config,
            client=request.client,
            engine=active_engine,
            scope_key=request.scope_key,
            chat_id=request.chat_id,
            message_thread_id=request.message_thread_id,
            message_id=request.message_id,
            prompt=request.prompt,
            photo_file_id=request.photo_file_ids[0] if request.photo_file_ids else None,
            photo_file_ids=request.photo_file_ids,
            voice_file_id=request.voice_file_id,
            document=request.document,
            cancel_event=cancel_event,
            stateless=request.stateless,
            sender_name=request.sender_name,
            enforce_voice_prefix_from_transcript=request.enforce_voice_prefix_from_transcript,
            actor_user_id=request.actor_user_id,
        )
    emit_event(
        "bridge.worker_started",
        fields={"chat_id": request.chat_id, "message_id": request.message_id},
    )
    if request.handle_update_started_at is not None:
        emit_phase_timing(
            chat_id=request.chat_id,
            message_id=request.message_id,
            phase="handle_update_pre_worker",
            started_at_monotonic=request.handle_update_started_at,
            routed_youtube=bool(request.youtube_route_url),
            stateless=request.stateless,
        )
    return True


def extract_incoming_update_context(update: Dict[str, object]) -> Optional[IncomingUpdateContext]:
    message, conversation_scope, message_id = extract_chat_context(update)
    if message is None or conversation_scope is None:
        return None
    chat_id = conversation_scope.chat_id
    message_thread_id = conversation_scope.message_thread_id
    scope_key = conversation_scope.scope_key
    from_obj = message.get("from")
    actor_user_id = (
        from_obj.get("id")
        if isinstance(from_obj, dict) and isinstance(from_obj.get("id"), int)
        else None
    )
    update_id = update.get("update_id")
    update_id_int = update_id if isinstance(update_id, int) else None
    chat_obj = message.get("chat")
    chat_type = chat_obj.get("type") if isinstance(chat_obj, dict) else None
    is_private_chat = isinstance(chat_type, str) and chat_type == "private"
    return IncomingUpdateContext(
        update=update,
        message=message,
        chat_id=chat_id,
        message_thread_id=message_thread_id,
        scope_key=scope_key,
        message_id=message_id,
        actor_user_id=actor_user_id,
        is_private_chat=is_private_chat,
        update_id=update_id_int,
    )


def allow_update_chat(
    ctx: IncomingUpdateContext,
    config,
    client: ChannelAdapter,
) -> bool:
    allow_private_unlisted = bool(getattr(config, "allow_private_chats_unlisted", False))
    allow_group_unlisted = bool(getattr(config, "allow_group_chats_unlisted", False))
    if ctx.chat_id in config.allowed_chat_ids:
        return True
    if allow_private_unlisted and ctx.is_private_chat:
        return True
    if allow_group_unlisted and not ctx.is_private_chat:
        return True

    logging.warning("Denied non-allowlisted chat_id=%s", ctx.chat_id)
    emit_event(
        "bridge.request_denied",
        level=logging.WARNING,
        fields={
            "chat_id": ctx.chat_id,
            "message_id": ctx.message_id,
            "reason": "chat_not_allowlisted",
        },
    )
    if config.channel_plugin != "whatsapp":
        client.send_message(
            ctx.chat_id,
            config.denied_message,
            reply_to_message_id=ctx.message_id,
        )
    return False


def prepare_update_request(
    state: State,
    config,
    client: ChannelAdapter,
    ctx: IncomingUpdateContext,
) -> Optional[PreparedUpdateRequest]:
    prompt_input, photo_file_ids, voice_file_id, document = extract_prompt_and_media(ctx.message)
    if prompt_input is None and not photo_file_ids and voice_file_id is None and document is None:
        return None

    explicit_photo_file_ids = extract_message_photo_file_ids(ctx.message)
    if explicit_photo_file_ids:
        remember_recent_scope_photos(
            state=state,
            scope_key=ctx.scope_key,
            message_id=ctx.message_id,
            photo_file_ids=explicit_photo_file_ids,
        )

    prewarm_attachment_archive_for_message(
        state=state,
        config=config,
        client=client,
        chat_id=ctx.chat_id,
        message=ctx.message,
    )

    reply_context_prompt = build_reply_context_prompt(ctx.message)
    telegram_context_prompt = ""
    if should_include_telegram_context_prompt(
        prompt_input,
        reply_context_prompt,
        getattr(client, "channel_name", "telegram"),
    ):
        telegram_context_prompt = build_telegram_context_prompt(
            chat_id=ctx.chat_id,
            message_thread_id=ctx.message_thread_id,
            scope_key=ctx.scope_key,
            message_id=ctx.message_id,
            message=ctx.message,
        )

    prefix_result = apply_required_prefix_gate(
        client=client,
        config=config,
        prompt_input=prompt_input,
        has_reply_context=bool(reply_context_prompt),
        voice_file_id=voice_file_id,
        document=document,
        is_private_chat=ctx.is_private_chat,
        normalize_command=normalize_command,
        strip_required_prefix=strip_required_prefix,
    )
    prompt_input = prefix_result.prompt_input
    if prefix_result.ignored:
        emit_event(
            "bridge.request_ignored",
            fields={
                "chat_id": ctx.chat_id,
                "message_id": ctx.message_id,
                "reason": prefix_result.rejection_reason,
            },
        )
        return None
    if prefix_result.rejection_reason:
        emit_event(
            "bridge.request_rejected",
            level=logging.WARNING,
            fields={
                "chat_id": ctx.chat_id,
                "message_id": ctx.message_id,
                "reason": prefix_result.rejection_reason,
            },
        )
        client.send_message(
            ctx.chat_id,
            prefix_result.rejection_message or PREFIX_HELP_MESSAGE,
            reply_to_message_id=ctx.message_id,
        )
        return None

    return PreparedUpdateRequest(
        ctx=ctx,
        prompt_input=prompt_input,
        photo_file_ids=list(photo_file_ids),
        voice_file_id=voice_file_id,
        document=document,
        reply_context_prompt=reply_context_prompt,
        telegram_context_prompt=telegram_context_prompt,
        enforce_voice_prefix_from_transcript=prefix_result.enforce_voice_prefix_from_transcript,
        sender_name=extract_sender_name(ctx.message),
        command=normalize_command(prompt_input or ""),
    )


def build_update_flow_state(
    state: State,
    config,
    client: ChannelAdapter,
    engine: Optional[EngineAdapter],
    prepared: PreparedUpdateRequest,
) -> UpdateFlowState:
    return UpdateFlowState(
        state=state,
        config=config,
        client=client,
        engine=engine,
        ctx=prepared.ctx,
        prompt_input=prepared.prompt_input,
        photo_file_ids=list(prepared.photo_file_ids),
        voice_file_id=prepared.voice_file_id,
        document=prepared.document,
        reply_context_prompt=prepared.reply_context_prompt,
        telegram_context_prompt=prepared.telegram_context_prompt,
        enforce_voice_prefix_from_transcript=prepared.enforce_voice_prefix_from_transcript,
        sender_name=prepared.sender_name,
        command=prepared.command,
    )


def maybe_handle_diary_update_flow(flow: UpdateFlowState) -> bool:
    if not diary_mode_enabled(flow.config):
        return False
    if handle_known_command(
        flow.state,
        flow.config,
        flow.client,
        flow.ctx.scope_key,
        flow.ctx.chat_id,
        flow.ctx.message_thread_id,
        flow.ctx.message_id,
        flow.command,
        flow.prompt_input or "",
    ):
        emit_event(
            "bridge.command_handled",
            fields={
                "chat_id": flow.ctx.chat_id,
                "message_id": flow.ctx.message_id,
                "command": flow.command or "",
            },
        )
        return True
    queue_diary_capture(
        state=flow.state,
        config=flow.config,
        client=flow.client,
        scope_key=flow.ctx.scope_key,
        chat_id=flow.ctx.chat_id,
        message_thread_id=flow.ctx.message_thread_id,
        message_id=flow.ctx.message_id,
        sender_name=flow.sender_name,
        actor_user_id=flow.ctx.actor_user_id,
        message=flow.ctx.message,
    )
    return True


def prepare_update_dispatch_request(
    flow: UpdateFlowState,
    handle_update_started_at: float,
) -> Optional[UpdateDispatchRequest]:
    keyword_result = apply_priority_keyword_routing(
        config=flow.config,
        prompt_input=flow.prompt_input,
        command=flow.command,
        chat_id=flow.ctx.chat_id,
    )
    if keyword_result.rejection_reason:
        emit_event(
            "bridge.request_rejected",
            level=logging.WARNING,
            fields={
                "chat_id": flow.ctx.chat_id,
                "message_id": flow.ctx.message_id,
                "reason": keyword_result.rejection_reason,
            },
        )
        flow.client.send_message(
            flow.ctx.chat_id,
            keyword_result.rejection_message or PREFIX_HELP_MESSAGE,
            reply_to_message_id=flow.ctx.message_id,
        )
        return None
    flow.prompt_input = keyword_result.prompt_input
    flow.command = keyword_result.command
    if keyword_result.priority_keyword_mode:
        flow.stateless = keyword_result.stateless
        flow.priority_keyword_mode = True
        if keyword_result.route_kind == "youtube_link":
            flow.youtube_route_url = keyword_result.route_value
        emit_event(
            keyword_result.routed_event or "bridge.keyword_routed",
            fields={"chat_id": flow.ctx.chat_id, "message_id": flow.ctx.message_id},
        )

    if flow.prompt_input:
        maybe_process_voice_alias_learning_confirmation(
            state=flow.state,
            config=flow.config,
            client=flow.client,
            chat_id=flow.ctx.chat_id,
            message_id=flow.ctx.message_id,
            prompt_input=flow.prompt_input,
            command=flow.command,
            priority_keyword_mode=flow.priority_keyword_mode,
            photo_file_id=flow.photo_file_ids[0] if flow.photo_file_ids else None,
            photo_file_ids=flow.photo_file_ids,
            voice_file_id=flow.voice_file_id,
            document=flow.document,
        )

    memory_engine = flow.state.memory_engine if isinstance(flow.state.memory_engine, MemoryEngine) else None
    memory_channel = getattr(flow.client, "channel_name", "telegram")
    if memory_engine is not None and flow.prompt_input and not flow.priority_keyword_mode:
        cmd_result = handle_memory_command(
            engine=memory_engine,
            conversation_key=resolve_memory_conversation_key(
                flow.config,
                memory_channel,
                flow.ctx.scope_key,
            ),
            text=flow.prompt_input,
        )
        if cmd_result.handled:
            if cmd_result.response:
                flow.client.send_message(
                    flow.ctx.chat_id,
                    cmd_result.response,
                    reply_to_message_id=flow.ctx.message_id,
                )
            if cmd_result.run_prompt is None:
                emit_event(
                    "bridge.command_handled",
                    fields={
                        "chat_id": flow.ctx.chat_id,
                        "message_id": flow.ctx.message_id,
                        "command": flow.command or "",
                    },
                )
                return None
            flow.prompt_input = cmd_result.run_prompt
            flow.stateless = cmd_result.stateless
            flow.command = None

    if handle_known_command(
        flow.state,
        flow.config,
        flow.client,
        flow.ctx.scope_key,
        flow.ctx.chat_id,
        flow.ctx.message_thread_id,
        flow.ctx.message_id,
        flow.command,
        flow.prompt_input or "",
    ):
        emit_event(
            "bridge.command_handled",
            fields={
                "chat_id": flow.ctx.chat_id,
                "message_id": flow.ctx.message_id,
                "command": flow.command or "",
            },
        )
        return None

    if memory_engine is not None and flow.prompt_input and not flow.priority_keyword_mode and not flow.stateless:
        recall_response = handle_natural_language_memory_query(
            memory_engine,
            resolve_memory_conversation_key(flow.config, memory_channel, flow.ctx.scope_key),
            flow.prompt_input,
        )
        if recall_response:
            flow.client.send_message(
                flow.ctx.chat_id,
                recall_response,
                reply_to_message_id=flow.ctx.message_id,
            )
            emit_event(
                "bridge.command_handled",
                fields={
                    "chat_id": flow.ctx.chat_id,
                    "message_id": flow.ctx.message_id,
                    "command": "natural_language_memory_recall",
                },
            )
            return None

    prompt = (flow.prompt_input or "").strip()
    raw_prompt = prompt
    prompt_context_parts: List[str] = []
    if flow.telegram_context_prompt:
        prompt_context_parts.append(flow.telegram_context_prompt)
    if flow.reply_context_prompt:
        prompt_context_parts.append(flow.reply_context_prompt)
    if prompt_context_parts:
        if prompt:
            prompt_context_parts.append("Current User Message:\n" f"{prompt}")
        prompt = "\n\n".join(prompt_context_parts)
    if not prompt and not flow.voice_file_id and flow.document is None:
        return None

    if prompt and len(prompt) > flow.config.max_input_chars:
        if prompt_context_parts and raw_prompt and len(raw_prompt) <= flow.config.max_input_chars:
            emit_event(
                "bridge.telegram_context_omitted",
                level=logging.WARNING,
                fields={
                    "chat_id": flow.ctx.chat_id,
                    "message_id": flow.ctx.message_id,
                    "reason": "max_input_chars",
                },
            )
            prompt = raw_prompt
        else:
            actual_length = (
                len(raw_prompt)
                if raw_prompt and len(raw_prompt) > flow.config.max_input_chars
                else len(prompt)
            )
            emit_event(
                "bridge.request_rejected",
                level=logging.WARNING,
                fields={
                    "chat_id": flow.ctx.chat_id,
                    "message_id": flow.ctx.message_id,
                    "reason": "input_too_long",
                },
            )
            send_input_too_long(
                client=flow.client,
                chat_id=flow.ctx.chat_id,
                message_id=flow.ctx.message_id,
                actual_length=actual_length,
                max_input_chars=flow.config.max_input_chars,
            )
            return None

    if prompt and len(prompt) > flow.config.max_input_chars:
        emit_event(
            "bridge.request_rejected",
            level=logging.WARNING,
            fields={
                "chat_id": flow.ctx.chat_id,
                "message_id": flow.ctx.message_id,
                "reason": "input_too_long",
            },
        )
        send_input_too_long(
            client=flow.client,
            chat_id=flow.ctx.chat_id,
            message_id=flow.ctx.message_id,
            actual_length=len(prompt),
            max_input_chars=flow.config.max_input_chars,
        )
        return None

    if is_rate_limited(flow.state, flow.config, flow.ctx.scope_key):
        emit_event(
            "bridge.request_rejected",
            level=logging.WARNING,
            fields={
                "chat_id": flow.ctx.chat_id,
                "message_id": flow.ctx.message_id,
                "reason": "rate_limited",
            },
        )
        flow.client.send_message(
            flow.ctx.chat_id,
            RATE_LIMIT_MESSAGE,
            reply_to_message_id=flow.ctx.message_id,
        )
        return None

    return UpdateDispatchRequest(
        state=flow.state,
        config=flow.config,
        client=flow.client,
        engine=flow.engine,
        scope_key=flow.ctx.scope_key,
        chat_id=flow.ctx.chat_id,
        message_thread_id=flow.ctx.message_thread_id,
        message_id=flow.ctx.message_id,
        prompt=prompt,
        raw_prompt=raw_prompt,
        photo_file_ids=list(flow.photo_file_ids),
        voice_file_id=flow.voice_file_id,
        document=flow.document,
        actor_user_id=flow.ctx.actor_user_id,
        sender_name=flow.sender_name,
        stateless=flow.stateless,
        enforce_voice_prefix_from_transcript=flow.enforce_voice_prefix_from_transcript,
        youtube_route_url=flow.youtube_route_url,
        handle_update_started_at=handle_update_started_at,
    )


def handle_update(
    state: State,
    config,
    client: ChannelAdapter,
    update: Dict[str, object],
    engine: Optional[EngineAdapter] = None,
) -> None:
    handle_update_started_at = time.monotonic()
    if handle_callback_query(state, config, client, update):
        return
    ctx = extract_incoming_update_context(update)
    if ctx is None:
        return
    emit_event(
        "bridge.update_received",
        fields={
            "chat_id": ctx.chat_id,
            "message_id": ctx.message_id,
            "scope_key": ctx.scope_key,
            "update_id": ctx.update_id,
        },
    )

    if not allow_update_chat(ctx, config, client):
        return

    prepared = prepare_update_request(state, config, client, ctx)
    if prepared is None:
        return
    chat_id = ctx.chat_id
    message_id = ctx.message_id
    message_thread_id = ctx.message_thread_id
    scope_key = ctx.scope_key
    flow = build_update_flow_state(state, config, client, engine, prepared)

    if maybe_handle_diary_update_flow(flow):
        return
    dispatch_request = prepare_update_dispatch_request(flow, handle_update_started_at)
    if dispatch_request is None:
        return

    if flow.command == "/dishframed":
        start_dishframed_dispatch(dispatch_request)
        return
    start_standard_dispatch(dispatch_request)
    return
