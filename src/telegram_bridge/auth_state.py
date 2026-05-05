from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Dict

from telegram_bridge.state_store import (
    CanonicalSession,
    ScopeKey,
    State,
    WorkerSession,
    canonical_session_is_empty,
    mirror_legacy_from_canonical,
    persist_chat_threads,
    persist_canonical_sessions,
    persist_worker_sessions,
)

def build_auth_fingerprint_state_path(state_dir: str) -> str:
    return os.path.join(state_dir, "auth_fingerprint.txt")

def load_saved_auth_fingerprint(path: str) -> str:
    if not path:
        return ""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except FileNotFoundError:
        return ""
    except OSError:
        return ""

def persist_saved_auth_fingerprint(path: str, fingerprint: str) -> None:
    if not path:
        return
    directory = os.path.dirname(path)
    if directory:
        Path(directory).mkdir(parents=True, exist_ok=True)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        handle.write(fingerprint.strip())
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)

def _stable_auth_identity(payload: Dict[str, object]) -> str:
    auth_mode = str(payload.get("auth_mode") or "").strip().lower()
    tokens = payload.get("tokens") if isinstance(payload.get("tokens"), dict) else {}
    account_id = str((tokens or {}).get("account_id") or "").strip()
    api_key = str(payload.get("OPENAI_API_KEY") or "").strip()

    if auth_mode and account_id:
        return f"{auth_mode}:{account_id}"
    if account_id:
        return f"account:{account_id}"
    if api_key:
        api_key_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
        return f"api_key:{api_key_hash}"
    return ""

def compute_current_auth_fingerprint(auth_path: str | None = None) -> str:
    resolved_path = (
        auth_path
        or os.getenv("SERVER3_CODEX_SHARED_AUTH_PATH", "").strip()
        or os.path.expanduser("~/.codex/auth.json")
    )
    if not resolved_path:
        return ""
    try:
        payload = json.loads(Path(resolved_path).read_text(encoding="utf-8"))
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    identity = _stable_auth_identity(payload)
    if not identity:
        return ""
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()

def clear_loaded_thread_state(
    loaded_threads: Dict[ScopeKey, str],
    loaded_worker_sessions: Dict[ScopeKey, WorkerSession],
    loaded_canonical_sessions: Dict[ScopeKey, CanonicalSession],
) -> Dict[str, int]:
    cleared_thread_count = sum(1 for thread_id in loaded_threads.values() if thread_id.strip())
    cleared_worker_session_count = len(loaded_worker_sessions)
    cleared_canonical_session_count = 0

    if loaded_threads:
        loaded_threads.clear()
    if loaded_worker_sessions:
        loaded_worker_sessions.clear()

    for scope_key in list(loaded_canonical_sessions):
        session = loaded_canonical_sessions[scope_key]
        changed = False
        if session.thread_id.strip():
            session.thread_id = ""
            changed = True
        if (
            session.worker_created_at is not None
            or session.worker_last_used_at is not None
            or session.worker_policy_fingerprint.strip()
        ):
            session.worker_created_at = None
            session.worker_last_used_at = None
            session.worker_policy_fingerprint = ""
            changed = True
        if changed:
            cleared_canonical_session_count += 1
        if canonical_session_is_empty(session):
            del loaded_canonical_sessions[scope_key]

    return {
        "threads": cleared_thread_count,
        "worker_sessions": cleared_worker_session_count,
        "canonical_sessions": cleared_canonical_session_count,
    }

def apply_auth_change_thread_reset(
    *,
    state_dir: str,
    current_auth_fingerprint: str,
    loaded_threads: Dict[ScopeKey, str],
    loaded_worker_sessions: Dict[ScopeKey, WorkerSession],
    loaded_canonical_sessions: Dict[ScopeKey, CanonicalSession],
) -> Dict[str, object]:
    if not current_auth_fingerprint.strip():
        return {
            "applied": False,
            "previous_auth_fingerprint": "",
            "counts": {
                "threads": 0,
                "worker_sessions": 0,
                "canonical_sessions": 0,
            },
        }

    state_path = build_auth_fingerprint_state_path(state_dir)
    previous_auth_fingerprint = load_saved_auth_fingerprint(state_path)
    reset_counts = {
        "threads": 0,
        "worker_sessions": 0,
        "canonical_sessions": 0,
    }
    applied = False

    if not previous_auth_fingerprint or previous_auth_fingerprint != current_auth_fingerprint:
        reset_counts = clear_loaded_thread_state(
            loaded_threads,
            loaded_worker_sessions,
            loaded_canonical_sessions,
        )
        applied = any(reset_counts.values())

    persist_saved_auth_fingerprint(state_path, current_auth_fingerprint)
    return {
        "applied": applied,
        "previous_auth_fingerprint": previous_auth_fingerprint,
        "counts": reset_counts,
    }

def clear_runtime_thread_state(state: State) -> Dict[str, int]:
    if state.canonical_sessions_enabled:
        cleared_thread_count = 0
        cleared_worker_session_count = 0
        cleared_canonical_session_count = 0
        with state.lock:
            for scope_key in list(state.chat_sessions):
                session = state.chat_sessions[scope_key]
                changed = False
                if session.thread_id.strip():
                    session.thread_id = ""
                    cleared_thread_count += 1
                    changed = True
                if (
                    session.worker_created_at is not None
                    or session.worker_last_used_at is not None
                    or session.worker_policy_fingerprint.strip()
                ):
                    session.worker_created_at = None
                    session.worker_last_used_at = None
                    session.worker_policy_fingerprint = ""
                    cleared_worker_session_count += 1
                    changed = True
                if changed:
                    cleared_canonical_session_count += 1
                if canonical_session_is_empty(session):
                    del state.chat_sessions[scope_key]
        persist_canonical_sessions(state)
        mirror_legacy_from_canonical(
            state,
            persist=state.canonical_legacy_mirror_enabled,
        )
        return {
            "threads": cleared_thread_count,
            "worker_sessions": cleared_worker_session_count,
            "canonical_sessions": cleared_canonical_session_count,
        }

    with state.lock:
        cleared_thread_count = sum(1 for thread_id in state.chat_threads.values() if thread_id.strip())
        cleared_worker_session_count = len(state.worker_sessions)
        state.chat_threads.clear()
        state.worker_sessions.clear()
    persist_chat_threads(state)
    persist_worker_sessions(state)
    return {
        "threads": cleared_thread_count,
        "worker_sessions": cleared_worker_session_count,
        "canonical_sessions": 0,
    }

def refresh_runtime_auth_fingerprint(state: State) -> Dict[str, object]:
    current_auth_fingerprint = compute_current_auth_fingerprint()
    if not current_auth_fingerprint.strip():
        return {
            "applied": False,
            "previous_auth_fingerprint": state.auth_fingerprint,
            "current_auth_fingerprint": "",
            "counts": {
                "threads": 0,
                "worker_sessions": 0,
                "canonical_sessions": 0,
            },
        }

    with state.auth_change_lock:
        previous_auth_fingerprint = state.auth_fingerprint.strip()
        if previous_auth_fingerprint == current_auth_fingerprint:
            return {
                "applied": False,
                "previous_auth_fingerprint": previous_auth_fingerprint,
                "current_auth_fingerprint": current_auth_fingerprint,
                "counts": {
                    "threads": 0,
                    "worker_sessions": 0,
                    "canonical_sessions": 0,
                },
            }

        reset_counts = clear_runtime_thread_state(state)

        state.auth_fingerprint = current_auth_fingerprint
        persist_saved_auth_fingerprint(state.auth_fingerprint_path, current_auth_fingerprint)
        return {
            "applied": True,
            "previous_auth_fingerprint": previous_auth_fingerprint,
            "current_auth_fingerprint": current_auth_fingerprint,
            "counts": reset_counts,
        }
