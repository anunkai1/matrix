import json
import subprocess
import threading
from typing import Optional
from urllib import error as urllib_error
from urllib import request as urllib_request

from telegram_bridge.engines._base import (
    CompletedProcessOutputMixin,
    ProgressCallback,
    _communicate_process_with_cancel,
    _completed_process_with_output,
    _run_blocking_with_cancel,
)
from telegram_bridge.executor import ExecutorCancelledError


class GemmaEngineAdapter(CompletedProcessOutputMixin):
    engine_name = "gemma"

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
