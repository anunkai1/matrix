import json
import os
from typing import Dict, List, Optional
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class WhatsAppChannelAdapter:
    channel_name = "whatsapp"

    def __init__(self, config) -> None:
        self.config = config
        if not bool(getattr(config, "whatsapp_plugin_enabled", False)):
            raise RuntimeError(
                "Channel plugin 'whatsapp' is disabled. Set WHATSAPP_PLUGIN_ENABLED=true to enable."
            )
        self.api_base = str(getattr(config, "whatsapp_bridge_api_base", "")).rstrip("/")
        if not self.api_base:
            raise RuntimeError("WHATSAPP_BRIDGE_API_BASE is required for whatsapp channel plugin.")
        self.auth_token = str(getattr(config, "whatsapp_bridge_auth_token", "")).strip()
        self.timeout_seconds = int(getattr(config, "whatsapp_poll_timeout_seconds", 20))

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        return headers

    def _request_json(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, object]] = None,
    ) -> Dict[str, object]:
        endpoint = f"{self.api_base}{path}"
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        request = Request(endpoint, data=data, method=method)
        for name, value in self._headers().items():
            request.add_header(name, value)
        try:
            with urlopen(request, timeout=self.timeout_seconds + 10) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8")
            except Exception:
                detail = ""
            message = f"WhatsApp bridge HTTP {exc.code}"
            if detail:
                message = f"{message}: {detail}"
            raise RuntimeError(message) from exc
        decoded = json.loads(body) if body else {}
        if not isinstance(decoded, dict):
            raise RuntimeError("WhatsApp bridge response must be a JSON object")
        if decoded.get("ok") is False:
            description = decoded.get("description") or "unknown WhatsApp bridge error"
            raise RuntimeError(f"WhatsApp bridge request failed: {description}")
        return decoded

    def get_updates(
        self,
        offset: int,
        timeout_seconds: Optional[int] = None,
    ) -> List[Dict[str, object]]:
        timeout = self.timeout_seconds if timeout_seconds is None else timeout_seconds
        query = urlencode({"offset": offset, "timeout": timeout})
        response = self._request_json("GET", f"/updates?{query}")
        result = response.get("result", [])
        if not isinstance(result, list):
            raise RuntimeError("Invalid WhatsApp bridge updates response")
        return result

    def send_message(
        self,
        chat_id: int,
        text: str,
        reply_to_message_id: Optional[int] = None,
    ) -> None:
        payload: Dict[str, object] = {"chat_id": str(chat_id), "text": text}
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = str(reply_to_message_id)
        self._request_json("POST", "/messages", payload)

    def send_message_get_id(
        self,
        chat_id: int,
        text: str,
        reply_to_message_id: Optional[int] = None,
    ) -> Optional[int]:
        payload: Dict[str, object] = {"chat_id": str(chat_id), "text": text}
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = str(reply_to_message_id)
        response = self._request_json("POST", "/messages", payload)
        result = response.get("result")
        if isinstance(result, dict):
            message_id = result.get("message_id")
            if isinstance(message_id, int):
                return message_id
        return None

    def _send_media(
        self,
        media_type: str,
        chat_id: int,
        media_ref: str,
        caption: Optional[str],
        reply_to_message_id: Optional[int],
    ) -> Dict[str, object]:
        payload: Dict[str, object] = {
            "chat_id": str(chat_id),
            "media_ref": media_ref,
            "media_type": media_type,
        }
        if caption:
            payload["caption"] = caption
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = str(reply_to_message_id)
        return self._request_json("POST", "/media", payload)

    def send_photo(
        self,
        chat_id: int,
        photo: str,
        caption: Optional[str] = None,
        reply_to_message_id: Optional[int] = None,
    ) -> Dict[str, object]:
        return self._send_media("photo", chat_id, photo, caption, reply_to_message_id)

    def send_document(
        self,
        chat_id: int,
        document: str,
        caption: Optional[str] = None,
        reply_to_message_id: Optional[int] = None,
    ) -> Dict[str, object]:
        return self._send_media("document", chat_id, document, caption, reply_to_message_id)

    def send_audio(
        self,
        chat_id: int,
        audio: str,
        caption: Optional[str] = None,
        reply_to_message_id: Optional[int] = None,
    ) -> Dict[str, object]:
        return self._send_media("audio", chat_id, audio, caption, reply_to_message_id)

    def send_voice(
        self,
        chat_id: int,
        voice: str,
        caption: Optional[str] = None,
        reply_to_message_id: Optional[int] = None,
    ) -> Dict[str, object]:
        return self._send_media("voice", chat_id, voice, caption, reply_to_message_id)

    def edit_message(self, chat_id: int, message_id: int, text: str) -> None:
        payload: Dict[str, object] = {
            "chat_id": str(chat_id),
            "message_id": str(message_id),
            "text": text,
        }
        self._request_json("POST", "/messages/edit", payload)

    def send_chat_action(self, chat_id: int, action: str = "typing") -> None:
        payload: Dict[str, object] = {"chat_id": str(chat_id), "action": action}
        self._request_json("POST", "/chat-action", payload)

    def get_file(self, file_id: str) -> Dict[str, object]:
        response = self._request_json("GET", f"/files/meta?{urlencode({'file_id': file_id})}")
        result = response.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("Invalid WhatsApp bridge file metadata response")
        return result

    def download_file_to_path(
        self,
        file_path: str,
        target_path: str,
        max_bytes: int,
        size_label: str = "File",
    ) -> None:
        query = urlencode({"file_path": file_path})
        endpoint = f"{self.api_base}/files/content?{query}"
        request = Request(endpoint, method="GET")
        if self.auth_token:
            request.add_header("Authorization", f"Bearer {self.auth_token}")

        total = 0
        with (
            urlopen(request, timeout=self.timeout_seconds + 10) as response,
            open(target_path, "wb") as handle,
        ):
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(f"{size_label} too large (> {max_bytes} bytes).")
                handle.write(chunk)

        if total <= 0 and os.path.exists(target_path):
            # Keep explicit failure semantics if bridge returned an empty body.
            raise RuntimeError("WhatsApp bridge file download returned empty content")
