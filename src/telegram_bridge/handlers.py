import logging
import json
import os
import re
import secrets
import shlex
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

try:
    from .executor import (
        ExecutorProgressEvent,
        parse_executor_output,
        should_reset_thread_after_resume_failure,
    )
    from .channel_adapter import ChannelAdapter
    from .engine_adapter import CodexEngineAdapter, EngineAdapter
    from .media import TelegramFileDownloadSpec, download_telegram_file_to_temp
    from .memory_engine import MemoryEngine, TurnContext, build_memory_help_lines, handle_memory_command
    from .google_ops import CalendarEventSummary, GmailMessageSummary, GoogleOpsClient, GoogleOpsError
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
        ExecutorProgressEvent,
        parse_executor_output,
        should_reset_thread_after_resume_failure,
    )
    from channel_adapter import ChannelAdapter
    from engine_adapter import CodexEngineAdapter, EngineAdapter
    from media import TelegramFileDownloadSpec, download_telegram_file_to_temp
    from memory_engine import MemoryEngine, TurnContext, build_memory_help_lines, handle_memory_command
    from google_ops import CalendarEventSummary, GmailMessageSummary, GoogleOpsClient, GoogleOpsError
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
GOOGLE_CONFIRM_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
GOOGLE_CONFIRM_CODE_LENGTH = 6
GOOGLE_CONFIRM_COMMAND = "/google confirm"
RATE_LIMIT_MESSAGE = "Rate limit exceeded. Please wait a minute and retry."
RETRY_WITH_NEW_SESSION_PHASE = "Execution failed. Retrying once with a new session."
RETRY_FAILED_MESSAGE = "Execution failed after an automatic retry. Please resend your request."
HA_KEYWORD_HELP_MESSAGE = (
    "HA mode needs an action. Example: `HA turn on masters AC to dry mode at 9:25am`."
)
PREFIX_HELP_MESSAGE = (
    "Helper mode needs a prefixed prompt. Example: `@helper summarize this file`."
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
    document_path: Optional[str] = None


@dataclass
class OutboundMediaDirective:
    media_ref: str
    as_voice: bool


@dataclass
class PendingGoogleAction:
    code: str
    kind: str
    payload: Dict[str, str]
    summary: str
    created_at: float


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


def assistant_label(config) -> str:
    value = getattr(config, "assistant_name", "").strip()
    return value or "Architect"


def start_command_message(config) -> str:
    return f"Telegram {assistant_label(config)} bridge is online. Send a prompt to begin."


def resume_retry_phase(config) -> str:
    return f"Retrying as a new {assistant_label(config)} session."


def normalize_command(text: str) -> Optional[str]:
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    head = stripped.split(maxsplit=1)[0]
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
        fallback_text = output or ""
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
        client.send_message(chat_id, rendered_text, reply_to_message_id=message_id)
        return rendered_text

    caption = rendered_text if rendered_text else None
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
        fallback_text = rendered_text or output
        client.send_message(chat_id, fallback_text, reply_to_message_id=message_id)
        return fallback_text

    if follow_up_text:
        client.send_message(chat_id, follow_up_text, reply_to_message_id=message_id)

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
    ) -> None:
        self.client = client
        self.chat_id = chat_id
        self.reply_to_message_id = reply_to_message_id
        self.assistant_name = assistant_name
        self.started_at = time.time()
        self.progress_message_id: Optional[int] = None
        self.phase = "Starting request."
        self.commands_started = 0
        self.commands_completed = 0
        self.pending_update = True
        self.last_edit_at = 0.0
        self.last_rendered_text = ""
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker: Optional[threading.Thread] = None

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
                next_progress_at = now + PROGRESS_HEARTBEAT_EDIT_SECONDS
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
        text = f"{self.assistant_name} is working... {elapsed}s elapsed.\n{phase}"
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
        if not force and now - self.last_edit_at < PROGRESS_EDIT_MIN_INTERVAL_SECONDS:
            return

        text = self._render_progress_text()
        if not force and text == self.last_rendered_text:
            with self._lock:
                self.pending_update = False
            return

        try:
            self.client.edit_message(self.chat_id, message_id, text)
        except RuntimeError as exc:
            if "message is not modified" in str(exc).lower():
                with self._lock:
                    self.pending_update = False
                return
            logging.debug("Failed to edit progress message for chat_id=%s: %s", self.chat_id, exc)
            return
        except Exception:
            logging.debug("Failed to edit progress message for chat_id=%s", self.chat_id)
            return

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


def extract_prompt_and_media(
    message: Dict[str, object]
) -> tuple[Optional[str], Optional[str], Optional[str], Optional[DocumentPayload]]:
    text = message.get("text")
    if isinstance(text, str):
        return text, None, None, None

    photo_items = message.get("photo")
    if isinstance(photo_items, list) and photo_items:
        file_id = pick_largest_photo_file_id(photo_items)
        if not file_id:
            return None, None, None, None

        caption = message.get("caption")
        if isinstance(caption, str) and caption.strip():
            return caption, file_id, None, None
        return "Please analyze this image.", file_id, None, None

    voice = message.get("voice")
    if isinstance(voice, dict):
        voice_file_id = voice.get("file_id")
        if not isinstance(voice_file_id, str) or not voice_file_id.strip():
            return None, None, None, None
        caption = message.get("caption")
        if isinstance(caption, str):
            return caption, None, voice_file_id.strip(), None
        return "", None, voice_file_id.strip(), None

    document = message.get("document")
    if isinstance(document, dict):
        file_id = document.get("file_id")
        if not isinstance(file_id, str) or not file_id.strip():
            return None, None, None, None
        file_name = document.get("file_name")
        mime_type = document.get("mime_type")
        payload = DocumentPayload(
            file_id=file_id.strip(),
            file_name=file_name.strip() if isinstance(file_name, str) and file_name.strip() else "unnamed",
            mime_type=mime_type.strip() if isinstance(mime_type, str) and mime_type.strip() else "unknown",
        )
        caption = message.get("caption")
        if isinstance(caption, str) and caption.strip():
            return caption, None, None, payload
        return "Please analyze this file.", None, None, payload

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


def extract_sender_id(message: Dict[str, object]) -> Optional[int]:
    sender = message.get("from")
    if not isinstance(sender, dict):
        return None
    sender_id = sender.get("id")
    if isinstance(sender_id, int):
        return sender_id
    return None


def build_google_help_text(config) -> str:
    enabled = getattr(config, "google_enabled", False)
    status = "enabled" if enabled else "disabled"
    return (
        "Google assistant commands:\n"
        f"- Status: {status}\n"
        "- /google help\n"
        "- /google gmail unread [limit]\n"
        "- /google gmail read <message_id>\n"
        "- /google gmail send <to_email> | <subject> | <body>\n"
        "- /google calendar today [limit]\n"
        "- /google calendar agenda [days]\n"
        "- /google calendar create <start_iso> | <end_iso> | <title> | [description]\n"
        "- /google confirm <code>\n"
        "- /google cancel\n\n"
        "Notes:\n"
        "- send/create actions are pending until confirmed.\n"
        "- datetime format: 2026-03-01T17:30 or 2026-03-01T17:30+10:00"
    )


def parse_positive_int(value: str, fallback: int, minimum: int, maximum: int) -> int:
    if not value.strip():
        return fallback
    parsed = int(value.strip())
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"value must be between {minimum} and {maximum}")
    return parsed


def parse_pipe_fields(raw: str, min_parts: int, max_parts: int) -> Optional[List[str]]:
    parts = [item.strip() for item in raw.split("|")]
    if len(parts) < min_parts or len(parts) > max_parts:
        return None
    if any(not part for part in parts):
        return None
    return parts


def build_google_client(config) -> GoogleOpsClient:
    return GoogleOpsClient(
        client_secret_path=getattr(
            config,
            "google_client_secret_path",
            "/home/architect/.config/google/architect/client_secret.json",
        ),
        token_path=getattr(
            config,
            "google_token_path",
            "/home/architect/.config/google/architect/oauth_token.json",
        ),
        default_timezone=getattr(config, "google_default_timezone", "Australia/Brisbane"),
    )


def is_google_sender_allowed(config, sender_id: Optional[int]) -> bool:
    allowed = getattr(config, "google_allowed_sender_ids", set())
    if not allowed:
        return True
    if sender_id is None:
        return False
    return sender_id in allowed


def make_google_confirm_code() -> str:
    return "".join(secrets.choice(GOOGLE_CONFIRM_ALPHABET) for _ in range(GOOGLE_CONFIRM_CODE_LENGTH))


def get_or_init_google_pending_store(state: State) -> Dict[int, PendingGoogleAction]:
    store = getattr(state, "google_pending_actions", None)
    if not isinstance(store, dict):
        store = {}
        state.google_pending_actions = store
    return store


def set_pending_google_action(state: State, chat_id: int, action: PendingGoogleAction) -> None:
    with state.lock:
        store = get_or_init_google_pending_store(state)
        store[chat_id] = action


def get_pending_google_action(state: State, chat_id: int) -> Optional[PendingGoogleAction]:
    with state.lock:
        store = get_or_init_google_pending_store(state)
        action = store.get(chat_id)
        if isinstance(action, PendingGoogleAction):
            return action
        return None


def clear_pending_google_action(state: State, chat_id: int) -> bool:
    with state.lock:
        store = get_or_init_google_pending_store(state)
        if chat_id in store:
            del store[chat_id]
            return True
    return False


def render_gmail_summary(item: GmailMessageSummary) -> str:
    return (
        f"ID: `{item.message_id}`\n"
        f"From: {item.from_value}\n"
        f"Subject: {item.subject}\n"
        f"Date: {item.date}\n"
        f"Snippet: {item.snippet or '(no snippet)'}"
    )


def render_calendar_summary(item: CalendarEventSummary) -> str:
    base = (
        f"ID: `{item.event_id}`\n"
        f"Title: {item.summary}\n"
        f"Start: {item.start}\n"
        f"End: {item.end}"
    )
    if item.html_link:
        return f"{base}\nLink: {item.html_link}"
    return base


def build_calendar_list_response(events: List[CalendarEventSummary], heading: str) -> str:
    if not events:
        return f"{heading}\nNo events found."
    lines = [heading]
    for index, event in enumerate(events, start=1):
        lines.append(
            (
                f"{index}. {event.summary}\n"
                f"   start: {event.start}\n"
                f"   end: {event.end}\n"
                f"   id: {event.event_id}"
            )
        )
    return trim_output("\\n".join(lines), TELEGRAM_LIMIT)


def build_gmail_list_response(messages: List[GmailMessageSummary], heading: str) -> str:
    if not messages:
        return f"{heading}\nNo matching emails found."
    lines = [heading]
    for index, item in enumerate(messages, start=1):
        lines.append(
            (
                f"{index}. {item.subject}\n"
                f"   from: {item.from_value}\n"
                f"   date: {item.date}\n"
                f"   id: {item.message_id}"
            )
        )
    return trim_output("\\n".join(lines), TELEGRAM_LIMIT)


def _handle_google_confirm_command(
    state: State,
    config,
    client: ChannelAdapter,
    chat_id: int,
    message_id: Optional[int],
    confirm_code: str,
) -> bool:
    pending = get_pending_google_action(state, chat_id)
    if pending is None:
        client.send_message(
            chat_id,
            "No pending Google action to confirm.",
            reply_to_message_id=message_id,
        )
        return True

    ttl_seconds = max(30, int(getattr(config, "google_pending_confirm_ttl_seconds", 600)))
    age_seconds = time.time() - pending.created_at
    if age_seconds > ttl_seconds:
        clear_pending_google_action(state, chat_id)
        client.send_message(
            chat_id,
            "Pending Google action expired. Please run the command again.",
            reply_to_message_id=message_id,
        )
        return True

    if pending.code.casefold() != confirm_code.casefold():
        client.send_message(
            chat_id,
            "Confirmation code does not match pending action.",
            reply_to_message_id=message_id,
        )
        return True

    try:
        google_client = build_google_client(config)
        if pending.kind == "gmail_send":
            payload = pending.payload
            message_sent_id = google_client.gmail_send_message(
                to_email=payload["to_email"],
                subject=payload["subject"],
                body_text=payload["body"],
            )
            response = f"Gmail sent successfully. Message id: `{message_sent_id}`"
        elif pending.kind == "calendar_create":
            payload = pending.payload
            created = google_client.calendar_create_event(
                title=payload["title"],
                start_iso=payload["start_iso"],
                end_iso=payload["end_iso"],
                description=payload.get("description", ""),
            )
            response = (
                "Calendar event created successfully.\n"
                + render_calendar_summary(created)
            )
        else:
            clear_pending_google_action(state, chat_id)
            client.send_message(
                chat_id,
                "Pending Google action type is unknown. Cleared.",
                reply_to_message_id=message_id,
            )
            return True
    except GoogleOpsError as exc:
        logging.warning("Google action confirm failed for chat_id=%s: %s", chat_id, exc)
        client.send_message(
            chat_id,
            f"Google action failed: {exc}",
            reply_to_message_id=message_id,
        )
        return True
    except Exception:
        logging.exception("Unexpected Google action confirm failure for chat_id=%s", chat_id)
        client.send_message(
            chat_id,
            "Google action failed due to an unexpected error.",
            reply_to_message_id=message_id,
        )
        return True

    clear_pending_google_action(state, chat_id)
    client.send_message(
        chat_id,
        trim_output(response, TELEGRAM_LIMIT),
        reply_to_message_id=message_id,
    )
    return True


def handle_google_command(
    state: State,
    config,
    client: ChannelAdapter,
    chat_id: int,
    message_id: Optional[int],
    raw_text: str,
    sender_id: Optional[int],
) -> bool:
    if not getattr(config, "google_enabled", False):
        client.send_message(
            chat_id,
            "Google assistant commands are disabled. Set TELEGRAM_GOOGLE_ENABLED=true.",
            reply_to_message_id=message_id,
        )
        return True

    if not is_google_sender_allowed(config, sender_id):
        client.send_message(
            chat_id,
            "Google assistant commands are not allowed for this Telegram user.",
            reply_to_message_id=message_id,
        )
        return True

    pieces = raw_text.strip().split(maxsplit=1)
    tail = pieces[1].strip() if len(pieces) > 1 else "help"
    if not tail:
        tail = "help"

    try:
        tokens = shlex.split(tail)
    except ValueError:
        client.send_message(
            chat_id,
            "Invalid quoting in /google command.",
            reply_to_message_id=message_id,
        )
        return True
    if not tokens:
        tokens = ["help"]

    top = tokens[0].lower()
    if top in ("help", "h"):
        client.send_message(
            chat_id,
            build_google_help_text(config),
            reply_to_message_id=message_id,
        )
        return True

    if top == "cancel":
        cleared = clear_pending_google_action(state, chat_id)
        message = "Pending Google action canceled." if cleared else "No pending Google action."
        client.send_message(chat_id, message, reply_to_message_id=message_id)
        return True

    if top == "confirm":
        if len(tokens) < 2:
            client.send_message(
                chat_id,
                f"Usage: {GOOGLE_CONFIRM_COMMAND} <code>",
                reply_to_message_id=message_id,
            )
            return True
        return _handle_google_confirm_command(
            state=state,
            config=config,
            client=client,
            chat_id=chat_id,
            message_id=message_id,
            confirm_code=tokens[1].strip(),
        )

    try:
        google_client = build_google_client(config)
        max_results = max(1, min(int(getattr(config, "google_max_results", 10)), 50))

        if top == "gmail":
            if len(tokens) < 2:
                client.send_message(
                    chat_id,
                    build_google_help_text(config),
                    reply_to_message_id=message_id,
                )
                return True
            gmail_action = tokens[1].lower()

            if gmail_action in ("unread", "list"):
                limit = max_results
                if len(tokens) >= 3:
                    limit = parse_positive_int(tokens[2], max_results, 1, 50)
                messages = google_client.gmail_list_unread(limit=limit)
                client.send_message(
                    chat_id,
                    build_gmail_list_response(messages, heading=f"Unread Gmail (max {limit})"),
                    reply_to_message_id=message_id,
                )
                return True

            if gmail_action == "read":
                if len(tokens) < 3:
                    client.send_message(
                        chat_id,
                        "Usage: /google gmail read <message_id>",
                        reply_to_message_id=message_id,
                    )
                    return True
                message_summary = google_client.gmail_read_message(tokens[2])
                client.send_message(
                    chat_id,
                    trim_output(render_gmail_summary(message_summary), TELEGRAM_LIMIT),
                    reply_to_message_id=message_id,
                )
                return True

            if gmail_action == "send":
                match = re.match(r"(?is)^gmail\s+send\s+(.+)$", tail)
                if not match:
                    client.send_message(
                        chat_id,
                        "Usage: /google gmail send <to_email> | <subject> | <body>",
                        reply_to_message_id=message_id,
                    )
                    return True
                parsed_fields = parse_pipe_fields(match.group(1), 3, 3)
                if parsed_fields is None:
                    client.send_message(
                        chat_id,
                        "Usage: /google gmail send <to_email> | <subject> | <body>",
                        reply_to_message_id=message_id,
                    )
                    return True
                to_email, subject, body = parsed_fields
                code = make_google_confirm_code()
                pending = PendingGoogleAction(
                    code=code,
                    kind="gmail_send",
                    payload={"to_email": to_email, "subject": subject, "body": body},
                    summary=f"Send Gmail to {to_email} with subject '{subject}'",
                    created_at=time.time(),
                )
                set_pending_google_action(state, chat_id, pending)
                preview_body = body if len(body) <= 240 else body[:237].rstrip() + "..."
                client.send_message(
                    chat_id,
                    trim_output(
                        (
                            "Pending Gmail send action:\n"
                            f"To: {to_email}\n"
                            f"Subject: {subject}\n"
                            f"Body: {preview_body}\n\n"
                            f"Confirm with: `{GOOGLE_CONFIRM_COMMAND} {code}`\n"
                            "Cancel with: `/google cancel`"
                        ),
                        TELEGRAM_LIMIT,
                    ),
                    reply_to_message_id=message_id,
                )
                return True

            client.send_message(
                chat_id,
                build_google_help_text(config),
                reply_to_message_id=message_id,
            )
            return True

        if top == "calendar":
            if len(tokens) < 2:
                client.send_message(
                    chat_id,
                    build_google_help_text(config),
                    reply_to_message_id=message_id,
                )
                return True
            calendar_action = tokens[1].lower()

            if calendar_action == "today":
                limit = max_results
                if len(tokens) >= 3:
                    limit = parse_positive_int(tokens[2], max_results, 1, 50)
                events = google_client.calendar_today_events(limit=limit)
                client.send_message(
                    chat_id,
                    build_calendar_list_response(events, heading=f"Calendar today (max {limit})"),
                    reply_to_message_id=message_id,
                )
                return True

            if calendar_action in ("agenda", "list"):
                days = 7
                if len(tokens) >= 3:
                    days = parse_positive_int(tokens[2], 7, 1, 30)
                events = google_client.calendar_list_events(days=days, limit=max_results)
                client.send_message(
                    chat_id,
                    build_calendar_list_response(
                        events,
                        heading=f"Calendar agenda (next {days} day{'s' if days != 1 else ''})",
                    ),
                    reply_to_message_id=message_id,
                )
                return True

            if calendar_action in ("create", "add"):
                match = re.match(r"(?is)^calendar\s+(?:create|add)\s+(.+)$", tail)
                if not match:
                    client.send_message(
                        chat_id,
                        "Usage: /google calendar create <start_iso> | <end_iso> | <title> | [description]",
                        reply_to_message_id=message_id,
                    )
                    return True
                parsed_fields = parse_pipe_fields(match.group(1), 3, 4)
                if parsed_fields is None:
                    client.send_message(
                        chat_id,
                        "Usage: /google calendar create <start_iso> | <end_iso> | <title> | [description]",
                        reply_to_message_id=message_id,
                    )
                    return True
                start_iso = parsed_fields[0]
                end_iso = parsed_fields[1]
                title = parsed_fields[2]
                description = parsed_fields[3] if len(parsed_fields) > 3 else ""

                code = make_google_confirm_code()
                pending = PendingGoogleAction(
                    code=code,
                    kind="calendar_create",
                    payload={
                        "start_iso": start_iso,
                        "end_iso": end_iso,
                        "title": title,
                        "description": description,
                    },
                    summary=f"Create calendar event '{title}' from {start_iso} to {end_iso}",
                    created_at=time.time(),
                )
                set_pending_google_action(state, chat_id, pending)

                preview = (
                    "Pending calendar create action:\n"
                    f"Title: {title}\n"
                    f"Start: {start_iso}\n"
                    f"End: {end_iso}\n"
                )
                if description:
                    preview += f"Description: {description}\n"
                preview += (
                    f"\nConfirm with: `{GOOGLE_CONFIRM_COMMAND} {code}`\n"
                    "Cancel with: `/google cancel`"
                )
                client.send_message(
                    chat_id,
                    trim_output(preview, TELEGRAM_LIMIT),
                    reply_to_message_id=message_id,
                )
                return True

            client.send_message(
                chat_id,
                build_google_help_text(config),
                reply_to_message_id=message_id,
            )
            return True

        client.send_message(
            chat_id,
            build_google_help_text(config),
            reply_to_message_id=message_id,
        )
        return True
    except ValueError as exc:
        client.send_message(
            chat_id,
            f"Invalid value: {exc}",
            reply_to_message_id=message_id,
        )
        return True
    except GoogleOpsError as exc:
        logging.warning("Google command failed for chat_id=%s: %s", chat_id, exc)
        client.send_message(
            chat_id,
            f"Google command failed: {exc}",
            reply_to_message_id=message_id,
        )
        return True
    except Exception:
        logging.exception("Unexpected Google command failure for chat_id=%s", chat_id)
        client.send_message(
            chat_id,
            "Google command failed due to an unexpected error.",
            reply_to_message_id=message_id,
        )
        return True


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
    confirm_example = transcript
    required_prefixes = getattr(config, "required_prefixes", [])
    if required_prefixes:
        confirm_example = f"{required_prefixes[0]} {transcript}".strip()
    return (
        f"Voice transcript confidence is low ({confidence:.2f}).\n"
        f"I heard:\n{transcript}\n\n"
        "If this is correct, send it as text so I execute exactly this command:\n"
        f"{confirm_example}\n\n"
        "Or resend a clearer voice note."
    )


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
    name = assistant_label(config)
    base = (
        "Available commands:\n"
        "/start - verify bridge connectivity\n"
        "/help or /h - show this message\n"
        "/status - show bridge status and context\n"
        "/reset - clear saved context for this chat\n"
        "/restart - queue a safe bridge restart\n"
        "/google help - show Google Gmail/Calendar commands\n"
        "/voice-alias list - show pending learned voice corrections\n"
        "/voice-alias approve <id> - approve one learned correction\n"
        "server3-tv-start - start TV desktop mode (local shell command)\n"
        "server3-tv-stop - stop TV desktop mode and return to CLI (local shell command)\n\n"
        f"Send text, images, voice notes, or files and {name} will process them.\n"
        "Use `HA ...` or `Home Assistant ...` to force Home Assistant script routing."
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
                emit_event(
                    "bridge.request_ignored",
                    fields={
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "reason": "prefix_required_transcript",
                    },
                )
                progress.mark_failure("Voice transcript missing required prefix.")
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
    session_continuity_enabled: bool = True,
) -> Optional[subprocess.CompletedProcess[str]]:
    allow_automatic_retry = config.persistent_workers_enabled
    retry_attempted = False
    attempt_thread_id: Optional[str] = previous_thread_id
    attempt = 0

    while True:
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
            )
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
    progress = ProgressReporter(client, chat_id, message_id, assistant_label(config))
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
    ha_keyword_mode: bool,
    photo_file_id: Optional[str],
    voice_file_id: Optional[str],
    document: Optional[DocumentPayload],
) -> None:
    if not prompt_input.strip():
        return
    if command is not None:
        return
    if ha_keyword_mode:
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
    sender_id: Optional[int],
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
    if command == "/google":
        return handle_google_command(
            state=state,
            config=config,
            client=client,
            chat_id=chat_id,
            message_id=message_id,
            raw_text=raw_text,
            sender_id=sender_id,
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

    enforce_voice_prefix_from_transcript = False
    if prompt_input is not None and requires_prefix_for_message:
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
    sender_id = extract_sender_id(message)
    stateless = False
    command = normalize_command(prompt_input or "")
    ha_keyword_mode = False
    if prompt_input:
        ha_keyword_mode, ha_request = extract_ha_keyword_request(prompt_input)
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
            ha_keyword_mode=ha_keyword_mode,
            photo_file_id=photo_file_id,
            voice_file_id=voice_file_id,
            document=document,
        )

    memory_engine = state.memory_engine if isinstance(state.memory_engine, MemoryEngine) else None
    if memory_engine is not None and prompt_input and not ha_keyword_mode:
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
        sender_id,
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
        stateless=stateless,
        sender_name=sender_name,
        enforce_voice_prefix_from_transcript=enforce_voice_prefix_from_transcript,
    )
    emit_event(
        "bridge.worker_started",
        fields={"chat_id": chat_id, "message_id": message_id},
    )
