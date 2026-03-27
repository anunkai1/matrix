from __future__ import annotations

try:
    from .conversation_scope import parse_telegram_scope_key
    from .memory_engine import MemoryEngine
except ImportError:
    from conversation_scope import parse_telegram_scope_key
    from memory_engine import MemoryEngine


def resolve_shared_memory_archive_key(config, channel_name: str) -> str:
    shared_key = getattr(config, "shared_memory_key", "").strip()
    normalized_channel = (channel_name or "telegram").strip().lower()
    if shared_key and normalized_channel == "telegram":
        return shared_key
    return ""


def resolve_memory_conversation_key(config, channel_name: str, scope_key: str | int) -> str:
    shared_archive_key = resolve_shared_memory_archive_key(config, channel_name)
    if isinstance(scope_key, int):
        scoped_key = MemoryEngine.channel_key(channel_name, scope_key)
    else:
        scoped_key = str(scope_key or "").strip()
        if not scoped_key:
            raise ValueError("scope_key must not be empty")
        normalized_channel = (channel_name or "telegram").strip().lower()
        if normalized_channel != "telegram":
            try:
                parsed_scope = parse_telegram_scope_key(scoped_key)
            except ValueError:
                parsed_scope = None
            if parsed_scope is not None and parsed_scope.message_thread_id is None:
                scoped_key = MemoryEngine.channel_key(normalized_channel, parsed_scope.chat_id)
    if shared_archive_key:
        return f"{shared_archive_key}:session:{scoped_key}"
    return scoped_key
