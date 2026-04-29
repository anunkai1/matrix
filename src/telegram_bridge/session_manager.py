import hashlib
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import List, Optional

try:
    from .conversation_scope import build_telegram_scope_key, parse_telegram_scope_key
    from .memory_engine import MemoryEngine
    from .memory_merge import merge_conversation_keys
    from .memory_scope import resolve_memory_conversation_key, resolve_shared_memory_archive_key
    from .runtime_paths import build_shared_core_root, shared_core_path
    from .state_store import (
        CanonicalSession,
        State,
        StateRepository,
        WorkerSession,
        canonical_session_is_empty,
        mirror_legacy_from_canonical,
        persist_canonical_sessions,
        persist_chat_threads,
        persist_worker_sessions,
        sync_canonical_session,
    )
    from .structured_logging import emit_event
except ImportError:
    from conversation_scope import build_telegram_scope_key, parse_telegram_scope_key
    from memory_engine import MemoryEngine
    from memory_merge import merge_conversation_keys
    from memory_scope import resolve_memory_conversation_key, resolve_shared_memory_archive_key
    from runtime_paths import build_shared_core_root, shared_core_path
    from state_store import (
        CanonicalSession,
        State,
        StateRepository,
        WorkerSession,
        canonical_session_is_empty,
        mirror_legacy_from_canonical,
        persist_canonical_sessions,
        persist_chat_threads,
        persist_worker_sessions,
        sync_canonical_session,
    )
    from structured_logging import emit_event


def build_repo_root() -> str:
    return build_shared_core_root()


def _legacy_scope_alias(scope_key: str) -> Optional[int]:
    try:
        target = parse_telegram_scope_key(scope_key)
    except ValueError:
        return None
    if target.message_thread_id is not None:
        return None
    return target.chat_id


def _resolve_scope_key(
    scope_key: Optional[str],
    chat_id: int,
    message_thread_id: Optional[int],
) -> str:
    if scope_key:
        return scope_key
    return build_telegram_scope_key(chat_id, message_thread_id=message_thread_id)


def _normalize_scope_key(scope_key: object) -> str:
    if isinstance(scope_key, int):
        return build_telegram_scope_key(scope_key)
    return str(scope_key or "").strip()


def _scope_is_busy(state: State, scope_key: object) -> bool:
    normalized_scope_key = _normalize_scope_key(scope_key)
    legacy_alias = _legacy_scope_alias(normalized_scope_key)
    return normalized_scope_key in state.busy_chats or (
        legacy_alias is not None and legacy_alias in state.busy_chats
    )


def build_restart_script_path() -> str:
    configured = os.getenv("TELEGRAM_RESTART_SCRIPT", "").strip()
    if configured:
        return configured
    return shared_core_path("ops", "telegram-bridge", "restart_and_verify.sh")


def build_restart_unit_name() -> str:
    for env_name in ("TELEGRAM_RESTART_UNIT", "UNIT_NAME"):
        configured = os.getenv(env_name, "").strip()
        if configured:
            return configured
    return "telegram-architect-bridge.service"


def compute_policy_fingerprint(paths: List[str]) -> str:
    hasher = hashlib.sha256()
    for file_path in paths:
        hasher.update(file_path.encode("utf-8"))
        hasher.update(b"\0")
        try:
            stats = os.stat(file_path)
            hasher.update(str(stats.st_mtime_ns).encode("utf-8"))
            hasher.update(b":")
            hasher.update(str(stats.st_size).encode("utf-8"))
        except OSError:
            hasher.update(b"missing")
        hasher.update(b"\0")
    return hasher.hexdigest()


def is_rate_limited(state: State, config, scope_key: str) -> bool:
    now = time.time()
    legacy_alias = _legacy_scope_alias(scope_key)
    with state.lock:
        entries = state.recent_requests.get(scope_key)
        if entries is None and legacy_alias is not None:
            entries = state.recent_requests.pop(legacy_alias, None)
            if entries is not None:
                state.recent_requests[scope_key] = entries
        if entries is None:
            entries = state.recent_requests.setdefault(scope_key, [])
        threshold = now - 60
        entries[:] = [t for t in entries if t >= threshold]
        if len(entries) >= config.rate_limit_per_minute:
            return True
        entries.append(now)
    return False


def mark_busy(state: State, scope_key: str) -> bool:
    legacy_alias = _legacy_scope_alias(scope_key)
    with state.lock:
        if scope_key in state.busy_chats:
            return False
        if legacy_alias is not None and legacy_alias in state.busy_chats:
            return False
        state.busy_chats.add(scope_key)
        if legacy_alias is not None:
            state.busy_chats.discard(legacy_alias)
    return True


def clear_busy(state: State, scope_key: str) -> None:
    legacy_alias = _legacy_scope_alias(scope_key)
    with state.lock:
        state.busy_chats.discard(scope_key)
        if legacy_alias is not None:
            state.busy_chats.discard(legacy_alias)


def _has_active_worker(session: Optional[CanonicalSession]) -> bool:
    return (
        session is not None
        and session.worker_created_at is not None
        and session.worker_last_used_at is not None
    )


WORKER_EVICTED_MESSAGE = (
    "Your session was closed to free worker capacity. "
    "Send a new message to start a fresh context."
)
WORKER_POLICY_REFRESH_MESSAGE = (
    "Policy/context files changed. Your previous session was reset and this request "
    "will continue in a new session."
)
WORKER_CAPACITY_REJECTED_MESSAGE = "All workers are currently in use. Please wait and retry."
POLICY_FINGERPRINT_CACHE_TTL_SECONDS = 10.0

_policy_fingerprint_cache_lock = threading.Lock()
_policy_fingerprint_cache: dict[tuple[str, ...], tuple[float, str]] = {}


@dataclass
class WorkerSessionEnsureOutcome:
    allowed: bool
    evicted_idle_scope_key: Optional[str] = None
    session_replaced_for_policy: bool = False


def _normalize_policy_fingerprint_paths(paths: List[str]) -> tuple[str, ...]:
    return tuple(sorted({str(path) for path in paths if str(path).strip()}))


def _send_worker_eviction_notice(client, scope_key: str) -> None:
    try:
        target = parse_telegram_scope_key(scope_key)
    except ValueError:
        logging.warning("Skipping worker-eviction notice for non-Telegram scope=%s", scope_key)
        return
    try:
        client.send_message(
            target.chat_id,
            WORKER_EVICTED_MESSAGE,
            message_thread_id=target.message_thread_id,
        )
    except Exception:
        logging.exception("Failed to send worker-eviction notice for scope=%s", scope_key)


def _send_policy_refresh_notice(
    client,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
) -> None:
    try:
        client.send_message(
            chat_id,
            WORKER_POLICY_REFRESH_MESSAGE,
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
    except Exception:
        logging.exception("Failed to send policy-refresh notice for chat_id=%s", chat_id)


def _archive_expired_chat_memory(state: State, config, client, scope_key: str) -> None:
    channel_name = getattr(client, "channel_name", "telegram")
    archive_key = resolve_shared_memory_archive_key(config, channel_name)
    if not archive_key:
        return
    memory_engine = state.memory_engine
    if not isinstance(memory_engine, MemoryEngine):
        return
    live_key = resolve_memory_conversation_key(config, channel_name, scope_key)
    if not live_key or live_key == archive_key:
        return

    try:
        status = memory_engine.get_status(live_key)
    except Exception:
        logging.exception("Failed to read live memory status before expiry for scope=%s", scope_key)
        return

    if (
        status.message_count <= 0
        and status.active_fact_count <= 0
        and status.summary_count <= 0
        and not status.session_active
    ):
        return

    try:
        result = merge_conversation_keys(
            db_path=memory_engine.db_path,
            source_keys=[live_key],
            target_key=archive_key,
            allow_existing_target=True,
            force_summarize_target=True,
            min_message_score=0.75,
        )
        memory_engine.clear_session(live_key)
        emit_event(
            "bridge.memory_archived_on_expiry",
            fields={
                "scope_key": scope_key,
                "source_key": live_key,
                "target_key": archive_key,
                "messages_copied": result.messages_copied,
                "facts_merged": result.facts_merged,
                "summaries_generated": result.summaries_generated,
            },
        )
    except Exception:
        logging.exception("Failed to archive expired live memory for scope=%s", scope_key)


def get_cached_policy_fingerprint(paths: List[str], now: Optional[float] = None) -> str:
    if not paths:
        return compute_policy_fingerprint(paths)

    normalized_paths = _normalize_policy_fingerprint_paths(paths)
    if not normalized_paths:
        return compute_policy_fingerprint([])

    key = normalized_paths
    current = time.time() if now is None else now
    with _policy_fingerprint_cache_lock:
        cached = _policy_fingerprint_cache.get(key)
        if cached is not None:
            expires_at, value = cached
            if current < expires_at:
                return value

    value = compute_policy_fingerprint(list(normalized_paths))
    with _policy_fingerprint_cache_lock:
        _policy_fingerprint_cache[key] = (
            current + POLICY_FINGERPRINT_CACHE_TTL_SECONDS,
            value,
        )
    return value


def _ensure_chat_worker_session_canonical(
    state: State,
    config,
    scope_key: str,
    now: float,
    current_policy_fingerprint: str,
) -> WorkerSessionEnsureOutcome:
    session_replaced_for_policy = False
    evicted_idle_scope_key: Optional[str] = None
    rejected_for_capacity = False

    changed = False
    with state.lock:
        session = state.chat_sessions.get(scope_key)

        if (
            _has_active_worker(session)
            and session is not None
            and session.worker_policy_fingerprint
            and session.worker_policy_fingerprint != current_policy_fingerprint
        ):
            session.worker_created_at = None
            session.worker_last_used_at = None
            session.worker_policy_fingerprint = ""
            session.thread_id = ""
            if canonical_session_is_empty(session):
                del state.chat_sessions[scope_key]
                session = None
            session_replaced_for_policy = True
            changed = True

        active_workers = {
            candidate_scope_key: candidate_session
            for candidate_scope_key, candidate_session in state.chat_sessions.items()
            if _has_active_worker(candidate_session)
        }

        if not _has_active_worker(session) and len(active_workers) >= config.persistent_workers_max:
            idle_candidates = [
                (candidate_scope_key, candidate_session)
                for candidate_scope_key, candidate_session in active_workers.items()
                if not _scope_is_busy(state, candidate_scope_key) and candidate_scope_key != scope_key
            ]
            if idle_candidates:
                idle_candidates.sort(
                    key=lambda item: item[1].worker_last_used_at if item[1].worker_last_used_at is not None else 0.0
                )
                evicted_idle_scope_key = idle_candidates[0][0]
                evicted = state.chat_sessions.get(evicted_idle_scope_key)
                if evicted is not None:
                    evicted.worker_created_at = None
                    evicted.worker_last_used_at = None
                    evicted.worker_policy_fingerprint = ""
                    evicted.thread_id = ""
                    if canonical_session_is_empty(evicted):
                        del state.chat_sessions[evicted_idle_scope_key]
                    changed = True
            else:
                rejected_for_capacity = True

        if not rejected_for_capacity:
            session = state.chat_sessions.get(scope_key)
            if session is None:
                session = CanonicalSession()
                state.chat_sessions[scope_key] = session
                changed = True

            if not _has_active_worker(session):
                session.worker_created_at = now
                session.worker_last_used_at = now
                session.worker_policy_fingerprint = current_policy_fingerprint
                changed = True
            else:
                if session.worker_last_used_at != now:
                    session.worker_last_used_at = now
                    changed = True
                if session.worker_policy_fingerprint != current_policy_fingerprint:
                    session.worker_policy_fingerprint = current_policy_fingerprint
                    changed = True

    if changed:
        persist_canonical_sessions(state)
        mirror_legacy_from_canonical(
            state,
            persist=state.canonical_legacy_mirror_enabled,
        )

    return WorkerSessionEnsureOutcome(
        allowed=not rejected_for_capacity,
        evicted_idle_scope_key=evicted_idle_scope_key,
        session_replaced_for_policy=session_replaced_for_policy,
    )


def _ensure_chat_worker_session_legacy(
    state: State,
    config,
    scope_key: str,
    now: float,
    current_policy_fingerprint: str,
) -> WorkerSessionEnsureOutcome:
    session_replaced_for_policy = False
    evicted_idle_scope_key: Optional[str] = None
    rejected_for_capacity = False

    needs_persist_threads = False
    needs_persist_sessions = False

    with state.lock:
        session = state.worker_sessions.get(scope_key)

        if (
            session is not None
            and session.policy_fingerprint
            and session.policy_fingerprint != current_policy_fingerprint
        ):
            del state.worker_sessions[scope_key]
            if scope_key in state.chat_threads:
                del state.chat_threads[scope_key]
                needs_persist_threads = True
            session = None
            session_replaced_for_policy = True
            needs_persist_sessions = True

        if session is None and len(state.worker_sessions) >= config.persistent_workers_max:
            idle_candidates = [
                (candidate_scope_key, candidate_session)
                for candidate_scope_key, candidate_session in state.worker_sessions.items()
                if not _scope_is_busy(state, candidate_scope_key) and candidate_scope_key != scope_key
            ]
            if idle_candidates:
                idle_candidates.sort(key=lambda item: item[1].last_used_at)
                evicted_idle_scope_key = idle_candidates[0][0]
                del state.worker_sessions[evicted_idle_scope_key]
                if evicted_idle_scope_key in state.chat_threads:
                    del state.chat_threads[evicted_idle_scope_key]
                    needs_persist_threads = True
                needs_persist_sessions = True
            else:
                rejected_for_capacity = True

        if not rejected_for_capacity:
            session = state.worker_sessions.get(scope_key)
            if session is None:
                seed_thread_id = state.chat_threads.get(scope_key, "")
                state.worker_sessions[scope_key] = WorkerSession(
                    created_at=now,
                    last_used_at=now,
                    thread_id=seed_thread_id,
                    policy_fingerprint=current_policy_fingerprint,
                )
                needs_persist_sessions = True
            else:
                session.last_used_at = now
                session.policy_fingerprint = current_policy_fingerprint
                session.thread_id = state.chat_threads.get(scope_key, session.thread_id)
                needs_persist_sessions = True

    if needs_persist_threads:
        persist_chat_threads(state)
    if needs_persist_sessions:
        persist_worker_sessions(state)
    if state.canonical_sessions_enabled:
        sync_canonical_session(state, scope_key)
        if evicted_idle_scope_key is not None:
            sync_canonical_session(state, evicted_idle_scope_key)

    return WorkerSessionEnsureOutcome(
        allowed=not rejected_for_capacity,
        evicted_idle_scope_key=evicted_idle_scope_key,
        session_replaced_for_policy=session_replaced_for_policy,
    )


def ensure_chat_worker_session(
    state: State,
    config,
    client,
    scope_key: Optional[str] = None,
    chat_id: int = 0,
    message_thread_id: Optional[int] = None,
    message_id: Optional[int] = None,
) -> bool:
    scope_key = _resolve_scope_key(scope_key, chat_id, message_thread_id)
    if not config.persistent_workers_enabled:
        return True

    now = time.time()
    current_policy_fingerprint = get_cached_policy_fingerprint(
        config.persistent_workers_policy_files,
        now=now,
    )

    if state.canonical_sessions_enabled:
        outcome = _ensure_chat_worker_session_canonical(
            state=state,
            config=config,
            scope_key=scope_key,
            now=now,
            current_policy_fingerprint=current_policy_fingerprint,
        )
    else:
        outcome = _ensure_chat_worker_session_legacy(
            state=state,
            config=config,
            scope_key=scope_key,
            now=now,
            current_policy_fingerprint=current_policy_fingerprint,
        )

    if outcome.evicted_idle_scope_key is not None:
        try:
            evicted_target = parse_telegram_scope_key(outcome.evicted_idle_scope_key)
        except ValueError:
            evicted_target = None
        if evicted_target is not None and evicted_target.chat_id in config.allowed_chat_ids:
            _send_worker_eviction_notice(client, outcome.evicted_idle_scope_key)
            emit_event(
                "bridge.worker_evicted_for_capacity",
                level=logging.WARNING,
                fields={
                    "request_scope_key": scope_key,
                    "request_chat_id": chat_id,
                    "evicted_scope_key": outcome.evicted_idle_scope_key,
                    "evicted_chat_id": evicted_target.chat_id,
                },
            )

    if outcome.session_replaced_for_policy:
        _send_policy_refresh_notice(client, chat_id, message_thread_id, message_id)
        emit_event(
            "bridge.worker_reset_for_policy_change",
            fields={"chat_id": chat_id, "message_id": message_id, "scope_key": scope_key},
        )

    if not outcome.allowed:
        client.send_message(
            chat_id,
            WORKER_CAPACITY_REJECTED_MESSAGE,
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        emit_event(
            "bridge.worker_capacity_rejected",
            level=logging.WARNING,
            fields={"chat_id": chat_id, "message_id": message_id, "scope_key": scope_key},
        )
        return False
    return True


def expire_idle_worker_sessions(
    state: State,
    config,
    client,
) -> None:
    return


def request_safe_restart(
    state: State,
    chat_id: int,
    message_thread_id: Optional[int],
    reply_to_message_id: Optional[int],
) -> tuple[str, int]:
    with state.lock:
        busy_count = len(state.busy_chats)
        if state.restart_in_progress:
            emit_event(
                "bridge.restart_state_checked",
                fields={"chat_id": chat_id, "status": "in_progress", "busy_count": busy_count},
            )
            return "in_progress", busy_count
        if state.restart_requested:
            emit_event(
                "bridge.restart_state_checked",
                fields={"chat_id": chat_id, "status": "already_queued", "busy_count": busy_count},
            )
            return "already_queued", busy_count

        state.restart_chat_id = chat_id
        state.restart_message_thread_id = message_thread_id
        state.restart_reply_to_message_id = reply_to_message_id
        if busy_count > 0:
            state.restart_requested = True
            emit_event(
                "bridge.restart_state_checked",
                fields={"chat_id": chat_id, "status": "queued", "busy_count": busy_count},
            )
            return "queued", busy_count

        state.restart_in_progress = True
        emit_event(
            "bridge.restart_state_checked",
            fields={"chat_id": chat_id, "status": "run_now", "busy_count": busy_count},
        )
        return "run_now", busy_count


def pop_ready_restart_request(state: State) -> Optional[tuple[int, Optional[int], Optional[int]]]:
    with state.lock:
        if state.restart_in_progress:
            return None
        if not state.restart_requested:
            return None
        if state.busy_chats:
            return None
        if state.restart_chat_id is None:
            return None

        state.restart_requested = False
        state.restart_in_progress = True
        return (
            state.restart_chat_id,
            state.restart_message_thread_id,
            state.restart_reply_to_message_id,
        )


def finish_restart_attempt(state: State) -> None:
    with state.lock:
        state.restart_in_progress = False


def run_restart_script(
    state: State,
    client,
    chat_id: int,
    message_thread_id: Optional[int],
    reply_to_message_id: Optional[int],
) -> None:
    script_path = build_restart_script_path()
    restart_unit = build_restart_unit_name()
    emit_event(
        "bridge.restart_script_started",
        fields={"chat_id": chat_id, "script_path": script_path, "restart_unit": restart_unit},
    )
    try:
        result = subprocess.run(
            ["bash", script_path, "--unit", restart_unit],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logging.error("Bridge restart command timed out.")
        emit_event(
            "bridge.restart_script_failed",
            level=logging.ERROR,
            fields={"chat_id": chat_id, "reason": "timeout"},
        )
        client.send_message(
            chat_id,
            "Restart command timed out. Please run restart manually.",
            reply_to_message_id=reply_to_message_id,
            message_thread_id=message_thread_id,
        )
        finish_restart_attempt(state)
        return
    except Exception:
        logging.exception("Bridge restart command failed to execute.")
        emit_event(
            "bridge.restart_script_failed",
            level=logging.ERROR,
            fields={"chat_id": chat_id, "reason": "execution_exception"},
        )
        client.send_message(
            chat_id,
            "Restart command failed to execute. Please run restart manually.",
            reply_to_message_id=reply_to_message_id,
            message_thread_id=message_thread_id,
        )
        finish_restart_attempt(state)
        return

    if result.returncode != 0:
        logging.error(
            "Bridge restart command failed returncode=%s stderr=%r",
            result.returncode,
            (result.stderr or "")[-1000:],
        )
        emit_event(
            "bridge.restart_script_failed",
            level=logging.ERROR,
            fields={"chat_id": chat_id, "reason": "nonzero_exit", "returncode": result.returncode},
        )
        client.send_message(
            chat_id,
            (
                "Restart failed. Please run "
                f"`bash {script_path} --unit {restart_unit}`."
            ),
            reply_to_message_id=reply_to_message_id,
            message_thread_id=message_thread_id,
        )
        finish_restart_attempt(state)
        return

    # If this process survives a successful restart command invocation,
    # clear restart state so future restart requests are not blocked.
    emit_event(
        "bridge.restart_script_succeeded",
        fields={"chat_id": chat_id},
    )
    finish_restart_attempt(state)


def trigger_restart_async(
    state: State,
    client,
    chat_id: int,
    message_thread_id: Optional[int],
    reply_to_message_id: Optional[int],
) -> None:
    worker = threading.Thread(
        target=run_restart_script,
        args=(state, client, chat_id, message_thread_id, reply_to_message_id),
        daemon=True,
    )
    worker.start()


def finalize_chat_work(
    state: State,
    client,
    chat_id: int,
    scope_key: Optional[str] = None,
    message_thread_id: Optional[int] = None,
) -> None:
    scope_key = _resolve_scope_key(scope_key, chat_id, message_thread_id)
    state_repo = StateRepository(state)
    try:
        state_repo.clear_in_flight_request(scope_key)
    except Exception:
        logging.exception("Failed to clear in-flight request state for scope=%s", scope_key)
    finally:
        clear_busy(state, scope_key)
    emit_event(
        "bridge.chat_work_finalized",
        fields={"chat_id": chat_id, "scope_key": scope_key},
    )
    ready_restart = pop_ready_restart_request(state)
    if not ready_restart:
        return

    restart_chat_id, restart_message_thread_id, restart_reply_to = ready_restart
    try:
        client.send_message(
            restart_chat_id,
            "Current request completed. Restarting bridge now.",
            reply_to_message_id=restart_reply_to,
            message_thread_id=restart_message_thread_id,
        )
    except Exception:
        logging.exception(
            "Failed to send queued restart acknowledgement for chat_id=%s",
            restart_chat_id,
        )
    trigger_restart_async(
        state,
        client,
        restart_chat_id,
        restart_message_thread_id,
        restart_reply_to,
    )
    emit_event(
        "bridge.restart_triggered_after_work",
        fields={"completed_chat_id": chat_id, "completed_scope_key": scope_key, "restart_chat_id": restart_chat_id},
    )
