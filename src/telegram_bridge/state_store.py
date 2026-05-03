import json
import os
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional

try:
    from .conversation_scope import normalize_scope_storage_key, parse_telegram_scope_key
    from . import request_state
    from . import session_state
    from .state_models import (
        CanonicalSession,
        PendingDiaryBatch,
        PendingMediaGroup,
        RecentPhotoSelection,
        ScopeKey,
        State,
        WorkerSession,
        normalize_scope_key,
    )
except ImportError:
    from conversation_scope import normalize_scope_storage_key, parse_telegram_scope_key
    import request_state
    import session_state
    from state_models import (
        CanonicalSession,
        PendingDiaryBatch,
        PendingMediaGroup,
        RecentPhotoSelection,
        ScopeKey,
        State,
        WorkerSession,
        normalize_scope_key,
    )


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


def _load_json_object(path: str, *, state_label: str) -> Dict[object, object]:
    data_path = Path(path)
    if not data_path.exists():
        return {}
    try:
        raw = json.loads(data_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to parse {state_label} state {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid {state_label} state {path}: root is not object")
    return raw


def _load_scope_string_map(
    path: str,
    *,
    state_label: str,
    normalize_value,
) -> Dict[ScopeKey, str]:
    raw = _load_json_object(path, state_label=state_label)
    parsed: Dict[ScopeKey, str] = {}
    for key, value in raw.items():
        if not isinstance(value, str) or not value.strip():
            continue
        scope_key = normalize_scope_storage_key(key)
        if scope_key is None:
            continue
        normalized_value = normalize_value(value.strip())
        if normalized_value:
            parsed[scope_key] = normalized_value
    return parsed


def load_chat_threads(path: str) -> Dict[ScopeKey, str]:
    return _load_scope_string_map(
        path,
        state_label="chat thread",
        normalize_value=lambda value: value,
    )


def load_chat_engines(path: str) -> Dict[ScopeKey, str]:
    return _load_scope_string_map(
        path,
        state_label="chat engine",
        normalize_value=lambda value: value.lower(),
    )


def load_chat_codex_models(path: str) -> Dict[ScopeKey, str]:
    return _load_scope_string_map(
        path,
        state_label="chat Codex model",
        normalize_value=lambda value: value,
    )


def load_chat_codex_efforts(path: str) -> Dict[ScopeKey, str]:
    return _load_scope_string_map(
        path,
        state_label="chat Codex effort",
        normalize_value=lambda value: value.lower(),
    )


def load_chat_pi_models(path: str) -> Dict[ScopeKey, str]:
    return _load_scope_string_map(
        path,
        state_label="chat Pi model",
        normalize_value=lambda value: value,
    )


def load_chat_pi_providers(path: str) -> Dict[ScopeKey, str]:
    return _load_scope_string_map(
        path,
        state_label="chat Pi provider",
        normalize_value=lambda value: value.lower(),
    )


def load_worker_sessions(path: str) -> Dict[ScopeKey, WorkerSession]:
    raw = _load_json_object(path, state_label="worker session")
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
    raw = _load_json_object(path, state_label="in-flight")
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
    raw = _load_json_object(path, state_label="canonical session")
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


def _get_string_override(
    state: State,
    scope_key: ScopeKey,
    values: Dict[ScopeKey, str],
    *,
    normalize=str.strip,
) -> Optional[str]:
    scope_key = normalize_scope_key(scope_key)
    with state.lock:
        value = normalize(values.get(scope_key, ""))
    return value or None


def _set_string_override(
    state: State,
    scope_key: ScopeKey,
    values: Dict[ScopeKey, str],
    raw_value: str,
    persist_fn,
    *,
    normalize=str.strip,
) -> None:
    scope_key = normalize_scope_key(scope_key)
    normalized_value = normalize(raw_value)
    with state.lock:
        values[scope_key] = normalized_value
    persist_fn(state)


def _clear_string_override(
    state: State,
    scope_key: ScopeKey,
    values: Dict[ScopeKey, str],
    persist_fn,
) -> bool:
    scope_key = normalize_scope_key(scope_key)
    removed = False
    with state.lock:
        if scope_key in values:
            del values[scope_key]
            removed = True
    if removed:
        persist_fn(state)
    return removed


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


def get_chat_engine(state: State, scope_key: ScopeKey) -> Optional[str]:
    return _get_string_override(
        state,
        scope_key,
        state.chat_engines,
        normalize=lambda value: value.strip().lower(),
    )


def set_chat_engine(state: State, scope_key: ScopeKey, engine_name: str) -> None:
    _set_string_override(
        state,
        scope_key,
        state.chat_engines,
        engine_name,
        persist_chat_engines,
        normalize=lambda value: value.strip().lower(),
    )


def clear_chat_engine(state: State, scope_key: ScopeKey) -> bool:
    return _clear_string_override(
        state,
        scope_key,
        state.chat_engines,
        persist_chat_engines,
    )


def get_chat_codex_model(state: State, scope_key: ScopeKey) -> Optional[str]:
    return _get_string_override(state, scope_key, state.chat_codex_models)


def set_chat_codex_model(state: State, scope_key: ScopeKey, model_name: str) -> None:
    _set_string_override(
        state,
        scope_key,
        state.chat_codex_models,
        model_name,
        persist_chat_codex_models,
    )


def clear_chat_codex_model(state: State, scope_key: ScopeKey) -> bool:
    return _clear_string_override(
        state,
        scope_key,
        state.chat_codex_models,
        persist_chat_codex_models,
    )


def get_chat_codex_effort(state: State, scope_key: ScopeKey) -> Optional[str]:
    return _get_string_override(
        state,
        scope_key,
        state.chat_codex_efforts,
        normalize=lambda value: value.strip().lower(),
    )


def set_chat_codex_effort(state: State, scope_key: ScopeKey, effort_name: str) -> None:
    _set_string_override(
        state,
        scope_key,
        state.chat_codex_efforts,
        effort_name,
        persist_chat_codex_efforts,
        normalize=lambda value: value.strip().lower(),
    )


def clear_chat_codex_effort(state: State, scope_key: ScopeKey) -> bool:
    return _clear_string_override(
        state,
        scope_key,
        state.chat_codex_efforts,
        persist_chat_codex_efforts,
    )


def get_chat_pi_provider(state: State, scope_key: ScopeKey) -> Optional[str]:
    return _get_string_override(
        state,
        scope_key,
        state.chat_pi_providers,
        normalize=lambda value: value.strip().lower(),
    )


def set_chat_pi_provider(state: State, scope_key: ScopeKey, provider_name: str) -> None:
    _set_string_override(
        state,
        scope_key,
        state.chat_pi_providers,
        provider_name,
        persist_chat_pi_providers,
        normalize=lambda value: value.strip().lower(),
    )


def clear_chat_pi_provider(state: State, scope_key: ScopeKey) -> bool:
    return _clear_string_override(
        state,
        scope_key,
        state.chat_pi_providers,
        persist_chat_pi_providers,
    )


def get_chat_pi_model(state: State, scope_key: ScopeKey) -> Optional[str]:
    return _get_string_override(state, scope_key, state.chat_pi_models)


def set_chat_pi_model(state: State, scope_key: ScopeKey, model_name: str) -> None:
    _set_string_override(
        state,
        scope_key,
        state.chat_pi_models,
        model_name,
        persist_chat_pi_models,
    )


def clear_chat_pi_model(state: State, scope_key: ScopeKey) -> bool:
    return _clear_string_override(
        state,
        scope_key,
        state.chat_pi_models,
        persist_chat_pi_models,
    )


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
        _persist_legacy_state(
            state,
            chat_threads=True,
            worker_sessions=True,
            in_flight_requests=True,
        )


def persist_canonical_and_mirror_legacy(state: State) -> None:
    persist_canonical_sessions(state)
    mirror_legacy_from_canonical(
        state,
        persist=state.canonical_legacy_mirror_enabled,
    )


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
        persist_canonical_and_mirror_legacy(state)


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
    return session_state.clear_worker_session(
        state,
        scope_key,
        normalize_scope_key_fn=normalize_scope_key,
        canonical_session_is_empty_fn=canonical_session_is_empty,
        persist_canonical_and_mirror_legacy_fn=persist_canonical_and_mirror_legacy,
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
        persist_canonical_and_mirror_legacy_fn=persist_canonical_and_mirror_legacy,
        sync_canonical_session_fn=sync_canonical_session,
    )


def clear_thread_id(state: State, scope_key: ScopeKey) -> bool:
    return session_state.clear_thread_id(
        state,
        scope_key,
        normalize_scope_key_fn=normalize_scope_key,
        canonical_session_is_empty_fn=canonical_session_is_empty,
        persist_legacy_state_fn=_persist_legacy_state,
        persist_canonical_and_mirror_legacy_fn=persist_canonical_and_mirror_legacy,
        sync_canonical_session_fn=sync_canonical_session,
    )


def mark_in_flight_request(state: State, scope_key: ScopeKey, message_id: Optional[int]) -> None:
    request_state.mark_in_flight_request(
        state,
        scope_key,
        message_id,
        normalize_scope_key_fn=normalize_scope_key,
        canonical_session_cls=CanonicalSession,
        persist_canonical_and_mirror_legacy_fn=persist_canonical_and_mirror_legacy,
        persist_in_flight_requests_fn=persist_in_flight_requests,
        sync_canonical_session_fn=sync_canonical_session,
    )


def clear_in_flight_request(state: State, scope_key: ScopeKey) -> None:
    request_state.clear_in_flight_request(
        state,
        scope_key,
        normalize_scope_key_fn=normalize_scope_key,
        canonical_session_is_empty_fn=canonical_session_is_empty,
        persist_canonical_and_mirror_legacy_fn=persist_canonical_and_mirror_legacy,
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
