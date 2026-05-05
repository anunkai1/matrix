import time
from typing import Dict, Optional

from telegram_bridge.state_models import ScopeKey, State

def _build_in_flight_payload(
    *,
    started_at: float,
    message_id: Optional[int],
) -> Dict[str, object]:
    payload: Dict[str, object] = {"started_at": started_at}
    if isinstance(message_id, int):
        payload["message_id"] = message_id
    return payload

def mark_in_flight_request(
    state: State,
    scope_key: ScopeKey,
    message_id: Optional[int],
    *,
    normalize_scope_key_fn,
    canonical_session_cls,
    persist_canonical_and_mirror_legacy_fn,
    persist_in_flight_requests_fn,
    sync_canonical_session_fn,
) -> None:
    scope_key = normalize_scope_key_fn(scope_key)
    if state.canonical_sessions_enabled:
        with state.lock:
            session = state.chat_sessions.get(scope_key)
            if session is None:
                session = canonical_session_cls()
                state.chat_sessions[scope_key] = session
            session.in_flight_started_at = time.time()
            session.in_flight_message_id = message_id if isinstance(message_id, int) else None
        persist_canonical_and_mirror_legacy_fn(state)
        return

    payload = _build_in_flight_payload(started_at=time.time(), message_id=message_id)
    with state.lock:
        state.in_flight_requests[scope_key] = payload
    persist_in_flight_requests_fn(state)
    sync_canonical_session_fn(state, scope_key)

def clear_in_flight_request(
    state: State,
    scope_key: ScopeKey,
    *,
    normalize_scope_key_fn,
    canonical_session_is_empty_fn,
    persist_canonical_and_mirror_legacy_fn,
    persist_in_flight_requests_fn,
    sync_canonical_session_fn,
) -> None:
    scope_key = normalize_scope_key_fn(scope_key)
    if state.canonical_sessions_enabled:
        changed = False
        with state.lock:
            session = state.chat_sessions.get(scope_key)
            if session is not None and (
                session.in_flight_started_at is not None
                or session.in_flight_message_id is not None
            ):
                session.in_flight_started_at = None
                session.in_flight_message_id = None
                if canonical_session_is_empty_fn(session):
                    del state.chat_sessions[scope_key]
                changed = True
        if changed:
            persist_canonical_and_mirror_legacy_fn(state)
        return

    removed = False
    with state.lock:
        if scope_key in state.in_flight_requests:
            del state.in_flight_requests[scope_key]
            removed = True
    if removed:
        persist_in_flight_requests_fn(state)
        sync_canonical_session_fn(state, scope_key)

def pop_interrupted_requests(
    state: State,
    *,
    canonical_session_is_empty_fn,
    persist_canonical_and_mirror_legacy_fn,
    persist_in_flight_requests_fn,
    sync_canonical_session_fn,
) -> Dict[ScopeKey, Dict[str, object]]:
    if state.canonical_sessions_enabled:
        interrupted: Dict[ScopeKey, Dict[str, object]] = {}
        with state.lock:
            for scope_key, session in state.chat_sessions.items():
                if session.in_flight_started_at is None:
                    continue
                interrupted[scope_key] = _build_in_flight_payload(
                    started_at=float(session.in_flight_started_at),
                    message_id=session.in_flight_message_id,
                )

            if not interrupted:
                return {}

            for scope_key in list(interrupted):
                session = state.chat_sessions.get(scope_key)
                if session is None:
                    continue
                session.in_flight_started_at = None
                session.in_flight_message_id = None
                if canonical_session_is_empty_fn(session):
                    del state.chat_sessions[scope_key]
        persist_canonical_and_mirror_legacy_fn(state)
        return interrupted

    with state.lock:
        if not state.in_flight_requests:
            return {}
        interrupted = dict(state.in_flight_requests)
        state.in_flight_requests = {}
    persist_in_flight_requests_fn(state)
    if state.canonical_sessions_enabled:
        for scope_key in interrupted:
            sync_canonical_session_fn(state, scope_key)
    return interrupted
