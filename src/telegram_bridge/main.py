#!/usr/bin/env python3
"""Telegram long-poll bridge to local Codex CLI."""

import argparse
import logging
import os
import time
from typing import Dict, Optional
from urllib.error import HTTPError, URLError

try:
    from .channel_adapter import ChannelAdapter
    from .executor import (
        ExecutorProgressEvent,
        extract_executor_progress_event,
        parse_executor_output,
    )
    from .engine_adapter import EngineAdapter
    from .handlers import DocumentPayload, extract_prompt_and_media, handle_update
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
        State,
        StateRepository,
        WorkerSession,
        canonical_session_is_empty,
        build_canonical_sessions_from_legacy,
        build_legacy_from_canonical,
        ensure_state_dir,
        load_canonical_sessions,
        load_canonical_sessions_sqlite,
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
    from channel_adapter import ChannelAdapter
    from executor import (
        ExecutorProgressEvent,
        extract_executor_progress_event,
        parse_executor_output,
    )
    from engine_adapter import EngineAdapter
    from handlers import DocumentPayload, extract_prompt_and_media, handle_update
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
        State,
        StateRepository,
        WorkerSession,
        canonical_session_is_empty,
        build_canonical_sessions_from_legacy,
        build_legacy_from_canonical,
        ensure_state_dir,
        load_canonical_sessions,
        load_canonical_sessions_sqlite,
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


def clear_thread_state_for_policy_change(
    loaded_threads: Dict[int, str],
    loaded_worker_sessions: Dict[int, WorkerSession],
    loaded_canonical_sessions: Dict[int, CanonicalSession],
) -> Dict[str, int]:
    cleared_thread_count = sum(1 for thread_id in loaded_threads.values() if thread_id.strip())
    cleared_worker_session_count = len(loaded_worker_sessions)
    cleared_canonical_session_count = 0

    if loaded_threads:
        loaded_threads.clear()
    if loaded_worker_sessions:
        loaded_worker_sessions.clear()

    for chat_id in list(loaded_canonical_sessions):
        session = loaded_canonical_sessions[chat_id]
        changed = False
        if session.thread_id.strip():
            session.thread_id = ""
            changed = True
        if (
            session.worker_created_at is not None
            or session.worker_last_used_at is not None
            or session.worker_policy_fingerprint.strip()
        ):
            session.worker_created_at = None
            session.worker_last_used_at = None
            session.worker_policy_fingerprint = ""
            changed = True
        if changed:
            cleared_canonical_session_count += 1
        if canonical_session_is_empty(session):
            del loaded_canonical_sessions[chat_id]

    return {
        "threads": cleared_thread_count,
        "worker_sessions": cleared_worker_session_count,
        "canonical_sessions": cleared_canonical_session_count,
    }


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
    status, _ = request_safe_restart(restart_state, chat_id=1, reply_to_message_id=None)
    if status != "run_now":
        raise RuntimeError("Restart self-test failed (run_now)")
    finish_restart_attempt(restart_state)
    with restart_state.lock:
        restart_state.busy_chats.add(1)
    status, _ = request_safe_restart(restart_state, chat_id=1, reply_to_message_id=None)
    if status != "queued":
        raise RuntimeError("Restart self-test failed (queued)")
    clear_busy(restart_state, 1)
    ready = pop_ready_restart_request(restart_state)
    if not ready or ready[0] != 1:
        raise RuntimeError("Restart self-test failed (pop_ready)")
    finish_restart_attempt(restart_state)

    print("self-test: ok")
    return 0


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


def run_bridge(config: Config) -> int:
    emit_event(
        "bridge.starting",
        fields={
            "allowed_chat_count": len(config.allowed_chat_ids),
            "persistent_workers_enabled": config.persistent_workers_enabled,
            "canonical_sessions_enabled": config.canonical_sessions_enabled,
            "canonical_sqlite_enabled": config.canonical_sqlite_enabled,
        },
    )
    ensure_state_dir(config.state_dir)
    memory_engine = MemoryEngine(
        config.memory_sqlite_path,
        max_messages_per_key=config.memory_max_messages_per_key,
        max_summaries_per_key=config.memory_max_summaries_per_key,
        prune_interval_seconds=config.memory_prune_interval_seconds,
    )
    chat_thread_path = os.path.join(config.state_dir, "chat_threads.json")
    worker_sessions_path = os.path.join(config.state_dir, "worker_sessions.json")
    in_flight_path = os.path.join(config.state_dir, "in_flight_requests.json")
    chat_sessions_path = os.path.join(config.state_dir, "chat_sessions.json")
    try:
        loaded_threads = load_chat_threads(chat_thread_path)
    except Exception:
        logging.exception(
            "Failed to load chat thread mappings from %s; starting with empty mappings.",
            chat_thread_path,
        )
        moved = quarantine_corrupt_state_file(chat_thread_path)
        if moved:
            logging.error("Quarantined corrupt chat thread state file to %s", moved)
        emit_event(
            "bridge.state_load_failed",
            level=logging.WARNING,
            fields={"state_file": chat_thread_path},
        )
        loaded_threads = {}

    try:
        loaded_worker_sessions = load_worker_sessions(worker_sessions_path)
    except Exception:
        logging.exception(
            "Failed to load worker session state from %s; starting with empty worker sessions.",
            worker_sessions_path,
        )
        moved = quarantine_corrupt_state_file(worker_sessions_path)
        if moved:
            logging.error("Quarantined corrupt worker session state file to %s", moved)
        emit_event(
            "bridge.state_load_failed",
            level=logging.WARNING,
            fields={"state_file": worker_sessions_path},
        )
        loaded_worker_sessions = {}

    try:
        loaded_in_flight = load_in_flight_requests(in_flight_path)
    except Exception:
        logging.exception(
            "Failed to load in-flight request state from %s; starting with empty in-flight state.",
            in_flight_path,
        )
        moved = quarantine_corrupt_state_file(in_flight_path)
        if moved:
            logging.error("Quarantined corrupt in-flight state file to %s", moved)
        emit_event(
            "bridge.state_load_failed",
            level=logging.WARNING,
            fields={"state_file": in_flight_path},
        )
        loaded_in_flight = {}

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
        voice_alias_learning_store=voice_alias_learning_store,
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
        for chat_id in sorted(interrupted):
            if chat_id not in config.allowed_chat_ids:
                continue
            try:
                client.send_message(
                    chat_id,
                    "Your previous request was interrupted because the bridge restarted. "
                    "Please resend it.",
                )
            except Exception:
                logging.exception(
                    "Failed to send restart-interruption notice for chat_id=%s",
                    chat_id,
                )
        logging.warning(
            "Detected %s interrupted in-flight request(s) from previous runtime.",
            len(interrupted),
        )
    emit_event(
        "bridge.interrupted_requests_processed",
        fields={"count": len(interrupted)},
    )

    try:
        offset = drop_pending_updates(client)
    except Exception:
        logging.exception("Failed to discard queued startup updates; defaulting to offset=0")
        emit_event(
            "bridge.startup_backlog_discard_failed",
            level=logging.WARNING,
        )
        offset = 0

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
        "Persistent workers enabled=%s count=%s max=%s idle_timeout=%ss",
        config.persistent_workers_enabled,
        len(loaded_worker_sessions),
        config.persistent_workers_max,
        config.persistent_workers_idle_timeout_seconds,
    )
    logging.info("Loaded %s in-flight request marker(s) from %s", len(loaded_in_flight), in_flight_path)
    logging.info("Memory SQLite path=%s", config.memory_sqlite_path)
    logging.info(
        "Memory retention max_messages_per_key=%s max_summaries_per_key=%s prune_interval_seconds=%s",
        config.memory_max_messages_per_key,
        config.memory_max_summaries_per_key,
        config.memory_prune_interval_seconds,
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
            "memory_max_messages_per_key": config.memory_max_messages_per_key,
            "memory_max_summaries_per_key": config.memory_max_summaries_per_key,
            "memory_prune_interval_seconds": config.memory_prune_interval_seconds,
            "channel_plugin": config.channel_plugin,
            "engine_plugin": config.engine_plugin,
            "whatsapp_plugin_enabled": config.whatsapp_plugin_enabled,
        },
    )

    while True:
        try:
            expire_idle_worker_sessions(state, config, client)
            updates = client.get_updates(offset)
            if updates:
                emit_event(
                    "bridge.poll_updates_received",
                    fields={"count": len(updates), "offset_before": offset},
                )
            for update in updates:
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    offset = max(offset, update_id + 1)
                handle_update(state, config, client, update, engine=engine)
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
