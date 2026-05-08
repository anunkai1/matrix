import sqlite3
from pathlib import Path
from typing import Dict, Optional

from telegram_bridge.conversation_scope import parse_telegram_scope_key
from telegram_bridge.state_models import (
    CanonicalSession,
    ScopeKey,
    WorkerSession,
    normalize_scope_key,
    normalize_scope_storage_key,
)


def load_canonical_sessions_from_json_object(
    raw: Dict[object, object],
) -> Dict[ScopeKey, CanonicalSession]:
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


def _canonical_session_sqlite_row(
    scope_key: ScopeKey,
    session: CanonicalSession,
) -> tuple[str, Optional[int], Optional[int], str, Optional[float], Optional[float], str, Optional[float], Optional[int]]:
    normalized_scope_key = normalize_scope_key(scope_key)
    chat_id: Optional[int] = None
    message_thread_id: Optional[int] = None
    if normalized_scope_key.startswith("tg:"):
        try:
            parsed_scope = parse_telegram_scope_key(normalized_scope_key)
        except ValueError:
            parsed_scope = None
        if parsed_scope is not None:
            chat_id = parsed_scope.chat_id
            message_thread_id = parsed_scope.message_thread_id
    return (
        normalized_scope_key,
        chat_id,
        message_thread_id,
        session.thread_id,
        session.worker_created_at,
        session.worker_last_used_at,
        session.worker_policy_fingerprint,
        session.in_flight_started_at,
        session.in_flight_message_id,
    )


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
                    _canonical_session_sqlite_row(scope_key, session)
                    for scope_key, session in sorted(sessions.items())
                ],
            )
        conn.commit()


def persist_canonical_session_sqlite(
    path: str,
    scope_key: ScopeKey,
    session: Optional[CanonicalSession],
) -> None:
    if not path:
        return
    ensure_canonical_sessions_sqlite(path)
    normalized_scope_key = normalize_scope_key(scope_key)
    with sqlite3.connect(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        if session is None:
            conn.execute(
                "DELETE FROM canonical_sessions WHERE scope_key = ?",
                (normalized_scope_key,),
            )
        else:
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
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(scope_key) DO UPDATE SET
                    chat_id = excluded.chat_id,
                    message_thread_id = excluded.message_thread_id,
                    thread_id = excluded.thread_id,
                    worker_created_at = excluded.worker_created_at,
                    worker_last_used_at = excluded.worker_last_used_at,
                    worker_policy_fingerprint = excluded.worker_policy_fingerprint,
                    in_flight_started_at = excluded.in_flight_started_at,
                    in_flight_message_id = excluded.in_flight_message_id
                """,
                _canonical_session_sqlite_row(normalized_scope_key, session),
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


def copy_canonical_session(session: CanonicalSession) -> CanonicalSession:
    return CanonicalSession(
        thread_id=session.thread_id,
        worker_created_at=session.worker_created_at,
        worker_last_used_at=session.worker_last_used_at,
        worker_policy_fingerprint=session.worker_policy_fingerprint,
        in_flight_started_at=session.in_flight_started_at,
        in_flight_message_id=session.in_flight_message_id,
    )


def serialize_canonical_sessions(
    sessions: Dict[ScopeKey, CanonicalSession],
) -> Dict[ScopeKey, Dict[str, object]]:
    return {
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
