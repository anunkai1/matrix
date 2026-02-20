#!/usr/bin/env python3
"""Telegram long-poll bridge to local Architect/Codex CLI."""

import argparse
import hashlib
import json
import logging
import os
import shlex
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

TELEGRAM_LIMIT = 4096
OUTPUT_BEGIN_MARKER = "OUTPUT_BEGIN"
PROGRESS_TYPING_INTERVAL_SECONDS = 4
PROGRESS_EDIT_MIN_INTERVAL_SECONDS = 6
PROGRESS_HEARTBEAT_EDIT_SECONDS = 30


@dataclass
class Config:
    token: str
    allowed_chat_ids: Set[int]
    api_base: str
    poll_timeout_seconds: int
    retry_sleep_seconds: float
    exec_timeout_seconds: int
    max_input_chars: int
    max_output_chars: int
    max_image_bytes: int
    max_voice_bytes: int
    max_document_bytes: int
    rate_limit_per_minute: int
    executor_cmd: List[str]
    voice_transcribe_cmd: List[str]
    voice_transcribe_timeout_seconds: int
    state_dir: str
    persistent_workers_enabled: bool
    persistent_workers_max: int
    persistent_workers_idle_timeout_seconds: int
    persistent_workers_policy_files: List[str]
    busy_message: str = "Another request is still running. Please wait."
    denied_message: str = "Access denied for this chat."
    timeout_message: str = "Request timed out. Please try a shorter prompt."
    generic_error_message: str = "Execution failed. Please try again later."
    image_download_error_message: str = "Image download failed. Please send another image."
    voice_download_error_message: str = "Voice download failed. Please send another voice message."
    document_download_error_message: str = "File download failed. Please send another file."
    voice_not_configured_message: str = (
        "Voice transcription is not configured. Please ask admin to set TELEGRAM_VOICE_TRANSCRIBE_CMD."
    )
    voice_transcribe_error_message: str = "Voice transcription failed. Please send clearer audio."
    voice_transcribe_empty_message: str = (
        "Voice transcription was empty. Please send clearer audio."
    )
    empty_output_message: str = "(No output from Architect)"


@dataclass
class State:
    started_at: float = field(default_factory=time.time)
    busy_chats: Set[int] = field(default_factory=set)
    recent_requests: Dict[int, List[float]] = field(default_factory=dict)
    chat_threads: Dict[int, str] = field(default_factory=dict)
    chat_thread_path: str = ""
    worker_sessions: Dict[int, "WorkerSession"] = field(default_factory=dict)
    worker_sessions_path: str = ""
    in_flight_requests: Dict[int, Dict[str, object]] = field(default_factory=dict)
    in_flight_path: str = ""
    restart_requested: bool = False
    restart_in_progress: bool = False
    restart_chat_id: Optional[int] = None
    restart_reply_to_message_id: Optional[int] = None
    lock: threading.Lock = field(default_factory=threading.Lock)


@dataclass
class DocumentPayload:
    file_id: str
    file_name: str
    mime_type: str


@dataclass
class ExecutorProgressEvent:
    kind: str
    detail: str = ""
    exit_code: Optional[int] = None


@dataclass
class WorkerSession:
    created_at: float
    last_used_at: float
    thread_id: str
    policy_fingerprint: str


def parse_int_env(name: str, default: int, minimum: int = 1) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return parsed


def parse_bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in ("1", "true", "yes", "on"):
        return True
    if normalized in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"{name} must be a boolean value")


def parse_allowed_chat_ids(raw: str) -> Set[int]:
    values = [item.strip() for item in raw.split(",") if item.strip()]
    if not values:
        raise ValueError("TELEGRAM_ALLOWED_CHAT_IDS is empty")
    parsed: Set[int] = set()
    for value in values:
        try:
            parsed.add(int(value))
        except ValueError as exc:
            raise ValueError(
                f"Invalid TELEGRAM_ALLOWED_CHAT_IDS value: {value!r}"
            ) from exc
    return parsed


def build_repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def build_policy_watch_files() -> List[str]:
    repo_root = build_repo_root()
    return [
        os.path.join(repo_root, "AGENTS.md"),
        os.path.join(repo_root, "ARCHITECT_INSTRUCTION.md"),
        os.path.join(repo_root, "SERVER3_PROGRESS.md"),
    ]


def build_default_executor() -> str:
    repo_root = build_repo_root()
    return os.path.join(repo_root, "src", "telegram_bridge", "executor.sh")


def build_restart_script_path() -> str:
    repo_root = build_repo_root()
    return os.path.join(repo_root, "ops", "telegram-bridge", "restart_and_verify.sh")


def parse_executor_cmd() -> List[str]:
    raw = os.getenv("TELEGRAM_EXECUTOR_CMD", "").strip()
    if raw:
        cmd = shlex.split(raw)
        if not cmd:
            raise ValueError("TELEGRAM_EXECUTOR_CMD cannot be blank")
        return cmd
    return [build_default_executor()]


def parse_optional_cmd_env(name: str) -> List[str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return []
    cmd = shlex.split(raw)
    if not cmd:
        raise ValueError(f"{name} cannot be blank")
    return cmd


def load_config() -> Config:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required")

    raw_chat_ids = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").strip()
    if not raw_chat_ids:
        raise ValueError("TELEGRAM_ALLOWED_CHAT_IDS is required")
    state_dir = os.getenv(
        "TELEGRAM_BRIDGE_STATE_DIR",
        "/home/architect/.local/state/telegram-architect-bridge",
    ).strip()
    if not state_dir:
        raise ValueError("TELEGRAM_BRIDGE_STATE_DIR cannot be empty")

    allowed_chat_ids = parse_allowed_chat_ids(raw_chat_ids)

    return Config(
        token=token,
        allowed_chat_ids=allowed_chat_ids,
        api_base=os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/"),
        poll_timeout_seconds=parse_int_env("TELEGRAM_POLL_TIMEOUT_SECONDS", 30),
        retry_sleep_seconds=float(os.getenv("TELEGRAM_RETRY_SLEEP_SECONDS", "3")),
        exec_timeout_seconds=parse_int_env("TELEGRAM_EXEC_TIMEOUT_SECONDS", 36000),
        max_input_chars=parse_int_env("TELEGRAM_MAX_INPUT_CHARS", TELEGRAM_LIMIT),
        max_output_chars=parse_int_env("TELEGRAM_MAX_OUTPUT_CHARS", 20000),
        max_image_bytes=parse_int_env("TELEGRAM_MAX_IMAGE_BYTES", 10 * 1024 * 1024, minimum=1024),
        max_voice_bytes=parse_int_env("TELEGRAM_MAX_VOICE_BYTES", 20 * 1024 * 1024, minimum=1024),
        max_document_bytes=parse_int_env("TELEGRAM_MAX_DOCUMENT_BYTES", 50 * 1024 * 1024, minimum=1024),
        rate_limit_per_minute=parse_int_env("TELEGRAM_RATE_LIMIT_PER_MINUTE", 12),
        executor_cmd=parse_executor_cmd(),
        voice_transcribe_cmd=parse_optional_cmd_env("TELEGRAM_VOICE_TRANSCRIBE_CMD"),
        voice_transcribe_timeout_seconds=parse_int_env(
            "TELEGRAM_VOICE_TRANSCRIBE_TIMEOUT_SECONDS",
            120,
        ),
        state_dir=state_dir,
        persistent_workers_enabled=parse_bool_env(
            "TELEGRAM_PERSISTENT_WORKERS_ENABLED",
            False,
        ),
        persistent_workers_max=parse_int_env(
            "TELEGRAM_PERSISTENT_WORKERS_MAX",
            4,
            minimum=1,
        ),
        persistent_workers_idle_timeout_seconds=parse_int_env(
            "TELEGRAM_PERSISTENT_WORKERS_IDLE_TIMEOUT_SECONDS",
            45 * 60,
            minimum=60,
        ),
        persistent_workers_policy_files=build_policy_watch_files(),
    )


class TelegramClient:
    def __init__(self, config: Config) -> None:
        self.config = config

    def _request(self, method: str, payload: Dict[str, object]) -> Dict[str, object]:
        endpoint = f"{self.config.api_base}/bot{self.config.token}/{method}"
        data = urlencode(payload).encode("utf-8")
        request = Request(endpoint, data=data, method="POST")
        with urlopen(request, timeout=self.config.poll_timeout_seconds + 10) as response:
            body = response.read().decode("utf-8")
        decoded = json.loads(body)
        if not decoded.get("ok"):
            description = decoded.get("description", "unknown Telegram error")
            raise RuntimeError(f"Telegram API {method} failed: {description}")
        return decoded

    def get_updates(
        self,
        offset: int,
        timeout_seconds: Optional[int] = None,
    ) -> List[Dict[str, object]]:
        timeout = self.config.poll_timeout_seconds if timeout_seconds is None else timeout_seconds
        payload: Dict[str, object] = {
            "offset": offset,
            "timeout": timeout,
            "allowed_updates": json.dumps(["message"]),
        }
        response = self._request("getUpdates", payload)
        result = response.get("result", [])
        if not isinstance(result, list):
            raise RuntimeError("Invalid getUpdates response: result is not a list")
        return result

    def send_message(
        self,
        chat_id: int,
        text: str,
        reply_to_message_id: Optional[int] = None,
    ) -> None:
        for chunk in to_telegram_chunks(text):
            payload: Dict[str, object] = {
                "chat_id": str(chat_id),
                "text": chunk,
                "disable_web_page_preview": "true",
            }
            if reply_to_message_id is not None:
                payload["reply_to_message_id"] = str(reply_to_message_id)
            self._request("sendMessage", payload)

    def send_message_get_id(
        self,
        chat_id: int,
        text: str,
        reply_to_message_id: Optional[int] = None,
    ) -> Optional[int]:
        payload: Dict[str, object] = {
            "chat_id": str(chat_id),
            "text": text,
            "disable_web_page_preview": "true",
        }
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = str(reply_to_message_id)
        response = self._request("sendMessage", payload)
        result = response.get("result")
        if isinstance(result, dict):
            message_id = result.get("message_id")
            if isinstance(message_id, int):
                return message_id
        return None

    def edit_message(self, chat_id: int, message_id: int, text: str) -> None:
        payload: Dict[str, object] = {
            "chat_id": str(chat_id),
            "message_id": str(message_id),
            "text": text,
            "disable_web_page_preview": "true",
        }
        self._request("editMessageText", payload)

    def send_chat_action(self, chat_id: int, action: str = "typing") -> None:
        payload: Dict[str, object] = {
            "chat_id": str(chat_id),
            "action": action,
        }
        self._request("sendChatAction", payload)

    def get_file(self, file_id: str) -> Dict[str, object]:
        response = self._request("getFile", {"file_id": file_id})
        result = response.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("Invalid getFile response: result is not an object")
        return result

    def download_file_to_path(
        self,
        file_path: str,
        target_path: str,
        max_bytes: int,
        size_label: str = "File",
    ) -> None:
        cleaned = file_path.lstrip("/")
        if not cleaned:
            raise RuntimeError("Invalid Telegram file_path")
        encoded = quote(cleaned, safe="/")
        endpoint = f"{self.config.api_base}/file/bot{self.config.token}/{encoded}"
        request = Request(endpoint, method="GET")

        total = 0
        with (
            urlopen(request, timeout=self.config.poll_timeout_seconds + 10) as response,
            open(target_path, "wb") as handle,
        ):
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(
                        f"{size_label} too large (> {max_bytes} bytes)."
                    )
                handle.write(chunk)


def normalize_command(text: str) -> Optional[str]:
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    head = stripped.split(maxsplit=1)[0]
    return head.split("@", maxsplit=1)[0]


def trim_output(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    marker = "\n\n[output truncated]"
    return text[: max(0, limit - len(marker))] + marker


def split_for_limit(text: str, limit: int) -> List[str]:
    if not text:
        return [""]
    chunks: List[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        split_at = remaining.rfind("\n", 0, limit)
        if split_at <= 0:
            split_at = limit
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip("\n")
    return chunks


def to_telegram_chunks(text: str) -> List[str]:
    stripped = text.strip()
    if not stripped:
        return [""]

    # Reserve room for a multipart prefix like [2/7]\n
    base_chunks = split_for_limit(stripped, TELEGRAM_LIMIT - 16)
    if len(base_chunks) == 1:
        return base_chunks

    total = len(base_chunks)
    output: List[str] = []
    for index, chunk in enumerate(base_chunks, start=1):
        output.append(f"[{index}/{total}]\n{chunk}")
    return output


def compact_progress_text(text: str, max_chars: int = 120) -> str:
    cleaned = " ".join(text.replace("\n", " ").split())
    cleaned = cleaned.replace("**", "").replace("`", "")
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 3].rstrip() + "..."


def parse_stream_json_line(raw_line: str) -> Optional[Dict[str, object]]:
    stripped = raw_line.strip()
    if not stripped.startswith("{"):
        return None
    try:
        payload = json.loads(stripped)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def extract_executor_progress_event(payload: Dict[str, object]) -> Optional[ExecutorProgressEvent]:
    event_type = payload.get("type")
    if event_type == "turn.started":
        return ExecutorProgressEvent(kind="turn_started")
    if event_type == "turn.completed":
        return ExecutorProgressEvent(kind="turn_completed")

    if event_type not in ("item.started", "item.completed"):
        return None
    item = payload.get("item")
    if not isinstance(item, dict):
        return None

    item_type = item.get("type")
    if event_type == "item.started" and item_type == "command_execution":
        command = item.get("command")
        detail = command if isinstance(command, str) else ""
        return ExecutorProgressEvent(kind="command_started", detail=detail)

    if event_type == "item.completed" and item_type == "command_execution":
        command = item.get("command")
        detail = command if isinstance(command, str) else ""
        exit_code = item.get("exit_code")
        parsed_exit_code = exit_code if isinstance(exit_code, int) else None
        return ExecutorProgressEvent(
            kind="command_completed",
            detail=detail,
            exit_code=parsed_exit_code,
        )

    if event_type == "item.completed" and item_type == "reasoning":
        text = item.get("text")
        detail = text if isinstance(text, str) else ""
        return ExecutorProgressEvent(kind="reasoning", detail=detail)

    if event_type == "item.completed" and item_type == "agent_message":
        text = item.get("text")
        detail = text if isinstance(text, str) else ""
        return ExecutorProgressEvent(kind="agent_message", detail=detail)

    return None


class ProgressReporter:
    def __init__(
        self,
        client: TelegramClient,
        chat_id: int,
        reply_to_message_id: Optional[int],
    ) -> None:
        self.client = client
        self.chat_id = chat_id
        self.reply_to_message_id = reply_to_message_id
        self.started_at = time.time()
        self.phase = "Preparing request."
        self.commands_started = 0
        self.commands_completed = 0
        self.progress_message_id: Optional[int] = None
        self.last_rendered_text = ""
        self.last_edit_at = 0.0
        self.pending_update = False
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._heartbeat_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        initial = self._render_progress_text()
        try:
            self.progress_message_id = self.client.send_message_get_id(
                self.chat_id,
                initial,
                reply_to_message_id=self.reply_to_message_id,
            )
            self.last_rendered_text = initial
            self.last_edit_at = time.time()
        except Exception:
            logging.exception("Failed to send progress bootstrap message for chat_id=%s", self.chat_id)
            self.progress_message_id = None

        self._send_typing()
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()

    def close(self) -> None:
        self._stop_event.set()
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=1.5)

    def set_phase(self, phase: str, force: bool = False, immediate: bool = True) -> None:
        with self._lock:
            self.phase = compact_progress_text(phase, max_chars=180)
            self.pending_update = True
        if immediate or force:
            self._maybe_edit(force=force)

    def mark_success(self) -> None:
        self.set_phase("Completed. Sending response.", force=True)

    def mark_failure(self, reason: str) -> None:
        self.set_phase(reason, force=True)

    def handle_executor_event(self, event: ExecutorProgressEvent) -> None:
        if event.kind == "turn_started":
            self.set_phase("Architect is planning the approach.", immediate=False)
            return
        if event.kind == "turn_completed":
            self.set_phase("Architect is finalizing the response.", immediate=False)
            return
        if event.kind == "reasoning":
            if event.detail:
                self.set_phase(
                    f"Architect step: {compact_progress_text(event.detail)}",
                    immediate=False,
                )
            return
        if event.kind == "agent_message":
            self.set_phase("Architect is composing the reply.", immediate=False)
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
        text = f"Architect is working... {elapsed}s elapsed.\n{phase}"
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


def run_executor(
    config: Config,
    prompt: str,
    thread_id: Optional[str],
    image_path: Optional[str] = None,
    progress_callback: Optional[Callable[[ExecutorProgressEvent], None]] = None,
) -> subprocess.CompletedProcess[str]:
    cmd = list(config.executor_cmd)
    if thread_id:
        cmd.extend(["resume", thread_id])
    else:
        cmd.append("new")
    if image_path:
        cmd.extend(["--image", image_path])
    logging.info("Running executor command: %s", cmd)
    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    stdout_chunks: List[str] = []
    stderr_chunks: List[str] = []

    if process.stdin is None or process.stdout is None or process.stderr is None:
        raise RuntimeError("Failed to initialize executor process pipes")

    def drain_stdout() -> None:
        for raw_line in process.stdout:
            stdout_chunks.append(raw_line)
            payload = parse_stream_json_line(raw_line)
            if payload is None:
                continue
            event = extract_executor_progress_event(payload)
            if event and progress_callback:
                try:
                    progress_callback(event)
                except Exception:
                    logging.exception("Progress callback failure")

    def drain_stderr() -> None:
        for raw_line in process.stderr:
            stderr_chunks.append(raw_line)

    stdout_worker = threading.Thread(target=drain_stdout, daemon=True)
    stderr_worker = threading.Thread(target=drain_stderr, daemon=True)
    stdout_worker.start()
    stderr_worker.start()

    try:
        process.stdin.write(prompt)
        if not prompt.endswith("\n"):
            process.stdin.write("\n")
        process.stdin.close()
    except Exception:
        process.kill()
        process.wait(timeout=5)
        raise

    try:
        return_code = process.wait(timeout=config.exec_timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.wait(timeout=5)
        stdout_worker.join(timeout=1.5)
        stderr_worker.join(timeout=1.5)
        raise subprocess.TimeoutExpired(cmd, config.exec_timeout_seconds) from exc

    stdout_worker.join(timeout=1.5)
    stderr_worker.join(timeout=1.5)

    return subprocess.CompletedProcess(
        args=cmd,
        returncode=return_code,
        stdout="".join(stdout_chunks),
        stderr="".join(stderr_chunks),
    )


def is_rate_limited(state: State, config: Config, chat_id: int) -> bool:
    now = time.time()
    with state.lock:
        entries = state.recent_requests.setdefault(chat_id, [])
        threshold = now - 60
        entries[:] = [t for t in entries if t >= threshold]
        if len(entries) >= config.rate_limit_per_minute:
            return True
        entries.append(now)
    return False


def mark_busy(state: State, chat_id: int) -> bool:
    with state.lock:
        if chat_id in state.busy_chats:
            return False
        state.busy_chats.add(chat_id)
    return True


def clear_busy(state: State, chat_id: int) -> None:
    with state.lock:
        state.busy_chats.discard(chat_id)


def ensure_state_dir(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def compute_policy_fingerprint(paths: List[str]) -> str:
    hasher = hashlib.sha256()
    for file_path in paths:
        hasher.update(file_path.encode("utf-8"))
        hasher.update(b"\0")
        try:
            stats = os.stat(file_path)
            hasher.update(str(stats.st_mtime_ns).encode("utf-8"))
            hasher.update(b":")
            hasher.update(str(stats.st_size).encode("utf-8"))
        except OSError:
            hasher.update(b"missing")
        hasher.update(b"\0")
    return hasher.hexdigest()


def quarantine_corrupt_state_file(path: str) -> Optional[str]:
    data_path = Path(path)
    if not data_path.exists():
        return None
    timestamp = time.strftime("%Y%m%d%H%M%S", time.gmtime())
    quarantined = data_path.with_name(f"{data_path.name}.corrupt.{timestamp}")
    data_path.replace(quarantined)
    return str(quarantined)


def load_chat_threads(path: str) -> Dict[int, str]:
    data_path = Path(path)
    if not data_path.exists():
        return {}
    try:
        raw = json.loads(data_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to parse chat thread state {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid chat thread state {path}: root is not object")
    parsed: Dict[int, str] = {}
    for key, value in raw.items():
        if not isinstance(value, str) or not value.strip():
            continue
        try:
            chat_id = int(key)
        except ValueError:
            continue
        parsed[chat_id] = value.strip()
    return parsed


def load_worker_sessions(path: str) -> Dict[int, WorkerSession]:
    data_path = Path(path)
    if not data_path.exists():
        return {}
    try:
        raw = json.loads(data_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to parse worker session state {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid worker session state {path}: root is not object")

    parsed: Dict[int, WorkerSession] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        try:
            chat_id = int(key)
        except ValueError:
            continue
        created_at = value.get("created_at")
        last_used_at = value.get("last_used_at")
        thread_id = value.get("thread_id")
        policy_fingerprint = value.get("policy_fingerprint")
        if not isinstance(created_at, (int, float)):
            continue
        if not isinstance(last_used_at, (int, float)):
            last_used_at = float(created_at)
        if not isinstance(thread_id, str):
            thread_id = ""
        if not isinstance(policy_fingerprint, str):
            policy_fingerprint = ""
        parsed[chat_id] = WorkerSession(
            created_at=float(created_at),
            last_used_at=float(last_used_at),
            thread_id=thread_id.strip(),
            policy_fingerprint=policy_fingerprint.strip(),
        )
    return parsed


def persist_chat_threads(state: State) -> None:
    if not state.chat_thread_path:
        return
    path = Path(state.chat_thread_path)
    tmp_path = path.with_suffix(".tmp")
    with state.lock:
        serialized = {str(chat_id): thread_id for chat_id, thread_id in state.chat_threads.items()}
    tmp_path.write_text(json.dumps(serialized, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def persist_worker_sessions(state: State) -> None:
    if not state.worker_sessions_path:
        return
    path = Path(state.worker_sessions_path)
    tmp_path = path.with_suffix(".tmp")
    with state.lock:
        serialized = {
            str(chat_id): {
                "created_at": session.created_at,
                "last_used_at": session.last_used_at,
                "thread_id": session.thread_id,
                "policy_fingerprint": session.policy_fingerprint,
            }
            for chat_id, session in state.worker_sessions.items()
        }
    tmp_path.write_text(json.dumps(serialized, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def touch_worker_session(state: State, chat_id: int, at_time: Optional[float] = None) -> None:
    now = time.time() if at_time is None else at_time
    updated = False
    with state.lock:
        session = state.worker_sessions.get(chat_id)
        if session is not None:
            session.last_used_at = now
            updated = True
    if updated:
        persist_worker_sessions(state)


def clear_worker_session(state: State, chat_id: int) -> bool:
    removed = False
    with state.lock:
        if chat_id in state.worker_sessions:
            del state.worker_sessions[chat_id]
            removed = True
    if removed:
        persist_worker_sessions(state)
    return removed


def get_thread_id(state: State, chat_id: int) -> Optional[str]:
    with state.lock:
        return state.chat_threads.get(chat_id)


def set_thread_id(state: State, chat_id: int, thread_id: str) -> None:
    normalized_thread_id = thread_id.strip()
    with state.lock:
        state.chat_threads[chat_id] = normalized_thread_id
        session = state.worker_sessions.get(chat_id)
        if session is not None:
            session.thread_id = normalized_thread_id
            session.last_used_at = time.time()
    persist_chat_threads(state)
    persist_worker_sessions(state)


def clear_thread_id(state: State, chat_id: int) -> bool:
    removed = False
    with state.lock:
        if chat_id in state.chat_threads:
            del state.chat_threads[chat_id]
            removed = True
        session = state.worker_sessions.get(chat_id)
        if session is not None:
            session.thread_id = ""
            session.last_used_at = time.time()
    if removed:
        persist_chat_threads(state)
    persist_worker_sessions(state)
    return removed


def ensure_chat_worker_session(
    state: State,
    config: Config,
    client: TelegramClient,
    chat_id: int,
    message_id: Optional[int],
) -> bool:
    if not config.persistent_workers_enabled:
        return True

    now = time.time()
    current_policy_fingerprint = compute_policy_fingerprint(config.persistent_workers_policy_files)
    session_replaced_for_policy = False
    evicted_idle_chat_id: Optional[int] = None
    rejected_for_capacity = False
    needs_persist_threads = False
    needs_persist_sessions = False

    with state.lock:
        session = state.worker_sessions.get(chat_id)

        if (
            session is not None
            and session.policy_fingerprint
            and session.policy_fingerprint != current_policy_fingerprint
        ):
            del state.worker_sessions[chat_id]
            if chat_id in state.chat_threads:
                del state.chat_threads[chat_id]
                needs_persist_threads = True
            session = None
            session_replaced_for_policy = True
            needs_persist_sessions = True

        if session is None and len(state.worker_sessions) >= config.persistent_workers_max:
            idle_candidates = [
                (candidate_chat_id, candidate_session)
                for candidate_chat_id, candidate_session in state.worker_sessions.items()
                if candidate_chat_id not in state.busy_chats and candidate_chat_id != chat_id
            ]
            if idle_candidates:
                idle_candidates.sort(key=lambda item: item[1].last_used_at)
                evicted_idle_chat_id = idle_candidates[0][0]
                del state.worker_sessions[evicted_idle_chat_id]
                if evicted_idle_chat_id in state.chat_threads:
                    del state.chat_threads[evicted_idle_chat_id]
                    needs_persist_threads = True
                needs_persist_sessions = True
            else:
                rejected_for_capacity = True

        if not rejected_for_capacity:
            session = state.worker_sessions.get(chat_id)
            if session is None:
                seed_thread_id = state.chat_threads.get(chat_id, "")
                state.worker_sessions[chat_id] = WorkerSession(
                    created_at=now,
                    last_used_at=now,
                    thread_id=seed_thread_id,
                    policy_fingerprint=current_policy_fingerprint,
                )
                needs_persist_sessions = True
            else:
                session.last_used_at = now
                session.policy_fingerprint = current_policy_fingerprint
                session.thread_id = state.chat_threads.get(chat_id, session.thread_id)
                needs_persist_sessions = True

    if needs_persist_threads:
        persist_chat_threads(state)
    if needs_persist_sessions:
        persist_worker_sessions(state)

    if evicted_idle_chat_id is not None and evicted_idle_chat_id in config.allowed_chat_ids:
        try:
            client.send_message(
                evicted_idle_chat_id,
                "Your Architect session was closed to free worker capacity. "
                "Send a new message to start a fresh context.",
            )
        except Exception:
            logging.exception(
                "Failed to send worker-eviction notice for chat_id=%s",
                evicted_idle_chat_id,
            )

    if session_replaced_for_policy:
        try:
            client.send_message(
                chat_id,
                "Policy/context files changed. Your previous session was reset and this request "
                "will continue in a new session.",
                reply_to_message_id=message_id,
            )
        except Exception:
            logging.exception("Failed to send policy-refresh notice for chat_id=%s", chat_id)

    if rejected_for_capacity:
        client.send_message(
            chat_id,
            "All Architect workers are currently in use. Please wait and retry.",
            reply_to_message_id=message_id,
        )
        return False

    return True


def expire_idle_worker_sessions(
    state: State,
    config: Config,
    client: TelegramClient,
) -> None:
    if not config.persistent_workers_enabled:
        return

    now = time.time()
    expired_chat_ids: List[int] = []
    needs_persist_threads = False
    needs_persist_sessions = False
    with state.lock:
        for chat_id, session in list(state.worker_sessions.items()):
            if chat_id in state.busy_chats:
                continue
            if now - session.last_used_at < config.persistent_workers_idle_timeout_seconds:
                continue
            expired_chat_ids.append(chat_id)
            del state.worker_sessions[chat_id]
            if chat_id in state.chat_threads:
                del state.chat_threads[chat_id]
                needs_persist_threads = True
            needs_persist_sessions = True

    if needs_persist_threads:
        persist_chat_threads(state)
    if needs_persist_sessions:
        persist_worker_sessions(state)

    if not expired_chat_ids:
        return

    timeout_mins = max(1, config.persistent_workers_idle_timeout_seconds // 60)
    for chat_id in expired_chat_ids:
        if chat_id not in config.allowed_chat_ids:
            continue
        try:
            client.send_message(
                chat_id,
                f"Your Architect session expired after {timeout_mins} minutes of inactivity. "
                "Context was cleared.",
            )
        except Exception:
            logging.exception("Failed to send idle-expiry notice for chat_id=%s", chat_id)


def load_in_flight_requests(path: str) -> Dict[int, Dict[str, object]]:
    data_path = Path(path)
    if not data_path.exists():
        return {}
    try:
        raw = json.loads(data_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to parse in-flight state {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid in-flight state {path}: root is not object")

    out: Dict[int, Dict[str, object]] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        try:
            chat_id = int(key)
        except ValueError:
            continue
        payload: Dict[str, object] = {}
        started_at = value.get("started_at")
        if isinstance(started_at, (int, float)):
            payload["started_at"] = float(started_at)
        message_id = value.get("message_id")
        if isinstance(message_id, int):
            payload["message_id"] = message_id
        out[chat_id] = payload
    return out


def persist_in_flight_requests(state: State) -> None:
    if not state.in_flight_path:
        return
    path = Path(state.in_flight_path)
    tmp_path = path.with_suffix(".tmp")
    with state.lock:
        serialized = {
            str(chat_id): payload
            for chat_id, payload in state.in_flight_requests.items()
        }
    tmp_path.write_text(
        json.dumps(serialized, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)


def mark_in_flight_request(state: State, chat_id: int, message_id: Optional[int]) -> None:
    payload: Dict[str, object] = {"started_at": time.time()}
    if isinstance(message_id, int):
        payload["message_id"] = message_id
    with state.lock:
        state.in_flight_requests[chat_id] = payload
    persist_in_flight_requests(state)


def clear_in_flight_request(state: State, chat_id: int) -> None:
    removed = False
    with state.lock:
        if chat_id in state.in_flight_requests:
            del state.in_flight_requests[chat_id]
            removed = True
    if removed:
        persist_in_flight_requests(state)


def pop_interrupted_requests(state: State) -> Dict[int, Dict[str, object]]:
    with state.lock:
        if not state.in_flight_requests:
            return {}
        interrupted = dict(state.in_flight_requests)
        state.in_flight_requests = {}
    persist_in_flight_requests(state)
    return interrupted


def parse_executor_output(stdout: str) -> tuple[Optional[str], str]:
    lines = (stdout or "").splitlines()
    thread_id: Optional[str] = None
    last_agent_message: Optional[str] = None
    output_lines: List[str] = []
    seen_output = False
    seen_json_events = False
    for line in lines:
        payload = parse_stream_json_line(line)
        if payload is not None:
            seen_json_events = True
            payload_type = payload.get("type")
            if payload_type == "thread.started":
                payload_thread_id = payload.get("thread_id")
                if isinstance(payload_thread_id, str) and payload_thread_id.strip():
                    thread_id = payload_thread_id.strip()
            elif payload_type == "item.completed":
                item = payload.get("item")
                if isinstance(item, dict) and item.get("type") == "agent_message":
                    text = item.get("text")
                    if isinstance(text, str):
                        last_agent_message = text

        if not seen_output:
            if line.startswith("THREAD_ID="):
                thread_id = line[len("THREAD_ID="):].strip()
                continue
            if line.strip() == OUTPUT_BEGIN_MARKER:
                seen_output = True
                continue
        else:
            output_lines.append(line)

    if seen_output:
        output = "\n".join(output_lines).strip()
    elif seen_json_events and last_agent_message is not None:
        output = last_agent_message.strip()
    else:
        output = (stdout or "").strip()
    return thread_id, output


def should_reset_thread_after_resume_failure(
    stderr: str,
    stdout: str,
) -> bool:
    combined = f"{stderr}\n{stdout}".lower()
    reset_markers = (
        "thread not found",
        "unknown thread",
        "invalid thread",
        "thread id not found",
        "conversation not found",
        "session not found",
        "no such thread",
        "could not find thread",
    )
    return any(marker in combined for marker in reset_markers)


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


def download_photo_to_temp(
    client: TelegramClient,
    config: Config,
    photo_file_id: str,
) -> str:
    file_meta = client.get_file(photo_file_id)
    file_path = file_meta.get("file_path")
    if not isinstance(file_path, str) or not file_path.strip():
        raise RuntimeError("Telegram getFile response missing file_path")

    file_size = file_meta.get("file_size")
    if isinstance(file_size, int) and file_size > config.max_image_bytes:
        raise ValueError(
            f"Image too large ({file_size} bytes). Max is {config.max_image_bytes} bytes."
        )

    suffix = Path(file_path).suffix or ".jpg"
    fd, tmp_path = tempfile.mkstemp(prefix="telegram-bridge-photo-", suffix=suffix)
    os.close(fd)
    try:
        client.download_file_to_path(
            file_path,
            tmp_path,
            config.max_image_bytes,
            size_label="Image",
        )
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise
    return tmp_path


def download_voice_to_temp(
    client: TelegramClient,
    config: Config,
    voice_file_id: str,
) -> str:
    file_meta = client.get_file(voice_file_id)
    file_path = file_meta.get("file_path")
    if not isinstance(file_path, str) or not file_path.strip():
        raise RuntimeError("Telegram getFile response missing file_path")

    file_size = file_meta.get("file_size")
    if isinstance(file_size, int) and file_size > config.max_voice_bytes:
        raise ValueError(
            f"Voice file too large ({file_size} bytes). Max is {config.max_voice_bytes} bytes."
        )

    suffix = Path(file_path).suffix or ".ogg"
    fd, tmp_path = tempfile.mkstemp(prefix="telegram-bridge-voice-", suffix=suffix)
    os.close(fd)
    try:
        client.download_file_to_path(
            file_path,
            tmp_path,
            config.max_voice_bytes,
            size_label="Voice file",
        )
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise
    return tmp_path


def download_document_to_temp(
    client: TelegramClient,
    config: Config,
    document: DocumentPayload,
) -> tuple[str, int]:
    file_meta = client.get_file(document.file_id)
    file_path = file_meta.get("file_path")
    if not isinstance(file_path, str) or not file_path.strip():
        raise RuntimeError("Telegram getFile response missing file_path")

    file_size = file_meta.get("file_size")
    if isinstance(file_size, int) and file_size > config.max_document_bytes:
        raise ValueError(
            f"File too large ({file_size} bytes). Max is {config.max_document_bytes} bytes."
        )

    suffix = Path(document.file_name).suffix or Path(file_path).suffix or ".bin"
    fd, tmp_path = tempfile.mkstemp(prefix="telegram-bridge-file-", suffix=suffix)
    os.close(fd)
    try:
        client.download_file_to_path(
            file_path,
            tmp_path,
            config.max_document_bytes,
            size_label="File",
        )
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise

    final_size = file_size if isinstance(file_size, int) else os.path.getsize(tmp_path)
    return tmp_path, final_size


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


def transcribe_voice(config: Config, voice_path: str) -> str:
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
    return transcript


def transcribe_voice_for_chat(
    config: Config,
    client: TelegramClient,
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
            transcript = transcribe_voice(config, voice_path)
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

        if echo_transcript:
            try:
                client.send_message(
                    chat_id,
                    f"Voice transcript:\n{transcript}",
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


def build_help_text() -> str:
    return (
        "Commands:\n"
        "/start - bridge intro\n"
        "/help - show commands\n"
        "/h - short help alias\n"
        "/status - show bridge health\n"
        "/restart - safe restart (queued until current work completes)\n"
        "/reset - clear chat context\n"
        "Chat mode: Architect-only for all allowlisted chats.\n\n"
        "All text/photo/voice/file messages are sent to Architect."
    )


def build_status_text(state: State, config: Config, chat_id: Optional[int] = None) -> str:
    uptime = int(time.time() - state.started_at)
    now = time.time()
    with state.lock:
        busy_count = len(state.busy_chats)
        restart_queued = state.restart_requested
        restart_running = state.restart_in_progress
        worker_count = len(state.worker_sessions)
        session = state.worker_sessions.get(chat_id) if chat_id is not None else None
        chat_has_thread = chat_id in state.chat_threads if chat_id is not None else False
        chat_busy = chat_id in state.busy_chats if chat_id is not None else False

    lines = [
        "Bridge status: healthy",
        f"Uptime: {uptime}s",
        f"Busy chats: {busy_count}",
        f"Restart queued: {'yes' if restart_queued else 'no'}",
        f"Restart in progress: {'yes' if restart_running else 'no'}",
        f"Persistent workers: {'enabled' if config.persistent_workers_enabled else 'disabled'}",
    ]

    if config.persistent_workers_enabled:
        lines.append(
            f"Workers active: {worker_count}/{config.persistent_workers_max}"
        )
        lines.append(
            f"Worker idle timeout: {config.persistent_workers_idle_timeout_seconds}s"
        )
        if chat_id is not None:
            if session is None:
                lines.append("This chat worker: none")
            else:
                idle_for = int(max(0, now - session.last_used_at))
                lines.append(
                    "This chat worker: active "
                    f"(idle={idle_for}s busy={'yes' if chat_busy else 'no'} "
                    f"thread={'yes' if bool(session.thread_id) else 'no'})"
                )
    elif chat_id is not None and chat_has_thread:
        lines.append("This chat has saved context.")

    return "\n".join(lines)


def request_safe_restart(
    state: State,
    chat_id: int,
    reply_to_message_id: Optional[int],
) -> tuple[str, int]:
    with state.lock:
        busy_count = len(state.busy_chats)
        if state.restart_in_progress:
            return "in_progress", busy_count
        if state.restart_requested:
            return "already_queued", busy_count

        state.restart_chat_id = chat_id
        state.restart_reply_to_message_id = reply_to_message_id
        if busy_count > 0:
            state.restart_requested = True
            return "queued", busy_count

        state.restart_in_progress = True
        return "run_now", busy_count


def pop_ready_restart_request(state: State) -> Optional[tuple[int, Optional[int]]]:
    with state.lock:
        if state.restart_in_progress:
            return None
        if not state.restart_requested:
            return None
        if state.busy_chats:
            return None
        if state.restart_chat_id is None:
            return None

        state.restart_requested = False
        state.restart_in_progress = True
        return state.restart_chat_id, state.restart_reply_to_message_id


def finish_restart_attempt(state: State) -> None:
    with state.lock:
        state.restart_in_progress = False


def run_restart_script(
    state: State,
    client: TelegramClient,
    chat_id: int,
    reply_to_message_id: Optional[int],
) -> None:
    script_path = build_restart_script_path()
    try:
        result = subprocess.run(
            ["bash", script_path],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logging.error("Bridge restart command timed out.")
        client.send_message(
            chat_id,
            "Restart command timed out. Please run restart manually.",
            reply_to_message_id=reply_to_message_id,
        )
        finish_restart_attempt(state)
        return
    except Exception:
        logging.exception("Bridge restart command failed to execute.")
        client.send_message(
            chat_id,
            "Restart command failed to execute. Please run restart manually.",
            reply_to_message_id=reply_to_message_id,
        )
        finish_restart_attempt(state)
        return

    if result.returncode != 0:
        logging.error(
            "Bridge restart command failed returncode=%s stderr=%r",
            result.returncode,
            (result.stderr or "")[-1000:],
        )
        client.send_message(
            chat_id,
            "Restart failed. Please run `bash ops/telegram-bridge/restart_and_verify.sh`.",
            reply_to_message_id=reply_to_message_id,
        )
        finish_restart_attempt(state)
        return

    # If this process survives a successful restart command invocation,
    # clear restart state so future restart requests are not blocked.
    finish_restart_attempt(state)


def trigger_restart_async(
    state: State,
    client: TelegramClient,
    chat_id: int,
    reply_to_message_id: Optional[int],
) -> None:
    worker = threading.Thread(
        target=run_restart_script,
        args=(state, client, chat_id, reply_to_message_id),
        daemon=True,
    )
    worker.start()


def finalize_chat_work(
    state: State,
    client: TelegramClient,
    chat_id: int,
) -> None:
    clear_in_flight_request(state, chat_id)
    clear_busy(state, chat_id)
    ready_restart = pop_ready_restart_request(state)
    if not ready_restart:
        return

    restart_chat_id, restart_reply_to = ready_restart
    try:
        client.send_message(
            restart_chat_id,
            "Current request completed. Restarting bridge now.",
            reply_to_message_id=restart_reply_to,
        )
    except Exception:
        logging.exception(
            "Failed to send queued restart acknowledgement for chat_id=%s",
            restart_chat_id,
        )
    trigger_restart_async(state, client, restart_chat_id, restart_reply_to)


def process_prompt(
    state: State,
    config: Config,
    client: TelegramClient,
    chat_id: int,
    message_id: Optional[int],
    prompt: str,
    photo_file_id: Optional[str],
    voice_file_id: Optional[str],
    document: Optional[DocumentPayload],
) -> None:
    previous_thread_id = get_thread_id(state, chat_id)
    prompt_text = prompt.strip()
    image_path: Optional[str] = None
    document_path: Optional[str] = None
    progress = ProgressReporter(client, chat_id, message_id)
    try:
        progress.start()

        if photo_file_id:
            progress.set_phase("Downloading image from Telegram.")
            try:
                image_path = download_photo_to_temp(client, config, photo_file_id)
            except ValueError as exc:
                logging.warning("Photo rejected for chat_id=%s: %s", chat_id, exc)
                progress.mark_failure("Image request rejected.")
                client.send_message(chat_id, str(exc), reply_to_message_id=message_id)
                return
            except Exception:
                logging.exception("Photo download failed for chat_id=%s", chat_id)
                progress.mark_failure("Image download failed.")
                client.send_message(
                    chat_id,
                    config.image_download_error_message,
                    reply_to_message_id=message_id,
                )
                return

        if voice_file_id:
            progress.set_phase("Transcribing voice message.")
            transcript = transcribe_voice_for_chat(
                config=config,
                client=client,
                chat_id=chat_id,
                message_id=message_id,
                voice_file_id=voice_file_id,
                echo_transcript=True,
            )
            if transcript is None:
                progress.mark_failure("Voice transcription failed.")
                return

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
                return
            except Exception:
                logging.exception("Document download failed for chat_id=%s", chat_id)
                progress.mark_failure("File download failed.")
                client.send_message(
                    chat_id,
                    config.document_download_error_message,
                    reply_to_message_id=message_id,
                )
                return

            context = build_document_analysis_context(document_path, document, file_size)
            if prompt_text:
                prompt_text = f"{prompt_text}\n\n{context}"
            else:
                prompt_text = context

        if not prompt_text:
            progress.mark_failure("No prompt content to execute.")
            return

        if len(prompt_text) > config.max_input_chars:
            progress.mark_failure("Input rejected as too long.")
            client.send_message(
                chat_id,
                f"Input too long ({len(prompt_text)} chars). Max is {config.max_input_chars}.",
                reply_to_message_id=message_id,
            )
            return

        touch_worker_session(state, chat_id)
        progress.set_phase("Sending request to Architect.")
        allow_automatic_retry = config.persistent_workers_enabled
        retry_attempted = False
        attempt_thread_id: Optional[str] = previous_thread_id

        while True:
            try:
                result = run_executor(
                    config,
                    prompt_text,
                    attempt_thread_id,
                    image_path=image_path,
                    progress_callback=progress.handle_executor_event,
                )
            except subprocess.TimeoutExpired:
                logging.warning("Executor timeout for chat_id=%s", chat_id)
                progress.mark_failure("Execution timed out.")
                client.send_message(chat_id, config.timeout_message, reply_to_message_id=message_id)
                return
            except FileNotFoundError:
                logging.exception("Executor command not found: %s", config.executor_cmd)
                progress.mark_failure("Executor command not found.")
                client.send_message(
                    chat_id,
                    config.generic_error_message,
                    reply_to_message_id=message_id,
                )
                return
            except Exception:
                logging.exception("Unexpected executor error for chat_id=%s", chat_id)
                if allow_automatic_retry and not retry_attempted:
                    retry_attempted = True
                    clear_thread_id(state, chat_id)
                    attempt_thread_id = None
                    progress.set_phase("Execution failed. Retrying once with a new session.")
                    continue
                progress.mark_failure("Execution failed before completion.")
                if allow_automatic_retry:
                    client.send_message(
                        chat_id,
                        "Execution failed after an automatic retry. Please resend your request.",
                        reply_to_message_id=message_id,
                    )
                else:
                    client.send_message(
                        chat_id,
                        config.generic_error_message,
                        reply_to_message_id=message_id,
                    )
                return

            if result.returncode == 0:
                break

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
                progress.set_phase("Retrying as a new Architect session.")
            elif allow_automatic_retry and not retry_attempted:
                logging.warning(
                    "Executor failed for chat_id=%s; retrying once as new. returncode=%s stderr=%r",
                    chat_id,
                    result.returncode,
                    (result.stderr or "")[-1000:],
                )
                reset_and_retry_new = True
                retry_attempted = True
                progress.set_phase("Execution failed. Retrying once with a new session.")

            if reset_and_retry_new:
                clear_thread_id(state, chat_id)
                attempt_thread_id = None
                retry_attempted = True
                continue

            logging.error(
                "Executor failed for chat_id=%s returncode=%s stderr=%r",
                chat_id,
                result.returncode,
                (result.stderr or "")[-1000:],
            )
            progress.mark_failure("Execution failed.")
            if allow_automatic_retry:
                client.send_message(
                    chat_id,
                    "Execution failed after an automatic retry. Please resend your request.",
                    reply_to_message_id=message_id,
                )
            else:
                client.send_message(
                    chat_id,
                    config.generic_error_message,
                    reply_to_message_id=message_id,
                )
            return

        new_thread_id, output = parse_executor_output(result.stdout or "")
        if new_thread_id:
            set_thread_id(state, chat_id, new_thread_id)
        if not output:
            output = config.empty_output_message
        output = trim_output(output, config.max_output_chars)
        progress.mark_success()
        client.send_message(chat_id, output, reply_to_message_id=message_id)
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


def process_message_worker(
    state: State,
    config: Config,
    client: TelegramClient,
    chat_id: int,
    message_id: Optional[int],
    prompt: str,
    photo_file_id: Optional[str],
    voice_file_id: Optional[str],
    document: Optional[DocumentPayload],
) -> None:
    prompt_invoked = False
    try:
        prompt_invoked = True
        process_prompt(
            state,
            config,
            client,
            chat_id,
            message_id,
            prompt,
            photo_file_id,
            voice_file_id,
            document,
        )
    except Exception:
        logging.exception("Unexpected message worker error for chat_id=%s", chat_id)
        try:
            client.send_message(
                chat_id,
                config.generic_error_message,
                reply_to_message_id=message_id,
            )
        except Exception:
            logging.exception("Failed to send worker error response for chat_id=%s", chat_id)
    finally:
        if not prompt_invoked:
            finalize_chat_work(state, client, chat_id)


def handle_reset_command(
    state: State,
    config: Config,
    client: TelegramClient,
    chat_id: int,
    message_id: Optional[int],
) -> None:
    removed_thread = clear_thread_id(state, chat_id)
    removed_worker = clear_worker_session(state, chat_id) if config.persistent_workers_enabled else False
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
    client: TelegramClient,
    chat_id: int,
    message_id: Optional[int],
) -> None:
    status, busy_count = request_safe_restart(state, chat_id, message_id)
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


def handle_update(
    state: State,
    config: Config,
    client: TelegramClient,
    update: Dict[str, object],
) -> None:
    message = update.get("message")
    if not isinstance(message, dict):
        return

    chat = message.get("chat")
    if not isinstance(chat, dict):
        return

    chat_id = chat.get("id")
    if not isinstance(chat_id, int):
        return

    message_id = message.get("message_id")
    if not isinstance(message_id, int):
        message_id = None

    if chat_id not in config.allowed_chat_ids:
        logging.warning("Denied non-allowlisted chat_id=%s", chat_id)
        client.send_message(chat_id, config.denied_message, reply_to_message_id=message_id)
        return

    prompt_input, photo_file_id, voice_file_id, document = extract_prompt_and_media(message)
    if prompt_input is None and voice_file_id is None and document is None:
        return

    command = normalize_command(prompt_input or "")
    if command == "/start":
        client.send_message(
            chat_id,
            "Telegram Architect bridge is online. Send a prompt to begin.",
            reply_to_message_id=message_id,
        )
        return
    if command in ("/help", "/h"):
        client.send_message(
            chat_id,
            build_help_text(),
            reply_to_message_id=message_id,
        )
        return
    if command == "/status":
        client.send_message(
            chat_id,
            build_status_text(state, config, chat_id=chat_id),
            reply_to_message_id=message_id,
        )
        return
    if command == "/restart":
        handle_restart_command(state, client, chat_id, message_id)
        return
    if command == "/reset":
        handle_reset_command(state, config, client, chat_id, message_id)
        return

    prompt = (prompt_input or "").strip()
    if not prompt and not voice_file_id and document is None:
        return

    if prompt and len(prompt) > config.max_input_chars:
        client.send_message(
            chat_id,
            f"Input too long ({len(prompt)} chars). Max is {config.max_input_chars}.",
            reply_to_message_id=message_id,
        )
        return

    if is_rate_limited(state, config, chat_id):
        client.send_message(
            chat_id,
            "Rate limit exceeded. Please wait a minute and retry.",
            reply_to_message_id=message_id,
        )
        return

    if not ensure_chat_worker_session(state, config, client, chat_id, message_id):
        return

    if not mark_busy(state, chat_id):
        client.send_message(
            chat_id,
            config.busy_message,
            reply_to_message_id=message_id,
        )
        return
    mark_in_flight_request(state, chat_id, message_id)

    worker = threading.Thread(
        target=process_message_worker,
        args=(
            state,
            config,
            client,
            chat_id,
            message_id,
            prompt,
            photo_file_id,
            voice_file_id,
            document,
        ),
        daemon=True,
    )
    worker.start()


def run_self_test() -> int:
    sample = "x" * (TELEGRAM_LIMIT + 50)
    chunks = to_telegram_chunks(sample)
    if len(chunks) < 2:
        raise RuntimeError("Chunking self-test failed")

    prompt, _, _, document = extract_prompt_and_media(
        {"document": {"file_id": "f1", "file_name": "sample.txt", "mime_type": "text/plain"}}
    )
    if prompt != "Please analyze this file." or not document or document.file_id != "f1":
        raise RuntimeError("Document parsing self-test failed")

    sample_stream = (
        '{"type":"thread.started","thread_id":"thread-123"}\n'
        '{"type":"item.completed","item":{"type":"agent_message","text":"hello"}}\n'
    )
    parsed_thread, parsed_output = parse_executor_output(sample_stream)
    if parsed_thread != "thread-123" or parsed_output != "hello":
        raise RuntimeError("Executor stream parse self-test failed")

    progress_event = extract_executor_progress_event(
        {
            "type": "item.started",
            "item": {"type": "command_execution", "command": "pwd", "status": "in_progress"},
        }
    )
    if not progress_event or progress_event.kind != "command_started":
        raise RuntimeError("Progress event self-test failed")

    restart_state = State()
    status, _ = request_safe_restart(restart_state, chat_id=1, reply_to_message_id=None)
    if status != "run_now":
        raise RuntimeError("Restart self-test failed (run_now)")
    finish_restart_attempt(restart_state)
    with restart_state.lock:
        restart_state.busy_chats.add(1)
    status, _ = request_safe_restart(restart_state, chat_id=1, reply_to_message_id=None)
    if status != "queued":
        raise RuntimeError("Restart self-test failed (queued)")
    clear_busy(restart_state, 1)
    ready = pop_ready_restart_request(restart_state)
    if not ready or ready[0] != 1:
        raise RuntimeError("Restart self-test failed (pop_ready)")
    finish_restart_attempt(restart_state)

    print("self-test: ok")
    return 0


def drop_pending_updates(client: TelegramClient) -> int:
    offset = 0
    dropped = 0

    while True:
        updates = client.get_updates(offset, timeout_seconds=0)
        if not updates:
            break

        dropped += len(updates)
        next_offset = offset
        for update in updates:
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                next_offset = max(next_offset, update_id + 1)

        if next_offset == offset:
            logging.warning(
                "Startup backlog discard could not advance offset; stopping discard loop."
            )
            break

        offset = next_offset

    if dropped:
        logging.info("Dropped %s queued Telegram update(s) at startup.", dropped)
    else:
        logging.info("No queued Telegram updates found at startup.")
    return offset


def run_bridge(config: Config) -> int:
    ensure_state_dir(config.state_dir)
    chat_thread_path = os.path.join(config.state_dir, "chat_threads.json")
    worker_sessions_path = os.path.join(config.state_dir, "worker_sessions.json")
    in_flight_path = os.path.join(config.state_dir, "in_flight_requests.json")
    try:
        loaded_threads = load_chat_threads(chat_thread_path)
    except Exception:
        logging.exception(
            "Failed to load chat thread mappings from %s; starting with empty mappings.",
            chat_thread_path,
        )
        moved = quarantine_corrupt_state_file(chat_thread_path)
        if moved:
            logging.error("Quarantined corrupt chat thread state file to %s", moved)
        loaded_threads = {}

    try:
        loaded_worker_sessions = load_worker_sessions(worker_sessions_path)
    except Exception:
        logging.exception(
            "Failed to load worker session state from %s; starting with empty worker sessions.",
            worker_sessions_path,
        )
        moved = quarantine_corrupt_state_file(worker_sessions_path)
        if moved:
            logging.error("Quarantined corrupt worker session state file to %s", moved)
        loaded_worker_sessions = {}

    try:
        loaded_in_flight = load_in_flight_requests(in_flight_path)
    except Exception:
        logging.exception(
            "Failed to load in-flight request state from %s; starting with empty in-flight state.",
            in_flight_path,
        )
        moved = quarantine_corrupt_state_file(in_flight_path)
        if moved:
            logging.error("Quarantined corrupt in-flight state file to %s", moved)
        loaded_in_flight = {}

    if config.persistent_workers_enabled:
        now = time.time()
        current_policy_fingerprint = compute_policy_fingerprint(config.persistent_workers_policy_files)
        if not loaded_worker_sessions and loaded_threads:
            loaded_worker_sessions = {
                chat_id: WorkerSession(
                    created_at=now,
                    last_used_at=now,
                    thread_id=thread_id,
                    policy_fingerprint=current_policy_fingerprint,
                )
                for chat_id, thread_id in loaded_threads.items()
            }
        for chat_id, session in loaded_worker_sessions.items():
            if session.thread_id:
                loaded_threads[chat_id] = session.thread_id

    state = State(
        chat_threads=loaded_threads,
        chat_thread_path=chat_thread_path,
        worker_sessions=loaded_worker_sessions,
        worker_sessions_path=worker_sessions_path,
        in_flight_requests=loaded_in_flight,
        in_flight_path=in_flight_path,
    )
    client = TelegramClient(config)

    if config.persistent_workers_enabled:
        persist_chat_threads(state)
        persist_worker_sessions(state)

    interrupted = pop_interrupted_requests(state)
    if interrupted:
        for chat_id in sorted(interrupted):
            if chat_id not in config.allowed_chat_ids:
                continue
            try:
                client.send_message(
                    chat_id,
                    "Your previous request was interrupted because the bridge restarted. "
                    "Please resend it.",
                )
            except Exception:
                logging.exception(
                    "Failed to send restart-interruption notice for chat_id=%s",
                    chat_id,
                )
        logging.warning(
            "Detected %s interrupted in-flight request(s) from previous runtime.",
            len(interrupted),
        )

    try:
        offset = drop_pending_updates(client)
    except Exception:
        logging.exception("Failed to discard queued startup updates; defaulting to offset=0")
        offset = 0

    logging.info("Bridge started. Allowed chats=%s", sorted(config.allowed_chat_ids))
    logging.info("Architect-only routing active for all allowlisted chats.")
    logging.info("Executor command=%s", config.executor_cmd)
    logging.info("Loaded %s chat thread mappings from %s", len(loaded_threads), chat_thread_path)
    logging.info(
        "Persistent workers enabled=%s count=%s max=%s idle_timeout=%ss",
        config.persistent_workers_enabled,
        len(loaded_worker_sessions),
        config.persistent_workers_max,
        config.persistent_workers_idle_timeout_seconds,
    )
    logging.info("Loaded %s in-flight request marker(s) from %s", len(loaded_in_flight), in_flight_path)

    while True:
        try:
            expire_idle_worker_sessions(state, config, client)
            updates = client.get_updates(offset)
            for update in updates:
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    offset = max(offset, update_id + 1)
                handle_update(state, config, client, update)
        except (HTTPError, URLError, TimeoutError):
            logging.exception("Network/API error while polling Telegram")
            time.sleep(config.retry_sleep_seconds)
        except Exception:
            logging.exception("Unexpected loop error")
            time.sleep(config.retry_sleep_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description="Telegram Architect bridge")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="run local self test and exit",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=os.getenv("TELEGRAM_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.self_test:
        return run_self_test()

    try:
        config = load_config()
    except Exception as exc:
        logging.error("Configuration error: %s", exc)
        return 1

    return run_bridge(config)


if __name__ == "__main__":
    raise SystemExit(main())
