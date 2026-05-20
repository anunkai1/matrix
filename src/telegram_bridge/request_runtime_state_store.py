import threading
import time
from typing import Dict

from telegram_bridge.scope_state_store import load_json_object, persist_json_state_file
from telegram_bridge.state_models import ScopeKey, State, WorkerSession, normalize_scope_key, normalize_scope_storage_key

_IN_FLIGHT_WRITE_LOCK = threading.Lock()
_IN_FLIGHT_WRITE_CONDITION = threading.Condition(_IN_FLIGHT_WRITE_LOCK)
_IN_FLIGHT_WRITE_ACTIVE: Dict[str, bool] = {}
_IN_FLIGHT_WRITE_CONTENDED: Dict[str, bool] = {}
_IN_FLIGHT_WRITE_PENDING: Dict[str, Dict[str, object]] = {}
_IN_FLIGHT_WRITE_LAST_PERSISTED: Dict[str, Dict[str, object]] = {}
# Allow a short quiet window so overlapping request-start/request-finish updates
# collapse into one persisted snapshot instead of thrashing the same file.
_IN_FLIGHT_COALESCE_IDLE_SECONDS = 0.005


def _persist_in_flight_snapshot(path_value: str, serialized: Dict[str, object]) -> None:
    with _IN_FLIGHT_WRITE_LOCK:
        last_persisted = _IN_FLIGHT_WRITE_LAST_PERSISTED.get(path_value)
        if last_persisted == serialized and not _IN_FLIGHT_WRITE_ACTIVE.get(path_value, False):
            return
        if _IN_FLIGHT_WRITE_ACTIVE.get(path_value, False):
            pending = _IN_FLIGHT_WRITE_PENDING.get(path_value)
            if pending == serialized or last_persisted == serialized:
                return
            _IN_FLIGHT_WRITE_PENDING[path_value] = serialized
            _IN_FLIGHT_WRITE_CONTENDED[path_value] = True
            _IN_FLIGHT_WRITE_CONDITION.notify_all()
            return
        _IN_FLIGHT_WRITE_ACTIVE[path_value] = True
        _IN_FLIGHT_WRITE_CONTENDED[path_value] = False

    next_payload = serialized
    saw_distinct_pending = False
    while True:
        try:
            # In-flight request state churns on every request start/finish. Preserve
            # atomic replacement but skip per-write fsync to avoid turning concurrent
            # request bookkeeping into a disk-bound bottleneck.
            persist_json_state_file(
                path_value,
                next_payload,
                fsync_file=False,
                pretty=False,
                delete_when_empty=True,
            )
        except Exception:
            with _IN_FLIGHT_WRITE_LOCK:
                _IN_FLIGHT_WRITE_ACTIVE.pop(path_value, None)
                _IN_FLIGHT_WRITE_CONTENDED.pop(path_value, None)
                _IN_FLIGHT_WRITE_PENDING.pop(path_value, None)
            raise

        with _IN_FLIGHT_WRITE_LOCK:
            _IN_FLIGHT_WRITE_LAST_PERSISTED[path_value] = next_payload
            pending = _IN_FLIGHT_WRITE_PENDING.pop(path_value, None)
            if pending is not None:
                if pending != next_payload:
                    saw_distinct_pending = True
                    next_payload = pending
                    continue

            contended = _IN_FLIGHT_WRITE_CONTENDED.get(path_value, False)
            if (
                not contended
                or not saw_distinct_pending
                or _IN_FLIGHT_COALESCE_IDLE_SECONDS <= 0
            ):
                _IN_FLIGHT_WRITE_ACTIVE.pop(path_value, None)
                _IN_FLIGHT_WRITE_CONTENDED.pop(path_value, None)
                return

            deadline = time.monotonic() + _IN_FLIGHT_COALESCE_IDLE_SECONDS
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _IN_FLIGHT_WRITE_ACTIVE.pop(path_value, None)
                    _IN_FLIGHT_WRITE_CONTENDED.pop(path_value, None)
                    return
                _IN_FLIGHT_WRITE_CONDITION.wait(timeout=remaining)
                pending = _IN_FLIGHT_WRITE_PENDING.pop(path_value, None)
                if pending is not None:
                    _IN_FLIGHT_WRITE_CONTENDED[path_value] = False
                    saw_distinct_pending = True
                    next_payload = pending
                    break


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
    _persist_in_flight_snapshot(state.in_flight_path, serialized)
