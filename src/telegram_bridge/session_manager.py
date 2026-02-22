import hashlib
import logging
import os
import subprocess
import threading
import time
from typing import List, Optional

try:
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
except ImportError:
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


def build_repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def build_restart_script_path() -> str:
    repo_root = build_repo_root()
    return os.path.join(repo_root, "ops", "telegram-bridge", "restart_and_verify.sh")


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


def is_rate_limited(state: State, config, chat_id: int) -> bool:
    now = time.time()
    with state.lock:
        entries = state.recent_requests.setdefault(chat_id, [])
        threshold = now - 60
        entries[:] = [t for t in entries if t >= threshold]
        if len(entries) >= config.rate_limit_per_minute:
            return True
        entries.append(now)
    return False


def mark_busy(state: State, chat_id: int) -> bool:
    with state.lock:
        if chat_id in state.busy_chats:
            return False
        state.busy_chats.add(chat_id)
    return True


def clear_busy(state: State, chat_id: int) -> None:
    with state.lock:
        state.busy_chats.discard(chat_id)


def _has_active_worker(session: Optional[CanonicalSession]) -> bool:
    return (
        session is not None
        and session.worker_created_at is not None
        and session.worker_last_used_at is not None
    )


def ensure_chat_worker_session(
    state: State,
    config,
    client,
    chat_id: int,
    message_id: Optional[int],
) -> bool:
    if not config.persistent_workers_enabled:
        return True

    now = time.time()
    current_policy_fingerprint = compute_policy_fingerprint(config.persistent_workers_policy_files)
    session_replaced_for_policy = False
    evicted_idle_chat_id: Optional[int] = None
    rejected_for_capacity = False

    if state.canonical_sessions_enabled:
        changed = False
        with state.lock:
            session = state.chat_sessions.get(chat_id)

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
                    del state.chat_sessions[chat_id]
                    session = None
                session_replaced_for_policy = True
                changed = True

            active_workers = {
                candidate_chat_id: candidate_session
                for candidate_chat_id, candidate_session in state.chat_sessions.items()
                if _has_active_worker(candidate_session)
            }

            if not _has_active_worker(session) and len(active_workers) >= config.persistent_workers_max:
                idle_candidates = [
                    (candidate_chat_id, candidate_session)
                    for candidate_chat_id, candidate_session in active_workers.items()
                    if candidate_chat_id not in state.busy_chats and candidate_chat_id != chat_id
                ]
                if idle_candidates:
                    idle_candidates.sort(
                        key=lambda item: item[1].worker_last_used_at
                        if item[1].worker_last_used_at is not None
                        else 0.0
                    )
                    evicted_idle_chat_id = idle_candidates[0][0]
                    evicted = state.chat_sessions.get(evicted_idle_chat_id)
                    if evicted is not None:
                        evicted.worker_created_at = None
                        evicted.worker_last_used_at = None
                        evicted.worker_policy_fingerprint = ""
                        evicted.thread_id = ""
                        if canonical_session_is_empty(evicted):
                            del state.chat_sessions[evicted_idle_chat_id]
                        changed = True
                else:
                    rejected_for_capacity = True

            if not rejected_for_capacity:
                session = state.chat_sessions.get(chat_id)
                if session is None:
                    session = CanonicalSession()
                    state.chat_sessions[chat_id] = session
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
            mirror_legacy_from_canonical(state, persist=True)

        if evicted_idle_chat_id is not None and evicted_idle_chat_id in config.allowed_chat_ids:
            try:
                client.send_message(
                    evicted_idle_chat_id,
                    "Your Architect session was closed to free worker capacity. "
                    "Send a new message to start a fresh context.",
                )
            except Exception:
                logging.exception(
                    "Failed to send worker-eviction notice for chat_id=%s",
                    evicted_idle_chat_id,
                )

        if session_replaced_for_policy:
            try:
                client.send_message(
                    chat_id,
                    "Policy/context files changed. Your previous session was reset and this request "
                    "will continue in a new session.",
                    reply_to_message_id=message_id,
                )
            except Exception:
                logging.exception("Failed to send policy-refresh notice for chat_id=%s", chat_id)

        if rejected_for_capacity:
            client.send_message(
                chat_id,
                "All Architect workers are currently in use. Please wait and retry.",
                reply_to_message_id=message_id,
            )
            return False

        return True

    needs_persist_threads = False
    needs_persist_sessions = False

    with state.lock:
        session = state.worker_sessions.get(chat_id)

        if (
            session is not None
            and session.policy_fingerprint
            and session.policy_fingerprint != current_policy_fingerprint
        ):
            del state.worker_sessions[chat_id]
            if chat_id in state.chat_threads:
                del state.chat_threads[chat_id]
                needs_persist_threads = True
            session = None
            session_replaced_for_policy = True
            needs_persist_sessions = True

        if session is None and len(state.worker_sessions) >= config.persistent_workers_max:
            idle_candidates = [
                (candidate_chat_id, candidate_session)
                for candidate_chat_id, candidate_session in state.worker_sessions.items()
                if candidate_chat_id not in state.busy_chats and candidate_chat_id != chat_id
            ]
            if idle_candidates:
                idle_candidates.sort(key=lambda item: item[1].last_used_at)
                evicted_idle_chat_id = idle_candidates[0][0]
                del state.worker_sessions[evicted_idle_chat_id]
                if evicted_idle_chat_id in state.chat_threads:
                    del state.chat_threads[evicted_idle_chat_id]
                    needs_persist_threads = True
                needs_persist_sessions = True
            else:
                rejected_for_capacity = True

        if not rejected_for_capacity:
            session = state.worker_sessions.get(chat_id)
            if session is None:
                seed_thread_id = state.chat_threads.get(chat_id, "")
                state.worker_sessions[chat_id] = WorkerSession(
                    created_at=now,
                    last_used_at=now,
                    thread_id=seed_thread_id,
                    policy_fingerprint=current_policy_fingerprint,
                )
                needs_persist_sessions = True
            else:
                session.last_used_at = now
                session.policy_fingerprint = current_policy_fingerprint
                session.thread_id = state.chat_threads.get(chat_id, session.thread_id)
                needs_persist_sessions = True

    if needs_persist_threads:
        persist_chat_threads(state)
    if needs_persist_sessions:
        persist_worker_sessions(state)
    if state.canonical_sessions_enabled:
        sync_canonical_session(state, chat_id)
        if evicted_idle_chat_id is not None:
            sync_canonical_session(state, evicted_idle_chat_id)

    if evicted_idle_chat_id is not None and evicted_idle_chat_id in config.allowed_chat_ids:
        try:
            client.send_message(
                evicted_idle_chat_id,
                "Your Architect session was closed to free worker capacity. "
                "Send a new message to start a fresh context.",
            )
        except Exception:
            logging.exception(
                "Failed to send worker-eviction notice for chat_id=%s",
                evicted_idle_chat_id,
            )

    if session_replaced_for_policy:
        try:
            client.send_message(
                chat_id,
                "Policy/context files changed. Your previous session was reset and this request "
                "will continue in a new session.",
                reply_to_message_id=message_id,
            )
        except Exception:
            logging.exception("Failed to send policy-refresh notice for chat_id=%s", chat_id)

    if rejected_for_capacity:
        client.send_message(
            chat_id,
            "All Architect workers are currently in use. Please wait and retry.",
            reply_to_message_id=message_id,
        )
        return False

    return True


def expire_idle_worker_sessions(
    state: State,
    config,
    client,
) -> None:
    if not config.persistent_workers_enabled:
        return

    now = time.time()

    if state.canonical_sessions_enabled:
        expired_chat_ids: List[int] = []
        changed = False
        with state.lock:
            for chat_id, session in list(state.chat_sessions.items()):
                if chat_id in state.busy_chats:
                    continue
                if not _has_active_worker(session):
                    continue
                if (
                    session.worker_last_used_at is not None
                    and now - session.worker_last_used_at < config.persistent_workers_idle_timeout_seconds
                ):
                    continue
                expired_chat_ids.append(chat_id)
                session.worker_created_at = None
                session.worker_last_used_at = None
                session.worker_policy_fingerprint = ""
                session.thread_id = ""
                if canonical_session_is_empty(session):
                    del state.chat_sessions[chat_id]
                changed = True

        if changed:
            persist_canonical_sessions(state)
            mirror_legacy_from_canonical(state, persist=True)

        if not expired_chat_ids:
            return

        timeout_mins = max(1, config.persistent_workers_idle_timeout_seconds // 60)
        for chat_id in expired_chat_ids:
            if chat_id not in config.allowed_chat_ids:
                continue
            try:
                client.send_message(
                    chat_id,
                    f"Your Architect session expired after {timeout_mins} minutes of inactivity. "
                    "Context was cleared.",
                )
            except Exception:
                logging.exception("Failed to send idle-expiry notice for chat_id=%s", chat_id)
        return

    expired_chat_ids: List[int] = []
    needs_persist_threads = False
    needs_persist_sessions = False
    with state.lock:
        for chat_id, session in list(state.worker_sessions.items()):
            if chat_id in state.busy_chats:
                continue
            if now - session.last_used_at < config.persistent_workers_idle_timeout_seconds:
                continue
            expired_chat_ids.append(chat_id)
            del state.worker_sessions[chat_id]
            if chat_id in state.chat_threads:
                del state.chat_threads[chat_id]
                needs_persist_threads = True
            needs_persist_sessions = True

    if needs_persist_threads:
        persist_chat_threads(state)
    if needs_persist_sessions:
        persist_worker_sessions(state)
    if state.canonical_sessions_enabled:
        for chat_id in expired_chat_ids:
            sync_canonical_session(state, chat_id)

    if not expired_chat_ids:
        return

    timeout_mins = max(1, config.persistent_workers_idle_timeout_seconds // 60)
    for chat_id in expired_chat_ids:
        if chat_id not in config.allowed_chat_ids:
            continue
        try:
            client.send_message(
                chat_id,
                f"Your Architect session expired after {timeout_mins} minutes of inactivity. "
                "Context was cleared.",
            )
        except Exception:
            logging.exception("Failed to send idle-expiry notice for chat_id=%s", chat_id)


def request_safe_restart(
    state: State,
    chat_id: int,
    reply_to_message_id: Optional[int],
) -> tuple[str, int]:
    with state.lock:
        busy_count = len(state.busy_chats)
        if state.restart_in_progress:
            return "in_progress", busy_count
        if state.restart_requested:
            return "already_queued", busy_count

        state.restart_chat_id = chat_id
        state.restart_reply_to_message_id = reply_to_message_id
        if busy_count > 0:
            state.restart_requested = True
            return "queued", busy_count

        state.restart_in_progress = True
        return "run_now", busy_count


def pop_ready_restart_request(state: State) -> Optional[tuple[int, Optional[int]]]:
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
        return state.restart_chat_id, state.restart_reply_to_message_id


def finish_restart_attempt(state: State) -> None:
    with state.lock:
        state.restart_in_progress = False


def run_restart_script(
    state: State,
    client,
    chat_id: int,
    reply_to_message_id: Optional[int],
) -> None:
    script_path = build_restart_script_path()
    try:
        result = subprocess.run(
            ["bash", script_path],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logging.error("Bridge restart command timed out.")
        client.send_message(
            chat_id,
            "Restart command timed out. Please run restart manually.",
            reply_to_message_id=reply_to_message_id,
        )
        finish_restart_attempt(state)
        return
    except Exception:
        logging.exception("Bridge restart command failed to execute.")
        client.send_message(
            chat_id,
            "Restart command failed to execute. Please run restart manually.",
            reply_to_message_id=reply_to_message_id,
        )
        finish_restart_attempt(state)
        return

    if result.returncode != 0:
        logging.error(
            "Bridge restart command failed returncode=%s stderr=%r",
            result.returncode,
            (result.stderr or "")[-1000:],
        )
        client.send_message(
            chat_id,
            "Restart failed. Please run `bash ops/telegram-bridge/restart_and_verify.sh`.",
            reply_to_message_id=reply_to_message_id,
        )
        finish_restart_attempt(state)
        return

    # If this process survives a successful restart command invocation,
    # clear restart state so future restart requests are not blocked.
    finish_restart_attempt(state)


def trigger_restart_async(
    state: State,
    client,
    chat_id: int,
    reply_to_message_id: Optional[int],
) -> None:
    worker = threading.Thread(
        target=run_restart_script,
        args=(state, client, chat_id, reply_to_message_id),
        daemon=True,
    )
    worker.start()


def finalize_chat_work(
    state: State,
    client,
    chat_id: int,
) -> None:
    state_repo = StateRepository(state)
    state_repo.clear_in_flight_request(chat_id)
    clear_busy(state, chat_id)
    ready_restart = pop_ready_restart_request(state)
    if not ready_restart:
        return

    restart_chat_id, restart_reply_to = ready_restart
    try:
        client.send_message(
            restart_chat_id,
            "Current request completed. Restarting bridge now.",
            reply_to_message_id=restart_reply_to,
        )
    except Exception:
        logging.exception(
            "Failed to send queued restart acknowledgement for chat_id=%s",
            restart_chat_id,
        )
    trigger_restart_async(state, client, restart_chat_id, restart_reply_to)
