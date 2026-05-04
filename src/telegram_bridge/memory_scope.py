from __future__ import annotations

try:
    from .memory_engine import MemoryEngine
except ImportError:
    from memory_engine import MemoryEngine


def resolve_memory_conversation_key(config, channel_name: str, scope_key: str | int) -> str:
    if isinstance(scope_key, int):
        return MemoryEngine.channel_key(channel_name, scope_key)
    scoped_key = str(scope_key or "").strip()
    if not scoped_key:
        raise ValueError("scope_key must not be empty")
    return scoped_key
