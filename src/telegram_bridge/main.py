#!/usr/bin/env python3
"""Telegram long-poll bridge to local Codex CLI."""

import argparse
import logging
import os
import time
from typing import Optional
from urllib.error import HTTPError, URLError

from telegram_bridge.bridge_state_bootstrap import (
    build_policy_fingerprint_state_path,
    build_update_offset_state_path,
    load_canonical_session_bootstrap,
    load_saved_update_offset,
    persist_saved_update_offset,
)
from telegram_bridge.bridge_polling import (
    buffer_pending_media_group_updates,
    compute_initial_update_offset,
    compute_poll_timeout_seconds,
    drop_pending_updates,
    flush_ready_media_group_updates,
    maybe_reset_stale_runtime_offset,
    should_discard_startup_backlog,
    should_reset_saved_update_offset,
    should_resume_saved_update_offset,
)
from telegram_bridge.bridge_runtime_setup import (
    RuntimeBootstrap,
    apply_policy_change_thread_reset,
    build_runtime_bootstrap,
    clear_thread_state_for_policy_change,
    persist_bootstrap_state,
)
from telegram_bridge.conversation_scope import parse_telegram_scope_key
from telegram_bridge.executor import (
    ExecutorProgressEvent,
    extract_executor_progress_event,
    parse_executor_output,
)
from telegram_bridge.engine_adapter import EngineAdapter
from telegram_bridge.handlers import (
    DocumentPayload,
    extract_prompt_and_media,
    handle_update,
)
from telegram_bridge.media import TelegramFileDownloadSpec, download_telegram_file_to_temp
from telegram_bridge.plugin_registry import build_default_plugin_registry
from telegram_bridge.runtime_config import (
    Config,
    default_voice_alias_replacements,
    load_config,
    parse_plugin_name_env,
)
from telegram_bridge.session_manager import (
    clear_busy,
    compute_policy_fingerprint,
    ensure_chat_worker_session,
    expire_idle_worker_sessions,
    finish_restart_attempt,
    pop_ready_restart_request,
    request_safe_restart,
)
from telegram_bridge.state_store import (
    CanonicalSession,
    PendingMediaGroup,
    State,
    StateRepository,
    WorkerSession,
    canonical_session_is_empty,
    build_canonical_sessions_from_legacy,
    build_legacy_from_canonical,
    load_canonical_sessions,
    load_canonical_sessions_sqlite,
    load_or_import_canonical_sessions_sqlite,
    mirror_legacy_from_canonical,
    pop_interrupted_requests,
    persist_canonical_sessions,
    sync_all_canonical_sessions,
)
from telegram_bridge.stream_buffer import BoundedTextBuffer
from telegram_bridge.structured_logging import configure_bridge_logging, emit_event
from telegram_bridge.transport import TELEGRAM_LIMIT, TelegramClient, to_telegram_chunks

__all__ = [
    "CanonicalSession",
    "PendingMediaGroup",
    "RuntimeBootstrap",
    "StateRepository",
    "WorkerSession",
    "apply_policy_change_thread_reset",
    "buffer_pending_media_group_updates",
    "build_policy_fingerprint_state_path",
    "build_canonical_sessions_from_legacy",
    "build_legacy_from_canonical",
    "clear_thread_state_for_policy_change",
    "compute_initial_update_offset",
    "compute_poll_timeout_seconds",
    "compute_policy_fingerprint",
    "drop_pending_updates",
    "ensure_chat_worker_session",
    "flush_ready_media_group_updates",
    "load_canonical_session_bootstrap",
    "load_canonical_sessions",
    "load_canonical_sessions_sqlite",
    "load_or_import_canonical_sessions_sqlite",
    "load_saved_update_offset",
    "main",
    "maybe_reset_stale_runtime_offset",
    "mirror_legacy_from_canonical",
    "persist_canonical_sessions",
    "run_bridge",
    "run_self_test",
    "should_discard_startup_backlog",
    "should_reset_saved_update_offset",
    "should_resume_saved_update_offset",
    "sync_all_canonical_sessions",
]

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
    bootstrap: RuntimeBootstrap = build_runtime_bootstrap(config)
    state_paths = bootstrap.state_paths
    state = bootstrap.state
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

    persist_bootstrap_state(config, bootstrap)

    interrupted = pop_interrupted_requests(state)
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
    logging.info(
        "Loaded %s chat thread mappings from %s",
        len(bootstrap.loaded_threads),
        state_paths["chat_threads"],
    )
    logging.info(
        "Persistent workers enabled=%s count=%s max=%s idle_expiry=%s idle_timeout_setting=%ss",
        config.persistent_workers_enabled,
        len(bootstrap.loaded_worker_sessions),
        config.persistent_workers_max,
        (
            "enabled"
            if config.persistent_workers_enabled and config.persistent_workers_idle_timeout_seconds > 0
            else "disabled"
        ),
        config.persistent_workers_idle_timeout_seconds,
    )
    logging.info(
        "Loaded %s in-flight request marker(s) from %s",
        len(bootstrap.loaded_in_flight),
        state_paths["in_flight_requests"],
    )
    logging.info(
        "Affective runtime enabled=%s db_path=%s ping_target=%s",
        bool(bootstrap.affective_runtime),
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
        "Voice alias learning enabled=%s path=%s min_examples=%s confirmation_window_seconds=%s",
        bool(bootstrap.voice_alias_learning_store),
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
        bootstrap.canonical_bootstrap_source,
        state_paths["chat_sessions"],
        config.canonical_sqlite_path,
    )
    logging.info(
        "Canonical legacy mirror configured=%s (live mirroring disabled) canonical_json_mirror_enabled=%s",
        config.canonical_legacy_mirror_enabled,
        config.canonical_json_mirror_enabled,
    )
    emit_event(
        "bridge.started",
        fields={
            "offset": offset,
            "chat_thread_count": len(bootstrap.loaded_threads),
            "worker_session_count": len(bootstrap.loaded_worker_sessions),
            "in_flight_count": len(bootstrap.loaded_in_flight),
            "canonical_session_count": len(state.chat_sessions),
            "canonical_state_backend": (
                "sqlite"
                if config.canonical_sessions_enabled and config.canonical_sqlite_enabled
                else "json"
            ),
            "canonical_bootstrap_source": bootstrap.canonical_bootstrap_source,
            "attachment_retention_seconds": config.attachment_retention_seconds,
            "attachment_max_total_bytes": config.attachment_max_total_bytes,
            "channel_plugin": config.channel_plugin,
            "engine_plugin": config.engine_plugin,
            "whatsapp_plugin_enabled": config.whatsapp_plugin_enabled,
            "affective_runtime_enabled": bool(bootstrap.affective_runtime),
        },
    )

    while True:
        try:
            expire_idle_worker_sessions(state, config, client)
            ready_updates = flush_ready_media_group_updates(state)
            if ready_updates:
                for update in ready_updates:
                    handle_update(
                        state,
                        config,
                        client,
                        update,
                        engine=engine,
                        update_flow_dependencies=bootstrap.update_flow_dependencies,
                    )
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
                handle_update(
                    state,
                    config,
                    client,
                    update,
                    engine=engine,
                    update_flow_dependencies=bootstrap.update_flow_dependencies,
                )
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
