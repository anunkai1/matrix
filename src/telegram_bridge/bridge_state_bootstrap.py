import logging
import os
from typing import Dict

from telegram_bridge.runtime_config import Config
from telegram_bridge.state_store import (
    build_canonical_sessions_from_legacy,
    CanonicalSession,
    WorkerSession,
    ensure_state_dir,
    load_canonical_sessions,
    load_canonical_sessions_sqlite,
    load_chat_codex_efforts,
    load_chat_codex_models,
    load_chat_engines,
    load_chat_gemma_models,
    load_chat_pi_models,
    load_chat_pi_providers,
    load_chat_threads,
    load_in_flight_requests,
    load_or_import_canonical_sessions_sqlite,
    load_worker_sessions,
    quarantine_corrupt_state_file,
)
from telegram_bridge.structured_logging import emit_event


def build_policy_fingerprint_state_path(state_dir: str) -> str:
    return os.path.join(state_dir, "policy_fingerprint.txt")


def build_update_offset_state_path(state_dir: str, channel_plugin: str) -> str:
    normalized = (channel_plugin or "telegram").strip().lower() or "telegram"
    return os.path.join(state_dir, f"{normalized}_update_offset.txt")


def load_saved_policy_fingerprint(path: str) -> str:
    if not path:
        return ""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except FileNotFoundError:
        return ""
    except OSError:
        logging.exception("Failed to read policy fingerprint state from %s", path)
        return ""


def persist_saved_policy_fingerprint(path: str, fingerprint: str) -> None:
    if not path:
        return
    directory = os.path.dirname(path)
    if directory:
        ensure_state_dir(directory)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        handle.write(fingerprint.strip())
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)


def load_saved_update_offset(path: str) -> int:
    if not path:
        return 0
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = handle.read().strip()
    except FileNotFoundError:
        return 0
    except OSError:
        logging.exception("Failed to read saved update offset from %s", path)
        return 0
    if not raw:
        return 0
    try:
        parsed = int(raw)
    except ValueError:
        logging.warning("Ignoring invalid saved update offset in %s: %r", path, raw)
        return 0
    if parsed < 0:
        logging.warning("Ignoring negative saved update offset in %s: %s", path, parsed)
        return 0
    return parsed


def persist_saved_update_offset(path: str, offset: int) -> None:
    if not path:
        return
    directory = os.path.dirname(path)
    if directory:
        ensure_state_dir(directory)
    sanitized_offset = max(int(offset), 0)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        handle.write(f"{sanitized_offset}\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)


def load_state_mapping_or_empty(
    path: str,
    loader,
    *,
    description: str,
) -> Dict[object, object]:
    try:
        return loader(path)
    except Exception:
        logging.exception(
            "Failed to load %s from %s; starting with empty state.",
            description,
            path,
        )
        moved = quarantine_corrupt_state_file(path)
        if moved:
            logging.error("Quarantined corrupt %s to %s", description, moved)
        emit_event(
            "bridge.state_load_failed",
            level=logging.WARNING,
            fields={"state_file": path},
        )
        return {}


def build_bridge_state_paths(state_dir: str) -> Dict[str, str]:
    return {
        "chat_threads": os.path.join(state_dir, "chat_threads.json"),
        "chat_engines": os.path.join(state_dir, "chat_engines.json"),
        "chat_gemma_models": os.path.join(state_dir, "chat_gemma_models.json"),
        "chat_codex_models": os.path.join(state_dir, "chat_codex_models.json"),
        "chat_codex_efforts": os.path.join(state_dir, "chat_codex_efforts.json"),
        "chat_pi_providers": os.path.join(state_dir, "chat_pi_providers.json"),
        "chat_pi_models": os.path.join(state_dir, "chat_pi_models.json"),
        "worker_sessions": os.path.join(state_dir, "worker_sessions.json"),
        "in_flight_requests": os.path.join(state_dir, "in_flight_requests.json"),
        "chat_sessions": os.path.join(state_dir, "chat_sessions.json"),
    }


def load_bridge_state_mappings(state_paths: Dict[str, str]) -> Dict[str, Dict[object, object]]:
    state_specs = (
        ("threads", "chat_threads", load_chat_threads, "chat thread mappings"),
        ("engines", "chat_engines", load_chat_engines, "chat engine mappings"),
        ("gemma_models", "chat_gemma_models", load_chat_gemma_models, "chat Ollama (S4) model mappings"),
        ("codex_models", "chat_codex_models", load_chat_codex_models, "chat Codex model mappings"),
        ("codex_efforts", "chat_codex_efforts", load_chat_codex_efforts, "chat Codex effort mappings"),
        ("pi_models", "chat_pi_models", load_chat_pi_models, "chat Pi model mappings"),
        ("pi_providers", "chat_pi_providers", load_chat_pi_providers, "chat Pi provider mappings"),
        ("worker_sessions", "worker_sessions", load_worker_sessions, "worker session state"),
        ("in_flight", "in_flight_requests", load_in_flight_requests, "in-flight request state"),
    )
    loaded: Dict[str, Dict[object, object]] = {}
    for key, path_key, loader, description in state_specs:
        loaded[key] = load_state_mapping_or_empty(
            state_paths[path_key],
            loader,
            description=description,
        )
    return loaded


def _load_canonical_json_with_fallback(
    chat_sessions_path: str,
    *,
    failure_source: str,
    empty_source: str,
) -> tuple[Dict[int, CanonicalSession], str]:
    try:
        loaded_canonical_sessions = load_canonical_sessions(chat_sessions_path)
    except Exception:
        logging.exception(
            "Failed to load canonical session state from %s; starting with compatibility snapshot.",
            chat_sessions_path,
        )
        moved = quarantine_corrupt_state_file(chat_sessions_path)
        if moved:
            logging.error("Quarantined corrupt canonical session state file to %s", moved)
        emit_event(
            "bridge.state_load_failed",
            level=logging.WARNING,
            fields={"state_file": chat_sessions_path},
        )
        return {}, failure_source
    if loaded_canonical_sessions:
        return loaded_canonical_sessions, "canonical_json"
    return {}, empty_source


def load_canonical_session_bootstrap(
    config: Config,
    state_paths: Dict[str, str],
    loaded_threads: Dict[int, str],
    loaded_worker_sessions: Dict[int, WorkerSession],
    loaded_in_flight: Dict[int, Dict[str, object]],
) -> tuple[Dict[int, CanonicalSession], str]:
    if not config.canonical_sessions_enabled:
        return {}, "disabled"

    chat_sessions_path = state_paths["chat_sessions"]
    if not config.canonical_sqlite_enabled:
        return _load_canonical_json_with_fallback(
            chat_sessions_path,
            failure_source="canonical_json_reset_after_load_failure",
            empty_source="legacy_json_snapshot",
        )

    canonical_bootstrap_source = "sqlite"
    try:
        loaded_canonical_sessions = load_canonical_sessions_sqlite(
            config.canonical_sqlite_path
        )
    except Exception:
        logging.exception(
            "Failed to load canonical session SQLite state from %s; starting with compatibility snapshot.",
            config.canonical_sqlite_path,
        )
        moved = quarantine_corrupt_state_file(config.canonical_sqlite_path)
        if moved:
            logging.error(
                "Quarantined corrupt canonical session SQLite state file to %s",
                moved,
            )
        emit_event(
            "bridge.state_load_failed",
            level=logging.WARNING,
            fields={"state_file": config.canonical_sqlite_path},
        )
        loaded_canonical_sessions = {}
        canonical_bootstrap_source = "sqlite_reset_after_load_failure"

    if loaded_canonical_sessions:
        return loaded_canonical_sessions, canonical_bootstrap_source

    import_sessions, import_source = _load_canonical_json_with_fallback(
        chat_sessions_path,
        failure_source="none",
        empty_source="none",
    )
    if not import_sessions:
        import_sessions = build_canonical_sessions_from_legacy(
            loaded_threads,
            loaded_worker_sessions,
            loaded_in_flight,
        )
        if import_sessions:
            import_source = "legacy_json"

    try:
        loaded_canonical_sessions, imported = load_or_import_canonical_sessions_sqlite(
            config.canonical_sqlite_path,
            import_sessions=import_sessions,
        )
    except Exception:
        logging.exception(
            "Failed to import/initialize canonical session SQLite state at %s; starting empty.",
            config.canonical_sqlite_path,
        )
        moved = quarantine_corrupt_state_file(config.canonical_sqlite_path)
        if moved:
            logging.error(
                "Quarantined canonical session SQLite state file after import failure to %s",
                moved,
            )
        emit_event(
            "bridge.state_load_failed",
            level=logging.WARNING,
            fields={"state_file": config.canonical_sqlite_path},
        )
        return {}, "sqlite_reset_after_import_failure"

    if imported:
        return loaded_canonical_sessions, f"sqlite_imported_from_{import_source}"
    if loaded_canonical_sessions:
        return loaded_canonical_sessions, "sqlite"
    if canonical_bootstrap_source.startswith("sqlite_reset"):
        return {}, canonical_bootstrap_source
    return {}, "sqlite_empty"
