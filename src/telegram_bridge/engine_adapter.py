import base64
import json
import mimetypes
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


def _communicate_process_with_cancel(
    process: subprocess.Popen[str],
    *,
    timeout: int,
    cancel_event: Optional[threading.Event],
    cancel_message: str,
    input_text: Optional[str] = None,
) -> tuple[str, str]:
    result: dict[str, object] = {}
    done = threading.Event()

    def _worker() -> None:
        try:
            stdout, stderr = process.communicate(input=input_text, timeout=timeout)
            result["stdout"] = stdout
            result["stderr"] = stderr
        except BaseException as exc:
            result["exception"] = exc
        finally:
            done.set()

    worker = threading.Thread(target=_worker, daemon=True)
    worker.start()
    while not done.wait(0.1):
        if cancel_event is not None and cancel_event.is_set():
            process.kill()
            done.wait(5)
            raise ExecutorCancelledError(cancel_message)

    exc = result.get("exception")
    if isinstance(exc, BaseException):
        raise exc
    stdout = result.get("stdout")
    stderr = result.get("stderr")
    return str(stdout or ""), str(stderr or "")


def _run_blocking_with_cancel(
    func: Callable[[], str],
    *,
    cancel_event: Optional[threading.Event],
    cancel_message: str,
) -> str:
    result: dict[str, object] = {}
    done = threading.Event()

    def _worker() -> None:
        try:
            result["value"] = func()
        except BaseException as exc:
            result["exception"] = exc
        finally:
            done.set()

    worker = threading.Thread(target=_worker, daemon=True)
    worker.start()
    while not done.wait(0.1):
        if cancel_event is not None and cancel_event.is_set():
            raise ExecutorCancelledError(cancel_message)

    exc = result.get("exception")
    if isinstance(exc, BaseException):
        raise exc
    return str(result.get("value") or "")


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
        stdout, stderr = _communicate_process_with_cancel(
            process,
            timeout=timeout + 10,
            cancel_event=cancel_event,
            cancel_message="Gemma request canceled by user.",
            input_text=self._payload(config, prompt),
        )
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
                output = _run_blocking_with_cancel(
                    lambda: self._run_ollama_http(config, prompt),
                    cancel_event=cancel_event,
                    cancel_message="Gemma request canceled by user.",
                )
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


class VeniceEngineAdapter:
    engine_name = "venice"

    def _completed_process_with_output(self, output: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["venice"],
            returncode=0,
            stdout=f"{OUTPUT_BEGIN_MARKER}\n{str(output or '').strip()}",
            stderr="",
        )

    def _api_key(self, config) -> str:
        api_key = str(getattr(config, "venice_api_key", "") or "").strip()
        if not api_key:
            raise RuntimeError("VENICE_API_KEY is required")
        return api_key

    def _base_url(self, config) -> str:
        base_url = str(getattr(config, "venice_base_url", "https://api.venice.ai/api/v1") or "").strip()
        if not base_url:
            raise RuntimeError("VENICE_BASE_URL is required")
        return base_url.rstrip("/")

    def _request_headers(self, config) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key(config)}",
            "Content-Type": "application/json",
        }

    def _image_data_url(self, image_path: str) -> str:
        path = Path(image_path)
        if not path.is_file():
            raise RuntimeError(f"Venice image file not found: {image_path}")
        mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    def _build_messages(
        self,
        prompt: str,
        *,
        image_path: Optional[str] = None,
        image_paths: Optional[list[str]] = None,
    ) -> list[dict[str, object]]:
        normalized_image_paths: list[str] = []
        for candidate in image_paths or []:
            if candidate and candidate not in normalized_image_paths:
                normalized_image_paths.append(candidate)
        if image_path and image_path not in normalized_image_paths:
            normalized_image_paths.insert(0, image_path)

        if not normalized_image_paths:
            return [{"role": "user", "content": prompt}]

        content_parts: list[dict[str, object]] = []
        text_prompt = prompt.strip() or "Describe the attached image(s)."
        content_parts.append({"type": "text", "text": text_prompt})
        for candidate in normalized_image_paths:
            content_parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": self._image_data_url(candidate)},
                }
            )
        return [{"role": "user", "content": content_parts}]

    def _payload(
        self,
        config,
        prompt: str,
        *,
        image_path: Optional[str] = None,
        image_paths: Optional[list[str]] = None,
    ) -> str:
        payload = {
            "model": getattr(config, "venice_model", "mistral-31-24b"),
            "stream": False,
            "temperature": float(getattr(config, "venice_temperature", 0.2)),
            "messages": self._build_messages(
                prompt,
                image_path=image_path,
                image_paths=image_paths,
            ),
        }
        return json.dumps(payload)

    def _extract_venice_content(self, raw: str) -> str:
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Venice returned invalid JSON: {exc}") from exc
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("Venice response did not contain choices.")
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise RuntimeError("Venice response choice was not an object.")
        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise RuntimeError("Venice response did not contain an assistant message.")
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            text_parts: list[str] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") != "text":
                    continue
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    text_parts.append(text.strip())
            if text_parts:
                return "\n".join(text_parts).strip()
        tool_calls = message.get("tool_calls")
        if tool_calls:
            return json.dumps(tool_calls, ensure_ascii=False)
        raise RuntimeError("Venice response did not contain text content.")

    def _run_venice_http(
        self,
        config,
        prompt: str,
        *,
        image_path: Optional[str] = None,
        image_paths: Optional[list[str]] = None,
    ) -> str:
        base_url = self._base_url(config)
        timeout = int(getattr(config, "venice_request_timeout_seconds", 180))
        req = urllib_request.Request(
            f"{base_url}/chat/completions",
            data=self._payload(
                config,
                prompt,
                image_path=image_path,
                image_paths=image_paths,
            ).encode("utf-8"),
            headers=self._request_headers(config),
            method="POST",
        )
        with urllib_request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
        return self._extract_venice_content(raw)

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
        try:
            if cancel_event is not None and cancel_event.is_set():
                raise ExecutorCancelledError("Venice request canceled by user.")
            output = _run_blocking_with_cancel(
                lambda: self._run_venice_http(
                    config,
                    prompt,
                    image_path=image_path,
                    image_paths=image_paths,
                ),
                cancel_event=cancel_event,
                cancel_message="Venice request canceled by user.",
            )
            return self._completed_process_with_output(output)
        except ExecutorCancelledError:
            raise
        except subprocess.TimeoutExpired:
            raise
        except (RuntimeError, OSError, urllib_error.URLError) as exc:
            return self._completed_process_with_output(f"Venice request failed: {exc}")


class ChatGPTWebEngineAdapter:
    engine_name = "chatgptweb"

    def _completed_process_with_output(self, output: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["chatgptweb"],
            returncode=0,
            stdout=f"{OUTPUT_BEGIN_MARKER}\n{str(output or '').strip()}",
            stderr="",
        )

    def _bridge_script(self, config) -> str:
        configured = str(getattr(config, "chatgpt_web_bridge_script", "") or "").strip()
        if configured:
            return configured
        return str(Path(__file__).resolve().parents[2] / "ops" / "chatgpt_web_bridge.py")

    def _build_command(self, config) -> list[str]:
        cmd = [
            str(getattr(config, "chatgpt_web_python_bin", sys.executable) or sys.executable),
            self._bridge_script(config),
            "--base-url",
            str(getattr(config, "chatgpt_web_browser_brain_url", "http://127.0.0.1:47831") or "http://127.0.0.1:47831"),
            "--service-name",
            str(getattr(config, "chatgpt_web_browser_brain_service", "server3-browser-brain.service") or "server3-browser-brain.service"),
            "--request-timeout",
            str(int(getattr(config, "chatgpt_web_request_timeout_seconds", 30) or 30)),
            "ask",
            "--url",
            str(getattr(config, "chatgpt_web_url", "https://chatgpt.com/") or "https://chatgpt.com/"),
            "--ready-timeout",
            str(int(getattr(config, "chatgpt_web_ready_timeout_seconds", 45) or 45)),
            "--response-timeout",
            str(int(getattr(config, "chatgpt_web_response_timeout_seconds", 180) or 180)),
            "--poll-seconds",
            str(float(getattr(config, "chatgpt_web_poll_seconds", 3.0) or 3.0)),
            "--json",
        ]
        if bool(getattr(config, "chatgpt_web_start_service", False)):
            cmd.append("--start-service")
        return cmd

    def _parse_answer(self, stdout: str) -> str:
        raw = str(stdout or "").strip()
        if not raw:
            return ""
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return raw
        if isinstance(payload, dict):
            answer = payload.get("answer")
            if isinstance(answer, str):
                return answer.strip()
        return raw

    def _run_bridge(
        self,
        config,
        prompt: str,
        cancel_event: Optional[threading.Event],
    ) -> str:
        timeout = (
            int(getattr(config, "chatgpt_web_ready_timeout_seconds", 45) or 45)
            + int(getattr(config, "chatgpt_web_response_timeout_seconds", 180) or 180)
            + int(getattr(config, "chatgpt_web_request_timeout_seconds", 30) or 30)
            + 20
        )
        process = subprocess.Popen(
            self._build_command(config),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr = _communicate_process_with_cancel(
            process,
            timeout=timeout,
            cancel_event=cancel_event,
            cancel_message="ChatGPT web request canceled by user.",
            input_text=prompt,
        )
        if cancel_event is not None and cancel_event.is_set():
            raise ExecutorCancelledError("ChatGPT web request canceled by user.")
        if process.returncode != 0:
            raise RuntimeError((stderr or stdout or "ChatGPT web bridge failed.").strip())
        answer = self._parse_answer(stdout)
        if not answer:
            raise RuntimeError("ChatGPT web bridge returned an empty response.")
        return answer

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
                "ChatGPT web is configured for text-only requests right now. Use `/engine codex` for image or file-heavy work."
            )
        try:
            if cancel_event is not None and cancel_event.is_set():
                raise ExecutorCancelledError("ChatGPT web request canceled by user.")
            output = self._run_bridge(config, prompt, cancel_event)
            return self._completed_process_with_output(output)
        except ExecutorCancelledError:
            raise
        except subprocess.TimeoutExpired:
            raise
        except (RuntimeError, OSError, ValueError) as exc:
            return self._completed_process_with_output(f"ChatGPT web request failed: {exc}")


class PiEngineAdapter:
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

    def _completed_process_with_output(self, output: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["pi"],
            returncode=0,
            stdout=f"{OUTPUT_BEGIN_MARKER}\n{str(output or '').strip()}",
            stderr="",
        )

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
        env.setdefault("OLLAMA_HOST", f"http://127.0.0.1:{tunnel_port}")
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
        env.setdefault("OLLAMA_HOST", f"http://127.0.0.1:{tunnel_port}")
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
