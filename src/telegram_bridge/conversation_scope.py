from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


_TELEGRAM_SCOPE_PATTERN = re.compile(r"^tg:(-?\d+)(?::topic:(\d+))?$")


@dataclass(frozen=True)
class ConversationScope:
    chat_id: int
    message_thread_id: Optional[int] = None

    @property
    def scope_key(self) -> str:
        return build_telegram_scope_key(
            self.chat_id,
            message_thread_id=self.message_thread_id,
        )

    @property
    def is_topic(self) -> bool:
        return self.message_thread_id is not None


def normalize_message_thread_id(value: object) -> Optional[int]:
    if not isinstance(value, int):
        return None
    if value <= 0:
        return None
    return value


def build_telegram_scope_key(
    chat_id: int,
    message_thread_id: Optional[int] = None,
) -> str:
    normalized_thread_id = normalize_message_thread_id(message_thread_id)
    if normalized_thread_id is None:
        return f"tg:{chat_id}"
    return f"tg:{chat_id}:topic:{normalized_thread_id}"


def scope_key_from_legacy_chat_id(chat_id: int) -> str:
    return build_telegram_scope_key(chat_id)


def parse_telegram_scope_key(scope_key: str) -> ConversationScope:
    normalized = (scope_key or "").strip()
    match = _TELEGRAM_SCOPE_PATTERN.fullmatch(normalized)
    if match is None:
        raise ValueError(f"Invalid telegram scope key: {scope_key!r}")
    chat_id = int(match.group(1))
    message_thread_id = match.group(2)
    return ConversationScope(
        chat_id=chat_id,
        message_thread_id=int(message_thread_id) if message_thread_id is not None else None,
    )


def normalize_scope_storage_key(raw_key: object) -> Optional[str]:
    if raw_key is None:
        return None
    normalized = str(raw_key).strip()
    if not normalized:
        return None
    if _TELEGRAM_SCOPE_PATTERN.fullmatch(normalized):
        return normalized
    try:
        return scope_key_from_legacy_chat_id(int(normalized))
    except (TypeError, ValueError):
        return normalized


def scope_from_message(message: object) -> Optional[ConversationScope]:
    if not isinstance(message, dict):
        return None
    chat = message.get("chat")
    if not isinstance(chat, dict):
        return None
    chat_id = chat.get("id")
    if not isinstance(chat_id, int):
        return None

    chat_type = chat.get("type")
    if isinstance(chat_type, str) and chat_type == "private":
        message_thread_id = None
    else:
        is_topic_message = message.get("is_topic_message")
        raw_thread_id = message.get("message_thread_id")
        message_thread_id = (
            normalize_message_thread_id(raw_thread_id)
            if is_topic_message is True
            else None
        )
    return ConversationScope(chat_id=chat_id, message_thread_id=message_thread_id)
