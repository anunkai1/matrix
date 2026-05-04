#!/usr/bin/env python3
"""Telegram long-poll bridge to local Codex CLI."""

import argparse
import logging
import math
import os
import time
from typing import Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError

try:
    from .affective_runtime import build_affective_runtime
    from .auth_state import (
        apply_auth_change_thread_reset,
        build_auth_fingerprint_state_path,
        clear_loaded_thread_state,
        compute_current_auth_fingerprint,
    )
    from .attachment_store import AttachmentStore
    from .channel_adapter import ChannelAdapter
    from .conversation_scope import parse_telegram_scope_key
    from .executor import (
        ExecutorProgressEvent,
        extract_executor_progress_event,
        parse_executor_output,
    )
    from .engine_adapter import EngineAdapter
    from .handlers import (
        DocumentPayload,
        collapse_media_group_updates,
        extract_prompt_and_media,
        handle_update,
    )
    from .media import TelegramFileDownloadSpec, download_telegram_file_to_temp
    from .memory_engine import MemoryEngine
    from .plugin_registry import build_default_plugin_registry
    from .runtime_config import (
        Config,
        default_voice_alias_replacements,
        load_config,
        parse_plugin_name_env,
    )
    from .session_manager import (
        clear_busy,
        compute_policy_fingerprint,
        ensure_chat_worker_session,
        expire_idle_worker_sessions,
        finish_restart_attempt,
        pop_ready_restart_request,
        request_safe_restart,
    )
    from .state_store import (
        CanonicalSession,
        PendingMediaGroup,
        State,
        StateRepository,
        WorkerSession,
        canonical_session_is_empty,
        build_canonical_sessions_from_legacy,
        build_legacy_from_canonical,
        ensure_state_dir,
        load_canonical_sessions,
        load_canonical_sessions_sqlite,
        load_chat_codex_models,
        load_chat_codex_efforts,
        load_chat_engines,
        load_chat_pi_models,
        load_chat_pi_providers,
        load_chat_threads,
        load_in_flight_requests,
        load_or_import_canonical_sessions_sqlite,
        load_worker_sessions,
        mirror_legacy_from_canonical,
        persist_chat_threads,
        persist_canonical_sessions,
        persist_worker_sessions,
        quarantine_corrupt_state_file,
        sync_all_canonical_sessions,
    )
    from .stream_buffer import BoundedTextBuffer
    from .structured_logging import configure_bridge_logging, emit_event
    from .transport import TELEGRAM_LIMIT, TelegramClient, to_telegram_chunks
    from .voice_alias_learning import VoiceAliasLearningStore
except ImportError:
    from affective_runtime import build_affective_runtime
    from auth_state import (
        apply_auth_change_thread_reset,
        build_auth_fingerprint_state_path,
        clear_loaded_thread_state,
        compute_current_auth_fingerprint,
    )
    from attachment_store import AttachmentStore
    from channel_adapter import ChannelAdapter
    from conversation_scope import parse_telegram_scope_key
    from executor import (
        ExecutorProgressEvent,
        extract_executor_progress_event,
        parse_executor_output,
    )
    from engine_adapter import EngineAdapter
    from handlers import (
        DocumentPayload,
        collapse_media_group_updates,
        extract_prompt_and_media,
        handle_update,
    )
    from media import TelegramFileDownloadSpec, download_telegram_file_to_temp
    from memory_engine import MemoryEngine
    from plugin_registry import build_default_plugin_registry
    from runtime_config import (
        Config,
        default_voice_alias_replacements,
        load_config,
        parse_plugin_name_env,
    )
    from session_manager import (
        clear_busy,
        compute_policy_fingerprint,
        ensure_chat_worker_session,
        expire_idle_worker_sessions,
        finish_restart_attempt,
        pop_ready_restart_request,
        request_safe_restart,
    )
    from state_store import (
        CanonicalSession,
        PendingMediaGroup,
        State,
        StateRepository,
        WorkerSession,
        canonical_session_is_empty,
        build_canonical_sessions_from_legacy,
        build_legacy_from_canonical,
        ensure_state_dir,
        load_canonical_sessions,
        load_canonical_sessions_sqlite,
        load_chat_codex_models,
        load_chat_codex_efforts,
        load_chat_engines,
        load_chat_pi_models,
        load_chat_pi_providers,
        load_chat_threads,
        load_in_flight_requests,
        load_or_import_canonical_sessions_sqlite,
        load_worker_sessions,
        mirror_legacy_from_canonical,
        persist_chat_threads,
        persist_canonical_sessions,
        persist_worker_sessions,
        quarantine_corrupt_state_file,
        sync_all_canonical_sessions,
    )
    from stream_buffer import BoundedTextBuffer
    from structured_logging import configure_bridge_logging, emit_event
    from transport import TELEGRAM_LIMIT, TelegramClient, to_telegram_chunks
    from voice_alias_learning import VoiceAliasLearningStore


def build_policy_fingerprint_state_path(state_dir: str) -> str:
    return os.path.join(state_dir, "policy_fingerprint.txt")


def build_update_offset_state_path(state_dir: str, channel_plugin: str) -> str:
    normalized = (channel_plugin or "telegram").strip().lower() or "telegram"
    return os.path.join(state_dir, f"{normalized}_update_offset.txt")


def load_saved_policy_fingerprint(path: str) -> str:
    if not path:
        return ""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except FileNotFoundError:
        return ""
    except OSError:
        logging.exception("Failed to read policy fingerprint state from %s", path)
        return ""


def persist_saved_policy_fingerprint(path: str, fingerprint: str) -> None:
    if not path:
        return
    directory = os.path.dirname(path)
    if directory:
        ensure_state_dir(directory)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        handle.write(fingerprint.strip())
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)


def load_saved_update_offset(path: str) -> int:
    if not path:
        return 0
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = handle.read().strip()
    except FileNotFoundError:
        return 0
    except OSError:
        logging.exception("Failed to read saved update offset from %s", path)
        return 0
    if not raw:
        return 0
    try:
        parsed = int(raw)
    except ValueError:
        logging.warning("Ignoring invalid saved update offset in %s: %r", path, raw)
        return 0
    if parsed < 0:
        logging.warning("Ignoring negative saved update offset in %s: %s", path, parsed)
        return 0
    return parsed


def persist_saved_update_offset(path: str, offset: int) -> None:
    if not path:
        return
    directory = os.path.dirname(path)
    if directory:
        ensure_state_dir(directory)
    sanitized_offset = max(int(offset), 0)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        handle.write(f"{sanitized_offset}\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)


def clear_thread_state_for_policy_change(
    loaded_threads: Dict[int, str],
    loaded_worker_sessions: Dict[int, WorkerSession],
    loaded_canonical_sessions: Dict[int, CanonicalSession],
) -> Dict[str, int]:
    return clear_loaded_thread_state(
        loaded_threads,
        loaded_worker_sessions,
        loaded_canonical_sessions,
    )


def apply_policy_change_thread_reset(
    state_dir: str,
    current_policy_fingerprint: str,
    loaded_threads: Dict[int, str],
    loaded_worker_sessions: Dict[int, WorkerSession],
    loaded_canonical_sessions: Dict[int, CanonicalSession],
) -> Dict[str, object]:
    if not current_policy_fingerprint.strip():
        return {
            "applied": False,
            "previous_policy_fingerprint": "",
            "counts": {"threads": 0, "worker_sessions": 0, "canonical_sessions": 0},
        }

    state_path = build_policy_fingerprint_state_path(state_dir)
    previous_policy_fingerprint = load_saved_policy_fingerprint(state_path)
    reset_counts = {"threads": 0, "worker_sessions": 0, "canonical_sessions": 0}
    applied = False

    if (
        previous_policy_fingerprint
        and previous_policy_fingerprint != current_policy_fingerprint
    ):
        reset_counts = clear_thread_state_for_policy_change(
            loaded_threads,
            loaded_worker_sessions,
            loaded_canonical_sessions,
        )
        applied = any(reset_counts.values())

    persist_saved_policy_fingerprint(state_path, current_policy_fingerprint)
    return {
        "applied": applied,
        "previous_policy_fingerprint": previous_policy_fingerprint,
        "counts": reset_counts,
    }


def run_self_test() -> int:
    sample = "x" * (TELEGRAM_LIMIT + 50)
    chunks = to_telegram_chunks(sample)
    if len(chunks) < 2:
        raise RuntimeError("Chunking self-test failed")

    prompt, _, _, document = extract_prompt_and_media(
        {"document": {"file_id": "f1", "file_name": "sample.txt", "mime_type": "text/plain"}}
    )
    if prompt != "Please analyze this file." or not document or document.file_id != "f1":
        raise RuntimeError("Document parsing self-test failed")

    sample_stream = (
        '{"type":"thread.started","thread_id":"thread-123"}\n'
        '{"type":"item.completed","item":{"type":"agent_message","text":"hello"}}\n'
    )
    parsed_thread, parsed_output = parse_executor_output(sample_stream)
    if parsed_thread != "thread-123" or parsed_output != "hello":
        raise RuntimeError("Executor stream parse self-test failed")

    progress_event = extract_executor_progress_event(
        {
            "type": "item.started",
            "item": {"type": "command_execution", "command": "pwd", "status": "in_progress"},
        }
    )
    if not progress_event or progress_event.kind != "command_started":
        raise RuntimeError("Progress event self-test failed")

    stream_buffer = BoundedTextBuffer(
        96,
        head_chars=24,
        truncation_marker="\n...[truncated]...\n",
    )
    stream_buffer.append("HEAD-CONTENT-")
    stream_buffer.append("x" * 300)
    rendered = stream_buffer.render()
    if len(rendered) > 96 or "...[truncated]..." not in rendered:
        raise RuntimeError("Stream buffer self-test failed")

    restart_state = State()
    status, _ = request_safe_restart(
        restart_state,
        chat_id=1,
        message_thread_id=None,
        reply_to_message_id=None,
    )
    if status != "run_now":
        raise RuntimeError("Restart self-test failed (run_now)")
    finish_restart_attempt(restart_state)
    with restart_state.lock:
        restart_state.busy_chats.add("tg:1")
    status, _ = request_safe_restart(
        restart_state,
        chat_id=1,
        message_thread_id=None,
        reply_to_message_id=None,
    )
    if status != "queued":
        raise RuntimeError("Restart self-test failed (queued)")
    clear_busy(restart_state, "tg:1")
    ready = pop_ready_restart_request(restart_state)
    if not ready or ready[0] != 1:
        raise RuntimeError("Restart self-test failed (pop_ready)")
    finish_restart_attempt(restart_state)

    print("self-test: ok")
    return 0


def load_state_mapping_or_empty(
    path: str,
    loader,
    *,
    description: str,
) -> Dict[object, object]:
    try:
        return loader(path)
    except Exception:
        logging.exception(
            "Failed to load %s from %s; starting with empty state.",
            description,
            path,
        )
        moved = quarantine_corrupt_state_file(path)
        if moved:
            logging.error("Quarantined corrupt %s to %s", description, moved)
        emit_event(
            "bridge.state_load_failed",
            level=logging.WARNING,
            fields={"state_file": path},
        )
        return {}


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


MEDIA_GROUP_QUIET_WINDOW_SECONDS = 2.0


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


def compute_poll_timeout_seconds(state: State, config: Config, *, now: Optional[float] = None) -> Optional[int]:
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


def run_bridge(config: Config) -> int:
    emit_event(
        "bridge.starting",
        fields={
            "allowed_chat_count": len(config.allowed_chat_ids),
            "persistent_workers_enabled": config.persistent_workers_enabled,
            "canonical_sessions_enabled": config.canonical_sessions_enabled,
            "canonical_sqlite_enabled": config.canonical_sqlite_enabled,
            "affective_runtime_enabled": config.affective_runtime_enabled,
        },
    )
    ensure_state_dir(config.state_dir)
    attachment_store = AttachmentStore(
        os.path.join(config.state_dir, "attachments.sqlite3"),
        os.path.join(config.state_dir, "attachments"),
        retention_seconds=config.attachment_retention_seconds,
        max_total_bytes=config.attachment_max_total_bytes,
    )
    memory_engine = MemoryEngine(
        config.memory_sqlite_path,
    )
    affective_runtime = build_affective_runtime(config)
    chat_thread_path = os.path.join(config.state_dir, "chat_threads.json")
    chat_engine_path = os.path.join(config.state_dir, "chat_engines.json")
    chat_codex_model_path = os.path.join(config.state_dir, "chat_codex_models.json")
    chat_codex_effort_path = os.path.join(config.state_dir, "chat_codex_efforts.json")
    chat_pi_provider_path = os.path.join(config.state_dir, "chat_pi_providers.json")
    chat_pi_model_path = os.path.join(config.state_dir, "chat_pi_models.json")
    worker_sessions_path = os.path.join(config.state_dir, "worker_sessions.json")
    in_flight_path = os.path.join(config.state_dir, "in_flight_requests.json")
    chat_sessions_path = os.path.join(config.state_dir, "chat_sessions.json")
    loaded_threads = load_state_mapping_or_empty(
        chat_thread_path,
        load_chat_threads,
        description="chat thread mappings",
    )
    loaded_engines = load_state_mapping_or_empty(
        chat_engine_path,
        load_chat_engines,
        description="chat engine mappings",
    )
    loaded_codex_models = load_state_mapping_or_empty(
        chat_codex_model_path,
        load_chat_codex_models,
        description="chat Codex model mappings",
    )
    loaded_codex_efforts = load_state_mapping_or_empty(
        chat_codex_effort_path,
        load_chat_codex_efforts,
        description="chat Codex effort mappings",
    )
    loaded_pi_models = load_state_mapping_or_empty(
        chat_pi_model_path,
        load_chat_pi_models,
        description="chat Pi model mappings",
    )
    loaded_pi_providers = load_state_mapping_or_empty(
        chat_pi_provider_path,
        load_chat_pi_providers,
        description="chat Pi provider mappings",
    )
    loaded_worker_sessions = load_state_mapping_or_empty(
        worker_sessions_path,
        load_worker_sessions,
        description="worker session state",
    )
    loaded_in_flight = load_state_mapping_or_empty(
        in_flight_path,
        load_in_flight_requests,
        description="in-flight request state",
    )

    loaded_canonical_sessions: Dict[int, CanonicalSession] = {}
    canonical_bootstrap_source = "disabled"
    if config.canonical_sessions_enabled:
        if config.canonical_sqlite_enabled:
            canonical_bootstrap_source = "sqlite"
            try:
                loaded_canonical_sessions = load_canonical_sessions_sqlite(
                    config.canonical_sqlite_path
                )
            except Exception:
                logging.exception(
                    "Failed to load canonical session SQLite state from %s; starting with compatibility snapshot.",
                    config.canonical_sqlite_path,
                )
                moved = quarantine_corrupt_state_file(config.canonical_sqlite_path)
                if moved:
                    logging.error(
                        "Quarantined corrupt canonical session SQLite state file to %s",
                        moved,
                    )
                emit_event(
                    "bridge.state_load_failed",
                    level=logging.WARNING,
                    fields={"state_file": config.canonical_sqlite_path},
                )
                loaded_canonical_sessions = {}
                canonical_bootstrap_source = "sqlite_reset_after_load_failure"

            if not loaded_canonical_sessions:
                import_sessions: Dict[int, CanonicalSession] = {}
                import_source = "none"
                try:
                    import_sessions = load_canonical_sessions(chat_sessions_path)
                except Exception:
                    logging.exception(
                        "Failed to load canonical JSON state from %s during SQLite bootstrap; ignoring JSON source.",
                        chat_sessions_path,
                    )
                    moved = quarantine_corrupt_state_file(chat_sessions_path)
                    if moved:
                        logging.error(
                            "Quarantined corrupt canonical session JSON state file to %s",
                            moved,
                        )
                    emit_event(
                        "bridge.state_load_failed",
                        level=logging.WARNING,
                        fields={"state_file": chat_sessions_path},
                    )
                    import_sessions = {}
                if import_sessions:
                    import_source = "canonical_json"
                else:
                    import_sessions = build_canonical_sessions_from_legacy(
                        loaded_threads,
                        loaded_worker_sessions,
                        loaded_in_flight,
                    )
                    if import_sessions:
                        import_source = "legacy_json"

                try:
                    loaded_canonical_sessions, imported = load_or_import_canonical_sessions_sqlite(
                        config.canonical_sqlite_path,
                        import_sessions=import_sessions,
                    )
                except Exception:
                    logging.exception(
                        "Failed to import/initialize canonical session SQLite state at %s; starting empty.",
                        config.canonical_sqlite_path,
                    )
                    moved = quarantine_corrupt_state_file(config.canonical_sqlite_path)
                    if moved:
                        logging.error(
                            "Quarantined canonical session SQLite state file after import failure to %s",
                            moved,
                        )
                    emit_event(
                        "bridge.state_load_failed",
                        level=logging.WARNING,
                        fields={"state_file": config.canonical_sqlite_path},
                    )
                    loaded_canonical_sessions = {}
                    imported = False
                    canonical_bootstrap_source = "sqlite_reset_after_import_failure"

                if imported:
                    canonical_bootstrap_source = f"sqlite_imported_from_{import_source}"
                elif loaded_canonical_sessions:
                    canonical_bootstrap_source = "sqlite"
                elif not canonical_bootstrap_source.startswith("sqlite_reset"):
                    canonical_bootstrap_source = "sqlite_empty"
        else:
            try:
                loaded_canonical_sessions = load_canonical_sessions(chat_sessions_path)
            except Exception:
                logging.exception(
                    "Failed to load canonical session state from %s; starting with compatibility snapshot.",
                    chat_sessions_path,
                )
                moved = quarantine_corrupt_state_file(chat_sessions_path)
                if moved:
                    logging.error("Quarantined corrupt canonical session state file to %s", moved)
                emit_event(
                    "bridge.state_load_failed",
                    level=logging.WARNING,
                    fields={"state_file": chat_sessions_path},
                )
                loaded_canonical_sessions = {}
                canonical_bootstrap_source = "canonical_json_reset_after_load_failure"
            else:
                if loaded_canonical_sessions:
                    canonical_bootstrap_source = "canonical_json"
                else:
                    canonical_bootstrap_source = "legacy_json_snapshot"

        if loaded_canonical_sessions:
            (
                loaded_threads,
                loaded_worker_sessions,
                loaded_in_flight,
            ) = build_legacy_from_canonical(loaded_canonical_sessions)

    current_policy_fingerprint = ""
    policy_reset_result = {
        "applied": False,
        "previous_policy_fingerprint": "",
        "counts": {"threads": 0, "worker_sessions": 0, "canonical_sessions": 0},
    }
    if config.persistent_workers_policy_files:
        current_policy_fingerprint = compute_policy_fingerprint(
            config.persistent_workers_policy_files
        )
        policy_reset_result = apply_policy_change_thread_reset(
            state_dir=config.state_dir,
            current_policy_fingerprint=current_policy_fingerprint,
            loaded_threads=loaded_threads,
            loaded_worker_sessions=loaded_worker_sessions,
            loaded_canonical_sessions=loaded_canonical_sessions,
        )
        if policy_reset_result["applied"]:
            counts = policy_reset_result["counts"]
            logging.warning(
                "Policy fingerprint changed; cleared stored thread state "
                "(threads=%s worker_sessions=%s canonical_sessions=%s).",
                counts["threads"],
                counts["worker_sessions"],
                counts["canonical_sessions"],
            )
            emit_event(
                "bridge.thread_state_reset_for_policy_change",
                level=logging.WARNING,
                fields={
                    "thread_count": counts["threads"],
                    "worker_session_count": counts["worker_sessions"],
                    "canonical_session_count": counts["canonical_sessions"],
                },
            )
            if getattr(config, "policy_reset_memory_on_change", False):
                memory_reset_counts = memory_engine.hard_reset_all_memory()
                logging.warning(
                    "Policy fingerprint changed; hard-reset bridge memory "
                    "(sessions=%s messages=%s).",
                    memory_reset_counts["sessions"],
                    memory_reset_counts["messages"],
                )
                emit_event(
                    "bridge.memory_reset_for_policy_change",
                    level=logging.WARNING,
                    fields=memory_reset_counts,
                )

    current_auth_fingerprint = compute_current_auth_fingerprint()
    auth_reset_result = apply_auth_change_thread_reset(
        state_dir=config.state_dir,
        current_auth_fingerprint=current_auth_fingerprint,
        loaded_threads=loaded_threads,
        loaded_worker_sessions=loaded_worker_sessions,
        loaded_canonical_sessions=loaded_canonical_sessions,
        memory_engine=memory_engine,
    )
    if auth_reset_result["applied"]:
        counts = auth_reset_result["counts"]
        logging.warning(
            "Auth fingerprint changed; cleared stored thread state "
            "(threads=%s worker_sessions=%s canonical_sessions=%s memory_sessions=%s).",
            counts["threads"],
            counts["worker_sessions"],
            counts["canonical_sessions"],
            counts["memory_sessions"],
        )
        emit_event(
            "bridge.thread_state_reset_for_auth_change",
            level=logging.WARNING,
            fields={
                "thread_count": counts["threads"],
                "worker_session_count": counts["worker_sessions"],
                "canonical_session_count": counts["canonical_sessions"],
                "memory_session_count": counts["memory_sessions"],
            },
        )

    if config.persistent_workers_enabled:
        now = time.time()
        if not current_policy_fingerprint:
            current_policy_fingerprint = compute_policy_fingerprint(
                config.persistent_workers_policy_files
            )
        if not loaded_worker_sessions and loaded_threads:
            loaded_worker_sessions = {
                chat_id: WorkerSession(
                    created_at=now,
                    last_used_at=now,
                    thread_id=thread_id,
                    policy_fingerprint=current_policy_fingerprint,
                )
                for chat_id, thread_id in loaded_threads.items()
            }
        for chat_id, session in loaded_worker_sessions.items():
            if session.thread_id:
                loaded_threads[chat_id] = session.thread_id

    voice_alias_learning_store = None
    if config.voice_alias_learning_enabled:
        try:
            voice_alias_learning_store = VoiceAliasLearningStore(
                path=config.voice_alias_learning_path,
                min_examples=config.voice_alias_learning_min_examples,
                confirmation_window_seconds=config.voice_alias_learning_confirmation_window_seconds,
            )
        except Exception:
            logging.exception(
                "Failed to initialize voice alias learning store at %s; continuing without learning.",
                config.voice_alias_learning_path,
            )
            voice_alias_learning_store = None

    state = State(
        chat_threads=loaded_threads,
        chat_thread_path=chat_thread_path,
        chat_engines=loaded_engines,
        chat_engine_path=chat_engine_path,
        chat_codex_models=loaded_codex_models,
        chat_codex_model_path=chat_codex_model_path,
        chat_codex_efforts=loaded_codex_efforts,
        chat_codex_effort_path=chat_codex_effort_path,
        chat_pi_providers=loaded_pi_providers,
        chat_pi_provider_path=chat_pi_provider_path,
        chat_pi_models=loaded_pi_models,
        chat_pi_model_path=chat_pi_model_path,
        worker_sessions=loaded_worker_sessions,
        worker_sessions_path=worker_sessions_path,
        in_flight_requests=loaded_in_flight,
        in_flight_path=in_flight_path,
        canonical_sessions_enabled=config.canonical_sessions_enabled,
        canonical_legacy_mirror_enabled=config.canonical_legacy_mirror_enabled,
        canonical_sqlite_enabled=(
            config.canonical_sessions_enabled and config.canonical_sqlite_enabled
        ),
        canonical_sqlite_path=config.canonical_sqlite_path,
        canonical_json_mirror_enabled=config.canonical_json_mirror_enabled,
        chat_sessions=loaded_canonical_sessions,
        chat_sessions_path=chat_sessions_path,
        memory_engine=memory_engine,
        affective_runtime=affective_runtime,
        attachment_store=attachment_store,
        voice_alias_learning_store=voice_alias_learning_store,
        auth_fingerprint_path=build_auth_fingerprint_state_path(config.state_dir),
        auth_fingerprint=current_auth_fingerprint,
    )
    state_repo = StateRepository(state)
    registry = build_default_plugin_registry()
    try:
        client = registry.build_channel(config.channel_plugin, config)
        engine: EngineAdapter = registry.build_engine(config.engine_plugin)
    except (KeyError, RuntimeError, ValueError) as exc:
        logging.error(
            "Plugin selection error: channel=%s engine=%s error=%s",
            config.channel_plugin,
            config.engine_plugin,
            exc,
        )
        logging.error(
            "Available plugins: channels=%s engines=%s",
            registry.list_channels(),
            registry.list_engines(),
        )
        emit_event(
            "bridge.plugin_selection_failed",
            level=logging.ERROR,
            fields={
                "channel_plugin": config.channel_plugin,
                "engine_plugin": config.engine_plugin,
                "available_channels": registry.list_channels(),
                "available_engines": registry.list_engines(),
                "error_type": type(exc).__name__,
            },
        )
        return 1

    if config.persistent_workers_enabled and (
        not config.canonical_sessions_enabled or config.canonical_legacy_mirror_enabled
    ):
        persist_chat_threads(state)
        persist_worker_sessions(state)
    if config.canonical_sessions_enabled:
        if not state.chat_sessions:
            state.chat_sessions = build_canonical_sessions_from_legacy(
                state.chat_threads,
                state.worker_sessions,
                state.in_flight_requests,
            )
        persist_canonical_sessions(state)
        mirror_legacy_from_canonical(
            state,
            persist=state.canonical_legacy_mirror_enabled,
        )

    interrupted = state_repo.pop_interrupted_requests()
    if interrupted:
        for scope_key in sorted(interrupted):
            try:
                target = parse_telegram_scope_key(scope_key)
            except ValueError:
                continue
            if target.chat_id not in config.allowed_chat_ids:
                continue
            try:
                client.send_message(
                    target.chat_id,
                    "Your previous request was interrupted because the bridge restarted. "
                    "Please resend it.",
                    message_thread_id=target.message_thread_id,
                )
            except Exception:
                logging.exception(
                    "Failed to send restart-interruption notice for scope=%s",
                    scope_key,
                )
        logging.warning(
            "Detected %s interrupted in-flight request(s) from previous runtime.",
            len(interrupted),
        )
    emit_event(
        "bridge.interrupted_requests_processed",
        fields={"count": len(interrupted)},
    )

    offset = 0
    offset_state_path: Optional[str] = None
    if should_discard_startup_backlog(config):
        try:
            offset = drop_pending_updates(client)
        except Exception:
            logging.exception("Failed to discard queued startup updates; defaulting to offset=0")
            emit_event(
                "bridge.startup_backlog_discard_failed",
                level=logging.WARNING,
            )
            offset = 0
    else:
        try:
            offset, offset_state_path = compute_initial_update_offset(config, client)
        except Exception:
            logging.exception("Failed to restore saved update offset; defaulting to offset=0")
            emit_event(
                "bridge.startup_offset_resume_failed",
                level=logging.WARNING,
                fields={"channel_plugin": config.channel_plugin},
            )
            offset = 0
            offset_state_path = build_update_offset_state_path(config.state_dir, config.channel_plugin)
        emit_event(
            "bridge.startup_backlog_discard_skipped",
            fields={
                "channel_plugin": config.channel_plugin,
                "offset": offset,
            },
        )
        persist_saved_update_offset(offset_state_path, offset)

    logging.info("Bridge started. Allowed chats=%s", sorted(config.allowed_chat_ids))
    logging.info("Channel plugin active=%s", config.channel_plugin)
    logging.info("Engine plugin active=%s", config.engine_plugin)
    logging.info(
        "WhatsApp plugin enabled=%s api_base=%s poll_timeout_seconds=%s",
        config.whatsapp_plugin_enabled,
        config.whatsapp_bridge_api_base,
        config.whatsapp_poll_timeout_seconds,
    )
    logging.info("Executor command=%s", config.executor_cmd)
    logging.info("Loaded %s chat thread mappings from %s", len(loaded_threads), chat_thread_path)
    logging.info(
        "Persistent workers enabled=%s count=%s max=%s idle_expiry=disabled idle_timeout_setting=%ss ignored",
        config.persistent_workers_enabled,
        len(loaded_worker_sessions),
        config.persistent_workers_max,
        config.persistent_workers_idle_timeout_seconds,
    )
    logging.info("Loaded %s in-flight request marker(s) from %s", len(loaded_in_flight), in_flight_path)
    logging.info("Memory SQLite path=%s", config.memory_sqlite_path)
    logging.info(
        "Affective runtime enabled=%s db_path=%s ping_target=%s",
        bool(affective_runtime),
        config.affective_runtime_db_path,
        config.affective_runtime_ping_target,
    )
    logging.info(
        "Attachment archive path=%s retention_seconds=%s max_total_bytes=%s",
        os.path.join(config.state_dir, "attachments.sqlite3"),
        config.attachment_retention_seconds,
        config.attachment_max_total_bytes,
    )
    logging.info(
        "Memory db_path=%s",
        config.memory_sqlite_path,
    )
    logging.info(
        "Voice alias learning enabled=%s path=%s min_examples=%s confirmation_window_seconds=%s",
        bool(voice_alias_learning_store),
        config.voice_alias_learning_path,
        config.voice_alias_learning_min_examples,
        config.voice_alias_learning_confirmation_window_seconds,
    )
    logging.info(
        "Canonical sessions enabled=%s count=%s backend=%s source=%s json_path=%s sqlite_path=%s",
        config.canonical_sessions_enabled,
        len(state.chat_sessions),
        (
            "sqlite"
            if config.canonical_sessions_enabled and config.canonical_sqlite_enabled
            else "json"
        ),
        canonical_bootstrap_source,
        chat_sessions_path,
        config.canonical_sqlite_path,
    )
    logging.info(
        "Canonical legacy mirror enabled=%s canonical_json_mirror_enabled=%s",
        config.canonical_legacy_mirror_enabled,
        config.canonical_json_mirror_enabled,
    )
    emit_event(
        "bridge.started",
        fields={
            "offset": offset,
            "chat_thread_count": len(loaded_threads),
            "worker_session_count": len(loaded_worker_sessions),
            "in_flight_count": len(loaded_in_flight),
            "canonical_session_count": len(state.chat_sessions),
            "canonical_state_backend": (
                "sqlite"
                if config.canonical_sessions_enabled and config.canonical_sqlite_enabled
                else "json"
            ),
            "canonical_bootstrap_source": canonical_bootstrap_source,
            "memory_db_path": config.memory_sqlite_path,
            "attachment_retention_seconds": config.attachment_retention_seconds,
            "attachment_max_total_bytes": config.attachment_max_total_bytes,
            "channel_plugin": config.channel_plugin,
            "engine_plugin": config.engine_plugin,
            "whatsapp_plugin_enabled": config.whatsapp_plugin_enabled,
            "affective_runtime_enabled": bool(affective_runtime),
        },
    )

    while True:
        try:
            expire_idle_worker_sessions(state, config, client)
            ready_updates = flush_ready_media_group_updates(state)
            if ready_updates:
                for update in ready_updates:
                    handle_update(state, config, client, update, engine=engine)
                continue

            poll_timeout_seconds = compute_poll_timeout_seconds(state, config)
            updates = client.get_updates(offset, timeout_seconds=poll_timeout_seconds)
            if not updates and offset_state_path is not None and offset > 0:
                reset_offset = maybe_reset_stale_runtime_offset(config, client, offset)
                if reset_offset != offset:
                    offset = reset_offset
                    persist_saved_update_offset(offset_state_path, offset)
                    continue
            if updates:
                emit_event(
                    "bridge.poll_updates_received",
                    fields={
                        "count": len(updates),
                        "offset_before": offset,
                        "pending_media_group_count": len(state.pending_media_groups),
                        "poll_timeout_seconds": poll_timeout_seconds,
                    },
                )
            for update in updates:
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    offset = max(offset, update_id + 1)
            immediate_updates = buffer_pending_media_group_updates(state, updates)
            for update in immediate_updates:
                handle_update(state, config, client, update, engine=engine)
            if offset_state_path is not None:
                persist_saved_update_offset(offset_state_path, offset)
        except (HTTPError, URLError, TimeoutError):
            logging.exception("Network/API error while polling Telegram")
            emit_event(
                "bridge.poll_error",
                level=logging.WARNING,
                fields={"category": "network_api"},
            )
            time.sleep(config.retry_sleep_seconds)
        except Exception:
            logging.exception("Unexpected loop error")
            emit_event(
                "bridge.poll_error",
                level=logging.WARNING,
                fields={"category": "unexpected"},
            )
            time.sleep(config.retry_sleep_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description="Telegram Architect bridge")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="run local self test and exit",
    )
    args = parser.parse_args()

    configure_bridge_logging(os.getenv("TELEGRAM_LOG_LEVEL", "INFO"))

    if args.self_test:
        return run_self_test()

    try:
        config = load_config()
    except Exception as exc:
        logging.error("Configuration error: %s", exc)
        return 1

    return run_bridge(config)


if __name__ == "__main__":
    raise SystemExit(main())
