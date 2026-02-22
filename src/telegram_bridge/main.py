#!/usr/bin/env python3
"""Telegram long-poll bridge to local Architect/Codex CLI."""

import argparse
import logging
import os
import shlex
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Set
from urllib.error import HTTPError, URLError

try:
    from .executor import (
        ExecutorProgressEvent,
        extract_executor_progress_event,
        parse_executor_output,
    )
    from .handlers import DocumentPayload, extract_prompt_and_media, handle_update
    from .media import TelegramFileDownloadSpec, download_telegram_file_to_temp
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
        build_canonical_sessions_from_legacy,
        build_legacy_from_canonical,
        ensure_state_dir,
        load_canonical_sessions,
        load_chat_threads,
        load_in_flight_requests,
        load_worker_sessions,
        mirror_legacy_from_canonical,
        persist_chat_threads,
        persist_canonical_sessions,
        persist_worker_sessions,
        quarantine_corrupt_state_file,
        sync_all_canonical_sessions,
    )
    from .stream_buffer import BoundedTextBuffer
    from .transport import TELEGRAM_LIMIT, TelegramClient, to_telegram_chunks
except ImportError:
    from executor import (
        ExecutorProgressEvent,
        extract_executor_progress_event,
        parse_executor_output,
    )
    from handlers import DocumentPayload, extract_prompt_and_media, handle_update
    from media import TelegramFileDownloadSpec, download_telegram_file_to_temp
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
        build_canonical_sessions_from_legacy,
        build_legacy_from_canonical,
        ensure_state_dir,
        load_canonical_sessions,
        load_chat_threads,
        load_in_flight_requests,
        load_worker_sessions,
        mirror_legacy_from_canonical,
        persist_chat_threads,
        persist_canonical_sessions,
        persist_worker_sessions,
        quarantine_corrupt_state_file,
        sync_all_canonical_sessions,
    )
    from stream_buffer import BoundedTextBuffer
    from transport import TELEGRAM_LIMIT, TelegramClient, to_telegram_chunks


@dataclass
class Config:
    token: str
    allowed_chat_ids: Set[int]
    api_base: str
    poll_timeout_seconds: int
    retry_sleep_seconds: float
    exec_timeout_seconds: int
    max_input_chars: int
    max_output_chars: int
    max_image_bytes: int
    max_voice_bytes: int
    max_document_bytes: int
    rate_limit_per_minute: int
    executor_cmd: List[str]
    voice_transcribe_cmd: List[str]
    voice_transcribe_timeout_seconds: int
    state_dir: str
    persistent_workers_enabled: bool
    persistent_workers_max: int
    persistent_workers_idle_timeout_seconds: int
    persistent_workers_policy_files: List[str]
    canonical_sessions_enabled: bool
    busy_message: str = "Another request is still running. Please wait."
    denied_message: str = "Access denied for this chat."
    timeout_message: str = "Request timed out. Please try a shorter prompt."
    generic_error_message: str = "Execution failed. Please try again later."
    image_download_error_message: str = "Image download failed. Please send another image."
    voice_download_error_message: str = "Voice download failed. Please send another voice message."
    document_download_error_message: str = "File download failed. Please send another file."
    voice_not_configured_message: str = (
        "Voice transcription is not configured. Please ask admin to set TELEGRAM_VOICE_TRANSCRIBE_CMD."
    )
    voice_transcribe_error_message: str = "Voice transcription failed. Please send clearer audio."
    voice_transcribe_empty_message: str = (
        "Voice transcription was empty. Please send clearer audio."
    )
    empty_output_message: str = "(No output from Architect)"


def parse_int_env(name: str, default: int, minimum: int = 1) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return parsed


def parse_bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in ("1", "true", "yes", "on"):
        return True
    if normalized in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"{name} must be a boolean value")


def parse_allowed_chat_ids(raw: str) -> Set[int]:
    values = [item.strip() for item in raw.split(",") if item.strip()]
    if not values:
        raise ValueError("TELEGRAM_ALLOWED_CHAT_IDS is empty")
    parsed: Set[int] = set()
    for value in values:
        try:
            parsed.add(int(value))
        except ValueError as exc:
            raise ValueError(
                f"Invalid TELEGRAM_ALLOWED_CHAT_IDS value: {value!r}"
            ) from exc
    return parsed


def build_repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def build_policy_watch_files() -> List[str]:
    repo_root = build_repo_root()
    return [
        os.path.join(repo_root, "AGENTS.md"),
        os.path.join(repo_root, "ARCHITECT_INSTRUCTION.md"),
        os.path.join(repo_root, "SERVER3_PROGRESS.md"),
    ]


def build_default_executor() -> str:
    repo_root = build_repo_root()
    return os.path.join(repo_root, "src", "telegram_bridge", "executor.sh")


def parse_executor_cmd() -> List[str]:
    raw = os.getenv("TELEGRAM_EXECUTOR_CMD", "").strip()
    if raw:
        cmd = shlex.split(raw)
        if not cmd:
            raise ValueError("TELEGRAM_EXECUTOR_CMD cannot be blank")
        return cmd
    return [build_default_executor()]


def parse_optional_cmd_env(name: str) -> List[str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return []
    cmd = shlex.split(raw)
    if not cmd:
        raise ValueError(f"{name} cannot be blank")
    return cmd


def load_config() -> Config:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required")

    raw_chat_ids = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").strip()
    if not raw_chat_ids:
        raise ValueError("TELEGRAM_ALLOWED_CHAT_IDS is required")
    state_dir = os.getenv(
        "TELEGRAM_BRIDGE_STATE_DIR",
        "/home/architect/.local/state/telegram-architect-bridge",
    ).strip()
    if not state_dir:
        raise ValueError("TELEGRAM_BRIDGE_STATE_DIR cannot be empty")

    allowed_chat_ids = parse_allowed_chat_ids(raw_chat_ids)

    return Config(
        token=token,
        allowed_chat_ids=allowed_chat_ids,
        api_base=os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/"),
        poll_timeout_seconds=parse_int_env("TELEGRAM_POLL_TIMEOUT_SECONDS", 30),
        retry_sleep_seconds=float(os.getenv("TELEGRAM_RETRY_SLEEP_SECONDS", "3")),
        exec_timeout_seconds=parse_int_env("TELEGRAM_EXEC_TIMEOUT_SECONDS", 36000),
        max_input_chars=parse_int_env("TELEGRAM_MAX_INPUT_CHARS", TELEGRAM_LIMIT),
        max_output_chars=parse_int_env("TELEGRAM_MAX_OUTPUT_CHARS", 20000),
        max_image_bytes=parse_int_env("TELEGRAM_MAX_IMAGE_BYTES", 10 * 1024 * 1024, minimum=1024),
        max_voice_bytes=parse_int_env("TELEGRAM_MAX_VOICE_BYTES", 20 * 1024 * 1024, minimum=1024),
        max_document_bytes=parse_int_env("TELEGRAM_MAX_DOCUMENT_BYTES", 50 * 1024 * 1024, minimum=1024),
        rate_limit_per_minute=parse_int_env("TELEGRAM_RATE_LIMIT_PER_MINUTE", 12),
        executor_cmd=parse_executor_cmd(),
        voice_transcribe_cmd=parse_optional_cmd_env("TELEGRAM_VOICE_TRANSCRIBE_CMD"),
        voice_transcribe_timeout_seconds=parse_int_env(
            "TELEGRAM_VOICE_TRANSCRIBE_TIMEOUT_SECONDS",
            120,
        ),
        state_dir=state_dir,
        persistent_workers_enabled=parse_bool_env(
            "TELEGRAM_PERSISTENT_WORKERS_ENABLED",
            False,
        ),
        persistent_workers_max=parse_int_env(
            "TELEGRAM_PERSISTENT_WORKERS_MAX",
            4,
            minimum=1,
        ),
        persistent_workers_idle_timeout_seconds=parse_int_env(
            "TELEGRAM_PERSISTENT_WORKERS_IDLE_TIMEOUT_SECONDS",
            45 * 60,
            minimum=60,
        ),
        persistent_workers_policy_files=build_policy_watch_files(),
        canonical_sessions_enabled=parse_bool_env(
            "TELEGRAM_CANONICAL_SESSIONS_ENABLED",
            False,
        ),
    )


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


def drop_pending_updates(client: TelegramClient) -> int:
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
    return offset


def run_bridge(config: Config) -> int:
    ensure_state_dir(config.state_dir)
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
        loaded_in_flight = {}

    loaded_canonical_sessions: Dict[int, CanonicalSession] = {}
    if config.canonical_sessions_enabled:
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
            loaded_canonical_sessions = {}

        if loaded_canonical_sessions:
            (
                loaded_threads,
                loaded_worker_sessions,
                loaded_in_flight,
            ) = build_legacy_from_canonical(loaded_canonical_sessions)

    if config.persistent_workers_enabled:
        now = time.time()
        current_policy_fingerprint = compute_policy_fingerprint(config.persistent_workers_policy_files)
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

    state = State(
        chat_threads=loaded_threads,
        chat_thread_path=chat_thread_path,
        worker_sessions=loaded_worker_sessions,
        worker_sessions_path=worker_sessions_path,
        in_flight_requests=loaded_in_flight,
        in_flight_path=in_flight_path,
        canonical_sessions_enabled=config.canonical_sessions_enabled,
        chat_sessions=loaded_canonical_sessions,
        chat_sessions_path=chat_sessions_path,
    )
    state_repo = StateRepository(state)
    client = TelegramClient(config)

    if config.persistent_workers_enabled:
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
        mirror_legacy_from_canonical(state, persist=True)

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

    try:
        offset = drop_pending_updates(client)
    except Exception:
        logging.exception("Failed to discard queued startup updates; defaulting to offset=0")
        offset = 0

    logging.info("Bridge started. Allowed chats=%s", sorted(config.allowed_chat_ids))
    logging.info("Architect-only routing active for all allowlisted chats.")
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
    logging.info(
        "Canonical sessions enabled=%s count=%s path=%s",
        config.canonical_sessions_enabled,
        len(state.chat_sessions),
        chat_sessions_path,
    )

    while True:
        try:
            expire_idle_worker_sessions(state, config, client)
            updates = client.get_updates(offset)
            for update in updates:
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    offset = max(offset, update_id + 1)
                handle_update(state, config, client, update)
        except (HTTPError, URLError, TimeoutError):
            logging.exception("Network/API error while polling Telegram")
            time.sleep(config.retry_sleep_seconds)
        except Exception:
            logging.exception("Unexpected loop error")
            time.sleep(config.retry_sleep_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description="Telegram Architect bridge")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="run local self test and exit",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=os.getenv("TELEGRAM_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s",
    )

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
