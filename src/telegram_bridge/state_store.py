import json
import os
import sqlite3
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

try:
    from .conversation_scope import normalize_scope_storage_key, parse_telegram_scope_key
except ImportError:
    from conversation_scope import normalize_scope_storage_key, parse_telegram_scope_key


ScopeKey = str


def normalize_scope_key(scope_key: object) -> ScopeKey:
    normalized = normalize_scope_storage_key(scope_key)
    if normalized is None:
        raise ValueError(f"Invalid scope key: {scope_key!r}")
    return normalized


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
class PendingMediaGroup:
    chat_id: int
    media_group_id: str
    updates: List[Dict[str, object]] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    last_seen_at: float = field(default_factory=time.time)


@dataclass
class PendingDiaryBatch:
    scope_key: str
    chat_id: int
    message_thread_id: Optional[int]
    latest_message_id: Optional[int]
    sender_name: str
    actor_user_id: Optional[int]
    messages: List[Dict[str, object]] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    last_seen_at: float = field(default_factory=time.time)
    worker_started: bool = False


@dataclass
class RecentPhotoSelection:
    photo_file_ids: List[str] = field(default_factory=list)
    message_id: Optional[int] = None
    captured_at: float = field(default_factory=time.time)


@dataclass
class State:
    started_at: float = field(default_factory=time.time)
    busy_chats: Set[ScopeKey] = field(default_factory=set)
    recent_requests: Dict[ScopeKey, List[float]] = field(default_factory=dict)
    chat_threads: Dict[ScopeKey, str] = field(default_factory=dict)
    chat_thread_path: str = ""
    chat_engines: Dict[ScopeKey, str] = field(default_factory=dict)
    chat_engine_path: str = ""
    chat_codex_models: Dict[ScopeKey, str] = field(default_factory=dict)
    chat_codex_model_path: str = ""
    chat_codex_efforts: Dict[ScopeKey, str] = field(default_factory=dict)
    chat_codex_effort_path: str = ""
    chat_pi_providers: Dict[ScopeKey, str] = field(default_factory=dict)
    chat_pi_provider_path: str = ""
    chat_pi_models: Dict[ScopeKey, str] = field(default_factory=dict)
    chat_pi_model_path: str = ""
    worker_sessions: Dict[ScopeKey, WorkerSession] = field(default_factory=dict)
    worker_sessions_path: str = ""
    in_flight_requests: Dict[ScopeKey, Dict[str, object]] = field(default_factory=dict)
    in_flight_path: str = ""
    canonical_sessions_enabled: bool = False
    canonical_legacy_mirror_enabled: bool = False
    canonical_sqlite_enabled: bool = False
    canonical_sqlite_path: str = ""
    canonical_json_mirror_enabled: bool = False
    chat_sessions: Dict[ScopeKey, CanonicalSession] = field(default_factory=dict)
    chat_sessions_path: str = ""
    restart_requested: bool = False
    restart_in_progress: bool = False
    restart_chat_id: Optional[int] = None
    restart_message_thread_id: Optional[int] = None
    restart_reply_to_message_id: Optional[int] = None
    memory_engine: Optional[object] = None
    affective_runtime: Optional[object] = None
    attachment_store: Optional[object] = None
    voice_alias_learning_store: Optional[object] = None
    cancel_events: Dict[ScopeKey, threading.Event] = field(default_factory=dict)
    pending_media_groups: Dict[str, PendingMediaGroup] = field(default_factory=dict)
    recent_scope_photos: Dict[ScopeKey, RecentPhotoSelection] = field(default_factory=dict)
    pending_diary_batches: Dict[ScopeKey, PendingDiaryBatch] = field(default_factory=dict)
    queued_diary_batches: Dict[ScopeKey, List[PendingDiaryBatch]] = field(default_factory=dict)
    diary_queue_processing_scopes: Set[ScopeKey] = field(default_factory=set)
    auth_fingerprint_path: str = ""
    auth_fingerprint: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock)
    auth_change_lock: threading.Lock = field(default_factory=threading.Lock)


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


def load_chat_threads(path: str) -> Dict[ScopeKey, str]:
    data_path = Path(path)
    if not data_path.exists():
        return {}
    try:
        raw = json.loads(data_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to parse chat thread state {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid chat thread state {path}: root is not object")
    parsed: Dict[ScopeKey, str] = {}
    for key, value in raw.items():
        if not isinstance(value, str) or not value.strip():
            continue
        scope_key = normalize_scope_storage_key(key)
        if scope_key is None:
            continue
        parsed[scope_key] = value.strip()
    return parsed


def load_chat_engines(path: str) -> Dict[ScopeKey, str]:
    data_path = Path(path)
    if not data_path.exists():
        return {}
    try:
        raw = json.loads(data_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to parse chat engine state {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid chat engine state {path}: root is not object")
    parsed: Dict[ScopeKey, str] = {}
    for key, value in raw.items():
        if not isinstance(value, str) or not value.strip():
            continue
        scope_key = normalize_scope_storage_key(key)
        if scope_key is None:
            continue
        parsed[scope_key] = value.strip().lower()
    return parsed


def load_chat_codex_models(path: str) -> Dict[ScopeKey, str]:
    data_path = Path(path)
    if not data_path.exists():
        return {}
    try:
        raw = json.loads(data_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to parse chat Codex model state {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid chat Codex model state {path}: root is not object")
    parsed: Dict[ScopeKey, str] = {}
    for key, value in raw.items():
        if not isinstance(value, str) or not value.strip():
            continue
        scope_key = normalize_scope_storage_key(key)
        if scope_key is None:
            continue
        parsed[scope_key] = value.strip()
    return parsed


def load_chat_codex_efforts(path: str) -> Dict[ScopeKey, str]:
    data_path = Path(path)
    if not data_path.exists():
        return {}
    try:
        raw = json.loads(data_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to parse chat Codex effort state {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid chat Codex effort state {path}: root is not object")
    parsed: Dict[ScopeKey, str] = {}
    for key, value in raw.items():
        if not isinstance(value, str) or not value.strip():
            continue
        scope_key = normalize_scope_storage_key(key)
        if scope_key is None:
            continue
        parsed[scope_key] = value.strip().lower()
    return parsed


def load_chat_pi_models(path: str) -> Dict[ScopeKey, str]:
    data_path = Path(path)
    if not data_path.exists():
        return {}
    try:
        raw = json.loads(data_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to parse chat Pi model state {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid chat Pi model state {path}: root is not object")
    parsed: Dict[ScopeKey, str] = {}
    for key, value in raw.items():
        if not isinstance(value, str) or not value.strip():
            continue
        scope_key = normalize_scope_storage_key(key)
        if scope_key is None:
            continue
        parsed[scope_key] = value.strip()
    return parsed


def load_chat_pi_providers(path: str) -> Dict[ScopeKey, str]:
    data_path = Path(path)
    if not data_path.exists():
        return {}
    try:
        raw = json.loads(data_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to parse chat Pi provider state {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid chat Pi provider state {path}: root is not object")
    parsed: Dict[ScopeKey, str] = {}
    for key, value in raw.items():
        if not isinstance(value, str) or not value.strip():
            continue
        scope_key = normalize_scope_storage_key(key)
        if scope_key is None:
            continue
        parsed[scope_key] = value.strip().lower()
    return parsed


def load_worker_sessions(path: str) -> Dict[ScopeKey, WorkerSession]:
    data_path = Path(path)
    if not data_path.exists():
        return {}
    try:
        raw = json.loads(data_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to parse worker session state {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid worker session state {path}: root is not object")

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
    data_path = Path(path)
    if not data_path.exists():
        return {}
    try:
        raw = json.loads(data_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to parse in-flight state {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid in-flight state {path}: root is not object")

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


def load_canonical_sessions(path: str) -> Dict[ScopeKey, CanonicalSession]:
    data_path = Path(path)
    if not data_path.exists():
        return {}
    try:
        raw = json.loads(data_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to parse canonical session state {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid canonical session state {path}: root is not object")

    parsed: Dict[ScopeKey, CanonicalSession] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        scope_key = normalize_scope_storage_key(key)
        if scope_key is None:
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

        parsed[scope_key] = CanonicalSession(
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


def ensure_canonical_sessions_sqlite(path: str) -> None:
    if not path:
        return
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        has_table = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'canonical_sessions'
            """
        ).fetchone()
        if has_table is not None:
            columns = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(canonical_sessions)").fetchall()
            }
            if "scope_key" not in columns:
                conn.execute("ALTER TABLE canonical_sessions RENAME TO canonical_sessions_legacy")
                conn.execute(
                    """
                    CREATE TABLE canonical_sessions (
                        scope_key TEXT PRIMARY KEY,
                        chat_id INTEGER,
                        message_thread_id INTEGER,
                        thread_id TEXT NOT NULL DEFAULT '',
                        worker_created_at REAL,
                        worker_last_used_at REAL,
                        worker_policy_fingerprint TEXT NOT NULL DEFAULT '',
                        in_flight_started_at REAL,
                        in_flight_message_id INTEGER
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO canonical_sessions (
                        scope_key,
                        chat_id,
                        message_thread_id,
                        thread_id,
                        worker_created_at,
                        worker_last_used_at,
                        worker_policy_fingerprint,
                        in_flight_started_at,
                        in_flight_message_id
                    )
                    SELECT
                        'tg:' || chat_id,
                        chat_id,
                        NULL,
                        thread_id,
                        worker_created_at,
                        worker_last_used_at,
                        worker_policy_fingerprint,
                        in_flight_started_at,
                        in_flight_message_id
                    FROM canonical_sessions_legacy
                    """
                )
                conn.execute("DROP TABLE canonical_sessions_legacy")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS canonical_sessions (
                scope_key TEXT PRIMARY KEY,
                chat_id INTEGER,
                message_thread_id INTEGER,
                thread_id TEXT NOT NULL DEFAULT '',
                worker_created_at REAL,
                worker_last_used_at REAL,
                worker_policy_fingerprint TEXT NOT NULL DEFAULT '',
                in_flight_started_at REAL,
                in_flight_message_id INTEGER
            )
            """
        )
        conn.commit()


def load_canonical_sessions_sqlite(path: str) -> Dict[ScopeKey, CanonicalSession]:
    if not path:
        return {}
    ensure_canonical_sessions_sqlite(path)
    parsed: Dict[ScopeKey, CanonicalSession] = {}
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            """
            SELECT
                scope_key,
                thread_id,
                worker_created_at,
                worker_last_used_at,
                worker_policy_fingerprint,
                in_flight_started_at,
                in_flight_message_id
            FROM canonical_sessions
            ORDER BY scope_key
            """
        ).fetchall()
    for row in rows:
        scope_key = normalize_scope_storage_key(row[0])
        if scope_key is None:
            continue
        thread_id = str(row[1] or "").strip()
        worker_created_at = float(row[2]) if row[2] is not None else None
        worker_last_used_at = float(row[3]) if row[3] is not None else None
        worker_policy_fingerprint = str(row[4] or "").strip()
        in_flight_started_at = float(row[5]) if row[5] is not None else None
        in_flight_message_id = int(row[6]) if row[6] is not None else None
        parsed[scope_key] = CanonicalSession(
            thread_id=thread_id,
            worker_created_at=worker_created_at,
            worker_last_used_at=worker_last_used_at,
            worker_policy_fingerprint=worker_policy_fingerprint,
            in_flight_started_at=in_flight_started_at,
            in_flight_message_id=in_flight_message_id,
        )
    return parsed


def persist_canonical_sessions_sqlite(
    path: str,
    sessions: Dict[ScopeKey, CanonicalSession],
) -> None:
    if not path:
        return
    ensure_canonical_sessions_sqlite(path)
    with sqlite3.connect(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM canonical_sessions")
        if sessions:
            conn.executemany(
                """
                INSERT INTO canonical_sessions (
                    scope_key,
                    chat_id,
                    message_thread_id,
                    thread_id,
                    worker_created_at,
                    worker_last_used_at,
                    worker_policy_fingerprint,
                    in_flight_started_at,
                    in_flight_message_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        normalize_scope_key(scope_key),
                        (
                            parse_telegram_scope_key(normalize_scope_key(scope_key)).chat_id
                            if normalize_scope_key(scope_key).startswith("tg:")
                            else None
                        ),
                        (
                            parse_telegram_scope_key(normalize_scope_key(scope_key)).message_thread_id
                            if normalize_scope_key(scope_key).startswith("tg:")
                            else None
                        ),
                        session.thread_id,
                        session.worker_created_at,
                        session.worker_last_used_at,
                        session.worker_policy_fingerprint,
                        session.in_flight_started_at,
                        session.in_flight_message_id,
                    )
                    for scope_key, session in sorted(sessions.items())
                ],
            )
        conn.commit()


def load_or_import_canonical_sessions_sqlite(
    path: str,
    import_sessions: Optional[Dict[ScopeKey, CanonicalSession]] = None,
) -> tuple[Dict[ScopeKey, CanonicalSession], bool]:
    if not path:
        if import_sessions:
            return dict(import_sessions), False
        return {}, False
    sessions = load_canonical_sessions_sqlite(path)
    if sessions:
        return sessions, False
    ensure_canonical_sessions_sqlite(path)
    if not import_sessions:
        return {}, False
    persist_canonical_sessions_sqlite(path, import_sessions)
    return load_canonical_sessions_sqlite(path), True


def _build_canonical_session_for_scope(
    scope_key: ScopeKey,
    chat_threads: Dict[ScopeKey, str],
    worker_sessions: Dict[ScopeKey, WorkerSession],
    in_flight_requests: Dict[ScopeKey, Dict[str, object]],
) -> Optional[CanonicalSession]:
    thread_id = chat_threads.get(scope_key, "")
    worker = worker_sessions.get(scope_key)
    in_flight = in_flight_requests.get(scope_key)

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
    chat_threads: Dict[ScopeKey, str],
    worker_sessions: Dict[ScopeKey, WorkerSession],
    in_flight_requests: Dict[ScopeKey, Dict[str, object]],
) -> Dict[ScopeKey, CanonicalSession]:
    out: Dict[ScopeKey, CanonicalSession] = {}
    all_scope_keys = set(chat_threads) | set(worker_sessions) | set(in_flight_requests)
    for scope_key in all_scope_keys:
        session = _build_canonical_session_for_scope(
            scope_key,
            chat_threads,
            worker_sessions,
            in_flight_requests,
        )
        if session is not None:
            out[scope_key] = session
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
    canonical_sessions: Dict[ScopeKey, CanonicalSession],
) -> tuple[Dict[ScopeKey, str], Dict[ScopeKey, WorkerSession], Dict[ScopeKey, Dict[str, object]]]:
    chat_threads: Dict[ScopeKey, str] = {}
    worker_sessions: Dict[ScopeKey, WorkerSession] = {}
    in_flight_requests: Dict[ScopeKey, Dict[str, object]] = {}
    for scope_key, session in canonical_sessions.items():
        thread_value, worker_value, in_flight_value = _canonical_session_to_legacy(session)
        if thread_value is not None:
            chat_threads[scope_key] = thread_value
        if worker_value is not None:
            worker_sessions[scope_key] = worker_value
        if in_flight_value is not None:
            in_flight_requests[scope_key] = in_flight_value
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
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(serialized, indent=2, sort_keys=True) + "\n"

    # Use a unique temp file per write to avoid cross-thread collisions on a
    # shared '<name>.tmp' path.
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        tmp_path.replace(path)
    except Exception:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise


def persist_chat_threads(state: State) -> None:
    with state.lock:
        serialized = {
            normalize_scope_key(scope_key): thread_id
            for scope_key, thread_id in state.chat_threads.items()
        }
    persist_json_state_file(state.chat_thread_path, serialized)


def persist_chat_engines(state: State) -> None:
    with state.lock:
        serialized = {
            normalize_scope_key(scope_key): engine_name
            for scope_key, engine_name in state.chat_engines.items()
        }
    persist_json_state_file(state.chat_engine_path, serialized)


def persist_chat_codex_models(state: State) -> None:
    with state.lock:
        serialized = {
            normalize_scope_key(scope_key): model_name
            for scope_key, model_name in state.chat_codex_models.items()
        }
    persist_json_state_file(state.chat_codex_model_path, serialized)


def persist_chat_codex_efforts(state: State) -> None:
    with state.lock:
        serialized = {
            normalize_scope_key(scope_key): effort_name
            for scope_key, effort_name in state.chat_codex_efforts.items()
        }
    persist_json_state_file(state.chat_codex_effort_path, serialized)


def persist_chat_pi_models(state: State) -> None:
    with state.lock:
        serialized = {
            normalize_scope_key(scope_key): model_name
            for scope_key, model_name in state.chat_pi_models.items()
        }
    persist_json_state_file(state.chat_pi_model_path, serialized)


def persist_chat_pi_providers(state: State) -> None:
    with state.lock:
        serialized = {
            normalize_scope_key(scope_key): provider_name
            for scope_key, provider_name in state.chat_pi_providers.items()
        }
    persist_json_state_file(state.chat_pi_provider_path, serialized)


def get_chat_engine(state: State, scope_key: ScopeKey) -> Optional[str]:
    scope_key = normalize_scope_key(scope_key)
    with state.lock:
        engine_name = state.chat_engines.get(scope_key, "").strip().lower()
    return engine_name or None


def set_chat_engine(state: State, scope_key: ScopeKey, engine_name: str) -> None:
    scope_key = normalize_scope_key(scope_key)
    normalized_engine = engine_name.strip().lower()
    with state.lock:
        state.chat_engines[scope_key] = normalized_engine
    persist_chat_engines(state)


def clear_chat_engine(state: State, scope_key: ScopeKey) -> bool:
    scope_key = normalize_scope_key(scope_key)
    removed = False
    with state.lock:
        if scope_key in state.chat_engines:
            del state.chat_engines[scope_key]
            removed = True
    if removed:
        persist_chat_engines(state)
    return removed


def get_chat_codex_model(state: State, scope_key: ScopeKey) -> Optional[str]:
    scope_key = normalize_scope_key(scope_key)
    with state.lock:
        model_name = state.chat_codex_models.get(scope_key, "").strip()
    return model_name or None


def set_chat_codex_model(state: State, scope_key: ScopeKey, model_name: str) -> None:
    scope_key = normalize_scope_key(scope_key)
    normalized_model = model_name.strip()
    with state.lock:
        state.chat_codex_models[scope_key] = normalized_model
    persist_chat_codex_models(state)


def clear_chat_codex_model(state: State, scope_key: ScopeKey) -> bool:
    scope_key = normalize_scope_key(scope_key)
    removed = False
    with state.lock:
        if scope_key in state.chat_codex_models:
            del state.chat_codex_models[scope_key]
            removed = True
    if removed:
        persist_chat_codex_models(state)
    return removed


def get_chat_codex_effort(state: State, scope_key: ScopeKey) -> Optional[str]:
    scope_key = normalize_scope_key(scope_key)
    with state.lock:
        effort_name = state.chat_codex_efforts.get(scope_key, "").strip().lower()
    return effort_name or None


def set_chat_codex_effort(state: State, scope_key: ScopeKey, effort_name: str) -> None:
    scope_key = normalize_scope_key(scope_key)
    normalized_effort = effort_name.strip().lower()
    with state.lock:
        state.chat_codex_efforts[scope_key] = normalized_effort
    persist_chat_codex_efforts(state)


def clear_chat_codex_effort(state: State, scope_key: ScopeKey) -> bool:
    scope_key = normalize_scope_key(scope_key)
    removed = False
    with state.lock:
        if scope_key in state.chat_codex_efforts:
            del state.chat_codex_efforts[scope_key]
            removed = True
    if removed:
        persist_chat_codex_efforts(state)
    return removed


def get_chat_pi_provider(state: State, scope_key: ScopeKey) -> Optional[str]:
    scope_key = normalize_scope_key(scope_key)
    with state.lock:
        provider_name = state.chat_pi_providers.get(scope_key, "").strip().lower()
    return provider_name or None


def set_chat_pi_provider(state: State, scope_key: ScopeKey, provider_name: str) -> None:
    scope_key = normalize_scope_key(scope_key)
    normalized_provider = provider_name.strip().lower()
    with state.lock:
        state.chat_pi_providers[scope_key] = normalized_provider
    persist_chat_pi_providers(state)


def clear_chat_pi_provider(state: State, scope_key: ScopeKey) -> bool:
    scope_key = normalize_scope_key(scope_key)
    removed = False
    with state.lock:
        if scope_key in state.chat_pi_providers:
            del state.chat_pi_providers[scope_key]
            removed = True
    if removed:
        persist_chat_pi_providers(state)
    return removed


def get_chat_pi_model(state: State, scope_key: ScopeKey) -> Optional[str]:
    scope_key = normalize_scope_key(scope_key)
    with state.lock:
        model_name = state.chat_pi_models.get(scope_key, "").strip()
    return model_name or None


def set_chat_pi_model(state: State, scope_key: ScopeKey, model_name: str) -> None:
    scope_key = normalize_scope_key(scope_key)
    normalized_model = model_name.strip()
    with state.lock:
        state.chat_pi_models[scope_key] = normalized_model
    persist_chat_pi_models(state)


def clear_chat_pi_model(state: State, scope_key: ScopeKey) -> bool:
    scope_key = normalize_scope_key(scope_key)
    removed = False
    with state.lock:
        if scope_key in state.chat_pi_models:
            del state.chat_pi_models[scope_key]
            removed = True
    if removed:
        persist_chat_pi_models(state)
    return removed


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


def persist_canonical_sessions(state: State) -> None:
    if not state.canonical_sessions_enabled:
        return
    with state.lock:
        sessions = {
            normalize_scope_key(scope_key): CanonicalSession(
                thread_id=session.thread_id,
                worker_created_at=session.worker_created_at,
                worker_last_used_at=session.worker_last_used_at,
                worker_policy_fingerprint=session.worker_policy_fingerprint,
                in_flight_started_at=session.in_flight_started_at,
                in_flight_message_id=session.in_flight_message_id,
            )
            for scope_key, session in state.chat_sessions.items()
        }
        serialized = {
            scope_key: {
                "thread_id": session.thread_id,
                "worker_created_at": session.worker_created_at,
                "worker_last_used_at": session.worker_last_used_at,
                "worker_policy_fingerprint": session.worker_policy_fingerprint,
                "in_flight_started_at": session.in_flight_started_at,
                "in_flight_message_id": session.in_flight_message_id,
            }
            for scope_key, session in sessions.items()
        }
    if state.canonical_sqlite_enabled:
        persist_canonical_sessions_sqlite(state.canonical_sqlite_path, sessions)
        if state.canonical_json_mirror_enabled:
            persist_json_state_file(state.chat_sessions_path, serialized)
        return
    persist_json_state_file(state.chat_sessions_path, serialized)


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
        persist_chat_threads(state)
        persist_worker_sessions(state)
        persist_in_flight_requests(state)


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


def clear_worker_session(state: State, scope_key: ScopeKey) -> bool:
    scope_key = normalize_scope_key(scope_key)
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
                if canonical_session_is_empty(session):
                    del state.chat_sessions[scope_key]
                changed = True
        if changed:
            persist_canonical_sessions(state)
            mirror_legacy_from_canonical(
                state,
                persist=state.canonical_legacy_mirror_enabled,
            )
        return changed

    removed = False
    with state.lock:
        if scope_key in state.worker_sessions:
            del state.worker_sessions[scope_key]
            removed = True
    if removed:
        persist_worker_sessions(state)
        sync_canonical_session(state, scope_key)
    return removed


def get_thread_id(state: State, scope_key: ScopeKey) -> Optional[str]:
    scope_key = normalize_scope_key(scope_key)
    if state.canonical_sessions_enabled:
        with state.lock:
            session = state.chat_sessions.get(scope_key)
            if session is None:
                return None
            thread_id = session.thread_id.strip()
            return thread_id or None
    with state.lock:
        return state.chat_threads.get(scope_key)


def set_thread_id(state: State, scope_key: ScopeKey, thread_id: str) -> None:
    scope_key = normalize_scope_key(scope_key)
    if state.canonical_sessions_enabled:
        normalized_thread_id = thread_id.strip()
        changed = False
        with state.lock:
            session = state.chat_sessions.get(scope_key)
            if session is None:
                session = CanonicalSession()
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
            persist_canonical_sessions(state)
            mirror_legacy_from_canonical(
                state,
                persist=state.canonical_legacy_mirror_enabled,
            )
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
        persist_chat_threads(state)
    if persist_sessions:
        persist_worker_sessions(state)
    if persist_threads or persist_sessions:
        sync_canonical_session(state, scope_key)


def clear_thread_id(state: State, scope_key: ScopeKey) -> bool:
    scope_key = normalize_scope_key(scope_key)
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
                if canonical_session_is_empty(session):
                    del state.chat_sessions[scope_key]
                    removed = True
        if removed:
            persist_canonical_sessions(state)
            mirror_legacy_from_canonical(
                state,
                persist=state.canonical_legacy_mirror_enabled,
            )
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
        persist_chat_threads(state)
    if persist_sessions:
        persist_worker_sessions(state)
    if removed or persist_sessions:
        sync_canonical_session(state, scope_key)
    return removed


def mark_in_flight_request(state: State, scope_key: ScopeKey, message_id: Optional[int]) -> None:
    scope_key = normalize_scope_key(scope_key)
    if state.canonical_sessions_enabled:
        with state.lock:
            session = state.chat_sessions.get(scope_key)
            if session is None:
                session = CanonicalSession()
                state.chat_sessions[scope_key] = session
            session.in_flight_started_at = time.time()
            session.in_flight_message_id = message_id if isinstance(message_id, int) else None
        persist_canonical_sessions(state)
        mirror_legacy_from_canonical(
            state,
            persist=state.canonical_legacy_mirror_enabled,
        )
        return

    payload: Dict[str, object] = {"started_at": time.time()}
    if isinstance(message_id, int):
        payload["message_id"] = message_id
    with state.lock:
        state.in_flight_requests[scope_key] = payload
    persist_in_flight_requests(state)
    sync_canonical_session(state, scope_key)


def clear_in_flight_request(state: State, scope_key: ScopeKey) -> None:
    scope_key = normalize_scope_key(scope_key)
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
                if canonical_session_is_empty(session):
                    del state.chat_sessions[scope_key]
                changed = True
        if changed:
            persist_canonical_sessions(state)
            mirror_legacy_from_canonical(
                state,
                persist=state.canonical_legacy_mirror_enabled,
            )
        return

    removed = False
    with state.lock:
        if scope_key in state.in_flight_requests:
            del state.in_flight_requests[scope_key]
            removed = True
    if removed:
        persist_in_flight_requests(state)
        sync_canonical_session(state, scope_key)


def pop_interrupted_requests(state: State) -> Dict[ScopeKey, Dict[str, object]]:
    if state.canonical_sessions_enabled:
        interrupted: Dict[ScopeKey, Dict[str, object]] = {}
        with state.lock:
            for scope_key, session in state.chat_sessions.items():
                if session.in_flight_started_at is None:
                    continue
                payload: Dict[str, object] = {"started_at": float(session.in_flight_started_at)}
                if session.in_flight_message_id is not None:
                    payload["message_id"] = session.in_flight_message_id
                interrupted[scope_key] = payload

            if not interrupted:
                return {}

            for scope_key in list(interrupted):
                session = state.chat_sessions.get(scope_key)
                if session is None:
                    continue
                session.in_flight_started_at = None
                session.in_flight_message_id = None
                if canonical_session_is_empty(session):
                    del state.chat_sessions[scope_key]
        persist_canonical_sessions(state)
        mirror_legacy_from_canonical(
            state,
            persist=state.canonical_legacy_mirror_enabled,
        )
        return interrupted

    with state.lock:
        if not state.in_flight_requests:
            return {}
        interrupted = dict(state.in_flight_requests)
        state.in_flight_requests = {}
    persist_in_flight_requests(state)
    if state.canonical_sessions_enabled:
        for scope_key in interrupted:
            sync_canonical_session(state, scope_key)
    return interrupted


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
