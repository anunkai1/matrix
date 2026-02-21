import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set


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


def clear_worker_session(state: State, chat_id: int) -> bool:
    removed = False
    with state.lock:
        if chat_id in state.worker_sessions:
            del state.worker_sessions[chat_id]
            removed = True
    if removed:
        persist_worker_sessions(state)
    return removed


def get_thread_id(state: State, chat_id: int) -> Optional[str]:
    with state.lock:
        return state.chat_threads.get(chat_id)


def set_thread_id(state: State, chat_id: int, thread_id: str) -> None:
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


def clear_thread_id(state: State, chat_id: int) -> bool:
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
    return removed


def mark_in_flight_request(state: State, chat_id: int, message_id: Optional[int]) -> None:
    payload: Dict[str, object] = {"started_at": time.time()}
    if isinstance(message_id, int):
        payload["message_id"] = message_id
    with state.lock:
        state.in_flight_requests[chat_id] = payload
    persist_in_flight_requests(state)


def clear_in_flight_request(state: State, chat_id: int) -> None:
    removed = False
    with state.lock:
        if chat_id in state.in_flight_requests:
            del state.in_flight_requests[chat_id]
            removed = True
    if removed:
        persist_in_flight_requests(state)


def pop_interrupted_requests(state: State) -> Dict[int, Dict[str, object]]:
    with state.lock:
        if not state.in_flight_requests:
            return {}
        interrupted = dict(state.in_flight_requests)
        state.in_flight_requests = {}
    persist_in_flight_requests(state)
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
