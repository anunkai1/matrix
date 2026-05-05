import json
import logging
import mimetypes
import os
import socket
import time
import uuid
from typing import Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from telegram_bridge.structured_logging import emit_event

TELEGRAM_LIMIT = 4096
TELEGRAM_CAPTION_LIMIT = 1024
TELEGRAM_API_DEFAULT_MAX_ATTEMPTS = 3
TELEGRAM_API_MAX_BACKOFF_SECONDS = 10.0
TELEGRAM_TRANSIENT_ERROR_CODES = {429, 500, 502, 503, 504}

class TelegramApiError(RuntimeError):
    def __init__(
        self,
        method: str,
        description: str,
        error_code: Optional[int] = None,
        retry_after_seconds: Optional[float] = None,
    ) -> None:
        self.method = method
        self.description = description
        self.error_code = error_code
        self.retry_after_seconds = retry_after_seconds
        code_text = f"{error_code} " if error_code is not None else ""
        super().__init__(f"Telegram API {method} failed: {code_text}{description}")

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

class TelegramClient:
    def __init__(self, config) -> None:
        self.config = config

    def _api_max_attempts(self) -> int:
        raw = getattr(self.config, "api_max_attempts", TELEGRAM_API_DEFAULT_MAX_ATTEMPTS)
        try:
            parsed = int(raw)
        except Exception:
            parsed = TELEGRAM_API_DEFAULT_MAX_ATTEMPTS
        return max(1, parsed)

    def _api_backoff_base_seconds(self) -> float:
        raw = getattr(self.config, "retry_sleep_seconds", 1.0)
        try:
            parsed = float(raw)
        except Exception:
            parsed = 1.0
        return max(0.05, min(parsed, TELEGRAM_API_MAX_BACKOFF_SECONDS))

    def _is_transient_error(self, exc: Exception) -> bool:
        if isinstance(exc, TelegramApiError):
            return exc.error_code in TELEGRAM_TRANSIENT_ERROR_CODES
        if isinstance(exc, (URLError, TimeoutError, socket.timeout)):
            return True
        return False

    def _compute_backoff_seconds(self, exc: Exception, attempt_index: int) -> float:
        if isinstance(exc, TelegramApiError) and exc.retry_after_seconds is not None:
            return max(0.0, min(exc.retry_after_seconds, TELEGRAM_API_MAX_BACKOFF_SECONDS))
        base = self._api_backoff_base_seconds()
        return min(base * (2**attempt_index), TELEGRAM_API_MAX_BACKOFF_SECONDS)

    def _execute_with_retry(
        self,
        method: str,
        operation,
    ) -> str:
        max_attempts = self._api_max_attempts()
        for attempt_index in range(max_attempts):
            try:
                response_body = operation()
                if attempt_index > 0:
                    emit_event(
                        "bridge.telegram_api_retry_succeeded",
                        fields={
                            "method": method,
                            "attempt": attempt_index + 1,
                            "max_attempts": max_attempts,
                        },
                    )
                return response_body
            except Exception as exc:
                is_last_attempt = attempt_index >= (max_attempts - 1)
                is_transient = self._is_transient_error(exc)
                if is_last_attempt or not is_transient:
                    emit_event(
                        "bridge.telegram_api_failed",
                        level=logging.ERROR,
                        fields={
                            "method": method,
                            "attempt": attempt_index + 1,
                            "max_attempts": max_attempts,
                            "transient": bool(is_transient),
                            "error_type": type(exc).__name__,
                            "error_code": getattr(exc, "error_code", None),
                            "will_retry": False,
                        },
                    )
                    raise
                delay_seconds = self._compute_backoff_seconds(exc, attempt_index)
                emit_event(
                    "bridge.telegram_api_retry_scheduled",
                    level=logging.WARNING,
                    fields={
                        "method": method,
                        "attempt": attempt_index + 1,
                        "next_attempt": attempt_index + 2,
                        "max_attempts": max_attempts,
                        "error_type": type(exc).__name__,
                        "error_code": getattr(exc, "error_code", None),
                        "retry_delay_seconds": delay_seconds,
                    },
                )
                logging.warning(
                    "Telegram API %s transient failure (%s). Retrying in %.2fs (%s/%s).",
                    method,
                    exc,
                    delay_seconds,
                    attempt_index + 1,
                    max_attempts,
                )
                if delay_seconds > 0:
                    time.sleep(delay_seconds)

        raise RuntimeError("unreachable retry state")

    def _request(self, method: str, payload: Dict[str, object]) -> Dict[str, object]:
        def request_once() -> str:
            endpoint = f"{self.config.api_base}/bot{self.config.token}/{method}"
            data = urlencode(payload).encode("utf-8")
            request = Request(endpoint, data=data, method="POST")
            try:
                with urlopen(request, timeout=self.config.poll_timeout_seconds + 10) as response:
                    return response.read().decode("utf-8")
            except HTTPError as exc:
                response_body = ""
                try:
                    response_body = exc.read().decode("utf-8")
                except Exception:
                    response_body = ""
                description, code, retry_after = self._extract_telegram_error(
                    response_body,
                    fallback=f"HTTP {exc.code}",
                )
                raise TelegramApiError(
                    method,
                    description,
                    code or exc.code,
                    retry_after_seconds=retry_after,
                ) from exc

        body = self._execute_with_retry(method, request_once)
        decoded = json.loads(body)
        if not decoded.get("ok"):
            description = str(decoded.get("description", "unknown Telegram error"))
            error_code = decoded.get("error_code")
            parsed_code = int(error_code) if isinstance(error_code, int) else None
            retry_after = self._extract_retry_after(decoded)
            raise TelegramApiError(
                method,
                description,
                parsed_code,
                retry_after_seconds=retry_after,
            )
        return decoded

    def _extract_retry_after(self, decoded: Dict[str, object]) -> Optional[float]:
        parameters = decoded.get("parameters")
        if not isinstance(parameters, dict):
            return None
        retry_after = parameters.get("retry_after")
        if isinstance(retry_after, (int, float)):
            return float(retry_after)
        return None

    def _extract_telegram_error(
        self,
        body: str,
        fallback: str,
    ) -> Tuple[str, Optional[int], Optional[float]]:
        if not body:
            return fallback, None, None
        try:
            decoded = json.loads(body)
        except Exception:
            return fallback, None, None
        if not isinstance(decoded, dict):
            return fallback, None, None
        description = str(decoded.get("description", fallback))
        error_code = decoded.get("error_code")
        parsed_code = int(error_code) if isinstance(error_code, int) else None
        retry_after = self._extract_retry_after(decoded)
        return description, parsed_code, retry_after

    def _request_multipart(
        self,
        method: str,
        payload: Dict[str, object],
        file_field: str,
        file_name: str,
        file_bytes: bytes,
        content_type: str,
    ) -> Dict[str, object]:
        def request_once() -> str:
            endpoint = f"{self.config.api_base}/bot{self.config.token}/{method}"
            boundary = f"----telegram-bridge-{uuid.uuid4().hex}"
            body_parts: List[bytes] = []

            for key, value in payload.items():
                body_parts.append(f"--{boundary}\r\n".encode("utf-8"))
                body_parts.append(
                    f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8")
                )
                body_parts.append(str(value).encode("utf-8"))
                body_parts.append(b"\r\n")

            body_parts.append(f"--{boundary}\r\n".encode("utf-8"))
            body_parts.append(
                (
                    f'Content-Disposition: form-data; name="{file_field}"; '
                    f'filename="{file_name}"\r\n'
                ).encode("utf-8")
            )
            body_parts.append(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
            body_parts.append(file_bytes)
            body_parts.append(b"\r\n")
            body_parts.append(f"--{boundary}--\r\n".encode("utf-8"))
            body = b"".join(body_parts)

            request = Request(endpoint, data=body, method="POST")
            request.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
            request.add_header("Content-Length", str(len(body)))

            try:
                with urlopen(request, timeout=self.config.poll_timeout_seconds + 10) as response:
                    return response.read().decode("utf-8")
            except HTTPError as exc:
                error_body = ""
                try:
                    error_body = exc.read().decode("utf-8")
                except Exception:
                    error_body = ""
                description, code, retry_after = self._extract_telegram_error(
                    error_body,
                    fallback=f"HTTP {exc.code}",
                )
                raise TelegramApiError(
                    method,
                    description,
                    code or exc.code,
                    retry_after_seconds=retry_after,
                ) from exc

        response_body = self._execute_with_retry(method, request_once)

        decoded = json.loads(response_body)
        if not decoded.get("ok"):
            description = str(decoded.get("description", "unknown Telegram error"))
            error_code = decoded.get("error_code")
            parsed_code = int(error_code) if isinstance(error_code, int) else None
            retry_after = self._extract_retry_after(decoded)
            raise TelegramApiError(
                method,
                description,
                parsed_code,
                retry_after_seconds=retry_after,
            )
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
            "allowed_updates": json.dumps(["message", "callback_query"]),
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
        message_thread_id: Optional[int] = None,
        reply_markup: Optional[Dict[str, object]] = None,
    ) -> None:
        for chunk in to_telegram_chunks(text):
            payload: Dict[str, object] = {
                "chat_id": str(chat_id),
                "text": chunk,
                "disable_web_page_preview": "true",
            }
            if reply_to_message_id is not None:
                payload["reply_to_message_id"] = str(reply_to_message_id)
            if message_thread_id is not None:
                payload["message_thread_id"] = str(message_thread_id)
            if reply_markup:
                payload["reply_markup"] = json.dumps(reply_markup)
            self._request("sendMessage", payload)

    def send_message_get_id(
        self,
        chat_id: int,
        text: str,
        reply_to_message_id: Optional[int] = None,
        message_thread_id: Optional[int] = None,
        reply_markup: Optional[Dict[str, object]] = None,
    ) -> Optional[int]:
        payload: Dict[str, object] = {
            "chat_id": str(chat_id),
            "text": text,
            "disable_web_page_preview": "true",
        }
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = str(reply_to_message_id)
        if message_thread_id is not None:
            payload["message_thread_id"] = str(message_thread_id)
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup)
        response = self._request("sendMessage", payload)
        result = response.get("result")
        if isinstance(result, dict):
            message_id = result.get("message_id")
            if isinstance(message_id, int):
                return message_id
        return None

    def _send_media(
        self,
        method: str,
        media_field: str,
        chat_id: int,
        media: str,
        caption: Optional[str],
        reply_to_message_id: Optional[int],
        message_thread_id: Optional[int],
    ) -> Dict[str, object]:
        payload: Dict[str, object] = {
            "chat_id": str(chat_id),
        }
        if caption:
            payload["caption"] = caption[:TELEGRAM_CAPTION_LIMIT]
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = str(reply_to_message_id)
        if message_thread_id is not None:
            payload["message_thread_id"] = str(message_thread_id)

        if os.path.isfile(media):
            with open(media, "rb") as handle:
                file_bytes = handle.read()
            guessed_type, _ = mimetypes.guess_type(media)
            media_content_type = guessed_type or "application/octet-stream"
            payload_without_media = dict(payload)
            return self._request_multipart(
                method=method,
                payload=payload_without_media,
                file_field=media_field,
                file_name=os.path.basename(media) or "upload.bin",
                file_bytes=file_bytes,
                content_type=media_content_type,
            )

        payload[media_field] = media
        return self._request(method, payload)

    def send_photo(
        self,
        chat_id: int,
        photo: str,
        caption: Optional[str] = None,
        reply_to_message_id: Optional[int] = None,
        message_thread_id: Optional[int] = None,
    ) -> Dict[str, object]:
        return self._send_media(
            "sendPhoto",
            "photo",
            chat_id,
            photo,
            caption,
            reply_to_message_id,
            message_thread_id,
        )

    def send_document(
        self,
        chat_id: int,
        document: str,
        caption: Optional[str] = None,
        reply_to_message_id: Optional[int] = None,
        message_thread_id: Optional[int] = None,
    ) -> Dict[str, object]:
        return self._send_media(
            "sendDocument",
            "document",
            chat_id,
            document,
            caption,
            reply_to_message_id,
            message_thread_id,
        )

    def send_audio(
        self,
        chat_id: int,
        audio: str,
        caption: Optional[str] = None,
        reply_to_message_id: Optional[int] = None,
        message_thread_id: Optional[int] = None,
    ) -> Dict[str, object]:
        return self._send_media(
            "sendAudio",
            "audio",
            chat_id,
            audio,
            caption,
            reply_to_message_id,
            message_thread_id,
        )

    def send_voice(
        self,
        chat_id: int,
        voice: str,
        caption: Optional[str] = None,
        reply_to_message_id: Optional[int] = None,
        message_thread_id: Optional[int] = None,
    ) -> Dict[str, object]:
        return self._send_media(
            "sendVoice",
            "voice",
            chat_id,
            voice,
            caption,
            reply_to_message_id,
            message_thread_id,
        )

    def edit_message(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: Optional[Dict[str, object]] = None,
    ) -> None:
        payload: Dict[str, object] = {
            "chat_id": str(chat_id),
            "message_id": str(message_id),
            "text": text,
            "disable_web_page_preview": "true",
        }
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup)
        self._request("editMessageText", payload)

    def answer_callback_query(
        self,
        callback_query_id: str,
        text: Optional[str] = None,
    ) -> None:
        payload: Dict[str, object] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        self._request("answerCallbackQuery", payload)

    def send_chat_action(
        self,
        chat_id: int,
        action: str = "typing",
        message_thread_id: Optional[int] = None,
    ) -> None:
        payload: Dict[str, object] = {
            "chat_id": str(chat_id),
            "action": action,
        }
        if message_thread_id is not None:
            payload["message_thread_id"] = str(message_thread_id)
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
