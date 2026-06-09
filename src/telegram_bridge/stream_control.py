"""``/stream`` command — per-scope opt-in for progressive token streaming.

Stage 1 of the Hermes-style streaming rollout: the global
``Config.streaming.enabled`` flag defaults to False, but operators can
opt a single chat (or forum topic) in via ``/stream on`` and revert
with ``/stream off``. The per-scope flag is persisted under
``$TELEGRAM_BRIDGE_STATE_DIR/chat_streaming_enabled.json`` so it
survives bridge restarts.

The command follows the same shape as ``/engine`` / ``/model`` /
``/effort``:
  * ``/stream`` or ``/stream status`` — show current state
  * ``/stream on`` — enable streaming for this scope
  * ``/stream off`` — disable streaming for this scope
  * ``/stream reset`` — clear the per-scope override and fall back to
    the global ``Config.streaming.enabled`` default

Stage 1 only supports the codex app-server engine because that is the
only engine that surfaces token-level deltas today. The status text
calls that out explicitly so the operator knows the boundary.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from telegram_bridge.channel_adapter import ChannelAdapter
from telegram_bridge.state_store import (
    State,
    clear_chat_streaming_enabled,
    get_chat_streaming_enabled,
    set_chat_streaming_enabled,
)
from telegram_bridge.structured_logging import emit_event

logger = logging.getLogger("telegram_bridge.stream_control")


def _send_command_reply(
    client: ChannelAdapter,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    text: str,
) -> None:
    client.send_message(
        chat_id,
        text,
        reply_to_message_id=message_id,
        message_thread_id=message_thread_id,
    )


def _streaming_engine_supported(config, engine_plugin: str) -> bool:
    """True if the streaming config is wired up for the given engine.

    Mirrors ``StreamingConfig.is_engine_supported`` so the control
    command does not have to import the runtime config dataclass.
    """
    streaming_cfg = getattr(config, "streaming", None)
    if streaming_cfg is None:
        return False
    return bool(getattr(streaming_cfg, "is_engine_supported", lambda _p: False)(engine_plugin))


def build_streaming_status_text(
    state: State,
    config,
    scope_key: str,
    active_engine_plugin: str,
) -> str:
    """Render the per-scope streaming status for ``/stream status``.

    ``active_engine_plugin`` is the engine that the current scope is
    actually using (e.g. ``codex``, ``pi``, ``gemma``, ``venice``). The
    global ``Config.streaming.enabled`` flag is the authoritative
    kill-switch; the per-scope flag is an opt-in multiplier.
    """
    streaming_cfg = getattr(config, "streaming", None)
    global_enabled = bool(getattr(streaming_cfg, "enabled", False))
    scope_override = get_chat_streaming_enabled(state, scope_key)
    if scope_override is True:
        effective = "on (scope opt-in)"
    elif scope_override is False:
        effective = "off (scope opt-out)"
    else:
        effective = "on" if global_enabled else "off"
    supported = _streaming_engine_supported(config, active_engine_plugin)
    if not supported:
        streaming_cfg = getattr(config, "streaming", None)
        supported_list = (
            getattr(streaming_cfg, "supported_engine_plugins", "codex,pi")
            if streaming_cfg is not None
            else "codex,pi"
        )
        engine_note = (
            f"Note: streaming currently supports the following engines: "
            f"{supported_list}. "
            f"Current engine for this scope is `{active_engine_plugin or 'unknown'}`."
        )
    else:
        engine_note = f"Active engine: `{active_engine_plugin or 'unknown'}`."
    return (
        "Progressive streaming status:\n"
        f"- Global streaming: {'on' if global_enabled else 'off'}\n"
        f"- Per-scope override: "
        f"{'on' if scope_override is True else 'off' if scope_override is False else 'unset (uses global)'}\n"
        f"- Effective for this scope: {effective}\n"
        f"- {engine_note}\n"
        "Use /stream on, /stream off, or /stream reset."
    )


def handle_stream_command(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    raw_text: str,
    *,
    active_engine_plugin_fn: Callable[[State, str], str],
) -> bool:
    """Route ``/stream [on|off|status|reset]``.

    Returns True when the command was recognized (regardless of whether
    the requested state was a no-op). Unknown tails return a usage
    message.
    """
    pieces = raw_text.strip().split(maxsplit=1)
    tail = pieces[1].strip().lower() if len(pieces) > 1 else "status"
    engine_plugin = active_engine_plugin_fn(state, scope_key)

    if tail in {"", "status"}:
        _send_command_reply(
            client,
            chat_id,
            message_thread_id,
            message_id,
            build_streaming_status_text(state, config, scope_key, engine_plugin),
        )
        return True

    if tail in {"on", "enable", "1", "true"}:
        set_chat_streaming_enabled(state, scope_key, True)
        emit_event(
            "bridge.streaming_scope_enabled",
            fields={
                "chat_id": chat_id,
                "message_id": message_id,
                "scope_key": scope_key,
                "engine_plugin": engine_plugin,
            },
        )
        supported = _streaming_engine_supported(config, engine_plugin)
        note = (
            ""
            if supported
            else " Note: streaming currently supports the codex app-server and Pi"
            " RPC engines — streaming will silently stay off until the scope"
            " switches to a supported engine."
        )
        _send_command_reply(
            client,
            chat_id,
            message_thread_id,
            message_id,
            f"Progressive streaming enabled for this scope.{note}",
        )
        return True

    if tail in {"off", "disable", "0", "false"}:
        set_chat_streaming_enabled(state, scope_key, False)
        emit_event(
            "bridge.streaming_scope_disabled",
            fields={
                "chat_id": chat_id,
                "message_id": message_id,
                "scope_key": scope_key,
                "engine_plugin": engine_plugin,
            },
        )
        _send_command_reply(
            client,
            chat_id,
            message_thread_id,
            message_id,
            "Progressive streaming disabled for this scope.",
        )
        return True

    if tail in {"reset", "clear"}:
        cleared = clear_chat_streaming_enabled(state, scope_key)
        emit_event(
            "bridge.streaming_scope_reset",
            fields={
                "chat_id": chat_id,
                "message_id": message_id,
                "scope_key": scope_key,
                "engine_plugin": engine_plugin,
                "had_override": cleared,
            },
        )
        _send_command_reply(
            client,
            chat_id,
            message_thread_id,
            message_id,
            (
                "Per-scope streaming override cleared. "
                f"Now follows the global default ({'on' if getattr(getattr(config, 'streaming', None), 'enabled', False) else 'off'})."
            ),
        )
        return True

    _send_command_reply(
        client,
        chat_id,
        message_thread_id,
        message_id,
        "Unknown /stream command. Use /stream, /stream on, /stream off, or /stream reset.",
    )
    return True


__all__ = [
    "build_streaming_status_text",
    "handle_stream_command",
]
