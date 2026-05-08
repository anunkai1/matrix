import logging
import math
import time
from typing import Dict, List, Optional, Tuple

from telegram_bridge.channel_adapter import ChannelAdapter
from telegram_bridge.handlers import collapse_media_group_updates
from telegram_bridge.runtime_config import Config
from telegram_bridge.state_store import PendingMediaGroup, State
from telegram_bridge.structured_logging import emit_event

from telegram_bridge.bridge_state_bootstrap import (
    build_update_offset_state_path,
    load_saved_update_offset,
    persist_saved_update_offset,
)

MEDIA_GROUP_QUIET_WINDOW_SECONDS = 2.0


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
    if not state.pending_media_groups:
        return None

    current_time = time.time() if now is None else now
    remaining_windows = [
        max(0.0, MEDIA_GROUP_QUIET_WINDOW_SECONDS - (current_time - pending.last_seen_at))
        for pending in state.pending_media_groups.values()
        if pending.updates
    ]
    if not remaining_windows:
        return 0

    wait_seconds = max(1, int(math.ceil(min(remaining_windows))))
    return min(config.poll_timeout_seconds, wait_seconds)


def persist_resumed_update_offset(offset_state_path: Optional[str], offset: int) -> None:
    if offset_state_path is not None:
        persist_saved_update_offset(offset_state_path, offset)
