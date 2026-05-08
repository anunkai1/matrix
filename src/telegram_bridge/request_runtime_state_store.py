from typing import Dict

from telegram_bridge.scope_state_store import load_json_object, persist_json_state_file
from telegram_bridge.state_models import ScopeKey, State, WorkerSession, normalize_scope_key, normalize_scope_storage_key


def load_worker_sessions(path: str) -> Dict[ScopeKey, WorkerSession]:
    raw = load_json_object(path, state_label="worker session")
    parsed: Dict[ScopeKey, WorkerSession] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        scope_key = normalize_scope_storage_key(key)
        if scope_key is None:
            continue
        created_at = value.get("created_at")
        last_used_at = value.get("last_used_at")
        thread_id = value.get("thread_id")
        policy_fingerprint = value.get("policy_fingerprint")
        if not isinstance(created_at, (int, float)):
            continue
        if not isinstance(last_used_at, (int, float)):
            last_used_at = float(created_at)
        if not isinstance(thread_id, str):
            thread_id = ""
        if not isinstance(policy_fingerprint, str):
            policy_fingerprint = ""
        parsed[scope_key] = WorkerSession(
            created_at=float(created_at),
            last_used_at=float(last_used_at),
            thread_id=thread_id.strip(),
            policy_fingerprint=policy_fingerprint.strip(),
        )
    return parsed


def load_in_flight_requests(path: str) -> Dict[ScopeKey, Dict[str, object]]:
    raw = load_json_object(path, state_label="in-flight")
    out: Dict[ScopeKey, Dict[str, object]] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        scope_key = normalize_scope_storage_key(key)
        if scope_key is None:
            continue
        payload: Dict[str, object] = {}
        started_at = value.get("started_at")
        if isinstance(started_at, (int, float)):
            payload["started_at"] = float(started_at)
        message_id = value.get("message_id")
        if isinstance(message_id, int):
            payload["message_id"] = message_id
        out[scope_key] = payload
    return out


def persist_worker_sessions(state: State) -> None:
    with state.lock:
        serialized = {
            normalize_scope_key(scope_key): {
                "created_at": session.created_at,
                "last_used_at": session.last_used_at,
                "thread_id": session.thread_id,
                "policy_fingerprint": session.policy_fingerprint,
            }
            for scope_key, session in state.worker_sessions.items()
        }
    persist_json_state_file(state.worker_sessions_path, serialized)


def persist_in_flight_requests(state: State) -> None:
    with state.lock:
        serialized = {
            normalize_scope_key(scope_key): payload
            for scope_key, payload in state.in_flight_requests.items()
        }
    persist_json_state_file(state.in_flight_path, serialized)
