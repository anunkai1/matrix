import base64
import logging
import mimetypes
import os
import shlex
import subprocess
import threading
import time
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from telegram_bridge.executor import (
    ExecutorCancelledError,
    attach_cached_executor_result,
)


_SESSION_REGISTRY_LOCK = threading.Lock()
_SESSION_REGISTRY: Dict[str, "PiLiveRpcSession"] = {}


def _engines_config(config):
    return getattr(config, "engines", config)


def _enabled(config) -> bool:
    engines = _engines_config(config)
    return bool(getattr(engines, "pi_live_rpc_enabled", False))


def _idle_timeout_seconds_value(config) -> int:
    engines = _engines_config(config)
    raw = getattr(engines, "pi_live_rpc_idle_timeout_seconds", 15 * 60)
    try:
        return max(0, int(raw or 0))
    except (TypeError, ValueError):
        return 15 * 60


def _provider_value(config) -> str:
    return str(getattr(config, "pi_provider", "ollama") or "ollama").strip().lower() or "ollama"


def _model_value(config) -> str:
    return str(getattr(config, "pi_model", "qwen3-coder:30b") or "qwen3-coder:30b").strip() or "qwen3-coder:30b"


def _runner_value(config) -> str:
    return str(getattr(config, "pi_runner", "ssh") or "ssh").strip().lower() or "ssh"


def _session_signature(config) -> tuple[str, str, str]:
    return (_runner_value(config), _provider_value(config), _model_value(config))


def _model_supports_images(config) -> bool:
    models_path = Path.home() / ".pi" / "agent" / "models.json"
    model = _model_value(config)
    if not model or not models_path.is_file():
        return True
    try:
        data = json.loads(models_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return True
    providers = data.get("providers")
    if not isinstance(providers, dict):
        return True
    provider_cfg = providers.get(_provider_value(config))
    if not isinstance(provider_cfg, dict):
        return True
    models = provider_cfg.get("models")
    if not isinstance(models, list):
        return True
    for entry in models:
        if not isinstance(entry, dict):
            continue
        if entry.get("id") != model:
            continue
        supported_inputs = entry.get("input")
        return not isinstance(supported_inputs, list) or "image" in supported_inputs
    return True


def _build_session_args(config, session_key: Optional[str]) -> List[str]:
    from telegram_bridge.engines.pi_sessions import build_session_args

    return build_session_args(config, session_key)


def _clear_scope_session_files(config, scope_key: str) -> int:
    from telegram_bridge.engines.pi_sessions import clear_scope_session_files

    return clear_scope_session_files(config, scope_key)


def _sanitize_session_images(config, scope_key: str) -> None:
    from telegram_bridge.engines.pi_sessions import sanitize_session_images

    sanitize_session_images(config, scope_key)


def _build_pi_rpc_command(config, *, include_no_context_files: bool, session_key: Optional[str]) -> List[str]:
    from telegram_bridge.engines.pi_command import build_pi_rpc_args

    return build_pi_rpc_args(
        config,
        include_no_context_files=include_no_context_files,
        session_key=session_key,
        build_session_args_fn=_build_session_args,
    )


def _build_pi_text_command(config, *, include_no_context_files: bool, session_key: Optional[str]) -> List[str]:
    from telegram_bridge.engines.pi_command import build_pi_text_args

    return build_pi_text_args(
        config,
        include_no_context_files=include_no_context_files,
        session_key=session_key,
        build_pi_rpc_args_fn=lambda cfg, include_no_context_files, session_key: _build_pi_rpc_command(
            cfg,
            include_no_context_files=include_no_context_files,
            session_key=session_key,
        ),
    )


def _build_rpc_prompt(
    prompt: str,
    *,
    image_paths: Optional[List[str]],
    image_data_builder,
) -> str:
    from telegram_bridge.engines.pi_rpc import build_rpc_prompt_json

    return build_rpc_prompt_json(
        prompt,
        image_paths=image_paths,
        image_data_builder=image_data_builder,
    )


def _extract_rpc_output(stdout_lines: List[str]) -> str:
    from telegram_bridge.engines.pi_rpc import extract_rpc_response

    return extract_rpc_response(stdout_lines)


def _should_retry_text_mode(exc: RuntimeError, *, image_paths: Optional[List[str]]) -> bool:
    from telegram_bridge.engines.pi_rpc import should_retry_pi_text_mode

    return should_retry_pi_text_mode(exc, image_paths=image_paths)


def _image_url_error_markers() -> tuple[str, ...]:
    from telegram_bridge.engines.pi_rpc import IMAGE_URL_ERROR_MARKERS

    return IMAGE_URL_ERROR_MARKERS


def _pi_transport():
    from telegram_bridge.engines import pi_transport

    return pi_transport


def expire_idle_pi_rpc_sessions(config) -> int:
    timeout_seconds = _idle_timeout_seconds_value(config)
    if timeout_seconds <= 0:
        return 0

    now = time.monotonic()
    expired_scope_keys: List[str] = []
    with _SESSION_REGISTRY_LOCK:
        registry_snapshot = list(_SESSION_REGISTRY.items())
    for scope_key, session in registry_snapshot:
        try:
            expired = session.close_if_idle(timeout_seconds=timeout_seconds, now_monotonic=now)
        except Exception:
            logging.exception("Failed to expire idle Pi RPC session scope=%s", scope_key)
            continue
        if expired:
            expired_scope_keys.append(scope_key)

    expired_count = 0
    if not expired_scope_keys:
        return 0
    with _SESSION_REGISTRY_LOCK:
        for scope_key in expired_scope_keys:
            session = _SESSION_REGISTRY.get(scope_key)
            if session is None or session.has_active_turn():
                continue
            if session.process is not None and session.process.poll() is None:
                continue
            del _SESSION_REGISTRY[scope_key]
            expired_count += 1
    if expired_count:
        logging.info(
            "Expired %s idle Pi RPC session(s) after %ss timeout.",
            expired_count,
            timeout_seconds,
        )
    return expired_count


def try_steer_live_pi_turn(config, scope_key: Optional[str], prompt: str) -> bool:
    if not _enabled(config):
        return False
    normalized_scope_key = str(scope_key or "").strip()
    normalized_prompt = str(prompt or "").strip()
    if not normalized_scope_key or not normalized_prompt:
        return False
    with _SESSION_REGISTRY_LOCK:
        session = _SESSION_REGISTRY.get(normalized_scope_key)
    if session is None:
        return False
    try:
        return session.try_steer(normalized_prompt)
    except Exception:
        logging.exception("Failed to steer live Pi turn for scope=%s", normalized_scope_key)
        return False


def live_pi_turn_is_active(config, scope_key: Optional[str]) -> Optional[bool]:
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
        logging.exception("Failed to inspect live Pi turn state for scope=%s", normalized_scope_key)
        return None


def run_live_pi_turn(
    config,
    prompt: str,
    *,
    original_prompt: Optional[str],
    scope_key: Optional[str],
    image_paths: Optional[List[str]],
    cancel_event: Optional[threading.Event],
) -> subprocess.CompletedProcess[str]:
    normalized_scope_key = str(scope_key or "").strip()
    if not normalized_scope_key:
        raise RuntimeError("Live Pi session requires a scope key.")
    signature = _session_signature(config)
    with _SESSION_REGISTRY_LOCK:
        session = _SESSION_REGISTRY.get(normalized_scope_key)
        if session is None or session.signature != signature:
            if session is not None:
                session.close()
            session = PiLiveRpcSession(
                scope_key=normalized_scope_key,
                config=config,
                signature=signature,
            )
            _SESSION_REGISTRY[normalized_scope_key] = session
    return session.run_turn(
        prompt=str(prompt or "").strip(),
        original_prompt=str(original_prompt or "").strip(),
        image_paths=list(image_paths or []),
        cancel_event=cancel_event,
    )


@dataclass
class _PendingTurn:
    done: threading.Event = field(default_factory=threading.Event)
    original_prompt: str = ""
    follow_up_prompts: List[str] = field(default_factory=list)
    last_output: str = ""
    final_output: str = ""
    steered_follow_up_count: int = 0
    session_reset_note: str = ""


def _build_accumulated_follow_up_prompt(*, original_prompt: str, follow_up_prompts: List[str]) -> str:
    normalized_original = str(original_prompt or "").strip()
    normalized_follow_ups = [str(item or "").strip() for item in follow_up_prompts if str(item or "").strip()]
    if not normalized_follow_ups:
        return ""
    if len(normalized_follow_ups) == 1 and not normalized_original:
        return normalized_follow_ups[0]
    if len(normalized_follow_ups) == 1:
        return "\n".join(
            [
                "Continue the same in-progress request.",
                "Do not drop the original request.",
                "Answer the original request and the follow-up below in one coherent reply.",
                "",
                "Original request:",
                normalized_original,
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
        normalized_original or "(not available)",
        "",
        "Follow-up messages (oldest first):",
    ]
    for index, item in enumerate(normalized_follow_ups, start=1):
        lines.append(f"{index}. {item}")
    return "\n".join(lines).strip()


class PiLiveRpcSession:
    _STDERR_BUFFER_LINES = 200

    def __init__(self, *, scope_key: str, config, signature: tuple[str, str, str]) -> None:
        self.scope_key = scope_key
        self.config = config
        self.signature = signature
        self.process: Optional[subprocess.Popen[str]] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._stderr_lock = threading.Lock()
        self._stderr_buffer: List[str] = []
        self._lifecycle_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._pending_turn: Optional[_PendingTurn] = None
        self._last_used_at: float = time.monotonic()

    def run_turn(
        self,
        *,
        prompt: str,
        original_prompt: str,
        image_paths: List[str],
        cancel_event: Optional[threading.Event],
    ) -> subprocess.CompletedProcess[str]:
        self._mark_used()
        pending_turn = _PendingTurn(original_prompt=original_prompt)
        with self._state_lock:
            if self._pending_turn is not None and not self._pending_turn.done.is_set():
                raise RuntimeError(f"Live Pi turn is already active for scope={self.scope_key}")
            self._pending_turn = pending_turn

        if not image_paths and not _model_supports_images(self.config):
            _sanitize_session_images(self.config, self.scope_key)

        try:
            current_prompt = str(prompt or "").strip()
            current_images = list(image_paths)
            followed_up_count = 0
            reset_attempted = False
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    self._cancel_active_turn()
                    raise ExecutorCancelledError("Pi request canceled by user.")
                try:
                    output = self._run_prompt(
                        current_prompt,
                        current_images,
                        cancel_event=cancel_event,
                    )
                except ExecutorCancelledError:
                    self._stop_process()
                    raise
                except RuntimeError as exc:
                    error_lower = str(exc).lower()
                    if (
                        not current_images
                        and not reset_attempted
                        and any(marker in error_lower for marker in _image_url_error_markers())
                    ):
                        archived = _clear_scope_session_files(self.config, self.scope_key)
                        reset_attempted = True
                        pending_turn.session_reset_note = (
                            "Session was reset because the previous Pi session for this scope "
                            "contained image content that the provider could not replay cleanly."
                        )
                        logging.warning(
                            "Reset live Pi session scope=%s archived_scope_files=%s provider=%s model=%s",
                            self.scope_key,
                            archived,
                            _provider_value(self.config),
                            _model_value(self.config),
                        )
                        self._stop_process()
                        continue
                    if _should_retry_text_mode(exc, image_paths=current_images):
                        output = self._run_text_fallback(current_prompt)
                    else:
                        raise
                pending_turn.last_output = output.strip()
                with self._state_lock:
                    queued_follow_ups = pending_turn.follow_up_prompts[:]
                if len(queued_follow_ups) <= followed_up_count:
                    pending_turn.final_output = pending_turn.last_output
                    break
                followed_up_count = len(queued_follow_ups)
                pending_turn.steered_follow_up_count = followed_up_count
                current_prompt = _build_accumulated_follow_up_prompt(
                    original_prompt=pending_turn.original_prompt,
                    follow_up_prompts=queued_follow_ups,
                )
                current_images = []

            final_output = pending_turn.final_output.strip() or pending_turn.last_output.strip()
            if pending_turn.session_reset_note:
                final_output = f"({pending_turn.session_reset_note})\n\n{final_output}".strip()
            result = subprocess.CompletedProcess(
                args=["pi", "--mode", "rpc"],
                returncode=0,
                stdout="",
                stderr="",
            )
            return attach_cached_executor_result(
                result,
                None,
                final_output,
                steered_follow_up_count=pending_turn.steered_follow_up_count,
            )
        finally:
            pending_turn.done.set()
            with self._state_lock:
                if self._pending_turn is pending_turn:
                    self._pending_turn = None

    def try_steer(self, prompt: str) -> bool:
        normalized_prompt = str(prompt or "").strip()
        if not normalized_prompt:
            return False
        self._mark_used()
        with self._state_lock:
            pending_turn = self._pending_turn
            if pending_turn is None or pending_turn.done.is_set():
                return False
            pending_turn.follow_up_prompts.append(normalized_prompt)
        return True

    def has_active_turn(self) -> bool:
        with self._state_lock:
            pending_turn = self._pending_turn
            return pending_turn is not None and not pending_turn.done.is_set()

    def close_if_idle(self, *, timeout_seconds: int, now_monotonic: Optional[float] = None) -> bool:
        if timeout_seconds <= 0:
            return False
        now = time.monotonic() if now_monotonic is None else now_monotonic
        with self._state_lock:
            pending_turn = self._pending_turn
            last_used_at = self._last_used_at
        if pending_turn is not None and not pending_turn.done.is_set():
            return False
        process = self.process
        if process is None:
            return True
        if process.poll() is not None:
            self._stop_process()
            return True
        if now - last_used_at < timeout_seconds:
            return False
        logging.info(
            "Stopping idle Pi RPC scope=%s idle_for=%.1fs timeout=%ss",
            self.scope_key,
            max(0.0, now - last_used_at),
            timeout_seconds,
        )
        self._stop_process()
        return True

    def close(self) -> None:
        self._stop_process()

    def _mark_used(self) -> None:
        with self._state_lock:
            self._last_used_at = time.monotonic()

    def _cancel_active_turn(self) -> None:
        self._stop_process()

    def _image_data_url(self, image_path: str) -> dict[str, str]:
        path = Path(image_path)
        if not path.is_file():
            raise RuntimeError(f"Pi image file not found: {image_path}")
        mime_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return {"type": "image", "data": encoded, "mimeType": mime_type}

    def _build_rpc_args(self, *, include_no_context_files: bool) -> List[str]:
        return _build_pi_rpc_command(
            self.config,
            include_no_context_files=include_no_context_files,
            session_key=self.scope_key,
        )

    def _build_text_args(self, *, include_no_context_files: bool) -> List[str]:
        return _build_pi_text_command(
            self.config,
            include_no_context_files=include_no_context_files,
            session_key=self.scope_key,
        )

    def _run_prompt(
        self,
        prompt: str,
        image_paths: List[str],
        *,
        cancel_event: Optional[threading.Event],
    ) -> str:
        self._ensure_process()
        process = self.process
        if process is None or process.stdin is None or process.stdout is None:
            raise RuntimeError("Pi RPC session is unavailable.")
        prompt_json = _build_rpc_prompt(
            prompt,
            image_paths=image_paths,
            image_data_builder=self._image_data_url,
        )
        with self._write_lock:
            process.stdin.write(prompt_json + "\n")
            process.stdin.flush()
            stdout_lines = _pi_transport().read_rpc_stdout(
                process,
                cancel_event,
                int(getattr(self.config, "pi_request_timeout_seconds", 180)),
                time_module=time,
                executor_cancelled_error_cls=ExecutorCancelledError,
            )
        if cancel_event is not None and cancel_event.is_set():
            raise ExecutorCancelledError("Pi request canceled by user.")
        return_code = process.poll()
        if return_code not in (None, 0):
            stderr_text = self._stderr_text()
            self._stop_process()
            raise RuntimeError(
                (stderr_text or f"Pi RPC session exited with code {return_code}").strip()
            )
        return _extract_rpc_output(stdout_lines)

    def _run_text_fallback(self, prompt: str) -> str:
        runner = _runner_value(self.config)
        if runner in {"local", "server3"}:
            return _pi_transport().run_pi_text_local(
                self.config,
                prompt,
                self.scope_key,
                build_pi_text_args=lambda cfg, include_no_context_files, session_key: self._build_text_args(
                    include_no_context_files=include_no_context_files
                ),
                subprocess_module=subprocess,
            )

        timeout = int(getattr(self.config, "pi_request_timeout_seconds", 180))
        quoted = " ".join(
            shlex.quote(part)
            for part in (["timeout", str(timeout)] + self._build_text_args(include_no_context_files=True) + [prompt])
        )
        remote_cwd = str(getattr(self.config, "pi_remote_cwd", "/tmp") or "/tmp").strip()
        remote_command = f"cd {shlex.quote(remote_cwd)} && {quoted}" if remote_cwd else quoted
        completed = subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                str(getattr(self.config, "pi_ssh_host", "server4-beast") or "server4-beast").strip(),
                remote_command,
            ],
            capture_output=True,
            text=True,
            timeout=timeout + 5,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                completed.stderr.strip()
                or completed.stdout.strip()
                or "Pi text-mode SSH runner failed."
            )
        output = str(completed.stdout or "").strip()
        if not output:
            raise RuntimeError("Pi text-mode SSH runner produced no output.")
        return output

    def _ensure_process(self) -> None:
        with self._lifecycle_lock:
            process = self.process
            if process is not None and process.poll() is None:
                return
            self._start_process()

    def _start_process(self) -> None:
        runner = _runner_value(self.config)
        if runner in {"local", "server3"}:
            transport = _pi_transport()
            if transport.pi_provider_uses_ollama_tunnel(self.config):
                transport.ensure_local_ollama_tunnel(
                    self.config,
                    local_ollama_tunnel_healthy_fn=transport.local_ollama_tunnel_healthy,
                    subprocess_module=subprocess,
                    time_module=time,
                )
            env = os.environ.copy()
            env["OLLAMA_HOST"] = f"http://127.0.0.1:{int(getattr(self.config, 'pi_ollama_tunnel_local_port', 11435))}"
            self.process = subprocess.Popen(
                self._build_rpc_args(include_no_context_files=False),
                cwd=str(getattr(self.config, "pi_local_cwd", "") or "").strip() or None,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
        elif runner in {"ssh", "server4"}:
            quoted = " ".join(shlex.quote(part) for part in self._build_rpc_args(include_no_context_files=True))
            remote_cwd = str(getattr(self.config, "pi_remote_cwd", "/tmp") or "/tmp").strip()
            remote_command = f"cd {shlex.quote(remote_cwd)} && {quoted}" if remote_cwd else quoted
            self.process = subprocess.Popen(
                [
                    "ssh",
                    "-o",
                    "BatchMode=yes",
                    str(getattr(self.config, "pi_ssh_host", "server4-beast") or "server4-beast").strip(),
                    remote_command,
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        else:
            raise RuntimeError(f"Unsupported Pi runner: {runner}")
        self._stderr_buffer = []
        self._start_stderr_thread()

    def _start_stderr_thread(self) -> None:
        process = self.process
        if process is None or process.stderr is None:
            return

        def _drain_stderr() -> None:
            for raw_line in process.stderr:
                line = raw_line.rstrip()
                if not line:
                    continue
                with self._stderr_lock:
                    self._stderr_buffer.append(line)
                    if len(self._stderr_buffer) > self._STDERR_BUFFER_LINES:
                        self._stderr_buffer = self._stderr_buffer[-self._STDERR_BUFFER_LINES :]

        self._stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
        self._stderr_thread.start()

    def _stderr_text(self) -> str:
        with self._stderr_lock:
            return "\n".join(self._stderr_buffer).strip()

    def _stop_process(self) -> None:
        with self._lifecycle_lock:
            process = self.process
            self.process = None
            self._stderr_thread = None
            if process is None:
                return
            try:
                if process.stdin is not None and not process.stdin.closed:
                    process.stdin.close()
            except Exception:
                pass
            try:
                if process.poll() is None:
                    process.kill()
            except Exception:
                pass
            try:
                process.wait(timeout=5)
            except Exception:
                pass
            for pipe in (process.stdout, process.stderr):
                try:
                    if pipe is not None and not pipe.closed:
                        pipe.close()
                except Exception:
                    pass
