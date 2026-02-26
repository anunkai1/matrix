import json
from typing import Dict, List, Optional
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

TELEGRAM_LIMIT = 4096


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
        output.append(f"[{index}/{total}]\\n{chunk}")
    return output


class TelegramClient:
    def __init__(self, config) -> None:
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
