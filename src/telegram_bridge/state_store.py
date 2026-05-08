import json
import sqlite3
import time
from pathlib import Path
from typing import Dict, Optional

from telegram_bridge.canonical_state_store import (
    build_canonical_sessions_from_legacy,
    build_legacy_from_canonical,
    canonical_session_is_empty,
    ensure_canonical_sessions_sqlite,
    load_canonical_sessions_from_json_object,
    load_canonical_sessions_sqlite,
    load_or_import_canonical_sessions_sqlite,
    persist_canonical_session_sqlite,
    persist_canonical_sessions_sqlite,
)
from telegram_bridge.canonical_runtime_state_store import (
    _persist_legacy_state,
    mirror_legacy_from_canonical,
    persist_canonical_and_mirror_legacy,
    persist_canonical_scope_and_mirror_legacy,
    sync_all_canonical_sessions,
    sync_canonical_session,
)
from telegram_bridge.scope_state_store import (
    clear_chat_codex_effort,
    clear_chat_codex_model,
    clear_chat_engine,
    clear_chat_pi_model,
    clear_chat_pi_provider,
    get_chat_codex_effort,
    get_chat_codex_model,
    get_chat_engine,
    get_chat_pi_model,
    get_chat_pi_provider,
    load_chat_codex_efforts,
    load_chat_codex_models,
    load_chat_engines,
    load_chat_pi_models,
    load_chat_pi_providers,
    load_chat_threads,
    load_json_object,
    persist_chat_threads,
    persist_chat_codex_efforts,
    persist_chat_codex_models,
    persist_chat_engines,
    persist_chat_pi_models,
    persist_chat_pi_providers,
    set_chat_codex_effort,
    set_chat_codex_model,
    set_chat_engine,
    set_chat_pi_model,
    set_chat_pi_provider,
)
from telegram_bridge.request_runtime_state_store import (
    load_in_flight_requests,
    load_worker_sessions,
    persist_in_flight_requests,
    persist_worker_sessions,
)
from telegram_bridge import request_state
from telegram_bridge import session_state
from telegram_bridge.state_models import (
    CanonicalSession,
    PendingDiaryBatch,
    PendingMediaGroup,
    RecentPhotoSelection,
    ScopeKey,
    State,
    WorkerSession,
    normalize_scope_key,
)

__all__ = [
    "StateRepository",
    "build_canonical_sessions_from_legacy",
    "build_legacy_from_canonical",
    "canonical_session_is_empty",
    "clear_chat_codex_effort",
    "clear_chat_codex_model",
    "clear_chat_engine",
    "clear_chat_pi_model",
    "clear_chat_pi_provider",
    "clear_in_flight_request",
    "clear_thread_id",
    "clear_worker_session",
    "ensure_canonical_sessions_sqlite",
    "ensure_state_dir",
    "get_chat_codex_effort",
    "get_chat_codex_model",
    "get_chat_engine",
    "get_chat_pi_model",
    "get_chat_pi_provider",
    "get_thread_id",
    "load_canonical_sessions",
    "load_canonical_sessions_sqlite",
    "load_chat_codex_efforts",
    "load_chat_codex_models",
    "load_chat_engines",
    "load_chat_pi_models",
    "load_chat_pi_providers",
    "load_chat_threads",
    "load_in_flight_requests",
    "load_or_import_canonical_sessions_sqlite",
    "load_worker_sessions",
    "mark_in_flight_request",
    "mirror_legacy_from_canonical",
    "persist_canonical_and_mirror_legacy",
    "persist_canonical_scope_and_mirror_legacy",
    "persist_canonical_session_scope",
    "persist_canonical_session_sqlite",
    "persist_canonical_sessions",
    "persist_canonical_sessions_sqlite",
    "persist_chat_codex_efforts",
    "persist_chat_codex_models",
    "persist_chat_engines",
    "persist_chat_pi_models",
    "persist_chat_pi_providers",
    "persist_chat_threads",
    "persist_in_flight_requests",
    "persist_worker_sessions",
    "pop_interrupted_requests",
    "quarantine_corrupt_state_file",
    "set_chat_codex_effort",
    "set_chat_codex_model",
    "set_chat_engine",
    "set_chat_pi_model",
    "set_chat_pi_provider",
    "set_thread_id",
    "sync_all_canonical_sessions",
    "sync_canonical_session",
]

def ensure_state_dir(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)

def quarantine_corrupt_state_file(path: str) -> Optional[str]:
    data_path = Path(path)
    if not data_path.exists():
        return None
    timestamp = time.strftime("%Y%m%d%H%M%S", time.gmtime())
    quarantined = data_path.with_name(f"{data_path.name}.corrupt.{timestamp}")
    data_path.replace(quarantined)
    return str(quarantined)

def load_canonical_sessions(path: str) -> Dict[ScopeKey, CanonicalSession]:
    raw = load_json_object(path, state_label="canonical session")
    return load_canonical_sessions_from_json_object(raw)

def persist_canonical_sessions(state: State) -> None:
    from telegram_bridge.canonical_runtime_state_store import persist_canonical_sessions as _persist

    _persist(state)

def persist_canonical_session_scope(state: State, scope_key: ScopeKey) -> None:
    from telegram_bridge.canonical_runtime_state_store import (
        persist_canonical_session_scope as _persist_scope,
    )

    _persist_scope(state, scope_key)

def clear_worker_session(state: State, scope_key: ScopeKey) -> bool:
    return session_state.clear_worker_session(
        state,
        scope_key,
        normalize_scope_key_fn=normalize_scope_key,
        canonical_session_is_empty_fn=canonical_session_is_empty,
        persist_canonical_scope_and_mirror_legacy_fn=persist_canonical_scope_and_mirror_legacy,
        persist_worker_sessions_fn=persist_worker_sessions,
        sync_canonical_session_fn=sync_canonical_session,
    )

def get_thread_id(state: State, scope_key: ScopeKey) -> Optional[str]:
    return session_state.get_thread_id(
        state,
        scope_key,
        normalize_scope_key_fn=normalize_scope_key,
    )

def set_thread_id(state: State, scope_key: ScopeKey, thread_id: str) -> None:
    session_state.set_thread_id(
        state,
        scope_key,
        thread_id,
        normalize_scope_key_fn=normalize_scope_key,
        canonical_session_cls=CanonicalSession,
        persist_legacy_state_fn=_persist_legacy_state,
        persist_canonical_scope_and_mirror_legacy_fn=persist_canonical_scope_and_mirror_legacy,
        sync_canonical_session_fn=sync_canonical_session,
    )

def clear_thread_id(state: State, scope_key: ScopeKey) -> bool:
    return session_state.clear_thread_id(
        state,
        scope_key,
        normalize_scope_key_fn=normalize_scope_key,
        canonical_session_is_empty_fn=canonical_session_is_empty,
        persist_legacy_state_fn=_persist_legacy_state,
        persist_canonical_scope_and_mirror_legacy_fn=persist_canonical_scope_and_mirror_legacy,
        sync_canonical_session_fn=sync_canonical_session,
    )

def mark_in_flight_request(state: State, scope_key: ScopeKey, message_id: Optional[int]) -> None:
    request_state.mark_in_flight_request(
        state,
        scope_key,
        message_id,
        normalize_scope_key_fn=normalize_scope_key,
        canonical_session_cls=CanonicalSession,
        persist_canonical_scope_and_mirror_legacy_fn=persist_canonical_scope_and_mirror_legacy,
        persist_in_flight_requests_fn=persist_in_flight_requests,
        sync_canonical_session_fn=sync_canonical_session,
    )

def clear_in_flight_request(state: State, scope_key: ScopeKey) -> None:
    request_state.clear_in_flight_request(
        state,
        scope_key,
        normalize_scope_key_fn=normalize_scope_key,
        canonical_session_is_empty_fn=canonical_session_is_empty,
        persist_canonical_scope_and_mirror_legacy_fn=persist_canonical_scope_and_mirror_legacy,
        persist_in_flight_requests_fn=persist_in_flight_requests,
        sync_canonical_session_fn=sync_canonical_session,
    )

def pop_interrupted_requests(state: State) -> Dict[ScopeKey, Dict[str, object]]:
    return request_state.pop_interrupted_requests(
        state,
        canonical_session_is_empty_fn=canonical_session_is_empty,
        persist_canonical_and_mirror_legacy_fn=persist_canonical_and_mirror_legacy,
        persist_in_flight_requests_fn=persist_in_flight_requests,
        sync_canonical_session_fn=sync_canonical_session,
    )

class StateRepository:
    """State operations adapter used by handlers/workers."""

    def __init__(self, state: State) -> None:
        self.state = state

    def get_thread_id(self, scope_key: ScopeKey) -> Optional[str]:
        return get_thread_id(self.state, scope_key)

    def set_thread_id(self, scope_key: ScopeKey, thread_id: str) -> None:
        set_thread_id(self.state, scope_key, thread_id)

    def clear_thread_id(self, scope_key: ScopeKey) -> bool:
        return clear_thread_id(self.state, scope_key)

    def clear_worker_session(self, scope_key: ScopeKey) -> bool:
        return clear_worker_session(self.state, scope_key)

    def get_chat_engine(self, scope_key: ScopeKey) -> Optional[str]:
        return get_chat_engine(self.state, scope_key)

    def set_chat_engine(self, scope_key: ScopeKey, engine_name: str) -> None:
        set_chat_engine(self.state, scope_key, engine_name)

    def clear_chat_engine(self, scope_key: ScopeKey) -> bool:
        return clear_chat_engine(self.state, scope_key)

    def get_chat_codex_model(self, scope_key: ScopeKey) -> Optional[str]:
        return get_chat_codex_model(self.state, scope_key)

    def set_chat_codex_model(self, scope_key: ScopeKey, model_name: str) -> None:
        set_chat_codex_model(self.state, scope_key, model_name)

    def clear_chat_codex_model(self, scope_key: ScopeKey) -> bool:
        return clear_chat_codex_model(self.state, scope_key)

    def get_chat_codex_effort(self, scope_key: ScopeKey) -> Optional[str]:
        return get_chat_codex_effort(self.state, scope_key)

    def set_chat_codex_effort(self, scope_key: ScopeKey, effort_name: str) -> None:
        set_chat_codex_effort(self.state, scope_key, effort_name)

    def clear_chat_codex_effort(self, scope_key: ScopeKey) -> bool:
        return clear_chat_codex_effort(self.state, scope_key)

    def get_chat_pi_provider(self, scope_key: ScopeKey) -> Optional[str]:
        return get_chat_pi_provider(self.state, scope_key)

    def set_chat_pi_provider(self, scope_key: ScopeKey, provider_name: str) -> None:
        set_chat_pi_provider(self.state, scope_key, provider_name)

    def clear_chat_pi_provider(self, scope_key: ScopeKey) -> bool:
        return clear_chat_pi_provider(self.state, scope_key)

    def get_chat_pi_model(self, scope_key: ScopeKey) -> Optional[str]:
        return get_chat_pi_model(self.state, scope_key)

    def set_chat_pi_model(self, scope_key: ScopeKey, model_name: str) -> None:
        set_chat_pi_model(self.state, scope_key, model_name)

    def clear_chat_pi_model(self, scope_key: ScopeKey) -> bool:
        return clear_chat_pi_model(self.state, scope_key)

    def mark_in_flight_request(self, scope_key: ScopeKey, message_id: Optional[int]) -> None:
        mark_in_flight_request(self.state, scope_key, message_id)

    def clear_in_flight_request(self, scope_key: ScopeKey) -> None:
        clear_in_flight_request(self.state, scope_key)

    def pop_interrupted_requests(self) -> Dict[ScopeKey, Dict[str, object]]:
        return pop_interrupted_requests(self.state)
