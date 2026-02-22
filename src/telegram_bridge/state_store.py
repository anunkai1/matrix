import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set


@dataclass
class CanonicalSession:
    thread_id: str = ""
    worker_created_at: Optional[float] = None
    worker_last_used_at: Optional[float] = None
    worker_policy_fingerprint: str = ""
    in_flight_started_at: Optional[float] = None
    in_flight_message_id: Optional[int] = None


@dataclass
class WorkerSession:
    created_at: float
    last_used_at: float
    thread_id: str
    policy_fingerprint: str


@dataclass
class State:
    started_at: float = field(default_factory=time.time)
    busy_chats: Set[int] = field(default_factory=set)
    recent_requests: Dict[int, List[float]] = field(default_factory=dict)
    chat_threads: Dict[int, str] = field(default_factory=dict)
    chat_thread_path: str = ""
    worker_sessions: Dict[int, WorkerSession] = field(default_factory=dict)
    worker_sessions_path: str = ""
    in_flight_requests: Dict[int, Dict[str, object]] = field(default_factory=dict)
    in_flight_path: str = ""
    canonical_sessions_enabled: bool = False
    chat_sessions: Dict[int, CanonicalSession] = field(default_factory=dict)
    chat_sessions_path: str = ""
    restart_requested: bool = False
    restart_in_progress: bool = False
    restart_chat_id: Optional[int] = None
    restart_reply_to_message_id: Optional[int] = None
    lock: threading.Lock = field(default_factory=threading.Lock)


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


def load_chat_threads(path: str) -> Dict[int, str]:
    data_path = Path(path)
    if not data_path.exists():
        return {}
    try:
        raw = json.loads(data_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to parse chat thread state {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid chat thread state {path}: root is not object")
    parsed: Dict[int, str] = {}
    for key, value in raw.items():
        if not isinstance(value, str) or not value.strip():
            continue
        try:
            chat_id = int(key)
        except ValueError:
            continue
        parsed[chat_id] = value.strip()
    return parsed


def load_worker_sessions(path: str) -> Dict[int, WorkerSession]:
    data_path = Path(path)
    if not data_path.exists():
        return {}
    try:
        raw = json.loads(data_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to parse worker session state {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid worker session state {path}: root is not object")

    parsed: Dict[int, WorkerSession] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        try:
            chat_id = int(key)
        except ValueError:
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
        parsed[chat_id] = WorkerSession(
            created_at=float(created_at),
            last_used_at=float(last_used_at),
            thread_id=thread_id.strip(),
            policy_fingerprint=policy_fingerprint.strip(),
        )
    return parsed


def load_in_flight_requests(path: str) -> Dict[int, Dict[str, object]]:
    data_path = Path(path)
    if not data_path.exists():
        return {}
    try:
        raw = json.loads(data_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to parse in-flight state {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid in-flight state {path}: root is not object")

    out: Dict[int, Dict[str, object]] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        try:
            chat_id = int(key)
        except ValueError:
            continue
        payload: Dict[str, object] = {}
        started_at = value.get("started_at")
        if isinstance(started_at, (int, float)):
            payload["started_at"] = float(started_at)
        message_id = value.get("message_id")
        if isinstance(message_id, int):
            payload["message_id"] = message_id
        out[chat_id] = payload
    return out


def load_canonical_sessions(path: str) -> Dict[int, CanonicalSession]:
    data_path = Path(path)
    if not data_path.exists():
        return {}
    try:
        raw = json.loads(data_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to parse canonical session state {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid canonical session state {path}: root is not object")

    parsed: Dict[int, CanonicalSession] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        try:
            chat_id = int(key)
        except ValueError:
            continue

        thread_id = value.get("thread_id")
        if not isinstance(thread_id, str):
            thread_id = ""

        worker_created_at = value.get("worker_created_at")
        if not isinstance(worker_created_at, (int, float)):
            worker_created_at = None

        worker_last_used_at = value.get("worker_last_used_at")
        if not isinstance(worker_last_used_at, (int, float)):
            worker_last_used_at = None

        worker_policy_fingerprint = value.get("worker_policy_fingerprint")
        if not isinstance(worker_policy_fingerprint, str):
            worker_policy_fingerprint = ""

        in_flight_started_at = value.get("in_flight_started_at")
        if not isinstance(in_flight_started_at, (int, float)):
            in_flight_started_at = None

        in_flight_message_id = value.get("in_flight_message_id")
        if not isinstance(in_flight_message_id, int):
            in_flight_message_id = None

        parsed[chat_id] = CanonicalSession(
            thread_id=thread_id.strip(),
            worker_created_at=float(worker_created_at) if worker_created_at is not None else None,
            worker_last_used_at=float(worker_last_used_at) if worker_last_used_at is not None else None,
            worker_policy_fingerprint=worker_policy_fingerprint.strip(),
            in_flight_started_at=(
                float(in_flight_started_at) if in_flight_started_at is not None else None
            ),
            in_flight_message_id=in_flight_message_id,
        )

    return parsed


def _build_canonical_session_for_chat(
    chat_id: int,
    chat_threads: Dict[int, str],
    worker_sessions: Dict[int, WorkerSession],
    in_flight_requests: Dict[int, Dict[str, object]],
) -> Optional[CanonicalSession]:
    thread_id = chat_threads.get(chat_id, "")
    worker = worker_sessions.get(chat_id)
    in_flight = in_flight_requests.get(chat_id)

    if not thread_id and worker is None and in_flight is None:
        return None

    in_flight_started_at: Optional[float] = None
    in_flight_message_id: Optional[int] = None
    if isinstance(in_flight, dict):
        started_at = in_flight.get("started_at")
        message_id = in_flight.get("message_id")
        if isinstance(started_at, (int, float)):
            in_flight_started_at = float(started_at)
        if isinstance(message_id, int):
            in_flight_message_id = message_id

    return CanonicalSession(
        thread_id=thread_id,
        worker_created_at=worker.created_at if worker is not None else None,
        worker_last_used_at=worker.last_used_at if worker is not None else None,
        worker_policy_fingerprint=worker.policy_fingerprint if worker is not None else "",
        in_flight_started_at=in_flight_started_at,
        in_flight_message_id=in_flight_message_id,
    )


def build_canonical_sessions_from_legacy(
    chat_threads: Dict[int, str],
    worker_sessions: Dict[int, WorkerSession],
    in_flight_requests: Dict[int, Dict[str, object]],
) -> Dict[int, CanonicalSession]:
    out: Dict[int, CanonicalSession] = {}
    all_chat_ids = set(chat_threads) | set(worker_sessions) | set(in_flight_requests)
    for chat_id in all_chat_ids:
        session = _build_canonical_session_for_chat(
            chat_id,
            chat_threads,
            worker_sessions,
            in_flight_requests,
        )
        if session is not None:
            out[chat_id] = session
    return out


def _canonical_session_to_legacy(
    session: CanonicalSession,
) -> tuple[Optional[str], Optional[WorkerSession], Optional[Dict[str, object]]]:
    thread_id = session.thread_id.strip()
    thread_value: Optional[str] = thread_id if thread_id else None

    worker_value: Optional[WorkerSession] = None
    if session.worker_created_at is not None and session.worker_last_used_at is not None:
        worker_value = WorkerSession(
            created_at=float(session.worker_created_at),
            last_used_at=float(session.worker_last_used_at),
            thread_id=thread_id,
            policy_fingerprint=session.worker_policy_fingerprint.strip(),
        )

    in_flight_value: Optional[Dict[str, object]] = None
    if session.in_flight_started_at is not None:
        in_flight_value = {"started_at": float(session.in_flight_started_at)}
        if session.in_flight_message_id is not None:
            in_flight_value["message_id"] = session.in_flight_message_id

    return thread_value, worker_value, in_flight_value


def build_legacy_from_canonical(
    canonical_sessions: Dict[int, CanonicalSession],
) -> tuple[Dict[int, str], Dict[int, WorkerSession], Dict[int, Dict[str, object]]]:
    chat_threads: Dict[int, str] = {}
    worker_sessions: Dict[int, WorkerSession] = {}
    in_flight_requests: Dict[int, Dict[str, object]] = {}
    for chat_id, session in canonical_sessions.items():
        thread_value, worker_value, in_flight_value = _canonical_session_to_legacy(session)
        if thread_value is not None:
            chat_threads[chat_id] = thread_value
        if worker_value is not None:
            worker_sessions[chat_id] = worker_value
        if in_flight_value is not None:
            in_flight_requests[chat_id] = in_flight_value
    return chat_threads, worker_sessions, in_flight_requests


def canonical_session_is_empty(session: CanonicalSession) -> bool:
    return (
        not session.thread_id.strip()
        and session.worker_created_at is None
        and session.worker_last_used_at is None
        and not session.worker_policy_fingerprint.strip()
        and session.in_flight_started_at is None
        and session.in_flight_message_id is None
    )


def persist_json_state_file(path_value: str, serialized: Dict[str, object]) -> None:
    if not path_value:
        return
    path = Path(path_value)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(
        json.dumps(serialized, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)


def persist_chat_threads(state: State) -> None:
    with state.lock:
        serialized = {str(chat_id): thread_id for chat_id, thread_id in state.chat_threads.items()}
    persist_json_state_file(state.chat_thread_path, serialized)


def persist_worker_sessions(state: State) -> None:
    with state.lock:
        serialized = {
            str(chat_id): {
                "created_at": session.created_at,
                "last_used_at": session.last_used_at,
                "thread_id": session.thread_id,
                "policy_fingerprint": session.policy_fingerprint,
            }
            for chat_id, session in state.worker_sessions.items()
        }
    persist_json_state_file(state.worker_sessions_path, serialized)


def persist_in_flight_requests(state: State) -> None:
    with state.lock:
        serialized = {
            str(chat_id): payload
            for chat_id, payload in state.in_flight_requests.items()
        }
    persist_json_state_file(state.in_flight_path, serialized)


def persist_canonical_sessions(state: State) -> None:
    if not state.canonical_sessions_enabled:
        return
    with state.lock:
        serialized = {
            str(chat_id): {
                "thread_id": session.thread_id,
                "worker_created_at": session.worker_created_at,
                "worker_last_used_at": session.worker_last_used_at,
                "worker_policy_fingerprint": session.worker_policy_fingerprint,
                "in_flight_started_at": session.in_flight_started_at,
                "in_flight_message_id": session.in_flight_message_id,
            }
            for chat_id, session in state.chat_sessions.items()
        }
    persist_json_state_file(state.chat_sessions_path, serialized)


def mirror_legacy_from_canonical(state: State, persist: bool = True) -> None:
    if not state.canonical_sessions_enabled:
        return
    with state.lock:
        chat_threads, worker_sessions, in_flight_requests = build_legacy_from_canonical(
            state.chat_sessions
        )
        state.chat_threads = chat_threads
        state.worker_sessions = worker_sessions
        state.in_flight_requests = in_flight_requests
    if persist:
        persist_chat_threads(state)
        persist_worker_sessions(state)
        persist_in_flight_requests(state)


def sync_canonical_session(state: State, chat_id: int) -> None:
    if not state.canonical_sessions_enabled:
        return
    changed = False
    with state.lock:
        session = _build_canonical_session_for_chat(
            chat_id,
            state.chat_threads,
            state.worker_sessions,
            state.in_flight_requests,
        )
        existing = state.chat_sessions.get(chat_id)
        if session is None:
            if existing is not None:
                del state.chat_sessions[chat_id]
                changed = True
        elif existing != session:
            state.chat_sessions[chat_id] = session
            changed = True
    if changed:
        persist_canonical_sessions(state)


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


def clear_worker_session(state: State, chat_id: int) -> bool:
    if state.canonical_sessions_enabled:
        changed = False
        with state.lock:
            session = state.chat_sessions.get(chat_id)
            if session is not None and (
                session.worker_created_at is not None
                or session.worker_last_used_at is not None
                or session.worker_policy_fingerprint
            ):
                session.worker_created_at = None
                session.worker_last_used_at = None
                session.worker_policy_fingerprint = ""
                if canonical_session_is_empty(session):
                    del state.chat_sessions[chat_id]
                changed = True
        if changed:
            persist_canonical_sessions(state)
            mirror_legacy_from_canonical(state, persist=True)
        return changed

    removed = False
    with state.lock:
        if chat_id in state.worker_sessions:
            del state.worker_sessions[chat_id]
            removed = True
    if removed:
        persist_worker_sessions(state)
        sync_canonical_session(state, chat_id)
    return removed


def get_thread_id(state: State, chat_id: int) -> Optional[str]:
    if state.canonical_sessions_enabled:
        with state.lock:
            session = state.chat_sessions.get(chat_id)
            if session is None:
                return None
            thread_id = session.thread_id.strip()
            return thread_id or None
    with state.lock:
        return state.chat_threads.get(chat_id)


def set_thread_id(state: State, chat_id: int, thread_id: str) -> None:
    if state.canonical_sessions_enabled:
        normalized_thread_id = thread_id.strip()
        changed = False
        with state.lock:
            session = state.chat_sessions.get(chat_id)
            if session is None:
                session = CanonicalSession()
                state.chat_sessions[chat_id] = session
            if session.thread_id != normalized_thread_id:
                session.thread_id = normalized_thread_id
                changed = True
            if session.worker_created_at is not None:
                now = time.time()
                if session.worker_last_used_at != now:
                    session.worker_last_used_at = now
                    changed = True
        if changed:
            persist_canonical_sessions(state)
            mirror_legacy_from_canonical(state, persist=True)
        return

    normalized_thread_id = thread_id.strip()
    persist_threads = False
    persist_sessions = False
    with state.lock:
        if state.chat_threads.get(chat_id) != normalized_thread_id:
            state.chat_threads[chat_id] = normalized_thread_id
            persist_threads = True
        session = state.worker_sessions.get(chat_id)
        if session is not None:
            session.thread_id = normalized_thread_id
            session.last_used_at = time.time()
            persist_sessions = True
    if persist_threads:
        persist_chat_threads(state)
    if persist_sessions:
        persist_worker_sessions(state)
    if persist_threads or persist_sessions:
        sync_canonical_session(state, chat_id)


def clear_thread_id(state: State, chat_id: int) -> bool:
    if state.canonical_sessions_enabled:
        removed = False
        with state.lock:
            session = state.chat_sessions.get(chat_id)
            if session is not None:
                if session.thread_id:
                    session.thread_id = ""
                    removed = True
                if session.worker_created_at is not None:
                    session.worker_last_used_at = time.time()
                    removed = True
                if canonical_session_is_empty(session):
                    del state.chat_sessions[chat_id]
                    removed = True
        if removed:
            persist_canonical_sessions(state)
            mirror_legacy_from_canonical(state, persist=True)
        return removed

    removed = False
    persist_sessions = False
    with state.lock:
        if chat_id in state.chat_threads:
            del state.chat_threads[chat_id]
            removed = True
        session = state.worker_sessions.get(chat_id)
        if session is not None:
            session.thread_id = ""
            session.last_used_at = time.time()
            persist_sessions = True
    if removed:
        persist_chat_threads(state)
    if persist_sessions:
        persist_worker_sessions(state)
    if removed or persist_sessions:
        sync_canonical_session(state, chat_id)
    return removed


def mark_in_flight_request(state: State, chat_id: int, message_id: Optional[int]) -> None:
    if state.canonical_sessions_enabled:
        with state.lock:
            session = state.chat_sessions.get(chat_id)
            if session is None:
                session = CanonicalSession()
                state.chat_sessions[chat_id] = session
            session.in_flight_started_at = time.time()
            session.in_flight_message_id = message_id if isinstance(message_id, int) else None
        persist_canonical_sessions(state)
        mirror_legacy_from_canonical(state, persist=True)
        return

    payload: Dict[str, object] = {"started_at": time.time()}
    if isinstance(message_id, int):
        payload["message_id"] = message_id
    with state.lock:
        state.in_flight_requests[chat_id] = payload
    persist_in_flight_requests(state)
    sync_canonical_session(state, chat_id)


def clear_in_flight_request(state: State, chat_id: int) -> None:
    if state.canonical_sessions_enabled:
        changed = False
        with state.lock:
            session = state.chat_sessions.get(chat_id)
            if session is not None and (
                session.in_flight_started_at is not None
                or session.in_flight_message_id is not None
            ):
                session.in_flight_started_at = None
                session.in_flight_message_id = None
                if canonical_session_is_empty(session):
                    del state.chat_sessions[chat_id]
                changed = True
        if changed:
            persist_canonical_sessions(state)
            mirror_legacy_from_canonical(state, persist=True)
        return

    removed = False
    with state.lock:
        if chat_id in state.in_flight_requests:
            del state.in_flight_requests[chat_id]
            removed = True
    if removed:
        persist_in_flight_requests(state)
        sync_canonical_session(state, chat_id)


def pop_interrupted_requests(state: State) -> Dict[int, Dict[str, object]]:
    if state.canonical_sessions_enabled:
        interrupted: Dict[int, Dict[str, object]] = {}
        with state.lock:
            for chat_id, session in state.chat_sessions.items():
                if session.in_flight_started_at is None:
                    continue
                payload: Dict[str, object] = {"started_at": float(session.in_flight_started_at)}
                if session.in_flight_message_id is not None:
                    payload["message_id"] = session.in_flight_message_id
                interrupted[chat_id] = payload

            if not interrupted:
                return {}

            for chat_id in list(interrupted):
                session = state.chat_sessions.get(chat_id)
                if session is None:
                    continue
                session.in_flight_started_at = None
                session.in_flight_message_id = None
                if canonical_session_is_empty(session):
                    del state.chat_sessions[chat_id]
        persist_canonical_sessions(state)
        mirror_legacy_from_canonical(state, persist=True)
        return interrupted

    with state.lock:
        if not state.in_flight_requests:
            return {}
        interrupted = dict(state.in_flight_requests)
        state.in_flight_requests = {}
    persist_in_flight_requests(state)
    if state.canonical_sessions_enabled:
        for chat_id in interrupted:
            sync_canonical_session(state, chat_id)
    return interrupted


class StateRepository:
    """State operations adapter used by handlers/workers."""

    def __init__(self, state: State) -> None:
        self.state = state

    def get_thread_id(self, chat_id: int) -> Optional[str]:
        return get_thread_id(self.state, chat_id)

    def set_thread_id(self, chat_id: int, thread_id: str) -> None:
        set_thread_id(self.state, chat_id, thread_id)

    def clear_thread_id(self, chat_id: int) -> bool:
        return clear_thread_id(self.state, chat_id)

    def clear_worker_session(self, chat_id: int) -> bool:
        return clear_worker_session(self.state, chat_id)

    def mark_in_flight_request(self, chat_id: int, message_id: Optional[int]) -> None:
        mark_in_flight_request(self.state, chat_id, message_id)

    def clear_in_flight_request(self, chat_id: int) -> None:
        clear_in_flight_request(self.state, chat_id)

    def pop_interrupted_requests(self) -> Dict[int, Dict[str, object]]:
        return pop_interrupted_requests(self.state)
