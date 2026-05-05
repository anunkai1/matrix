import base64
import hashlib
import json
import mimetypes
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional
from urllib import error as urllib_error
from urllib import request as urllib_request

from telegram_bridge.engines._base import (
    CompletedProcessOutputMixin,
    ProgressCallback,
    _completed_process_with_output,
    _run_blocking_with_cancel,
)
from telegram_bridge.executor import ExecutorCancelledError


class VeniceEngineAdapter(CompletedProcessOutputMixin):
    engine_name = "venice"

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
