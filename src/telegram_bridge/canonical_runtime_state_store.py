from telegram_bridge.canonical_state_store import (
    _build_canonical_session_for_scope,
    build_canonical_sessions_from_legacy,
    build_legacy_from_canonical,
    copy_canonical_session,
    persist_canonical_session_sqlite,
    persist_canonical_sessions_sqlite,
    serialize_canonical_sessions,
)
from telegram_bridge.request_runtime_state_store import (
    persist_in_flight_requests,
    persist_worker_sessions,
)
from telegram_bridge.scope_state_store import persist_chat_threads, persist_json_state_file
from telegram_bridge.state_models import ScopeKey, State, normalize_scope_key


def _persist_legacy_state(
    state: State,
    *,
    chat_threads: bool = False,
    worker_sessions: bool = False,
    in_flight_requests: bool = False,
) -> None:
    if chat_threads:
        persist_chat_threads(state)
    if worker_sessions:
        persist_worker_sessions(state)
    if in_flight_requests:
        persist_in_flight_requests(state)


def persist_canonical_sessions(state: State) -> None:
    if not state.canonical_sessions_enabled:
        return
    with state.lock:
        sessions = {
            normalize_scope_key(scope_key): copy_canonical_session(session)
            for scope_key, session in state.chat_sessions.items()
        }
        serialized = serialize_canonical_sessions(sessions)
    if state.canonical_sqlite_enabled:
        persist_canonical_sessions_sqlite(state.canonical_sqlite_path, sessions)
        if state.canonical_json_mirror_enabled:
            persist_json_state_file(state.chat_sessions_path, serialized)
        return
    persist_json_state_file(state.chat_sessions_path, serialized)


def persist_canonical_session_scope(state: State, scope_key: ScopeKey) -> None:
    if not state.canonical_sessions_enabled:
        return
    normalized_scope_key = normalize_scope_key(scope_key)
    with state.lock:
        session = state.chat_sessions.get(normalized_scope_key)
        session_copy = copy_canonical_session(session) if session is not None else None
        json_mirror_payload = None
        if state.canonical_json_mirror_enabled:
            json_mirror_payload = serialize_canonical_sessions(
                {
                    normalize_scope_key(candidate_scope_key): copy_canonical_session(candidate_session)
                    for candidate_scope_key, candidate_session in state.chat_sessions.items()
                }
            )
    if state.canonical_sqlite_enabled:
        persist_canonical_session_sqlite(
            state.canonical_sqlite_path,
            normalized_scope_key,
            session_copy,
        )
        if json_mirror_payload is not None:
            persist_json_state_file(state.chat_sessions_path, json_mirror_payload)
        return
    persist_canonical_sessions(state)


def mirror_legacy_from_canonical(state: State, persist: bool = True) -> None:
    if not state.canonical_sessions_enabled:
        return
    persist_enabled = persist and state.canonical_legacy_mirror_enabled
    with state.lock:
        chat_threads, worker_sessions, in_flight_requests = build_legacy_from_canonical(
            state.chat_sessions
        )
        state.chat_threads = chat_threads
        state.worker_sessions = worker_sessions
        state.in_flight_requests = in_flight_requests
    if persist_enabled:
        _persist_legacy_state(
            state,
            chat_threads=True,
            worker_sessions=True,
            in_flight_requests=True,
        )


def persist_canonical_and_mirror_legacy(state: State) -> None:
    persist_canonical_sessions(state)


def persist_canonical_scope_and_mirror_legacy(state: State, scope_key: ScopeKey) -> None:
    persist_canonical_session_scope(state, scope_key)


def sync_canonical_session(state: State, scope_key: ScopeKey) -> None:
    if not state.canonical_sessions_enabled:
        return
    scope_key = normalize_scope_key(scope_key)
    changed = False
    with state.lock:
        session = _build_canonical_session_for_scope(
            scope_key,
            state.chat_threads,
            state.worker_sessions,
            state.in_flight_requests,
        )
        existing = state.chat_sessions.get(scope_key)
        if session is None:
            if existing is not None:
                del state.chat_sessions[scope_key]
                changed = True
        elif existing != session:
            state.chat_sessions[scope_key] = session
            changed = True
    if changed:
        persist_canonical_scope_and_mirror_legacy(state, scope_key)


def sync_all_canonical_sessions(state: State) -> None:
    if not state.canonical_sessions_enabled:
        return
    with state.lock:
        state.chat_sessions = build_canonical_sessions_from_legacy(
            state.chat_threads,
            state.worker_sessions,
            state.in_flight_requests,
        )
    persist_canonical_sessions(state)
