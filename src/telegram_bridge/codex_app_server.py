import json
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from telegram_bridge.executor import ExecutorCancelledError, ExecutorProgressEvent, attach_cached_executor_result


_SESSION_REGISTRY_LOCK = threading.Lock()
_SESSION_REGISTRY: Dict[str, "CodexAppServerSession"] = {}
FOLLOW_UP_STEER_DEBOUNCE_SECONDS = 0.6
FOLLOW_UP_STEER_IDLE_GRACE_SECONDS = 0.35
FOLLOW_UP_STEER_MAX_WAIT_SECONDS = 2.0


def _engines_config(config):
    return getattr(config, "engines", config)


def _reasoning_effort_value(config) -> Optional[str]:
    engines = _engines_config(config)
    raw = str(getattr(engines, "codex_reasoning_effort", "") or "").strip().lower()
    return raw or None


def _model_value(config) -> Optional[str]:
    engines = _engines_config(config)
    raw = str(getattr(engines, "codex_model", "") or "").strip()
    return raw or None


def _enabled(config) -> bool:
    engines = _engines_config(config)
    return bool(getattr(engines, "codex_app_server_enabled", False))


def try_steer_live_codex_turn(
    config,
    scope_key: Optional[str],
    prompt: str,
) -> bool:
    if not _enabled(config):
        return False
    normalized_scope_key = str(scope_key or "").strip()
    normalized_prompt = (prompt or "").strip()
    if not normalized_scope_key or not normalized_prompt:
        return False
    with _SESSION_REGISTRY_LOCK:
        session = _SESSION_REGISTRY.get(normalized_scope_key)
    if session is None:
        return False
    try:
        return session.try_steer(normalized_prompt)
    except Exception:
        logging.exception("Failed to steer live Codex turn for scope=%s", normalized_scope_key)
        return False


def live_codex_turn_is_active(
    config,
    scope_key: Optional[str],
) -> Optional[bool]:
    if not _enabled(config):
        return None
    normalized_scope_key = str(scope_key or "").strip()
    if not normalized_scope_key:
        return None
    with _SESSION_REGISTRY_LOCK:
        session = _SESSION_REGISTRY.get(normalized_scope_key)
    if session is None:
        return None
    try:
        return session.has_active_turn()
    except Exception:
        logging.exception("Failed to inspect live Codex turn state for scope=%s", normalized_scope_key)
        return None


def run_live_codex_turn(
    config,
    prompt: str,
    *,
    original_prompt: Optional[str],
    scope_key: Optional[str],
    previous_thread_id: Optional[str],
    image_paths: Optional[List[str]],
    progress_callback: Optional[Callable[[ExecutorProgressEvent], None]],
    cancel_event: Optional[threading.Event],
) -> subprocess.CompletedProcess[str]:
    normalized_scope_key = str(scope_key or "").strip()
    if not normalized_scope_key:
        raise RuntimeError("Codex live session requires a scope key.")
    with _SESSION_REGISTRY_LOCK:
        session = _SESSION_REGISTRY.get(normalized_scope_key)
        if session is None:
            session = CodexAppServerSession(
                scope_key=normalized_scope_key,
                config=config,
            )
            _SESSION_REGISTRY[normalized_scope_key] = session
    return session.run_turn(
        prompt=(prompt or "").strip(),
        original_prompt=(original_prompt or "").strip(),
        previous_thread_id=(previous_thread_id or "").strip() or None,
        image_paths=list(image_paths or []),
        progress_callback=progress_callback,
        cancel_event=cancel_event,
    )


@dataclass
class _PendingTurn:
    done: threading.Event = field(default_factory=threading.Event)
    active_turn_id: Optional[str] = None
    status: Optional[str] = None
    error: Optional[object] = None
    final_output: str = ""
    last_agent_message: str = ""
    progress_callback: Optional[Callable[[ExecutorProgressEvent], None]] = None
    interrupt_requested: bool = False
    original_prompt: str = ""
    follow_up_prompts: List[str] = field(default_factory=list)
    last_follow_up_at: float = 0.0
    steered_follow_up_count: int = 0
    steer_in_flight: bool = False


def _build_follow_up_steer_prompt(follow_up_prompts: List[str]) -> str:
    normalized_prompts = [str(prompt or "").strip() for prompt in follow_up_prompts if str(prompt or "").strip()]
    if not normalized_prompts:
        return ""
    if len(normalized_prompts) == 1:
        return normalized_prompts[0]
    lines = [
        "Additional follow-up messages arrived while you were already working on this request.",
        "Keep the original request active and incorporate all follow-up messages below in chronological order.",
        "Do not ignore earlier follow-up messages when a later one arrives.",
        "",
        "Follow-up messages (oldest first):",
    ]
    for index, prompt in enumerate(normalized_prompts, start=1):
        lines.append(f"{index}. {prompt}")
    return "\n".join(lines).strip()


def _build_accumulated_steer_prompt(
    *,
    original_prompt: str,
    follow_up_prompts: List[str],
) -> str:
    normalized_original_prompt = str(original_prompt or "").strip()
    normalized_follow_ups = [str(prompt or "").strip() for prompt in follow_up_prompts if str(prompt or "").strip()]
    if not normalized_follow_ups:
        return ""
    if len(normalized_follow_ups) == 1 and not normalized_original_prompt:
        return normalized_follow_ups[0]
    if len(normalized_follow_ups) == 1 and normalized_original_prompt:
        return "\n".join(
            [
                "Continue the same in-progress request.",
                "Do not drop the original request.",
                "Answer the original request and the follow-up below in one coherent reply.",
                "",
                "Original request:",
                normalized_original_prompt,
                "",
                "Follow-up message:",
                normalized_follow_ups[0],
            ]
        ).strip()

    lines = [
        "Continue the same in-progress request.",
        "Do not drop the original request or any earlier follow-up messages.",
        "Answer every unresolved item below in one coherent reply.",
        "",
        "Original request:",
        normalized_original_prompt or "(not available)",
        "",
        "Follow-up messages (oldest first):",
    ]
    for index, prompt in enumerate(normalized_follow_ups, start=1):
        lines.append(f"{index}. {prompt}")
    return "\n".join(lines).strip()


class CodexAppServerSession:
    def __init__(self, *, scope_key: str, config) -> None:
        self.scope_key = scope_key
        self.config = config
        self.process: Optional[subprocess.Popen[str]] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._write_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._request_id = 0
        self._request_events: Dict[int, threading.Event] = {}
        self._request_results: Dict[int, dict] = {}
        self._state_lock = threading.Lock()
        self._initialized = False
        self._thread_id: Optional[str] = None
        self._pending_turn: Optional[_PendingTurn] = None
        self._last_activity_at: float = 0.0

    def run_turn(
        self,
        *,
        prompt: str,
        original_prompt: str,
        previous_thread_id: Optional[str],
        image_paths: List[str],
        progress_callback: Optional[Callable[[ExecutorProgressEvent], None]],
        cancel_event: Optional[threading.Event],
    ) -> subprocess.CompletedProcess[str]:
        self._ensure_process()
        self._ensure_thread(previous_thread_id)
        pending_turn = _PendingTurn(
            progress_callback=progress_callback,
            original_prompt=(original_prompt or "").strip(),
        )
        with self._state_lock:
            if self._pending_turn is not None and not self._pending_turn.done.is_set():
                raise RuntimeError(f"Live Codex turn is already active for scope={self.scope_key}")
            self._pending_turn = pending_turn

        try:
            turn_response = self._call(
                "turn/start",
                {
                    "threadId": self._required_thread_id(),
                    "cwd": self._cwd(),
                    "input": self._build_user_inputs(prompt, image_paths),
                    "model": _model_value(self.config),
                    "effort": _reasoning_effort_value(self.config),
                    "approvalPolicy": "never",
                    "sandbox": "danger-full-access",
                },
            )
            started_turn = turn_response.get("turn") or {}
            started_turn_id = started_turn.get("id")
            if isinstance(started_turn_id, str) and started_turn_id.strip():
                with self._state_lock:
                    if self._pending_turn is pending_turn:
                        pending_turn.active_turn_id = started_turn_id.strip()

            while not pending_turn.done.wait(timeout=0.2):
                if cancel_event is None or not cancel_event.is_set():
                    continue
                self._interrupt_pending_turn(pending_turn)

            if cancel_event is not None and cancel_event.is_set():
                raise ExecutorCancelledError("Executor request canceled by user.")
            if pending_turn.status == "interrupted":
                raise ExecutorCancelledError("Executor request interrupted by user.")
            if pending_turn.status != "completed":
                raise RuntimeError(f"Live Codex turn ended with status={pending_turn.status!r}")

            output = pending_turn.final_output.strip() or pending_turn.last_agent_message.strip()
            result = subprocess.CompletedProcess(
                args=["codex", "app-server", "turn/start"],
                returncode=0,
                stdout="",
                stderr="",
            )
            return attach_cached_executor_result(result, self._thread_id, output)
        finally:
            with self._state_lock:
                if self._pending_turn is pending_turn:
                    self._pending_turn = None

    def try_steer(self, prompt: str) -> bool:
        normalized_prompt = (prompt or "").strip()
        if not normalized_prompt:
            return False
        self._ensure_process()
        deadline = time.monotonic() + 0.75
        pending_turn: Optional[_PendingTurn]
        thread_id: Optional[str]
        active_turn_id: Optional[str]
        while True:
            with self._state_lock:
                pending_turn = self._pending_turn
                thread_id = self._thread_id
                active_turn_id = pending_turn.active_turn_id if pending_turn is not None else None
                pending_turn_done = pending_turn.done.is_set() if pending_turn is not None else True
            if pending_turn is None or pending_turn_done or not thread_id:
                return False
            if active_turn_id:
                break
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)
        if not active_turn_id:
            return False
        with self._state_lock:
            pending_turn = self._pending_turn
            if pending_turn is None or pending_turn.done.is_set():
                return False
            pending_turn.follow_up_prompts.append(normalized_prompt)
            pending_turn.last_follow_up_at = time.monotonic()
            requested_follow_up_count = len(pending_turn.follow_up_prompts)
        steer_deadline = time.monotonic() + FOLLOW_UP_STEER_MAX_WAIT_SECONDS
        while True:
            send_payload: Optional[dict] = None
            with self._state_lock:
                pending_turn = self._pending_turn
                thread_id = self._thread_id
                if pending_turn is None or pending_turn.done.is_set() or not thread_id:
                    return False
                if requested_follow_up_count <= pending_turn.steered_follow_up_count:
                    return True
                now = time.monotonic()
                quiet_for = now - pending_turn.last_follow_up_at
                idle_for = now - self._last_activity_at
                should_flush = (
                    quiet_for >= FOLLOW_UP_STEER_DEBOUNCE_SECONDS
                    and idle_for >= FOLLOW_UP_STEER_IDLE_GRACE_SECONDS
                ) or now >= steer_deadline
                if should_flush and not pending_turn.steer_in_flight:
                    target_count = len(pending_turn.follow_up_prompts)
                    steer_prompt = _build_accumulated_steer_prompt(
                        original_prompt=pending_turn.original_prompt,
                        follow_up_prompts=pending_turn.follow_up_prompts[:target_count],
                    )
                    if not steer_prompt:
                        return False
                    pending_turn.steer_in_flight = True
                    send_payload = {
                        "threadId": thread_id,
                        "expectedTurnId": pending_turn.active_turn_id,
                        "input": self._build_user_inputs(steer_prompt, []),
                    }
                    send_target_count = target_count
                else:
                    send_target_count = 0
            if send_payload is None:
                time.sleep(0.05)
                continue
            try:
                self._call("turn/steer", send_payload)
            except Exception:
                with self._state_lock:
                    pending_turn = self._pending_turn
                    if pending_turn is not None:
                        pending_turn.steer_in_flight = False
                raise
            with self._state_lock:
                pending_turn = self._pending_turn
                if pending_turn is not None:
                    pending_turn.steered_follow_up_count = max(
                        pending_turn.steered_follow_up_count,
                        send_target_count,
                    )
                    pending_turn.steer_in_flight = False
            if requested_follow_up_count <= send_target_count:
                return True

    def has_active_turn(self) -> bool:
        self._ensure_process()
        with self._state_lock:
            pending_turn = self._pending_turn
            return pending_turn is not None and not pending_turn.done.is_set()

    def _interrupt_pending_turn(self, pending_turn: _PendingTurn) -> None:
        with self._state_lock:
            thread_id = self._thread_id
            active_turn_id = pending_turn.active_turn_id
            if pending_turn.interrupt_requested or not thread_id or not active_turn_id:
                return
            pending_turn.interrupt_requested = True
        try:
            self._call(
                "turn/interrupt",
                {
                    "threadId": thread_id,
                    "turnId": active_turn_id,
                },
            )
        except Exception:
            logging.exception("Failed to interrupt live Codex turn for scope=%s", self.scope_key)

    def _cwd(self) -> str:
        configured = str(getattr(self.config, "cwd", "") or "").strip()
        if configured:
            return configured
        return os.getcwd()

    def _required_thread_id(self) -> str:
        if not self._thread_id:
            raise RuntimeError(f"Live Codex thread is unavailable for scope={self.scope_key}")
        return self._thread_id

    def _build_user_inputs(self, prompt: str, image_paths: List[str]) -> List[dict]:
        inputs: List[dict] = []
        if prompt.strip():
            inputs.append({"type": "text", "text": prompt})
        for image_path in image_paths:
            if image_path:
                inputs.append({"type": "localImage", "path": image_path})
        return inputs

    def _ensure_thread(self, previous_thread_id: Optional[str]) -> None:
        with self._state_lock:
            current_thread_id = self._thread_id
        if current_thread_id:
            return
        if previous_thread_id:
            try:
                response = self._call("thread/resume", {"threadId": previous_thread_id})
            except Exception:
                logging.warning(
                    "Failed to resume Codex app-server thread_id=%s for scope=%s; starting new thread.",
                    previous_thread_id,
                    self.scope_key,
                )
            else:
                resumed_thread_id = (
                    (((response.get("thread") or {}).get("id")) or "").strip()
                    if isinstance((response.get("thread") or {}).get("id"), str)
                    else ""
                )
                if resumed_thread_id:
                    with self._state_lock:
                        self._thread_id = resumed_thread_id
                    return

        response = self._call(
            "thread/start",
            {
                "cwd": self._cwd(),
                "approvalPolicy": "never",
                "sandbox": "danger-full-access",
                "model": _model_value(self.config),
            },
        )
        thread = response.get("thread") or {}
        thread_id = thread.get("id")
        if not isinstance(thread_id, str) or not thread_id.strip():
            raise RuntimeError("Codex app-server thread/start did not return a thread id")
        with self._state_lock:
            self._thread_id = thread_id.strip()

    def _ensure_process(self) -> None:
        with self._lifecycle_lock:
            process = self.process
            if process is not None and process.poll() is None:
                if self._initialized:
                    return
            self._start_process()
            self._initialize()

    def _start_process(self) -> None:
        process = self.process
        if process is not None and process.poll() is None:
            return
        cmd = ["codex", "app-server", "--listen", "stdio://"]
        self.process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._initialized = False
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()
        self._stderr_thread = threading.Thread(target=self._stderr_loop, daemon=True)
        self._stderr_thread.start()

    def _initialize(self) -> None:
        try:
            result = self._call(
                "initialize",
                {
                    "clientInfo": {"name": "telegram-bridge", "version": "1"},
                    "capabilities": {"experimentalApi": True},
                },
            )
        except RuntimeError as exc:
            if "Already initialized" not in str(exc):
                raise
            result = {}
        if not isinstance(result, dict):
            raise RuntimeError("Codex app-server initialize returned invalid payload")
        self._initialized = True

    def _stderr_loop(self) -> None:
        process = self.process
        if process is None or process.stderr is None:
            return
        for raw_line in process.stderr:
            logging.info("Codex app-server stderr scope=%s: %s", self.scope_key, raw_line.rstrip())

    def _reader_loop(self) -> None:
        process = self.process
        if process is None or process.stdout is None:
            return
        for raw_line in process.stdout:
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                logging.warning("Invalid Codex app-server JSON scope=%s line=%r", self.scope_key, line)
                continue
            if "id" in payload and "method" in payload and "params" in payload:
                self._handle_server_request(payload)
                continue
            if "id" in payload and ("result" in payload or "error" in payload):
                self._handle_response(payload)
                continue
            self._handle_notification(payload)

    def _handle_response(self, payload: dict) -> None:
        request_id = payload.get("id")
        if not isinstance(request_id, int):
            return
        with self._write_lock:
            self._request_results[request_id] = payload
            event = self._request_events.get(request_id)
        if event is not None:
            event.set()

    def _handle_notification(self, payload: dict) -> None:
        self._mark_activity()
        method = payload.get("method")
        params = payload.get("params")
        if not isinstance(method, str) or not isinstance(params, dict):
            return
        if method == "turn/started":
            turn = params.get("turn") or {}
            turn_id = turn.get("id")
            if isinstance(turn_id, str) and turn_id.strip():
                with self._state_lock:
                    pending_turn = self._pending_turn
                    if pending_turn is not None and not pending_turn.done.is_set():
                        pending_turn.active_turn_id = turn_id.strip()
            callback = self._progress_callback()
            if callback is not None:
                callback(ExecutorProgressEvent("turn_started", "Assistant started working."))
            return
        if method == "turn/completed":
            turn = params.get("turn") or {}
            status = turn.get("status")
            with self._state_lock:
                pending_turn = self._pending_turn
                if pending_turn is not None:
                    pending_turn.status = status if isinstance(status, str) else None
                    pending_turn.done.set()
            callback = self._progress_callback()
            if callback is not None:
                callback(ExecutorProgressEvent("turn_completed", "Assistant finished reasoning."))
            return
        if method == "item/started":
            item = params.get("item") or {}
            self._handle_item_started(item)
            return
        if method == "item/completed":
            item = params.get("item") or {}
            self._handle_item_completed(item)
            return
        if method == "item/agentMessage/delta":
            delta = params.get("delta")
            if not isinstance(delta, str):
                return
            with self._state_lock:
                pending_turn = self._pending_turn
                if pending_turn is not None:
                    pending_turn.last_agent_message += delta
            return
        if method == "error":
            logging.warning("Codex app-server protocol error scope=%s params=%r", self.scope_key, params)
            return
        if method.endswith("/requestApproval") or method == "item/tool/requestUserInput":
            logging.warning("Unsupported Codex app-server request surfaced as notification scope=%s method=%s", self.scope_key, method)

    def _handle_server_request(self, payload: dict) -> None:
        request_id = payload.get("id")
        method = payload.get("method")
        if not isinstance(request_id, int) or not isinstance(method, str):
            return
        logging.warning("Unsupported Codex app-server server request scope=%s method=%s", self.scope_key, method)
        self._send_json(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32000,
                    "message": f"Unsupported server request in telegram bridge: {method}",
                },
            }
        )

    def _handle_item_started(self, item: dict) -> None:
        item_type = item.get("type")
        callback = self._progress_callback()
        if callback is None:
            return
        if item_type == "reasoning":
            callback(ExecutorProgressEvent("reasoning", ""))
            return
        if item_type == "commandExecution":
            command = item.get("command")
            callback(
                ExecutorProgressEvent(
                    "command_started",
                    command if isinstance(command, str) else "",
                )
            )

    def _handle_item_completed(self, item: dict) -> None:
        item_type = item.get("type")
        callback = self._progress_callback()
        if item_type == "commandExecution":
            if callback is None:
                return
            command = item.get("command")
            exit_code = item.get("exitCode")
            callback(
                ExecutorProgressEvent(
                    "command_completed",
                    command if isinstance(command, str) else "",
                    exit_code if isinstance(exit_code, int) else None,
                )
            )
            return
        if item_type != "agentMessage":
            return
        text = item.get("text")
        normalized_text = text if isinstance(text, str) else ""
        phase = item.get("phase")
        with self._state_lock:
            pending_turn = self._pending_turn
            if pending_turn is not None:
                if phase == "final_answer":
                    pending_turn.final_output = normalized_text
                pending_turn.last_agent_message = normalized_text or pending_turn.last_agent_message
        if callback is not None and normalized_text:
            callback(ExecutorProgressEvent("agent_message", normalized_text))

    def _progress_callback(self) -> Optional[Callable[[ExecutorProgressEvent], None]]:
        with self._state_lock:
            pending_turn = self._pending_turn
            return pending_turn.progress_callback if pending_turn is not None else None

    def _mark_activity(self) -> None:
        with self._state_lock:
            self._last_activity_at = time.monotonic()

    def _call(self, method: str, params: dict) -> dict:
        process = self.process
        if process is None or process.stdin is None:
            raise RuntimeError("Codex app-server process is unavailable")
        event = threading.Event()
        with self._write_lock:
            self._request_id += 1
            request_id = self._request_id
            self._request_events[request_id] = event
            self._send_json(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params,
                },
                already_locked=True,
            )
        if not event.wait(timeout=float(getattr(self.config, "exec_timeout_seconds", 3600) or 3600)):
            with self._write_lock:
                self._request_events.pop(request_id, None)
                self._request_results.pop(request_id, None)
            raise TimeoutError(f"Timed out waiting for Codex app-server response method={method}")
        with self._write_lock:
            self._request_events.pop(request_id, None)
            payload = self._request_results.pop(request_id, None)
        if not isinstance(payload, dict):
            raise RuntimeError(f"Missing Codex app-server response payload for method={method}")
        if "error" in payload:
            raise RuntimeError(f"Codex app-server {method} failed: {payload['error']}")
        result = payload.get("result")
        if not isinstance(result, dict):
            return {}
        return result

    def _send_json(self, payload: dict, *, already_locked: bool = False) -> None:
        process = self.process
        if process is None or process.stdin is None:
            raise RuntimeError("Codex app-server process is unavailable")
        raw = json.dumps(payload, separators=(",", ":"))
        if already_locked:
            process.stdin.write(raw + "\n")
            process.stdin.flush()
            return
        with self._write_lock:
            process.stdin.write(raw + "\n")
            process.stdin.flush()
