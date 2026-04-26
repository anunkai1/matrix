import json
import hashlib
import os
import re
import shlex
import socket
import subprocess
import threading
import sys
import time
from pathlib import Path
from typing import Callable, Optional, Protocol
from urllib import error as urllib_error
from urllib import request as urllib_request

try:
    from .executor import (
        ExecutorCancelledError,
        ExecutorProgressEvent,
        OUTPUT_BEGIN_MARKER,
        parse_executor_output,
        run_executor,
    )
except ImportError:
    from executor import (
        ExecutorCancelledError,
        ExecutorProgressEvent,
        OUTPUT_BEGIN_MARKER,
        parse_executor_output,
        run_executor,
    )

ProgressCallback = Callable[[ExecutorProgressEvent], None]


class EngineAdapter(Protocol):
    engine_name: str

    def run(
        self,
        config,
        prompt: str,
        thread_id: Optional[str],
        session_key: Optional[str] = None,
        channel_name: Optional[str] = None,
        actor_chat_id: Optional[int] = None,
        actor_user_id: Optional[int] = None,
        image_path: Optional[str] = None,
        image_paths: Optional[list[str]] = None,
        progress_callback: Optional[ProgressCallback] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> subprocess.CompletedProcess[str]:
        ...


class CodexEngineAdapter:
    engine_name = "codex"

    def run(
        self,
        config,
        prompt: str,
        thread_id: Optional[str],
        session_key: Optional[str] = None,
        channel_name: Optional[str] = None,
        actor_chat_id: Optional[int] = None,
        actor_user_id: Optional[int] = None,
        image_path: Optional[str] = None,
        image_paths: Optional[list[str]] = None,
        progress_callback: Optional[ProgressCallback] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> subprocess.CompletedProcess[str]:
        return run_executor(
            config=config,
            prompt=prompt,
            thread_id=thread_id,
            session_key=session_key,
            channel_name=channel_name,
            actor_chat_id=actor_chat_id,
            actor_user_id=actor_user_id,
            image_path=image_path,
            image_paths=image_paths,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
        )


class GemmaEngineAdapter:
    engine_name = "gemma"

    def _completed_process_with_output(self, output: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["gemma"],
            returncode=0,
            stdout=f"{OUTPUT_BEGIN_MARKER}\n{str(output or '').strip()}",
            stderr="",
        )

    def _payload(self, config, prompt: str) -> str:
        payload = {
            "model": getattr(config, "gemma_model", "gemma4:26b"),
            "stream": False,
            "messages": [{"role": "user", "content": prompt}],
        }
        return json.dumps(payload)

    def _run_ollama_http(self, config, prompt: str) -> str:
        base_url = str(getattr(config, "gemma_base_url", "http://127.0.0.1:11434")).rstrip("/")
        timeout = int(getattr(config, "gemma_request_timeout_seconds", 180))
        req = urllib_request.Request(
            f"{base_url}/api/chat",
            data=self._payload(config, prompt).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib_request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
        return self._extract_ollama_content(raw)

    def _run_ollama_ssh(
        self,
        config,
        prompt: str,
        cancel_event: Optional[threading.Event],
    ) -> str:
        timeout = int(getattr(config, "gemma_request_timeout_seconds", 180))
        ssh_host = str(getattr(config, "gemma_ssh_host", "server4-beast")).strip() or "server4-beast"
        remote_cmd = (
            "curl -sS "
            f"--max-time {timeout} "
            "http://127.0.0.1:11434/api/chat "
            "-H 'Content-Type: application/json' "
            "-d @-"
        )
        cmd = ["ssh", "-o", "BatchMode=yes", ssh_host, remote_cmd]
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, stderr = process.communicate(
                input=self._payload(config, prompt),
                timeout=timeout + 10,
            )
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
            raise
        if cancel_event is not None and cancel_event.is_set():
            raise ExecutorCancelledError("Gemma request canceled by user.")
        if process.returncode != 0:
            raise RuntimeError((stderr or stdout or "Gemma SSH transport failed.").strip())
        return self._extract_ollama_content(stdout)

    def _extract_ollama_content(self, raw: str) -> str:
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Gemma returned invalid JSON: {exc}") from exc
        message = payload.get("message")
        if not isinstance(message, dict):
            raise RuntimeError("Gemma response did not contain an assistant message.")
        content = message.get("content")
        if not isinstance(content, str):
            raise RuntimeError("Gemma response did not contain text content.")
        return content.strip()

    def run(
        self,
        config,
        prompt: str,
        thread_id: Optional[str],
        session_key: Optional[str] = None,
        channel_name: Optional[str] = None,
        actor_chat_id: Optional[int] = None,
        actor_user_id: Optional[int] = None,
        image_path: Optional[str] = None,
        image_paths: Optional[list[str]] = None,
        progress_callback: Optional[ProgressCallback] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> subprocess.CompletedProcess[str]:
        del thread_id, session_key, channel_name, actor_chat_id, actor_user_id, progress_callback
        if image_path or image_paths:
            return self._completed_process_with_output(
                "Gemma is configured for text-only requests right now. Use `/engine codex` for image or file-heavy work."
            )
        provider = str(getattr(config, "gemma_provider", "ollama_ssh")).strip().lower()
        try:
            if cancel_event is not None and cancel_event.is_set():
                raise ExecutorCancelledError("Gemma request canceled by user.")
            if provider in {"ollama_http", "http", "ollama"}:
                output = self._run_ollama_http(config, prompt)
            elif provider in {"ollama_ssh", "ssh"}:
                output = self._run_ollama_ssh(config, prompt, cancel_event)
            else:
                raise RuntimeError(f"Unsupported Gemma provider: {provider}")
            return self._completed_process_with_output(output)
        except ExecutorCancelledError:
            raise
        except subprocess.TimeoutExpired:
            raise
        except (RuntimeError, OSError, urllib_error.URLError) as exc:
            return self._completed_process_with_output(f"Gemma request failed: {exc}")


class PiEngineAdapter:
    engine_name = "pi"

    def _completed_process_with_output(self, output: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["pi"],
            returncode=0,
            stdout=f"{OUTPUT_BEGIN_MARKER}\n{str(output or '').strip()}",
            stderr="",
        )

    def _build_pi_args(
        self,
        config,
        prompt: str,
        *,
        include_no_context_files: bool,
        session_key: Optional[str] = None,
    ) -> list[str]:
        provider = str(getattr(config, "pi_provider", "ollama") or "ollama").strip()
        if provider.strip().lower() in {"ollama_ssh", "ssh"}:
            provider = "ollama"
        model = str(getattr(config, "pi_model", "gemma4:26b") or "gemma4:26b").strip()
        tools_mode = (
            str(getattr(config, "pi_tools_mode", "default") or "default")
            .strip()
            .lower()
        )
        tools_allowlist = str(getattr(config, "pi_tools_allowlist", "") or "").strip()
        extra_args = str(getattr(config, "pi_extra_args", "") or "").strip()

        args = [
            str(getattr(config, "pi_bin", "pi") or "pi").strip(),
            "--provider",
            provider,
            "--model",
            model,
            "--mode",
            "text",
            "--print",
        ]
        args.extend(self._build_session_args(config, session_key))
        if include_no_context_files:
            args.append("--no-context-files")
        if tools_mode in {"none", "no_tools", "disabled", "off"}:
            args.append("--no-tools")
        elif tools_mode in {"no_builtin", "no_builtin_tools"}:
            args.append("--no-builtin-tools")
        elif tools_mode in {"allowlist", "tools"} and tools_allowlist:
            args.extend(["--tools", tools_allowlist])
        elif tools_mode not in {"", "default", "all"}:
            raise RuntimeError(f"Unsupported Pi tools mode: {tools_mode}")
        if extra_args:
            args.extend(shlex.split(extra_args))
        args.append(prompt)
        return args

    def _safe_session_filename(self, session_key: str) -> str:
        digest = hashlib.sha256(session_key.encode("utf-8")).hexdigest()[:12]
        label = re.sub(r"[^A-Za-z0-9._-]+", "_", session_key).strip("._-")
        if not label:
            label = "telegram_scope"
        return f"{label[:80]}-{digest}.jsonl"

    def _build_session_args(self, config, session_key: Optional[str]) -> list[str]:
        mode = str(getattr(config, "pi_session_mode", "none") or "none").strip().lower()
        if mode in {"", "none", "off", "disabled", "no_session"}:
            return ["--no-session"]
        if mode not in {"telegram_scope", "scope", "session_key"}:
            raise RuntimeError(f"Unsupported Pi session mode: {mode}")
        if not session_key:
            return ["--no-session"]
        configured_dir = str(getattr(config, "pi_session_dir", "") or "").strip()
        base_dir = Path(configured_dir).expanduser() if configured_dir else Path.home() / ".pi" / "agent" / "telegram-sessions"
        session_path = base_dir / self._safe_session_filename(session_key)
        return ["--session-dir", str(base_dir), "--session", str(session_path)]

    def _build_remote_command(self, config, prompt: str) -> str:
        timeout = int(getattr(config, "pi_request_timeout_seconds", 180))
        remote_cwd = str(getattr(config, "pi_remote_cwd", "/tmp") or "/tmp").strip()
        args = ["timeout", str(timeout)] + self._build_pi_args(
            config,
            prompt,
            include_no_context_files=True,
            session_key=None,
        )

        quoted = " ".join(shlex.quote(part) for part in args)
        if remote_cwd:
            return f"cd {shlex.quote(remote_cwd)} && {quoted}"
        return quoted

    def _run_pi_ssh(
        self,
        config,
        prompt: str,
        cancel_event: Optional[threading.Event],
    ) -> str:
        timeout = int(getattr(config, "pi_request_timeout_seconds", 180))
        ssh_host = str(getattr(config, "pi_ssh_host", "server4-beast")).strip() or "server4-beast"
        process = subprocess.Popen(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                ssh_host,
                self._build_remote_command(config, prompt),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout + 10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
            raise
        if cancel_event is not None and cancel_event.is_set():
            raise ExecutorCancelledError("Pi request canceled by user.")
        if process.returncode != 0:
            raise RuntimeError((stderr or stdout or "Pi SSH transport failed.").strip())
        return stdout.strip()

    def _local_ollama_tunnel_healthy(self, port: int) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                return True
        except OSError:
            return False

    def _ensure_local_ollama_tunnel(self, config) -> None:
        enabled = bool(getattr(config, "pi_ollama_tunnel_enabled", True))
        if not enabled:
            return
        port = int(getattr(config, "pi_ollama_tunnel_local_port", 11435))
        if self._local_ollama_tunnel_healthy(port):
            return
        ssh_host = str(getattr(config, "pi_ssh_host", "server4-beast")).strip() or "server4-beast"
        remote_host = str(getattr(config, "pi_ollama_tunnel_remote_host", "127.0.0.1") or "127.0.0.1").strip()
        remote_port = int(getattr(config, "pi_ollama_tunnel_remote_port", 11434))
        tunnel_spec = f"127.0.0.1:{port}:{remote_host}:{remote_port}"
        completed = subprocess.run(
            [
                "ssh",
                "-fN",
                "-o",
                "ExitOnForwardFailure=yes",
                "-o",
                "BatchMode=yes",
                "-L",
                tunnel_spec,
                ssh_host,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if completed.returncode != 0 and not self._local_ollama_tunnel_healthy(port):
            raise RuntimeError(
                completed.stderr.strip()
                or completed.stdout.strip()
                or f"failed to start Pi Ollama tunnel on port {port}"
            )
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self._local_ollama_tunnel_healthy(port):
                return
            time.sleep(0.1)
        raise RuntimeError(f"Pi Ollama tunnel did not become ready on port {port}")

    def _run_pi_local(
        self,
        config,
        prompt: str,
        session_key: Optional[str],
        cancel_event: Optional[threading.Event],
    ) -> str:
        timeout = int(getattr(config, "pi_request_timeout_seconds", 180))
        self._ensure_local_ollama_tunnel(config)
        cwd = str(getattr(config, "pi_local_cwd", "") or "").strip() or None
        cmd = self._build_pi_args(
            config,
            prompt,
            include_no_context_files=False,
            session_key=session_key,
        )
        env = os.environ.copy()
        tunnel_port = int(getattr(config, "pi_ollama_tunnel_local_port", 11435))
        env.setdefault("OLLAMA_HOST", f"http://127.0.0.1:{tunnel_port}")
        process = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout + 10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
            raise
        if cancel_event is not None and cancel_event.is_set():
            raise ExecutorCancelledError("Pi request canceled by user.")
        if process.returncode != 0:
            raise RuntimeError((stderr or stdout or "Pi local runner failed.").strip())
        return stdout.strip()

    def run(
        self,
        config,
        prompt: str,
        thread_id: Optional[str],
        session_key: Optional[str] = None,
        channel_name: Optional[str] = None,
        actor_chat_id: Optional[int] = None,
        actor_user_id: Optional[int] = None,
        image_path: Optional[str] = None,
        image_paths: Optional[list[str]] = None,
        progress_callback: Optional[ProgressCallback] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> subprocess.CompletedProcess[str]:
        del thread_id, channel_name, actor_chat_id, actor_user_id, progress_callback
        if image_path or image_paths:
            return self._completed_process_with_output(
                "Pi is configured for text-only bridge requests right now. Use `/engine codex` for image or file-heavy work."
            )
        try:
            if cancel_event is not None and cancel_event.is_set():
                raise ExecutorCancelledError("Pi request canceled by user.")
            runner = str(getattr(config, "pi_runner", "ssh") or "ssh").strip().lower()
            if runner in {"local", "server3"}:
                output = self._run_pi_local(config, prompt, session_key, cancel_event)
            elif runner in {"ssh", "server4"}:
                output = self._run_pi_ssh(config, prompt, cancel_event)
            else:
                raise RuntimeError(f"Unsupported Pi runner: {runner}")
            return self._completed_process_with_output(output)
        except ExecutorCancelledError:
            raise
        except subprocess.TimeoutExpired:
            raise
        except (RuntimeError, OSError, ValueError) as exc:
            return self._completed_process_with_output(f"Pi request failed: {exc}")


class MavaliEthEngineAdapter:
    engine_name = "mavali_eth"
    _CONFIRM_INVITE_RE = re.compile(r"reply\s+`?confirm`?\s+to\s+execute", re.IGNORECASE)

    def _looks_like_help_text(self, text: str, expected_help: str) -> bool:
        normalized = str(text or "").strip()
        if normalized == expected_help:
            return True
        return normalized.startswith("I can show your wallet address") and "Examples:" in normalized

    def _invites_confirmation(self, text: str) -> bool:
        return self._CONFIRM_INVITE_RE.search(str(text or "")) is not None

    def _has_live_pending_action(self, service, session_key: str) -> bool:
        return (
            service.store.get_pending_action_envelope(session_key, now=service._now()) is not None
            or service.store.get_pending_action(session_key, now=service._now()) is not None
        )

    def _completed_process_with_output(
        self,
        *,
        thread_id: Optional[str],
        output: str,
    ) -> subprocess.CompletedProcess[str]:
        stdout = str(output or "").strip()
        if thread_id:
            stdout = f"THREAD_ID={thread_id}\nOUTPUT_BEGIN\n{stdout}"
        return subprocess.CompletedProcess(
            args=["mavali_eth"],
            returncode=0,
            stdout=stdout,
            stderr="",
        )

    def run(
        self,
        config,
        prompt: str,
        thread_id: Optional[str],
        session_key: Optional[str] = None,
        channel_name: Optional[str] = None,
        actor_chat_id: Optional[int] = None,
        actor_user_id: Optional[int] = None,
        image_path: Optional[str] = None,
        image_paths: Optional[list[str]] = None,
        progress_callback: Optional[ProgressCallback] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> subprocess.CompletedProcess[str]:
        codex_fallback = CodexEngineAdapter()
        src_root = Path(__file__).resolve().parents[1]
        if str(src_root) not in sys.path:
            sys.path.insert(0, str(src_root))
        try:
            from mavali_eth.config import MavaliEthConfig
            from mavali_eth.service import MavaliEthService
        except ImportError as exc:
            return subprocess.CompletedProcess(
                args=["mavali_eth"],
                returncode=0,
                stdout=f"mavali_eth runtime is unavailable: {exc}",
                stderr="",
            )

        if image_path or image_paths:
            return codex_fallback.run(
                config=config,
                prompt=prompt,
                thread_id=thread_id,
                session_key=session_key,
                channel_name=channel_name,
                actor_chat_id=actor_chat_id,
                actor_user_id=actor_user_id,
                image_path=image_path,
                image_paths=image_paths,
                progress_callback=progress_callback,
                cancel_event=cancel_event,
            )

        try:
            runtime_config = MavaliEthConfig.from_env(getattr(config, "state_dir", None))
            service = MavaliEthService(runtime_config)
            resolved_session_key = session_key or f"{channel_name or 'telegram'}:default"
            output = service.handle_prompt(
                resolved_session_key,
                prompt,
                actor_chat_id=actor_chat_id,
                actor_user_id=actor_user_id,
            )
            if self._looks_like_help_text(output, service.wallet_queries.help_message()):
                fallback_result = codex_fallback.run(
                    config=config,
                    prompt=prompt,
                    thread_id=thread_id,
                    session_key=session_key,
                    channel_name=channel_name,
                    actor_chat_id=actor_chat_id,
                    actor_user_id=actor_user_id,
                    image_path=image_path,
                    image_paths=image_paths,
                    progress_callback=progress_callback,
                    cancel_event=cancel_event,
                )
                fallback_thread_id, fallback_output = parse_executor_output(fallback_result.stdout or "")
                if self._invites_confirmation(fallback_output) and not self._has_live_pending_action(
                    service,
                    resolved_session_key,
                ):
                    return self._completed_process_with_output(
                        thread_id=fallback_thread_id,
                        output=(
                            "I did not actually stage a pending Mavali ETH action, so `confirm` would do nothing. "
                            "Use a currently supported exact command, or implement the missing action path before "
                            "advertising confirmation."
                        ),
                    )
                return fallback_result
        except (ExecutorCancelledError, subprocess.TimeoutExpired):
            raise
        except Exception as exc:
            output = str(exc) or "mavali_eth execution failed."

        return self._completed_process_with_output(thread_id=None, output=output)
