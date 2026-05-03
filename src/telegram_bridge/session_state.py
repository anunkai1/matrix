import time
from typing import Optional

try:
    from .state_models import ScopeKey, State
except ImportError:
    from state_models import ScopeKey, State


def clear_worker_session(
    state: State,
    scope_key: ScopeKey,
    *,
    normalize_scope_key_fn,
    canonical_session_is_empty_fn,
    persist_canonical_and_mirror_legacy_fn,
    persist_worker_sessions_fn,
    sync_canonical_session_fn,
) -> bool:
    scope_key = normalize_scope_key_fn(scope_key)
    if state.canonical_sessions_enabled:
        changed = False
        with state.lock:
            session = state.chat_sessions.get(scope_key)
            if session is not None and (
                session.worker_created_at is not None
                or session.worker_last_used_at is not None
                or session.worker_policy_fingerprint
            ):
                session.worker_created_at = None
                session.worker_last_used_at = None
                session.worker_policy_fingerprint = ""
                if canonical_session_is_empty_fn(session):
                    del state.chat_sessions[scope_key]
                changed = True
        if changed:
            persist_canonical_and_mirror_legacy_fn(state)
        return changed

    removed = False
    with state.lock:
        if scope_key in state.worker_sessions:
            del state.worker_sessions[scope_key]
            removed = True
    if removed:
        persist_worker_sessions_fn(state)
        sync_canonical_session_fn(state, scope_key)
    return removed


def get_thread_id(
    state: State,
    scope_key: ScopeKey,
    *,
    normalize_scope_key_fn,
) -> Optional[str]:
    scope_key = normalize_scope_key_fn(scope_key)
    if state.canonical_sessions_enabled:
        with state.lock:
            session = state.chat_sessions.get(scope_key)
            if session is None:
                return None
            thread_id = session.thread_id.strip()
            return thread_id or None
    with state.lock:
        return state.chat_threads.get(scope_key)


def set_thread_id(
    state: State,
    scope_key: ScopeKey,
    thread_id: str,
    *,
    normalize_scope_key_fn,
    canonical_session_cls,
    persist_legacy_state_fn,
    persist_canonical_and_mirror_legacy_fn,
    sync_canonical_session_fn,
) -> None:
    scope_key = normalize_scope_key_fn(scope_key)
    if state.canonical_sessions_enabled:
        normalized_thread_id = thread_id.strip()
        changed = False
        with state.lock:
            session = state.chat_sessions.get(scope_key)
            if session is None:
                session = canonical_session_cls()
                state.chat_sessions[scope_key] = session
            if session.thread_id != normalized_thread_id:
                session.thread_id = normalized_thread_id
                changed = True
            if session.worker_created_at is not None:
                now = time.time()
                if session.worker_last_used_at != now:
                    session.worker_last_used_at = now
                    changed = True
        if changed:
            persist_canonical_and_mirror_legacy_fn(state)
        return

    normalized_thread_id = thread_id.strip()
    persist_threads = False
    persist_sessions = False
    with state.lock:
        if state.chat_threads.get(scope_key) != normalized_thread_id:
            state.chat_threads[scope_key] = normalized_thread_id
            persist_threads = True
        session = state.worker_sessions.get(scope_key)
        if session is not None:
            session.thread_id = normalized_thread_id
            session.last_used_at = time.time()
            persist_sessions = True
    if persist_threads:
        persist_legacy_state_fn(state, chat_threads=True)
    if persist_sessions:
        persist_legacy_state_fn(state, worker_sessions=True)
    if persist_threads or persist_sessions:
        sync_canonical_session_fn(state, scope_key)


def clear_thread_id(
    state: State,
    scope_key: ScopeKey,
    *,
    normalize_scope_key_fn,
    canonical_session_is_empty_fn,
    persist_legacy_state_fn,
    persist_canonical_and_mirror_legacy_fn,
    sync_canonical_session_fn,
) -> bool:
    scope_key = normalize_scope_key_fn(scope_key)
    if state.canonical_sessions_enabled:
        removed = False
        with state.lock:
            session = state.chat_sessions.get(scope_key)
            if session is not None:
                if session.thread_id:
                    session.thread_id = ""
                    removed = True
                if session.worker_created_at is not None:
                    session.worker_last_used_at = time.time()
                    removed = True
                if canonical_session_is_empty_fn(session):
                    del state.chat_sessions[scope_key]
                    removed = True
        if removed:
            persist_canonical_and_mirror_legacy_fn(state)
        return removed

    removed = False
    persist_sessions = False
    with state.lock:
        if scope_key in state.chat_threads:
            del state.chat_threads[scope_key]
            removed = True
        session = state.worker_sessions.get(scope_key)
        if session is not None:
            session.thread_id = ""
            session.last_used_at = time.time()
            persist_sessions = True
    if removed:
        persist_legacy_state_fn(state, chat_threads=True)
    if persist_sessions:
        persist_legacy_state_fn(state, worker_sessions=True)
    if removed or persist_sessions:
        sync_canonical_session_fn(state, scope_key)
    return removed
