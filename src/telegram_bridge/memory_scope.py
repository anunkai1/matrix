from __future__ import annotations

try:
    from .memory_engine import MemoryEngine
except ImportError:
    from memory_engine import MemoryEngine


def resolve_shared_memory_archive_key(config, channel_name: str) -> str:
    shared_key = getattr(config, "shared_memory_key", "").strip()
    normalized_channel = (channel_name or "telegram").strip().lower()
    if shared_key and normalized_channel == "telegram":
        return shared_key
    return ""


def resolve_memory_conversation_key(config, channel_name: str, chat_id: int) -> str:
    shared_archive_key = resolve_shared_memory_archive_key(config, channel_name)
    if shared_archive_key:
        scoped_key = MemoryEngine.channel_key(channel_name, chat_id)
        return f"{shared_archive_key}:session:{scoped_key}"
    return MemoryEngine.channel_key(channel_name, chat_id)
