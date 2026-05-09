import logging
import threading
import time
from typing import Optional

from telegram_bridge.background_tasks import start_daemon_thread
from telegram_bridge.executor import ExecutorProgressEvent
from telegram_bridge.response_delivery import compact_progress_text
from telegram_bridge.structured_logging import emit_event
from telegram_bridge.transport import TELEGRAM_LIMIT

PROGRESS_TYPING_INTERVAL_SECONDS = 4
PROGRESS_EDIT_MIN_INTERVAL_SECONDS = 6
PROGRESS_HEARTBEAT_EDIT_SECONDS = 30
COMPACT_PROGRESS_EDIT_MIN_INTERVAL_SECONDS = 5
COMPACT_PROGRESS_HEARTBEAT_EDIT_SECONDS = 15
COMPACT_PROGRESS_ELAPSED_STEP_SECONDS = 5


def trim_output(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    marker = "\n\n[output truncated]"
    return text[: max(0, limit - len(marker))] + marker


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
            COMPACT_PROGRESS_EDIT_MIN_INTERVAL_SECONDS
            if self._is_compact_progress
            else PROGRESS_EDIT_MIN_INTERVAL_SECONDS
        )
        self._heartbeat_edit_seconds = (
            COMPACT_PROGRESS_HEARTBEAT_EDIT_SECONDS
            if self._is_compact_progress
            else PROGRESS_HEARTBEAT_EDIT_SECONDS
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
            elapsed = self._compact_elapsed_seconds(elapsed)
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
        if text == self.last_rendered_text:
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

    @staticmethod
    def _compact_elapsed_seconds(elapsed: int) -> int:
        return max(
            1,
            (elapsed // COMPACT_PROGRESS_ELAPSED_STEP_SECONDS)
            * COMPACT_PROGRESS_ELAPSED_STEP_SECONDS,
        )
