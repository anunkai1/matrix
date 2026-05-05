import base64
import hashlib
import json
import mimetypes
import os
import re
import shlex
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional
from urllib import request as urllib_request

from telegram_bridge.engines._base import (
    CompletedProcessOutputMixin,
    ProgressCallback,
    _communicate_process_with_cancel,
    _completed_process_with_output,
    _run_blocking_with_cancel,
)
from telegram_bridge.executor import ExecutorCancelledError
class PiEngineAdapter(CompletedProcessOutputMixin):
    engine_name = "pi"
    _RPC_EMPTY_OUTPUT_MARKER = "Pi RPC did not produce any output"
    _IMAGE_URL_ERROR_MARKERS = ("unknown variant image_url", "image_url", "expected text")
    _IMAGE_CAPABLE_MODEL_SUGGESTIONS = (
        "claude-sonnet-4-5",
        "gemini-3-flash-preview",
        "grok-41-fast",
        "qwen-3-6-plus",
        "google-gemma-4-26b-a4b-it",
        "kimi-k2-6",
    )

    @staticmethod
    def _pi_models_path(config) -> Path:
        home = Path.home()
        return home / ".pi" / "agent" / "models.json"

    def _model_supports_images(self, config) -> bool:
        provider = str(getattr(config, "pi_provider", "ollama") or "ollama").strip()
        if provider.strip().lower() in {"ollama_ssh", "ssh"}:
            provider = "ollama"
        model = str(getattr(config, "pi_model", "") or "").strip()
        if not model:
            return True
        models_path = self._pi_models_path(config)
        if not models_path.is_file():
            return True
        try:
            data = json.loads(models_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return True
        providers = data.get("providers")
        if not isinstance(providers, dict):
            return True
        provider_cfg = providers.get(provider)
        if not isinstance(provider_cfg, dict):
            return True
        models = provider_cfg.get("models")
        if not isinstance(models, list):
            return True
        for entry in models:
            if not isinstance(entry, dict):
                continue
            if entry.get("id") == model:
                supported_inputs = entry.get("input")
                if isinstance(supported_inputs, list) and "image" in supported_inputs:
                    return True
                return False
        return True

    def _image_data_url(self, image_path: str) -> dict[str, str]:
        path = Path(image_path)
        if not path.is_file():
            raise RuntimeError(f"Pi image file not found: {image_path}")
        mime_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return {"type": "image", "data": encoded, "mimeType": mime_type}

    def _build_pi_rpc_args(
        self,
        config,
        *,
        include_no_context_files: bool,
        session_key: Optional[str] = None,
    ) -> list[str]:
        provider = str(getattr(config, "pi_provider", "ollama") or "ollama").strip()
        if provider.strip().lower() in {"ollama_ssh", "ssh"}:
            provider = "ollama"
        model = str(getattr(config, "pi_model", "qwen3-coder:30b") or "qwen3-coder:30b").strip()
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
            "rpc",
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
        return args

    def _build_pi_text_args(
        self,
        config,
        *,
        include_no_context_files: bool,
        session_key: Optional[str] = None,
    ) -> list[str]:
        args = self._build_pi_rpc_args(
            config,
            include_no_context_files=include_no_context_files,
            session_key=session_key,
        )
        normalized: list[str] = []
        skip_next = False
        for index, value in enumerate(args):
            if skip_next:
                skip_next = False
                continue
            if value == "--mode" and index + 1 < len(args):
                skip_next = True
                continue
            normalized.append(value)
        normalized.append("--print")
        return normalized

    @staticmethod
    @classmethod
    def clear_scope_session_files(cls, config, scope_key: str) -> int:
        """Archive all Pi session files for a Telegram scope so a fresh session
        starts on the next turn.  Files are renamed with a timestamp suffix
        and moved to the archive directory — nothing is deleted.

        Returns the number of files archived.
        """
        mode = str(getattr(config, "pi_session_mode", "none") or "none").strip().lower()
        if mode in {"", "none", "off", "disabled", "no_session"}:
            return 0
        configured_dir = str(getattr(config, "pi_session_dir", "") or "").strip()
        base_dir = Path(configured_dir).expanduser() if configured_dir else Path.home() / ".pi" / "agent" / "telegram-sessions"
        if not base_dir.is_dir():
            return 0
        scope_label = re.sub(r"[^A-Za-z0-9._-]+", "_", scope_key).strip("._-")
        if not scope_label:
            return 0
        archive_dir = base_dir / ".archive"
        timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        archived = 0
        for f in list(base_dir.glob(f"{scope_label}*.jsonl")):
            if f.parent == archive_dir:
                continue
            archive_dir.mkdir(parents=True, exist_ok=True)
            archive_path = archive_dir / f"{f.stem}.reset.{timestamp}{f.suffix}"
            try:
                f.rename(archive_path)
                archived += 1
            except OSError:
                pass
        return archived

    def _safe_session_filename(self, session_key: str) -> str:
        digest = hashlib.sha256(session_key.encode("utf-8")).hexdigest()[:12]
        label = re.sub(r"[^A-Za-z0-9._-]+", "_", session_key).strip("._-")
        if not label:
            label = "telegram_scope"
        return f"{label[:80]}-{digest}.jsonl"

    def _resolve_session_path(self, config, session_key: str) -> Path:
        configured_dir = str(getattr(config, "pi_session_dir", "") or "").strip()
        base_dir = Path(configured_dir).expanduser() if configured_dir else Path.home() / ".pi" / "agent" / "telegram-sessions"
        scoped_session_key = self._provider_scoped_session_key(config, session_key)
        return base_dir / self._safe_session_filename(scoped_session_key)

    def _provider_scoped_session_key(self, config, session_key: str) -> str:
        provider = str(getattr(config, "pi_provider", "ollama") or "ollama").strip().lower() or "ollama"
        model = str(getattr(config, "pi_model", "qwen3-coder:30b") or "qwen3-coder:30b").strip() or "qwen3-coder:30b"
        return f"{session_key}|provider:{provider}|model:{model}"

    def _sanitize_session_images(self, config, session_key: str) -> None:
        """Remove image content blocks from session file for text-only models.

        Pi replays the entire session history (JSONL file) to the API on each
        turn.  If a past turn included an image and the model is text-only,
        the API rejects the replayed image_url content.  This strips image
        blocks from user messages so the session can be replayed cleanly.
        """
        try:
            session_path = self._resolve_session_path(config, session_key)
        except Exception:
            return
        if not session_path.is_file():
            return
        try:
            lines = session_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        sanitized_lines: list[str] = []
        changed = False
        for line in lines:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                sanitized_lines.append(line)
                continue
            if entry.get("type") != "message":
                sanitized_lines.append(line)
                continue
            message = entry.get("message")
            if not isinstance(message, dict):
                sanitized_lines.append(line)
                continue
            if message.get("role") != "user":
                sanitized_lines.append(line)
                continue
            content = message.get("content")
            if not isinstance(content, list):
                sanitized_lines.append(line)
                continue
            filtered = [block for block in content if block.get("type") != "image"]
            if len(filtered) == len(content):
                sanitized_lines.append(line)
                continue
            if not filtered:
                changed = True
                continue
            entry["message"]["content"] = filtered
            sanitized_lines.append(json.dumps(entry, ensure_ascii=False))
            changed = True
        if not changed:
            return
        try:
            raw = "\n".join(sanitized_lines) + ("\n" if sanitized_lines else "")
            session_path.write_text(raw, encoding="utf-8")
        except OSError:
            pass

    def _session_archive_dir(self, config, base_dir: Path) -> Path:
        configured_dir = str(getattr(config, "pi_session_archive_dir", "") or "").strip()
        if configured_dir:
            return Path(configured_dir).expanduser()
        return base_dir / ".archive"

    def _cleanup_session_archive_dir(self, archive_dir: Path, retention_seconds: int) -> None:
        if retention_seconds <= 0 or not archive_dir.exists():
            return
        cutoff = time.time() - retention_seconds
        for archive_path in archive_dir.glob("*.rotated.*.jsonl"):
            try:
                stat = archive_path.stat()
            except OSError:
                continue
            if stat.st_mtime < cutoff:
                try:
                    archive_path.unlink()
                except OSError:
                    continue

    def _rotate_session_file_if_needed(self, config, base_dir: Path, session_path: Path) -> None:
        max_bytes = int(getattr(config, "pi_session_max_bytes", 0) or 0)
        max_age_seconds = int(getattr(config, "pi_session_max_age_seconds", 0) or 0)
        retention_seconds = int(getattr(config, "pi_session_archive_retention_seconds", 0) or 0)
        archive_dir = self._session_archive_dir(config, base_dir)
        if not session_path.exists():
            self._cleanup_session_archive_dir(archive_dir, retention_seconds)
            return
        try:
            stat = session_path.stat()
        except OSError:
            return
        should_rotate = False
        if max_bytes > 0 and stat.st_size >= max_bytes:
            should_rotate = True
        if max_age_seconds > 0 and (time.time() - stat.st_mtime) >= max_age_seconds:
            should_rotate = True
        if should_rotate:
            archive_dir.mkdir(parents=True, exist_ok=True)
            timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
            archive_path = archive_dir / f"{session_path.stem}.rotated.{timestamp}{session_path.suffix}"
            try:
                session_path.replace(archive_path)
            except OSError:
                pass
        self._cleanup_session_archive_dir(archive_dir, retention_seconds)

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
        scoped_session_key = self._provider_scoped_session_key(config, session_key)
        session_path = base_dir / self._safe_session_filename(scoped_session_key)
        self._rotate_session_file_if_needed(config, base_dir, session_path)
        return ["--session-dir", str(base_dir), "--session", str(session_path)]

    def _build_rpc_prompt_json(
        self,
        prompt: str,
        *,
        image_path: Optional[str] = None,
        image_paths: Optional[list[str]] = None,
    ) -> str:
        normalized_image_paths: list[str] = []
        for candidate in image_paths or []:
            if candidate and candidate not in normalized_image_paths:
                normalized_image_paths.append(candidate)
        if image_path and image_path not in normalized_image_paths:
            normalized_image_paths.insert(0, image_path)

        if not normalized_image_paths:
            return json.dumps({"type": "prompt", "message": prompt})

        return json.dumps({
            "type": "prompt",
            "message": prompt.strip() or "Describe the attached image(s).",
            "images": [self._image_data_url(p) for p in normalized_image_paths],
        })

    def _extract_rpc_response(self, stdout_lines: list[str]) -> str:
        agent_end_event = None
        text_parts: list[str] = []
        for line in stdout_lines:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                event = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "agent_end":
                agent_end_event = event
                break
            if event.get("type") == "message_update":
                delta = event.get("assistantMessageEvent", {})
                if delta.get("type") == "text_delta":
                    text_parts.append(str(delta.get("delta", "")))
        if agent_end_event and isinstance(agent_end_event, dict):
            messages = agent_end_event.get("messages") or []
            for msg in reversed(messages):
                if isinstance(msg, dict) and msg.get("role") == "assistant":
                    content = msg.get("content") or []
                    for block in reversed(content if isinstance(content, list) else [content]):
                        if isinstance(block, dict) and block.get("type") == "text":
                            text = str(block.get("text", "")).strip()
                            if text:
                                return text
        fallback = "".join(text_parts).strip()
        if not fallback:
            raise RuntimeError(
                "Pi RPC did not produce any output (received %d lines, agent_end=%s)"
                % (len(stdout_lines), "yes" if agent_end_event else "no")
            )
        return fallback

    def _should_retry_pi_text_mode(
        self,
        exc: RuntimeError,
        *,
        image_path: Optional[str] = None,
        image_paths: Optional[list[str]] = None,
    ) -> bool:
        if image_path or image_paths:
            return False
        return str(exc).startswith(self._RPC_EMPTY_OUTPUT_MARKER)

    def _run_pi_text_local(
        self,
        config,
        prompt: str,
        session_key: Optional[str],
    ) -> str:
        cwd = str(getattr(config, "pi_local_cwd", "") or "").strip() or None
        cmd = self._build_pi_text_args(
            config,
            include_no_context_files=False,
            session_key=session_key,
        )
        env = os.environ.copy()
        tunnel_port = int(getattr(config, "pi_ollama_tunnel_local_port", 11435))
        env["OLLAMA_HOST"] = f"http://127.0.0.1:{tunnel_port}"
        completed = subprocess.run(
            cmd + [prompt],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=int(getattr(config, "pi_request_timeout_seconds", 180)),
        )
        if completed.returncode != 0:
            raise RuntimeError(
                completed.stderr.strip()
                or completed.stdout.strip()
                or "Pi text-mode local runner failed."
            )
        output = (completed.stdout or "").strip()
        if not output:
            raise RuntimeError("Pi text-mode local runner produced no output.")
        return output

    def _run_pi_text_ssh(
        self,
        config,
        prompt: str,
    ) -> str:
        timeout = int(getattr(config, "pi_request_timeout_seconds", 180))
        ssh_host = str(getattr(config, "pi_ssh_host", "server4-beast")).strip() or "server4-beast"
        remote_cwd = str(getattr(config, "pi_remote_cwd", "/tmp") or "/tmp").strip()
        args = ["timeout", str(timeout)] + self._build_pi_text_args(
            config,
            include_no_context_files=True,
            session_key=None,
        )
        quoted = " ".join(shlex.quote(part) for part in args + [prompt])
        remote_command = f"cd {shlex.quote(remote_cwd)} && {quoted}" if remote_cwd else quoted
        completed = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", ssh_host, remote_command],
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
        output = (completed.stdout or "").strip()
        if not output:
            raise RuntimeError("Pi text-mode SSH runner produced no output.")
        return output

    def _read_rpc_stdout(
        self,
        process: subprocess.Popen[str],
        cancel_event: Optional[threading.Event],
        timeout: int,
    ) -> list[str]:
        lines: list[str] = []
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            if cancel_event is not None and cancel_event.is_set():
                process.kill()
                raise ExecutorCancelledError("Pi request canceled by user.")
            line = process.stdout.readline() if process.stdout else ""
            if not line:
                if process.poll() is not None:
                    break
                time.sleep(0.05)
                continue
            lines.append(line)
            try:
                event = json.loads(line.strip())
            except json.JSONDecodeError:
                continue
            if event.get("type") == "agent_end":
                break
        return lines

    def _build_remote_command(self, config) -> str:
        timeout = int(getattr(config, "pi_request_timeout_seconds", 180))
        remote_cwd = str(getattr(config, "pi_remote_cwd", "/tmp") or "/tmp").strip()
        args = ["timeout", str(timeout)] + self._build_pi_rpc_args(
            config,
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
        *,
        image_path: Optional[str] = None,
        image_paths: Optional[list[str]] = None,
    ) -> str:
        timeout = int(getattr(config, "pi_request_timeout_seconds", 180))
        prompt_json = self._build_rpc_prompt_json(
            prompt,
            image_path=image_path,
            image_paths=image_paths,
        )
        ssh_host = str(getattr(config, "pi_ssh_host", "server4-beast")).strip() or "server4-beast"
        process = subprocess.Popen(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                ssh_host,
                self._build_remote_command(config),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            process.stdin.write(prompt_json + "\n")
            process.stdin.flush()
            stdout_lines = self._read_rpc_stdout(process, cancel_event, timeout + 10)
            process.stdin.close()
            process.stdin = None
            _, stderr = process.communicate(timeout=5)
        except BaseException:
            process.kill()
            raise
        if cancel_event is not None and cancel_event.is_set():
            raise ExecutorCancelledError("Pi request canceled by user.")
        if process.returncode != 0:
            raise RuntimeError(((stderr or "") + "\nstdout_lines=%d" % len(stdout_lines) or "".join(stdout_lines) or "Pi SSH transport failed.").strip())
        try:
            return self._extract_rpc_response(stdout_lines)
        except RuntimeError as exc:
            if not self._should_retry_pi_text_mode(
                exc,
                image_path=image_path,
                image_paths=image_paths,
            ):
                raise
            return self._run_pi_text_ssh(config, prompt)

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

    def _pi_provider_uses_ollama_tunnel(self, config) -> bool:
        provider = (
            str(getattr(config, "pi_provider", "ollama") or "ollama")
            .strip()
            .lower()
        )
        return provider in {"ollama", "ollama_ssh", "ssh"}

    def _run_pi_local(
        self,
        config,
        prompt: str,
        session_key: Optional[str],
        cancel_event: Optional[threading.Event],
        *,
        image_path: Optional[str] = None,
        image_paths: Optional[list[str]] = None,
    ) -> str:
        timeout = int(getattr(config, "pi_request_timeout_seconds", 180))
        if self._pi_provider_uses_ollama_tunnel(config):
            self._ensure_local_ollama_tunnel(config)
        prompt_json = self._build_rpc_prompt_json(
            prompt,
            image_path=image_path,
            image_paths=image_paths,
        )
        cwd = str(getattr(config, "pi_local_cwd", "") or "").strip() or None
        cmd = self._build_pi_rpc_args(
            config,
            include_no_context_files=False,
            session_key=session_key,
        )
        env = os.environ.copy()
        tunnel_port = int(getattr(config, "pi_ollama_tunnel_local_port", 11435))
        env["OLLAMA_HOST"] = f"http://127.0.0.1:{tunnel_port}"
        process = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        try:
            process.stdin.write(prompt_json + "\n")
            process.stdin.flush()
            stdout_lines = self._read_rpc_stdout(process, cancel_event, timeout + 10)
            process.stdin.close()
            process.stdin = None
            _, stderr = process.communicate(timeout=5)
        except BaseException:
            process.kill()
            raise
        if cancel_event is not None and cancel_event.is_set():
            raise ExecutorCancelledError("Pi request canceled by user.")
        if process.returncode != 0:
            raise RuntimeError(((stderr or "") + "\nstdout_lines=%d" % len(stdout_lines) or "".join(stdout_lines) or "Pi local runner failed.").strip())
        try:
            return self._extract_rpc_response(stdout_lines)
        except RuntimeError as exc:
            if not self._should_retry_pi_text_mode(
                exc,
                image_path=image_path,
                image_paths=image_paths,
            ):
                raise
            return self._run_pi_text_local(config, prompt, session_key)

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
        if not self._model_supports_images(config):
            if image_path or image_paths:
                model = str(getattr(config, "pi_model", "") or "").strip()
                suggestions = ", ".join(self._IMAGE_CAPABLE_MODEL_SUGGESTIONS)
                return self._completed_process_with_output(
                    f"Model '{model}' is text-only and does not support images. "
                    f"Use /model to switch to an image-capable model. "
                    f"Suggestions: {suggestions}."
                )
            if session_key:
                self._sanitize_session_images(config, session_key)
        try:
            if cancel_event is not None and cancel_event.is_set():
                raise ExecutorCancelledError("Pi request canceled by user.")
            runner = str(getattr(config, "pi_runner", "ssh") or "ssh").strip().lower()
            if runner in {"local", "server3"}:
                output = self._run_pi_local(
                    config,
                    prompt,
                    session_key,
                    cancel_event,
                    image_path=image_path,
                    image_paths=image_paths,
                )
            elif runner in {"ssh", "server4"}:
                output = self._run_pi_ssh(
                    config,
                    prompt,
                    cancel_event,
                    image_path=image_path,
                    image_paths=image_paths,
                )
            else:
                raise RuntimeError(f"Unsupported Pi runner: {runner}")
            return self._completed_process_with_output(output)
        except ExecutorCancelledError:
            raise
        except subprocess.TimeoutExpired:
            raise
        except (RuntimeError, OSError, ValueError) as exc:
            error_msg = str(exc)
            error_lower = error_msg.lower()
            if (
                not image_path
                and not image_paths
                and session_key
                and any(marker in error_lower for marker in self._IMAGE_URL_ERROR_MARKERS)
            ):
                try:
                    model = str(getattr(config, "pi_model", "") or "").strip()
                    runner = str(getattr(config, "pi_runner", "ssh") or "ssh").strip().lower()
                    if runner in {"local", "server3"}:
                        output = self._run_pi_local(config, prompt, None, cancel_event)
                    else:
                        output = self._run_pi_ssh(config, prompt, cancel_event)
                    if self._model_supports_images(config):
                        note = (
                            f"(Session was reset because the previous Pi session for model "
                            f"'{model}' contained image content that the provider could not "
                            f"replay cleanly on this text message.)\n\n"
                            + output
                        )
                    else:
                        note = (
                            f"(Session was reset because the previous Pi session for model "
                            f"'{model}' contained image content, but this model is text-only "
                            f"and cannot replay it. "
                            f"Use /model to switch to an image-capable model.)\n\n"
                            + output
                        )
                    return self._completed_process_with_output(note)
                except Exception:
                    pass
            return self._completed_process_with_output(f"Pi request failed: {exc}")

