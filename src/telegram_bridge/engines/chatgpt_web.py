import json
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

from telegram_bridge.engines._base import (
    CompletedProcessOutputMixin,
    ProgressCallback,
    _communicate_process_with_cancel,
    _completed_process_with_output,
)
from telegram_bridge.executor import ExecutorCancelledError


class ChatGPTWebEngineAdapter(CompletedProcessOutputMixin):
    engine_name = "chatgptweb"

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
