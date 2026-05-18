import logging
import math
import time
from typing import Dict, List, Optional, Tuple

from telegram_bridge.channel_adapter import ChannelAdapter
from telegram_bridge.conversation_scope import scope_from_message
from telegram_bridge.handlers import collapse_media_group_updates
from telegram_bridge.runtime_config import Config
from telegram_bridge.state_store import PendingMediaGroup, PendingTextBatch, State
from telegram_bridge.structured_logging import emit_event

from telegram_bridge.bridge_state_bootstrap import (
    build_update_offset_state_path,
    load_saved_update_offset,
    persist_saved_update_offset,
)

MEDIA_GROUP_QUIET_WINDOW_SECONDS = 2.0
TEXT_BATCH_QUIET_WINDOW_SECONDS = 0.35
TEXT_BATCH_MAX_WINDOW_SECONDS = 1.2


def drop_pending_updates(client: ChannelAdapter) -> int:
    offset = 0
    dropped = 0

    while True:
        updates = client.get_updates(offset, timeout_seconds=0)
        if not updates:
            break

        dropped += len(updates)
        next_offset = offset
        for update in updates:
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                next_offset = max(next_offset, update_id + 1)

        if next_offset == offset:
            logging.warning(
                "Startup backlog discard could not advance offset; stopping discard loop."
            )
            break

        offset = next_offset

    if dropped:
        logging.info("Dropped %s queued Telegram update(s) at startup.", dropped)
    else:
        logging.info("No queued Telegram updates found at startup.")
    emit_event(
        "bridge.startup_backlog_discard",
        fields={
            "dropped_updates": dropped,
            "next_offset": offset,
        },
    )
    return offset


def should_discard_startup_backlog(config: Config) -> bool:
    return getattr(config, "channel_plugin", "telegram") == "telegram"


def should_resume_saved_update_offset(config: Config) -> bool:
    return not should_discard_startup_backlog(config)


def should_reset_saved_update_offset(
    offset: int,
    queue_max_update_id: Optional[int],
) -> bool:
    return offset > 0 and queue_max_update_id is not None and offset > queue_max_update_id + 1


def inspect_channel_update_bounds(client: ChannelAdapter) -> Tuple[Optional[int], Optional[int]]:
    updates = client.get_updates(0, timeout_seconds=0)
    update_ids = [
        update_id
        for update in updates
        for update_id in [update.get("update_id")]
        if isinstance(update_id, int)
    ]
    if not update_ids:
        return None, None
    return min(update_ids), max(update_ids)


def compute_initial_update_offset(
    config: Config,
    client: ChannelAdapter,
) -> Tuple[int, Optional[str]]:
    if should_discard_startup_backlog(config):
        return 0, None

    offset_state_path = build_update_offset_state_path(config.state_dir, config.channel_plugin)
    saved_offset = load_saved_update_offset(offset_state_path)
    queue_min_update_id, queue_max_update_id = inspect_channel_update_bounds(client)

    offset = saved_offset
    offset_reset = False
    if should_reset_saved_update_offset(saved_offset, queue_max_update_id):
        offset = 0
        offset_reset = True

    emit_event(
        "bridge.startup_offset_resume_checked",
        fields={
            "channel_plugin": config.channel_plugin,
            "saved_offset": saved_offset,
            "offset": offset,
            "offset_reset": offset_reset,
            "queue_min_update_id": queue_min_update_id,
            "queue_max_update_id": queue_max_update_id,
        },
    )
    return offset, offset_state_path


def maybe_reset_stale_runtime_offset(
    config: Config,
    client: ChannelAdapter,
    offset: int,
) -> int:
    if not should_resume_saved_update_offset(config) or offset <= 0:
        return offset

    queue_min_update_id, queue_max_update_id = inspect_channel_update_bounds(client)
    if not should_reset_saved_update_offset(offset, queue_max_update_id):
        return offset

    emit_event(
        "bridge.runtime_offset_reset",
        level=logging.WARNING,
        fields={
            "channel_plugin": config.channel_plugin,
            "offset_before": offset,
            "queue_min_update_id": queue_min_update_id,
            "queue_max_update_id": queue_max_update_id,
        },
    )
    return 0


def get_media_group_identity(update: Dict[str, object]) -> Optional[Tuple[int, str]]:
    message = update.get("message")
    if not isinstance(message, dict):
        return None

    media_group_id = message.get("media_group_id")
    chat = message.get("chat")
    chat_id = chat.get("id") if isinstance(chat, dict) else None
    if not isinstance(chat_id, int):
        return None
    if not isinstance(media_group_id, str) or not media_group_id.strip():
        return None
    return chat_id, media_group_id.strip()


def _message_scope_key(message: Dict[str, object]) -> Optional[str]:
    scope = scope_from_message(message)
    if scope is None:
        return None
    return scope.scope_key


def _text_batch_identity(update: Dict[str, object]) -> Optional[Tuple[str, int, Optional[int], Optional[int]]]:
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    if not isinstance(message.get("text"), str) or not str(message.get("text") or "").strip():
        return None
    if isinstance(message.get("caption"), str) and str(message.get("caption") or "").strip():
        return None
    if message.get("reply_to_message") is not None:
        return None
    for media_field in ("photo", "voice", "document", "audio", "video", "sticker", "animation"):
        if message.get(media_field) is not None:
            return None
    text = str(message.get("text") or "").strip()
    if text.startswith("/"):
        return None
    scope_key = _message_scope_key(message)
    if not scope_key:
        return None
    chat = message.get("chat")
    chat_id = chat.get("id") if isinstance(chat, dict) else None
    if not isinstance(chat_id, int):
        return None
    from_obj = message.get("from")
    actor_user_id = (
        from_obj.get("id")
        if isinstance(from_obj, dict) and isinstance(from_obj.get("id"), int)
        else None
    )
    raw_thread_id = message.get("message_thread_id")
    message_thread_id = raw_thread_id if isinstance(raw_thread_id, int) and raw_thread_id > 0 else None
    return scope_key, chat_id, message_thread_id, actor_user_id


def _merge_text_batch_updates(updates: List[Dict[str, object]]) -> Dict[str, object]:
    ordered_updates = sorted(
        updates,
        key=lambda update: (
            update.get("update_id") if isinstance(update.get("update_id"), int) else 2**31,
        ),
    )
    first_update = ordered_updates[0]
    first_message = first_update.get("message")
    merged_update = dict(first_update)
    merged_message = dict(first_message) if isinstance(first_message, dict) else {}
    text_parts: List[str] = []
    latest_update_id: Optional[int] = None
    latest_message_id: Optional[int] = None
    coalesced_messages: List[Dict[str, object]] = []
    for item in ordered_updates:
        message = item.get("message")
        if not isinstance(message, dict):
            continue
        coalesced_messages.append(message)
        text_value = message.get("text")
        if isinstance(text_value, str) and text_value.strip():
            text_parts.append(text_value.strip())
        update_id = item.get("update_id")
        if isinstance(update_id, int):
            latest_update_id = update_id if latest_update_id is None else max(latest_update_id, update_id)
        message_id = message.get("message_id")
        if isinstance(message_id, int):
            latest_message_id = message_id if latest_message_id is None else max(latest_message_id, message_id)
    merged_message["text"] = "\n\n".join(text_parts).strip()
    if latest_message_id is not None:
        merged_message["message_id"] = latest_message_id
    if coalesced_messages:
        merged_message["coalesced_text_messages"] = coalesced_messages
    merged_update["message"] = merged_message
    if latest_update_id is not None:
        merged_update["update_id"] = latest_update_id
    return merged_update


def make_pending_media_group_key(chat_id: int, media_group_id: str) -> str:
    return f"{chat_id}:{media_group_id}"


def buffer_pending_media_group_updates(
    state: State,
    updates: List[Dict[str, object]],
    *,
    now: Optional[float] = None,
) -> List[Dict[str, object]]:
    current_time = time.time() if now is None else now
    immediate_updates: List[Dict[str, object]] = []
    for update in updates:
        identity = get_media_group_identity(update)
        if identity is None:
            immediate_updates.append(update)
            continue

        chat_id, media_group_id = identity
        pending_key = make_pending_media_group_key(chat_id, media_group_id)
        pending = state.pending_media_groups.get(pending_key)
        if pending is None:
            state.pending_media_groups[pending_key] = PendingMediaGroup(
                chat_id=chat_id,
                media_group_id=media_group_id,
                updates=[update],
                started_at=current_time,
                last_seen_at=current_time,
            )
            continue

        pending.updates.append(update)
        pending.last_seen_at = current_time

    return immediate_updates


def flush_ready_text_batch_updates(
    state: State,
    *,
    now: Optional[float] = None,
    force_scope_keys: Optional[set[str]] = None,
    force: bool = False,
) -> List[Dict[str, object]]:
    current_time = time.time() if now is None else now
    forced_scope_keys = set(force_scope_keys or set())
    ready_batches: List[Tuple[float, str]] = []
    for scope_key, pending in state.pending_text_batches.items():
        if not pending.updates:
            continue
        quiet_elapsed = current_time - pending.last_seen_at
        batch_elapsed = current_time - pending.started_at
        if not force and scope_key not in forced_scope_keys:
            if quiet_elapsed < TEXT_BATCH_QUIET_WINDOW_SECONDS and batch_elapsed < TEXT_BATCH_MAX_WINDOW_SECONDS:
                continue
        ready_batches.append((pending.started_at, scope_key))

    flushed_updates: List[Dict[str, object]] = []
    for _, scope_key in sorted(ready_batches):
        pending = state.pending_text_batches.pop(scope_key, None)
        if pending is None or not pending.updates:
            continue
        flushed_updates.append(_merge_text_batch_updates(pending.updates))
    return flushed_updates


def buffer_pending_text_updates(
    state: State,
    updates: List[Dict[str, object]],
    *,
    now: Optional[float] = None,
) -> List[Dict[str, object]]:
    current_time = time.time() if now is None else now
    immediate_updates: List[Dict[str, object]] = []
    for update in updates:
        identity = _text_batch_identity(update)
        message = update.get("message")
        scope_key = _message_scope_key(message) if isinstance(message, dict) else None
        if identity is None:
            if scope_key and scope_key in state.pending_text_batches:
                immediate_updates.extend(
                    flush_ready_text_batch_updates(
                        state,
                        now=current_time,
                        force_scope_keys={scope_key},
                    )
                )
            immediate_updates.append(update)
            continue

        scope_key, chat_id, message_thread_id, actor_user_id = identity
        pending = state.pending_text_batches.get(scope_key)
        if pending is None:
            state.pending_text_batches[scope_key] = PendingTextBatch(
                scope_key=scope_key,
                chat_id=chat_id,
                message_thread_id=message_thread_id,
                actor_user_id=actor_user_id,
                updates=[update],
                started_at=current_time,
                last_seen_at=current_time,
            )
            continue

        # If the apparent sender changes mid-batch, flush first so group-room users
        # do not get merged into the same synthesized continuation turn.
        if pending.actor_user_id != actor_user_id:
            immediate_updates.extend(
                flush_ready_text_batch_updates(
                    state,
                    now=current_time,
                    force_scope_keys={scope_key},
                )
            )
            state.pending_text_batches[scope_key] = PendingTextBatch(
                scope_key=scope_key,
                chat_id=chat_id,
                message_thread_id=message_thread_id,
                actor_user_id=actor_user_id,
                updates=[update],
                started_at=current_time,
                last_seen_at=current_time,
            )
            continue

        pending.updates.append(update)
        pending.last_seen_at = current_time

    return immediate_updates


def flush_ready_media_group_updates(
    state: State,
    *,
    now: Optional[float] = None,
    force: bool = False,
) -> List[Dict[str, object]]:
    current_time = time.time() if now is None else now
    ready_groups: List[Tuple[int, float, str]] = []
    for pending_key, pending in state.pending_media_groups.items():
        if not pending.updates:
            continue
        quiet_elapsed = current_time - pending.last_seen_at
        if not force and quiet_elapsed < MEDIA_GROUP_QUIET_WINDOW_SECONDS:
            continue
        first_update = pending.updates[0]
        first_update_id = first_update.get("update_id")
        sort_update_id = first_update_id if isinstance(first_update_id, int) else 2**31
        ready_groups.append((sort_update_id, pending.started_at, pending_key))

    flushed_updates: List[Dict[str, object]] = []
    for _, _, pending_key in sorted(ready_groups):
        pending = state.pending_media_groups.pop(pending_key, None)
        if pending is None or not pending.updates:
            continue
        flushed_updates.extend(collapse_media_group_updates(pending.updates))
    return flushed_updates


def compute_poll_timeout_seconds(
    state: State,
    config: Config,
    *,
    now: Optional[float] = None,
) -> Optional[int]:
    if not state.pending_media_groups and not state.pending_text_batches:
        return None

    current_time = time.time() if now is None else now
    remaining_windows = [
        max(0.0, MEDIA_GROUP_QUIET_WINDOW_SECONDS - (current_time - pending.last_seen_at))
        for pending in state.pending_media_groups.values()
        if pending.updates
    ]
    remaining_windows.extend(
        max(
            0.0,
            min(
                TEXT_BATCH_QUIET_WINDOW_SECONDS - (current_time - pending.last_seen_at),
                TEXT_BATCH_MAX_WINDOW_SECONDS - (current_time - pending.started_at),
            ),
        )
        for pending in state.pending_text_batches.values()
        if pending.updates
    )
    if not remaining_windows:
        return 0

    wait_seconds = max(1, int(math.ceil(min(remaining_windows))))
    return min(config.poll_timeout_seconds, wait_seconds)


def persist_resumed_update_offset(offset_state_path: Optional[str], offset: int) -> None:
    if offset_state_path is not None:
        persist_saved_update_offset(offset_state_path, offset)
