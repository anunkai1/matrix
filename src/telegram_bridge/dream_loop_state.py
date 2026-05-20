from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Iterable, List

from telegram_bridge.scope_state_store import load_json_object, persist_json_state_file
from telegram_bridge.state_models import ScopeKey, normalize_scope_key


DEFAULT_DREAM_LOOP_STATE_DIR = Path(
    os.getenv("DREAM_LOOP_STATE_DIR", "/var/lib/server3-dream-loop")
)
LATEST_TRUTH_STATE = "latest_truth_state.json"
LATEST_HEALTH_STATE = "latest_health_state.json"
LATEST_RUN_STATE = "latest_run_state.json"
LATEST_REPORT = "latest_report.md"
STALE_CONTEXT_STATE = "dream_loop_stale_context.json"


def build_dream_loop_state_dir() -> Path:
    return Path(os.getenv("DREAM_LOOP_STATE_DIR", str(DEFAULT_DREAM_LOOP_STATE_DIR)))


def build_dream_loop_artifact_path(filename: str) -> Path:
    return build_dream_loop_state_dir() / filename


def build_stale_context_state_path(bridge_state_dir: str | os.PathLike[str]) -> str:
    return str(Path(bridge_state_dir) / STALE_CONTEXT_STATE)


def _normalize_status_entry(scope_key: ScopeKey, raw: object) -> Dict[str, object]:
    parsed = raw if isinstance(raw, dict) else {}
    return {
        "scope_key": scope_key,
        "warning_fingerprint": str(parsed.get("warning_fingerprint") or "").strip(),
        "warning_generated_at": str(parsed.get("warning_generated_at") or "").strip(),
        "warning_outstanding": bool(parsed.get("warning_outstanding", False)),
        "handled_fingerprint": str(parsed.get("handled_fingerprint") or "").strip(),
        "handled_at": str(parsed.get("handled_at") or "").strip(),
        "last_reset_at": str(parsed.get("last_reset_at") or "").strip(),
    }


def load_stale_context_statuses(path: str) -> Dict[ScopeKey, Dict[str, object]]:
    if not path:
        return {}
    raw = load_json_object(path, state_label="dream-loop stale-context")
    parsed: Dict[ScopeKey, Dict[str, object]] = {}
    for key, value in raw.items():
        try:
            scope_key = normalize_scope_key(key)
        except Exception:
            continue
        parsed[scope_key] = _normalize_status_entry(scope_key, value)
    return parsed


def persist_stale_context_statuses(
    path: str,
    statuses: Dict[ScopeKey, Dict[str, object]],
) -> None:
    serialized = {
        normalize_scope_key(scope_key): _normalize_status_entry(normalize_scope_key(scope_key), value)
        for scope_key, value in statuses.items()
    }
    persist_json_state_file(path, serialized)


def apply_stale_context_updates(
    statuses: Dict[ScopeKey, Dict[str, object]],
    *,
    eligible_scope_keys: Iterable[ScopeKey],
    stale_fingerprint: str,
    generated_at: str,
    trigger_changed: bool,
) -> Dict[ScopeKey, Dict[str, object]]:
    updated = {
        normalize_scope_key(scope_key): _normalize_status_entry(normalize_scope_key(scope_key), value)
        for scope_key, value in statuses.items()
    }
    if not trigger_changed:
        return updated
    for raw_scope_key in eligible_scope_keys:
        scope_key = normalize_scope_key(raw_scope_key)
        entry = _normalize_status_entry(scope_key, updated.get(scope_key, {}))
        entry["warning_fingerprint"] = stale_fingerprint
        entry["warning_generated_at"] = generated_at
        if str(entry.get("handled_fingerprint") or "") != stale_fingerprint:
            entry["warning_outstanding"] = True
        updated[scope_key] = entry
    return updated


def snapshot_stale_context_statuses(
    statuses: Dict[ScopeKey, Dict[str, object]],
    scope_keys: Iterable[ScopeKey],
) -> List[Dict[str, object]]:
    snapshot: List[Dict[str, object]] = []
    for raw_scope_key in scope_keys:
        scope_key = normalize_scope_key(raw_scope_key)
        entry = statuses.get(scope_key)
        if entry is None:
            entry = _normalize_status_entry(scope_key, {})
        snapshot.append(_normalize_status_entry(scope_key, entry))
    return snapshot


def get_scope_stale_context_status(path: str, scope_key: ScopeKey) -> Dict[str, object]:
    normalized_scope_key = normalize_scope_key(scope_key)
    statuses = load_stale_context_statuses(path)
    return _normalize_status_entry(normalized_scope_key, statuses.get(normalized_scope_key, {}))


def mark_scope_stale_context_handled(
    path: str,
    scope_key: ScopeKey,
    *,
    handled_at: str,
) -> Dict[str, object]:
    normalized_scope_key = normalize_scope_key(scope_key)
    statuses = load_stale_context_statuses(path)
    entry = _normalize_status_entry(normalized_scope_key, statuses.get(normalized_scope_key, {}))
    warning_fingerprint = str(entry.get("warning_fingerprint") or "")
    if warning_fingerprint:
        entry["handled_fingerprint"] = warning_fingerprint
        entry["handled_at"] = handled_at
        entry["warning_outstanding"] = False
    entry["last_reset_at"] = handled_at
    statuses[normalized_scope_key] = entry
    persist_stale_context_statuses(path, statuses)
    return entry
