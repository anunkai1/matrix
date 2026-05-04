import logging
import threading
import time
from typing import Dict, List, Optional

try:
    from .background_tasks import start_daemon_thread
    from .conversation_scope import ConversationScope, build_telegram_scope_key, scope_from_message
    from .executor import ExecutorProgressEvent
    from .memory_engine import MemoryEngine
    from .memory_scope import resolve_memory_conversation_key
    from .runtime_profile import assistant_label
    from .state_store import State, StateRepository
    from .structured_logging import emit_event
    from .transport import TELEGRAM_LIMIT
    from .engine_controls import selectable_engine_plugins
    from .response_delivery import compact_progress_text
except ImportError:
    from background_tasks import start_daemon_thread
    from conversation_scope import ConversationScope, build_telegram_scope_key, scope_from_message
    from executor import ExecutorProgressEvent
    from memory_engine import MemoryEngine
    from memory_scope import resolve_memory_conversation_key
    from runtime_profile import assistant_label
    from state_store import State, StateRepository
    from structured_logging import emit_event
    from transport import TELEGRAM_LIMIT
    from engine_controls import selectable_engine_plugins
    from response_delivery import compact_progress_text


PROGRESS_TYPING_INTERVAL_SECONDS = 4
PROGRESS_EDIT_MIN_INTERVAL_SECONDS = 6
PROGRESS_HEARTBEAT_EDIT_SECONDS = 30
RATE_LIMIT_MESSAGE = "Rate limit exceeded. Please wait a minute and retry."


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
        client,
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
        self._worker = start_daemon_thread(self._heartbeat_loop)

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
    return base


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
                lines.append(f"Memory messages (last 5000 tokens): {memory_status.message_count}")
                lines.append(f"Memory session active: {memory_status.session_active}")

    return "\n".join(lines)
