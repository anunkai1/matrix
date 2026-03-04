import logging
import json
import os
import re
import subprocess
import threading
import time
from difflib import SequenceMatcher
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

try:
    from .executor import (
        ExecutorCancelledError,
        ExecutorProgressEvent,
        parse_executor_output,
        should_reset_thread_after_resume_failure,
    )
    from .channel_adapter import ChannelAdapter
    from .engine_adapter import CodexEngineAdapter, EngineAdapter
    from .media import TelegramFileDownloadSpec, download_telegram_file_to_temp
    from .memory_engine import MemoryEngine, TurnContext, build_memory_help_lines, handle_memory_command
    from .session_manager import (
        ensure_chat_worker_session,
        finalize_chat_work,
        is_rate_limited,
        mark_busy,
        request_safe_restart,
        trigger_restart_async,
    )
    from .state_store import State, StateRepository
    from .structured_logging import emit_event
    from .transport import TELEGRAM_CAPTION_LIMIT, TELEGRAM_LIMIT
except ImportError:
    from executor import (
        ExecutorCancelledError,
        ExecutorProgressEvent,
        parse_executor_output,
        should_reset_thread_after_resume_failure,
    )
    from channel_adapter import ChannelAdapter
    from engine_adapter import CodexEngineAdapter, EngineAdapter
    from media import TelegramFileDownloadSpec, download_telegram_file_to_temp
    from memory_engine import MemoryEngine, TurnContext, build_memory_help_lines, handle_memory_command
    from session_manager import (
        ensure_chat_worker_session,
        finalize_chat_work,
        is_rate_limited,
        mark_busy,
        request_safe_restart,
        trigger_restart_async,
    )
    from state_store import State, StateRepository
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

HELP_COMMAND_ALIASES = ("/help", "/h")
RATE_LIMIT_MESSAGE = "Rate limit exceeded. Please wait a minute and retry."
RETRY_WITH_NEW_SESSION_PHASE = "Execution failed. Retrying once with a new session."
RETRY_FAILED_MESSAGE = "Execution failed after an automatic retry. Please resend your request."
HA_KEYWORD_HELP_MESSAGE = (
    "HA mode needs an action. Example: `HA turn on masters AC to dry mode at 9:25am`."
)
SERVER3_KEYWORD_HELP_MESSAGE = (
    "Server3 TV mode needs an action. Example: `Server3 TV open desktop and play top YouTube result for deep house 2026`."
)
NEXTCLOUD_KEYWORD_HELP_MESSAGE = (
    "Nextcloud mode needs an action. Example: `Nextcloud create event tomorrow 3pm dentist in Personal calendar`."
)
PREFIX_HELP_MESSAGE = (
    "Helper mode needs a prefixed prompt. Example: `@helper summarize this file`."
)
CANCEL_REQUESTED_MESSAGE = "Cancel requested. Stopping current request."
CANCEL_ALREADY_REQUESTED_MESSAGE = (
    "Cancel is already in progress. Waiting for current request to stop."
)
CANCEL_NO_ACTIVE_MESSAGE = "No active request to cancel."
REQUEST_CANCELED_MESSAGE = "Request canceled."
WHATSAPP_REPLY_PREFIX = "Говорун:"


@dataclass
class DocumentPayload:
    file_id: str
    file_name: str
    mime_type: str


@dataclass
class PreparedPromptInput:
    prompt_text: str
    image_path: Optional[str] = None
    document_path: Optional[str] = None


@dataclass
class OutboundMediaDirective:
    media_ref: str
    as_voice: bool


def build_repo_root() -> str:
    return str(Path(__file__).resolve().parents[2])


def build_ha_routing_script_allowlist() -> List[str]:
    repo_root = build_repo_root()
    return [
        os.path.join(repo_root, "ops", "ha", "turn_entity_power.sh"),
        os.path.join(repo_root, "ops", "ha", "schedule_entity_power.sh"),
        os.path.join(repo_root, "ops", "ha", "set_climate_temperature.sh"),
        os.path.join(repo_root, "ops", "ha", "schedule_climate_temperature.sh"),
        os.path.join(repo_root, "ops", "ha", "set_climate_mode.sh"),
        os.path.join(repo_root, "ops", "ha", "schedule_climate_mode.sh"),
    ]


def build_server3_routing_script_allowlist() -> List[str]:
    repo_root = build_repo_root()
    return [
        "/usr/local/bin/server3-tv-start",
        "/usr/local/bin/server3-tv-stop",
        os.path.join(repo_root, "ops", "tv-desktop", "server3-tv-open-browser-url.sh"),
        os.path.join(repo_root, "ops", "tv-desktop", "server3-youtube-open-top-result.sh"),
        os.path.join(repo_root, "ops", "tv-desktop", "server3-tv-browser-youtube-pause.sh"),
        os.path.join(repo_root, "ops", "tv-desktop", "server3-tv-browser-youtube-play.sh"),
    ]


def build_nextcloud_routing_script_allowlist() -> List[str]:
    repo_root = build_repo_root()
    return [
        os.path.join(repo_root, "ops", "nextcloud", "nextcloud-files-list.sh"),
        os.path.join(repo_root, "ops", "nextcloud", "nextcloud-file-upload.sh"),
        os.path.join(repo_root, "ops", "nextcloud", "nextcloud-file-delete.sh"),
        os.path.join(repo_root, "ops", "nextcloud", "nextcloud-calendars-list.sh"),
        os.path.join(repo_root, "ops", "nextcloud", "nextcloud-calendar-create-event.sh"),
    ]


def assistant_label(config) -> str:
    value = getattr(config, "assistant_name", "").strip()
    return value or "Architect"


def start_command_message(config) -> str:
    return f"Telegram {assistant_label(config)} bridge is online. Send a prompt to begin."


def resume_retry_phase(config) -> str:
    return f"Retrying as a new {assistant_label(config)} session."


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


def extract_ha_keyword_request(text: str) -> tuple[bool, str]:
    stripped = text.strip()
    if not stripped:
        return False, ""

    lowered = stripped.lower()
    for keyword in ("ha", "home assistant"):
        if lowered == keyword:
            return True, ""
        if lowered.startswith(keyword):
            remainder = stripped[len(keyword):]
            if remainder and remainder[0] not in (" ", ":", "-"):
                continue
            return True, remainder.lstrip(" :-\t")
    return False, ""


def extract_server3_keyword_request(text: str) -> tuple[bool, str]:
    stripped = text.strip()
    if not stripped:
        return False, ""

    lowered = stripped.lower()
    for keyword in ("server3 tv",):
        if lowered == keyword:
            return True, ""
        if lowered.startswith(keyword):
            remainder = stripped[len(keyword):]
            if remainder and remainder[0] not in (" ", ":", "-"):
                continue
            return True, remainder.lstrip(" :-\t")
    return False, ""


def extract_nextcloud_keyword_request(text: str) -> tuple[bool, str]:
    stripped = text.strip()
    if not stripped:
        return False, ""

    lowered = stripped.lower()
    for keyword in ("nextcloud",):
        if lowered == keyword:
            return True, ""
        if lowered.startswith(keyword):
            remainder = stripped[len(keyword):]
            if remainder and remainder[0] not in (" ", ":", "-"):
                continue
            return True, remainder.lstrip(" :-\t")
    return False, ""


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


def build_ha_keyword_prompt(user_request: str) -> str:
    scripts = "\n".join(f"- {path}" for path in build_ha_routing_script_allowlist())
    return (
        "Home Assistant priority mode is active.\n"
        "Treat this as a Home Assistant action request.\n"
        f"User request: {user_request.strip()}\n\n"
        "Mandatory execution policy:\n"
        f"{scripts}\n"
        "- For scheduling, only use the schedule_* scripts with --at or --in.\n"
        "- Do not use inline systemd-run, /bin/bash -lc, or direct curl commands for HA actions.\n"
        "- If entity/time/mode is unclear, ask one concise clarification question instead of guessing.\n"
        "- After execution, report the result with state or timer/service unit names."
    )


def build_server3_keyword_prompt(user_request: str) -> str:
    scripts = "\n".join(f"- {path}" for path in build_server3_routing_script_allowlist())
    return (
        "Server3 TV operations priority mode is active.\n"
        "Treat this as a Server3 TV desktop/browser/UI action request.\n"
        f"User request: {user_request.strip()}\n\n"
        "Mandatory execution policy:\n"
        f"{scripts}\n"
        "- Prefer deterministic script execution over ad-hoc shell steps.\n"
        "- For browser navigation, use server3-tv-open-browser-url.sh with firefox or brave and explicit URL.\n"
        "- For YouTube top-result playback, use server3-youtube-open-top-result.sh with quoted query.\n"
        "- Respect optional min-duration constraints when explicitly requested.\n"
        "- If intent is unclear, ask one concise clarification question instead of guessing.\n"
        "- After execution, report exact scripts/commands used and final outcome."
    )


def build_nextcloud_keyword_prompt(user_request: str) -> str:
    scripts = "\n".join(f"- {path}" for path in build_nextcloud_routing_script_allowlist())
    return (
        "Nextcloud operations priority mode is active.\n"
        "Treat this as a Nextcloud file/calendar action request.\n"
        f"User request: {user_request.strip()}\n\n"
        "Mandatory execution policy:\n"
        f"{scripts}\n"
        "- Prefer deterministic script execution over ad-hoc shell or direct curl commands.\n"
        "- For file browsing use nextcloud-files-list.sh.\n"
        "- For calendar discovery use nextcloud-calendars-list.sh before creating events if unsure.\n"
        "- Do not print or expose credentials.\n"
        "- If path/calendar/time is unclear, ask one concise clarification question.\n"
        "- After execution, report exact scripts used and final outcome."
    )


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


def send_chat_action_safe(client: ChannelAdapter, chat_id: int, action: str) -> None:
    try:
        client.send_chat_action(chat_id, action=action)
    except Exception:
        logging.debug("Failed to send %s action for chat_id=%s", action, chat_id)


def apply_outbound_reply_prefix(client: ChannelAdapter, text: str) -> str:
    if not text:
        return text
    if getattr(client, "channel_name", "") != "whatsapp":
        return text
    stripped = text.lstrip()
    if not stripped:
        return WHATSAPP_REPLY_PREFIX
    if stripped.casefold().startswith(WHATSAPP_REPLY_PREFIX.casefold()):
        return text
    return f"{WHATSAPP_REPLY_PREFIX} {stripped}"


def is_whatsapp_channel(client: ChannelAdapter) -> bool:
    return getattr(client, "channel_name", "") == "whatsapp"


def command_bypasses_required_prefix(client: ChannelAdapter, command: Optional[str]) -> bool:
    return is_whatsapp_channel(client) and command == "/voice-alias"


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


def send_executor_failure_message(
    client: ChannelAdapter,
    config,
    chat_id: int,
    message_id: Optional[int],
    allow_automatic_retry: bool,
) -> None:
    if allow_automatic_retry:
        client.send_message(
            chat_id,
            RETRY_FAILED_MESSAGE,
            reply_to_message_id=message_id,
        )
        return
    client.send_message(
        chat_id,
        config.generic_error_message,
        reply_to_message_id=message_id,
    )


def register_cancel_event(state: State, chat_id: int) -> threading.Event:
    cancel_event = threading.Event()
    with state.lock:
        state.cancel_events[chat_id] = cancel_event
    return cancel_event


def clear_cancel_event(
    state: State,
    chat_id: int,
    expected_event: Optional[threading.Event] = None,
) -> None:
    with state.lock:
        current = state.cancel_events.get(chat_id)
        if current is None:
            return
        if expected_event is not None and current is not expected_event:
            return
        del state.cancel_events[chat_id]


def request_chat_cancel(state: State, chat_id: int) -> str:
    with state.lock:
        is_busy = chat_id in state.busy_chats
        cancel_event = state.cancel_events.get(chat_id)
        if not is_busy:
            if cancel_event is not None:
                del state.cancel_events[chat_id]
            return "idle"
        if cancel_event is None:
            return "unavailable"
        if cancel_event.is_set():
            return "already_requested"
        cancel_event.set()
        return "requested"


def extract_chat_context(update: Dict[str, object]) -> tuple[Optional[Dict[str, object]], Optional[int], Optional[int]]:
    message = update.get("message")
    if not isinstance(message, dict):
        return None, None, None

    chat = message.get("chat")
    if not isinstance(chat, dict):
        return None, None, None

    chat_id = chat.get("id")
    if not isinstance(chat_id, int):
        return None, None, None

    message_id = message.get("message_id")
    if not isinstance(message_id, int):
        message_id = None
    return message, chat_id, message_id


class ProgressReporter:
    def __init__(
        self,
        client: ChannelAdapter,
        chat_id: int,
        reply_to_message_id: Optional[int],
        assistant_name: str,
        progress_label: str = "",
        compact_elapsed_prefix: str = "Already",
        compact_elapsed_suffix: str = "s",
    ) -> None:
        self.client = client
        self.chat_id = chat_id
        self.reply_to_message_id = reply_to_message_id
        self.assistant_name = assistant_name
        self.progress_label = progress_label.strip()
        self.compact_elapsed_prefix = (compact_elapsed_prefix or "Already").strip() or "Already"
        self.compact_elapsed_suffix = compact_elapsed_suffix or "s"
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
            self.client.send_chat_action(self.chat_id, action="typing")
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
            text = f"{label}... {self.compact_elapsed_prefix} {elapsed}{self.compact_elapsed_suffix}"
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
            if getattr(self.client, "channel_name", "") == "whatsapp":
                # WhatsApp edit failures can create visible noise if retried aggressively.
                self.progress_message_id = None
            logging.debug("Failed to edit progress message for chat_id=%s: %s", self.chat_id, exc)
            return
        except Exception:
            self.edit_failures_other += 1
            if getattr(self.client, "channel_name", "") == "whatsapp":
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


def normalize_optional_text(value: object) -> Optional[str]:
    if not isinstance(value, str):
        return None
    return value.strip()


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


def extract_prompt_and_media(
    message: Dict[str, object]
) -> tuple[Optional[str], Optional[str], Optional[str], Optional[DocumentPayload]]:
    text = normalize_optional_text(message.get("text"))
    caption = normalize_optional_text(message.get("caption"))

    photo_items = message.get("photo")
    if isinstance(photo_items, list) and photo_items:
        file_id = pick_largest_photo_file_id(photo_items)
        if file_id:
            prompt = select_media_prompt(text, caption, "Please analyze this image.")
            return prompt, file_id, None, None

    voice = message.get("voice")
    if isinstance(voice, dict):
        voice_file_id = voice.get("file_id")
        if isinstance(voice_file_id, str) and voice_file_id.strip():
            prompt = select_media_prompt(text, caption, "")
            return prompt, None, voice_file_id.strip(), None

    document = message.get("document")
    if isinstance(document, dict):
        file_id = document.get("file_id")
        if isinstance(file_id, str) and file_id.strip():
            file_name = document.get("file_name")
            mime_type = document.get("mime_type")
            payload = DocumentPayload(
                file_id=file_id.strip(),
                file_name=file_name.strip() if isinstance(file_name, str) and file_name.strip() else "unnamed",
                mime_type=mime_type.strip() if isinstance(mime_type, str) and mime_type.strip() else "unknown",
            )
            prompt = select_media_prompt(text, caption, "Please analyze this file.")
            return prompt, None, None, payload

    if text is not None:
        return text, None, None, None

    return None, None, None, None


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


def build_help_text(config) -> str:
    minimal = (
        "Available commands:\n"
        "/start - verify bridge connectivity\n"
        "/help or /h - show this message\n"
        "/status - show bridge status and context\n"
        "/reset - clear saved context for this chat\n"
        "/cancel - cancel current in-flight request for this chat\n"
        "/restart - queue a safe bridge restart"
    )
    if getattr(config, "channel_plugin", "telegram") == "whatsapp":
        return minimal

    name = assistant_label(config)
    base = (
        minimal
        + "\n"
        "/voice-alias list - show pending learned voice corrections\n"
        "/voice-alias approve <id> - approve one learned correction\n"
        "server3-tv-start - start TV desktop mode (local shell command)\n"
        "server3-tv-stop - stop TV desktop mode and return to CLI (local shell command)\n\n"
        f"Send text, images, voice notes, or files and {name} will process them.\n"
        "Use `HA ...` or `Home Assistant ...` to force Home Assistant script routing.\n"
        "Use `Server3 TV ...` for Server3 desktop/browser/UI operations.\n"
        "Use `Nextcloud ...` for Nextcloud files/calendar operations.\n"
        "Use `SRO ...` when referring to Server3 Runtime Observer checks/summaries."
    )
    return base + "\n\n" + "\n".join(build_memory_help_lines())


def build_status_text(state: State, config, chat_id: Optional[int] = None) -> str:
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
            if chat_id is not None:
                session = state.chat_sessions.get(chat_id)
                if session is not None:
                    has_thread = bool(session.thread_id.strip())
                    has_worker = (
                        session.worker_created_at is not None
                        and session.worker_last_used_at is not None
                    )
        else:
            thread_count = len(state.chat_threads)
            worker_count = len(state.worker_sessions)
            has_thread = chat_id in state.chat_threads if chat_id is not None else False
            has_worker = chat_id in state.worker_sessions if chat_id is not None else False

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

    if chat_id is not None:
        lines.append(f"This chat has saved context: {has_thread}")
        lines.append(f"This chat has worker session: {has_worker}")
        memory_engine = state.memory_engine
        if isinstance(memory_engine, MemoryEngine):
            try:
                memory_status = memory_engine.get_status(MemoryEngine.telegram_key(chat_id))
            except Exception:
                logging.exception("Failed to query memory status for chat_id=%s", chat_id)
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
    enforce_voice_prefix_from_transcript: bool = False,
) -> Optional[PreparedPromptInput]:
    prompt_text = prompt.strip()
    image_path: Optional[str] = None
    document_path: Optional[str] = None

    if photo_file_id:
        progress.set_phase("Downloading image from Telegram.")
        try:
            image_path = download_photo_to_temp(client, config, photo_file_id)
        except ValueError as exc:
            logging.warning("Photo rejected for chat_id=%s: %s", chat_id, exc)
            progress.mark_failure("Image request rejected.")
            client.send_message(chat_id, str(exc), reply_to_message_id=message_id)
            return None
        except Exception:
            logging.exception("Photo download failed for chat_id=%s", chat_id)
            progress.mark_failure("Image download failed.")
            client.send_message(
                chat_id,
                config.image_download_error_message,
                reply_to_message_id=message_id,
            )
            return None

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
        progress.set_phase("Downloading file from Telegram.")
        try:
            document_path, file_size = download_document_to_temp(client, config, document)
        except ValueError as exc:
            logging.warning("Document rejected for chat_id=%s: %s", chat_id, exc)
            progress.mark_failure("File request rejected.")
            client.send_message(chat_id, str(exc), reply_to_message_id=message_id)
            return None
        except Exception:
            logging.exception("Document download failed for chat_id=%s", chat_id)
            progress.mark_failure("File download failed.")
            client.send_message(
                chat_id,
                config.document_download_error_message,
                reply_to_message_id=message_id,
            )
            return None

        context = build_document_analysis_context(document_path, document, file_size)
        if prompt_text:
            prompt_text = f"{prompt_text}\n\n{context}"
        else:
            prompt_text = context

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
        document_path=document_path,
    )


def execute_prompt_with_retry(
    state_repo: StateRepository,
    config,
    client: ChannelAdapter,
    engine: EngineAdapter,
    chat_id: int,
    message_id: Optional[int],
    prompt_text: str,
    previous_thread_id: Optional[str],
    image_path: Optional[str],
    progress: ProgressReporter,
    cancel_event: Optional[threading.Event] = None,
    session_continuity_enabled: bool = True,
) -> Optional[subprocess.CompletedProcess[str]]:
    allow_automatic_retry = config.persistent_workers_enabled
    retry_attempted = False
    attempt_thread_id: Optional[str] = previous_thread_id
    attempt = 0

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
            client.send_message(chat_id, REQUEST_CANCELED_MESSAGE, reply_to_message_id=message_id)
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
        try:
            result = engine.run(
                config=config,
                prompt=prompt_text,
                thread_id=attempt_thread_id,
                image_path=image_path,
                progress_callback=progress.handle_executor_event,
                cancel_event=cancel_event,
            )
        except ExecutorCancelledError:
            logging.info("Executor canceled for chat_id=%s", chat_id)
            emit_event(
                "bridge.request_cancelled",
                fields={"chat_id": chat_id, "message_id": message_id, "attempt": attempt},
            )
            progress.mark_failure("Execution canceled.")
            client.send_message(chat_id, REQUEST_CANCELED_MESSAGE, reply_to_message_id=message_id)
            return None
        except subprocess.TimeoutExpired:
            logging.warning("Executor timeout for chat_id=%s", chat_id)
            emit_event(
                "bridge.request_timeout",
                level=logging.WARNING,
                fields={"chat_id": chat_id, "message_id": message_id, "attempt": attempt},
            )
            progress.mark_failure("Execution timed out.")
            client.send_message(chat_id, config.timeout_message, reply_to_message_id=message_id)
            return None
        except FileNotFoundError:
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
            )
            return None
        except Exception:
            logging.exception("Unexpected executor error for chat_id=%s", chat_id)
            emit_event(
                "bridge.executor_exception",
                level=logging.WARNING,
                fields={"chat_id": chat_id, "message_id": message_id, "attempt": attempt},
            )
            if allow_automatic_retry and not retry_attempted:
                retry_attempted = True
                if session_continuity_enabled:
                    state_repo.clear_thread_id(chat_id)
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
                state_repo.clear_thread_id(chat_id)
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
) -> tuple[Optional[str], str]:
    new_thread_id, output = parse_executor_output(result.stdout or "")
    if new_thread_id:
        state_repo.set_thread_id(chat_id, new_thread_id)
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


def process_prompt(
    state: State,
    config,
    client: ChannelAdapter,
    engine: Optional[EngineAdapter],
    chat_id: int,
    message_id: Optional[int],
    prompt: str,
    photo_file_id: Optional[str],
    voice_file_id: Optional[str],
    document: Optional[DocumentPayload],
    cancel_event: Optional[threading.Event] = None,
    stateless: bool = False,
    sender_name: str = "Telegram User",
    enforce_voice_prefix_from_transcript: bool = False,
) -> None:
    active_engine = engine or CodexEngineAdapter()
    state_repo = StateRepository(state)
    memory_engine = state.memory_engine if isinstance(state.memory_engine, MemoryEngine) else None
    conversation_key = MemoryEngine.telegram_key(chat_id)
    previous_thread_id: Optional[str] = None
    turn_context: Optional[TurnContext] = None
    image_path: Optional[str] = None
    document_path: Optional[str] = None
    progress = ProgressReporter(
        client,
        chat_id,
        message_id,
        assistant_label(config),
        getattr(config, "progress_label", ""),
        getattr(config, "progress_elapsed_prefix", "Already"),
        getattr(config, "progress_elapsed_suffix", "s"),
    )
    try:
        progress.start()
        prepared = prepare_prompt_input(
            state=state,
            config=config,
            client=client,
            chat_id=chat_id,
            message_id=message_id,
            prompt=prompt,
            photo_file_id=photo_file_id,
            voice_file_id=voice_file_id,
            document=document,
            progress=progress,
            enforce_voice_prefix_from_transcript=enforce_voice_prefix_from_transcript,
        )
        if prepared is None:
            return
        image_path = prepared.image_path
        document_path = prepared.document_path
        prompt_text = prepared.prompt_text
        if memory_engine is not None:
            try:
                turn_context = memory_engine.begin_turn(
                    conversation_key=conversation_key,
                    channel="telegram",
                    sender_name=sender_name,
                    user_input=prompt_text,
                    stateless=stateless,
                )
                prompt_text = turn_context.prompt_text
                previous_thread_id = turn_context.thread_id
            except Exception:
                logging.exception("Failed to prepare shared memory turn for chat_id=%s", chat_id)
                turn_context = None
                previous_thread_id = None if stateless else state_repo.get_thread_id(chat_id)
        else:
            previous_thread_id = None if stateless else state_repo.get_thread_id(chat_id)
        emit_event(
            "bridge.request_processing_started",
            fields={
                "chat_id": chat_id,
                "message_id": message_id,
                "prompt_chars": len(prompt or ""),
                "has_photo": bool(photo_file_id),
                "has_voice": bool(voice_file_id),
                "has_document": document is not None,
                "has_previous_thread": bool(previous_thread_id),
            },
        )
        progress.set_phase(f"Sending request to {assistant_label(config)}.")
        result = execute_prompt_with_retry(
            state_repo=state_repo,
            config=config,
            client=client,
            engine=active_engine,
            chat_id=chat_id,
            message_id=message_id,
            prompt_text=prompt_text,
            previous_thread_id=previous_thread_id,
            image_path=image_path,
            progress=progress,
            cancel_event=cancel_event,
            session_continuity_enabled=not stateless,
        )
        if result is None:
            return
        new_thread_id, output = finalize_prompt_success(
            state_repo=state_repo,
            config=config,
            client=client,
            chat_id=chat_id,
            message_id=message_id,
            result=result,
            progress=progress,
        )
        if stateless:
            state_repo.clear_thread_id(chat_id)
        if memory_engine is not None and turn_context is not None:
            if stateless:
                state_repo.clear_thread_id(chat_id)
            try:
                memory_engine.finish_turn(
                    turn_context,
                    channel="telegram",
                    assistant_text=output,
                    new_thread_id=new_thread_id,
                )
            except Exception:
                logging.exception("Failed to finish shared memory turn for chat_id=%s", chat_id)
    finally:
        progress.close()
        clear_cancel_event(state, chat_id, expected_event=cancel_event)
        if image_path:
            try:
                os.remove(image_path)
            except OSError:
                logging.warning("Failed to remove temp image file: %s", image_path)
        if document_path:
            try:
                os.remove(document_path)
            except OSError:
                logging.warning("Failed to remove temp file: %s", document_path)
        finalize_chat_work(state, client, chat_id)
        emit_event(
            "bridge.request_processing_finished",
            fields={"chat_id": chat_id, "message_id": message_id},
        )


def process_message_worker(
    state: State,
    config,
    client: ChannelAdapter,
    engine: Optional[EngineAdapter],
    chat_id: int,
    message_id: Optional[int],
    prompt: str,
    photo_file_id: Optional[str],
    voice_file_id: Optional[str],
    document: Optional[DocumentPayload],
    cancel_event: Optional[threading.Event] = None,
    stateless: bool = False,
    sender_name: str = "Telegram User",
    enforce_voice_prefix_from_transcript: bool = False,
) -> None:
    try:
        process_prompt(
            state,
            config,
            client,
            engine,
            chat_id,
            message_id,
            prompt,
            photo_file_id,
            voice_file_id,
            document,
            cancel_event,
            stateless=stateless,
            sender_name=sender_name,
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


def handle_reset_command(
    state: State,
    config,
    client: ChannelAdapter,
    chat_id: int,
    message_id: Optional[int],
) -> None:
    state_repo = StateRepository(state)
    removed_thread = state_repo.clear_thread_id(chat_id)
    removed_worker = state_repo.clear_worker_session(chat_id) if config.persistent_workers_enabled else False
    memory_engine = state.memory_engine if isinstance(state.memory_engine, MemoryEngine) else None
    if memory_engine is not None:
        try:
            memory_engine.clear_session(MemoryEngine.telegram_key(chat_id))
        except Exception:
            logging.exception("Failed to clear shared memory session for chat_id=%s", chat_id)
    if removed_thread or removed_worker:
        client.send_message(
            chat_id,
            "Context reset. Your next message starts a new conversation.",
            reply_to_message_id=message_id,
        )
        return
    client.send_message(
        chat_id,
        "No saved context was found for this chat.",
        reply_to_message_id=message_id,
    )


def handle_restart_command(
    state: State,
    client: ChannelAdapter,
    chat_id: int,
    message_id: Optional[int],
) -> None:
    status, busy_count = request_safe_restart(state, chat_id, message_id)
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
        )
        return
    if status == "already_queued":
        client.send_message(
            chat_id,
            "Restart is already queued and will run after current work completes.",
            reply_to_message_id=message_id,
        )
        return
    if status == "queued":
        client.send_message(
            chat_id,
            f"Safe restart queued. Waiting for {busy_count} active request(s) to finish.",
            reply_to_message_id=message_id,
        )
        return

    client.send_message(
        chat_id,
        "No active request. Restarting bridge now.",
        reply_to_message_id=message_id,
    )
    trigger_restart_async(state, client, chat_id, message_id)


def handle_cancel_command(
    state: State,
    client: ChannelAdapter,
    chat_id: int,
    message_id: Optional[int],
) -> None:
    status = request_chat_cancel(state, chat_id)
    emit_event(
        "bridge.cancel_requested",
        fields={"chat_id": chat_id, "message_id": message_id, "status": status},
    )
    if status == "requested":
        client.send_message(
            chat_id,
            CANCEL_REQUESTED_MESSAGE,
            reply_to_message_id=message_id,
        )
        return
    if status == "already_requested":
        client.send_message(
            chat_id,
            CANCEL_ALREADY_REQUESTED_MESSAGE,
            reply_to_message_id=message_id,
        )
        return
    if status == "unavailable":
        client.send_message(
            chat_id,
            "Active request cannot be canceled at this stage. Please wait a few seconds and retry.",
            reply_to_message_id=message_id,
        )
        return
    client.send_message(
        chat_id,
        CANCEL_NO_ACTIVE_MESSAGE,
        reply_to_message_id=message_id,
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
) -> None:
    if not prompt_input.strip():
        return
    if command is not None:
        return
    if priority_keyword_mode:
        return
    if photo_file_id or voice_file_id or document is not None:
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


def handle_known_command(
    state: State,
    config,
    client: ChannelAdapter,
    chat_id: int,
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
            build_status_text(state, config, chat_id=chat_id),
            reply_to_message_id=message_id,
        )
        return True
    if command == "/restart":
        handle_restart_command(state, client, chat_id, message_id)
        return True
    if command == "/cancel":
        handle_cancel_command(state, client, chat_id, message_id)
        return True
    if command == "/reset":
        handle_reset_command(state, config, client, chat_id, message_id)
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
    return False


def start_message_worker(
    state: State,
    config,
    client: ChannelAdapter,
    engine: Optional[EngineAdapter],
    chat_id: int,
    message_id: Optional[int],
    prompt: str,
    photo_file_id: Optional[str],
    voice_file_id: Optional[str],
    document: Optional[DocumentPayload],
    cancel_event: Optional[threading.Event] = None,
    stateless: bool = False,
    sender_name: str = "Telegram User",
    enforce_voice_prefix_from_transcript: bool = False,
) -> None:
    worker = threading.Thread(
        target=process_message_worker,
        args=(
            state,
            config,
            client,
            engine,
            chat_id,
            message_id,
            prompt,
            photo_file_id,
            voice_file_id,
            document,
            cancel_event,
            stateless,
            sender_name,
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
    message, chat_id, message_id = extract_chat_context(update)
    if message is None or chat_id is None:
        return
    update_id = update.get("update_id")
    update_id_int = update_id if isinstance(update_id, int) else None
    emit_event(
        "bridge.update_received",
        fields={
            "chat_id": chat_id,
            "message_id": message_id,
            "update_id": update_id_int,
        },
    )

    if chat_id not in config.allowed_chat_ids:
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

    prompt_input, photo_file_id, voice_file_id, document = extract_prompt_and_media(message)
    if prompt_input is None and voice_file_id is None and document is None:
        return

    chat_obj = message.get("chat")
    chat_type = chat_obj.get("type") if isinstance(chat_obj, dict) else None
    is_private_chat = isinstance(chat_type, str) and chat_type == "private"
    requires_prefix_for_message = bool(config.required_prefixes) and (
        config.require_prefix_in_private or not is_private_chat
    )
    prefix_bypass_command = normalize_command(prompt_input or "")

    enforce_voice_prefix_from_transcript = False
    if (
        prompt_input is not None
        and requires_prefix_for_message
        and not command_bypasses_required_prefix(client, prefix_bypass_command)
    ):
        voice_without_caption = bool(voice_file_id) and not prompt_input.strip()
        if voice_without_caption:
            enforce_voice_prefix_from_transcript = True
        else:
            has_required_prefix, stripped_prompt = strip_required_prefix(
                prompt_input,
                config.required_prefixes,
                config.required_prefix_ignore_case,
            )
            if not has_required_prefix:
                emit_event(
                    "bridge.request_ignored",
                    fields={"chat_id": chat_id, "message_id": message_id, "reason": "prefix_required"},
                )
                return
            prompt_input = stripped_prompt
            if not prompt_input and voice_file_id is None and document is None:
                emit_event(
                    "bridge.request_rejected",
                    level=logging.WARNING,
                    fields={"chat_id": chat_id, "message_id": message_id, "reason": "prefix_missing_action"},
                )
                client.send_message(
                    chat_id,
                    PREFIX_HELP_MESSAGE,
                    reply_to_message_id=message_id,
                )
                return

    sender_name = extract_sender_name(message)
    stateless = False
    command = normalize_command(prompt_input or "")
    priority_keyword_mode = False
    if prompt_input:
        nextcloud_keyword_mode, nextcloud_request = extract_nextcloud_keyword_request(prompt_input)
        if nextcloud_keyword_mode:
            if not nextcloud_request.strip():
                emit_event(
                    "bridge.request_rejected",
                    level=logging.WARNING,
                    fields={
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "reason": "nextcloud_keyword_missing_action",
                    },
                )
                client.send_message(
                    chat_id,
                    NEXTCLOUD_KEYWORD_HELP_MESSAGE,
                    reply_to_message_id=message_id,
                )
                return
            prompt_input = build_nextcloud_keyword_prompt(nextcloud_request)
            command = None
            stateless = True
            priority_keyword_mode = True
            emit_event(
                "bridge.nextcloud_keyword_routed",
                fields={"chat_id": chat_id, "message_id": message_id},
            )
        else:
            server3_keyword_mode, server3_request = extract_server3_keyword_request(prompt_input)
            if server3_keyword_mode:
                if not server3_request.strip():
                    emit_event(
                        "bridge.request_rejected",
                        level=logging.WARNING,
                        fields={
                            "chat_id": chat_id,
                            "message_id": message_id,
                            "reason": "server3_keyword_missing_action",
                        },
                    )
                    client.send_message(
                        chat_id,
                        SERVER3_KEYWORD_HELP_MESSAGE,
                        reply_to_message_id=message_id,
                    )
                    return
                prompt_input = build_server3_keyword_prompt(server3_request)
                command = None
                stateless = True
                priority_keyword_mode = True
                emit_event(
                    "bridge.server3_keyword_routed",
                    fields={"chat_id": chat_id, "message_id": message_id},
                )
            else:
                ha_keyword_mode, ha_request = extract_ha_keyword_request(prompt_input)
                if not ha_keyword_mode:
                    ha_request = ""
                if ha_keyword_mode:
                    if not ha_request.strip():
                        emit_event(
                            "bridge.request_rejected",
                            level=logging.WARNING,
                            fields={
                                "chat_id": chat_id,
                                "message_id": message_id,
                                "reason": "ha_keyword_missing_action",
                            },
                        )
                        client.send_message(
                            chat_id,
                            HA_KEYWORD_HELP_MESSAGE,
                            reply_to_message_id=message_id,
                        )
                        return
                    prompt_input = build_ha_keyword_prompt(ha_request)
                    command = None
                    stateless = True
                    priority_keyword_mode = True
                    emit_event(
                        "bridge.ha_keyword_routed",
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
            photo_file_id=photo_file_id,
            voice_file_id=voice_file_id,
            document=document,
        )

    memory_engine = state.memory_engine if isinstance(state.memory_engine, MemoryEngine) else None
    if memory_engine is not None and prompt_input and not priority_keyword_mode:
        cmd_result = handle_memory_command(
            engine=memory_engine,
            conversation_key=MemoryEngine.telegram_key(chat_id),
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
        chat_id,
        message_id,
        command,
        prompt_input or "",
    ):
        emit_event(
            "bridge.command_handled",
            fields={"chat_id": chat_id, "message_id": message_id, "command": command or ""},
        )
        return

    prompt = (prompt_input or "").strip()
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

    if is_rate_limited(state, config, chat_id):
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
        if not ensure_chat_worker_session(state, config, client, chat_id, message_id):
            emit_event(
                "bridge.request_rejected",
                level=logging.WARNING,
                fields={"chat_id": chat_id, "message_id": message_id, "reason": "worker_capacity"},
            )
            return

    if not mark_busy(state, chat_id):
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
    cancel_event = register_cancel_event(state, chat_id)
    state_repo = StateRepository(state)
    state_repo.mark_in_flight_request(chat_id, message_id)
    emit_event(
        "bridge.request_accepted",
        fields={
            "chat_id": chat_id,
            "message_id": message_id,
            "has_photo": bool(photo_file_id),
            "has_voice": bool(voice_file_id),
            "has_document": document is not None,
            "stateless": stateless,
        },
    )
    start_message_worker(
        state=state,
        config=config,
        client=client,
        engine=engine,
        chat_id=chat_id,
        message_id=message_id,
        prompt=prompt,
        photo_file_id=photo_file_id,
        voice_file_id=voice_file_id,
        document=document,
        cancel_event=cancel_event,
        stateless=stateless,
        sender_name=sender_name,
        enforce_voice_prefix_from_transcript=enforce_voice_prefix_from_transcript,
    )
    emit_event(
        "bridge.worker_started",
        fields={"chat_id": chat_id, "message_id": message_id},
    )
    return
