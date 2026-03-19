from typing import Dict, List, Optional, Protocol

try:
    from .transport import TelegramClient
except ImportError:
    from transport import TelegramClient


class ChannelAdapter(Protocol):
    channel_name: str
    supports_message_edits: bool

    def get_updates(
        self,
        offset: int,
        timeout_seconds: Optional[int] = None,
    ) -> List[Dict[str, object]]:
        ...

    def send_message(
        self,
        chat_id: int,
        text: str,
        reply_to_message_id: Optional[int] = None,
        message_thread_id: Optional[int] = None,
    ) -> None:
        ...

    def send_message_get_id(
        self,
        chat_id: int,
        text: str,
        reply_to_message_id: Optional[int] = None,
        message_thread_id: Optional[int] = None,
    ) -> Optional[int]:
        ...

    def send_photo(
        self,
        chat_id: int,
        photo: str,
        caption: Optional[str] = None,
        reply_to_message_id: Optional[int] = None,
        message_thread_id: Optional[int] = None,
    ) -> Dict[str, object]:
        ...

    def send_document(
        self,
        chat_id: int,
        document: str,
        caption: Optional[str] = None,
        reply_to_message_id: Optional[int] = None,
        message_thread_id: Optional[int] = None,
    ) -> Dict[str, object]:
        ...

    def send_audio(
        self,
        chat_id: int,
        audio: str,
        caption: Optional[str] = None,
        reply_to_message_id: Optional[int] = None,
        message_thread_id: Optional[int] = None,
    ) -> Dict[str, object]:
        ...

    def send_voice(
        self,
        chat_id: int,
        voice: str,
        caption: Optional[str] = None,
        reply_to_message_id: Optional[int] = None,
        message_thread_id: Optional[int] = None,
    ) -> Dict[str, object]:
        ...

    def edit_message(self, chat_id: int, message_id: int, text: str) -> None:
        ...

    def send_chat_action(
        self,
        chat_id: int,
        action: str = "typing",
        message_thread_id: Optional[int] = None,
    ) -> None:
        ...

    def get_file(self, file_id: str) -> Dict[str, object]:
        ...

    def download_file_to_path(
        self,
        file_path: str,
        target_path: str,
        max_bytes: int,
        size_label: str = "File",
    ) -> None:
        ...


class TelegramChannelAdapter:
    channel_name = "telegram"
    supports_message_edits = True

    def __init__(self, client: TelegramClient) -> None:
        self._client = client

    @property
    def client(self) -> TelegramClient:
        return self._client

    def get_updates(
        self,
        offset: int,
        timeout_seconds: Optional[int] = None,
    ) -> List[Dict[str, object]]:
        return self._client.get_updates(offset, timeout_seconds=timeout_seconds)

    def send_message(
        self,
        chat_id: int,
        text: str,
        reply_to_message_id: Optional[int] = None,
        message_thread_id: Optional[int] = None,
    ) -> None:
        self._client.send_message(
            chat_id=chat_id,
            text=text,
            reply_to_message_id=reply_to_message_id,
            message_thread_id=message_thread_id,
        )

    def send_message_get_id(
        self,
        chat_id: int,
        text: str,
        reply_to_message_id: Optional[int] = None,
        message_thread_id: Optional[int] = None,
    ) -> Optional[int]:
        return self._client.send_message_get_id(
            chat_id=chat_id,
            text=text,
            reply_to_message_id=reply_to_message_id,
            message_thread_id=message_thread_id,
        )

    def send_photo(
        self,
        chat_id: int,
        photo: str,
        caption: Optional[str] = None,
        reply_to_message_id: Optional[int] = None,
        message_thread_id: Optional[int] = None,
    ) -> Dict[str, object]:
        return self._client.send_photo(
            chat_id=chat_id,
            photo=photo,
            caption=caption,
            reply_to_message_id=reply_to_message_id,
            message_thread_id=message_thread_id,
        )

    def send_document(
        self,
        chat_id: int,
        document: str,
        caption: Optional[str] = None,
        reply_to_message_id: Optional[int] = None,
        message_thread_id: Optional[int] = None,
    ) -> Dict[str, object]:
        return self._client.send_document(
            chat_id=chat_id,
            document=document,
            caption=caption,
            reply_to_message_id=reply_to_message_id,
            message_thread_id=message_thread_id,
        )

    def send_audio(
        self,
        chat_id: int,
        audio: str,
        caption: Optional[str] = None,
        reply_to_message_id: Optional[int] = None,
        message_thread_id: Optional[int] = None,
    ) -> Dict[str, object]:
        return self._client.send_audio(
            chat_id=chat_id,
            audio=audio,
            caption=caption,
            reply_to_message_id=reply_to_message_id,
            message_thread_id=message_thread_id,
        )

    def send_voice(
        self,
        chat_id: int,
        voice: str,
        caption: Optional[str] = None,
        reply_to_message_id: Optional[int] = None,
        message_thread_id: Optional[int] = None,
    ) -> Dict[str, object]:
        return self._client.send_voice(
            chat_id=chat_id,
            voice=voice,
            caption=caption,
            reply_to_message_id=reply_to_message_id,
            message_thread_id=message_thread_id,
        )

    def edit_message(self, chat_id: int, message_id: int, text: str) -> None:
        self._client.edit_message(chat_id, message_id, text)

    def send_chat_action(
        self,
        chat_id: int,
        action: str = "typing",
        message_thread_id: Optional[int] = None,
    ) -> None:
        self._client.send_chat_action(
            chat_id,
            action=action,
            message_thread_id=message_thread_id,
        )

    def get_file(self, file_id: str) -> Dict[str, object]:
        return self._client.get_file(file_id)

    def download_file_to_path(
        self,
        file_path: str,
        target_path: str,
        max_bytes: int,
        size_label: str = "File",
    ) -> None:
        self._client.download_file_to_path(
            file_path=file_path,
            target_path=target_path,
            max_bytes=max_bytes,
            size_label=size_label,
        )
