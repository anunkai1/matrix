import json
import os
import tempfile
from pathlib import Path
from typing import Dict, Optional

from telegram_bridge.conversation_scope import normalize_scope_storage_key
from telegram_bridge.state_models import ScopeKey, State, normalize_scope_key


def load_json_object(path: str, *, state_label: str) -> Dict[object, object]:
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


def persist_json_state_file(path_value: str, serialized: Dict[str, object]) -> None:
    if not path_value:
        return
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(serialized, indent=2, sort_keys=True) + "\n"

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


def _load_scope_string_map(
    path: str,
    *,
    state_label: str,
    normalize_value,
) -> Dict[ScopeKey, str]:
    raw = load_json_object(path, state_label=state_label)
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


def load_chat_gemma_models(path: str) -> Dict[ScopeKey, str]:
    return _load_scope_string_map(
        path,
        state_label="chat Ollama (S4) model",
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


def _persist_scope_string_map(path_value: str, values: Dict[ScopeKey, str]) -> None:
    serialized = {
        normalize_scope_key(scope_key): value
        for scope_key, value in values.items()
    }
    persist_json_state_file(path_value, serialized)


def persist_chat_threads(state: State) -> None:
    with state.lock:
        values = dict(state.chat_threads)
    _persist_scope_string_map(state.chat_thread_path, values)


def persist_chat_engines(state: State) -> None:
    with state.lock:
        values = dict(state.chat_engines)
    _persist_scope_string_map(state.chat_engine_path, values)


def persist_chat_codex_models(state: State) -> None:
    with state.lock:
        values = dict(state.chat_codex_models)
    _persist_scope_string_map(state.chat_codex_model_path, values)


def persist_chat_gemma_models(state: State) -> None:
    with state.lock:
        values = dict(state.chat_gemma_models)
    _persist_scope_string_map(state.chat_gemma_model_path, values)


def persist_chat_codex_efforts(state: State) -> None:
    with state.lock:
        values = dict(state.chat_codex_efforts)
    _persist_scope_string_map(state.chat_codex_effort_path, values)


def persist_chat_pi_models(state: State) -> None:
    with state.lock:
        values = dict(state.chat_pi_models)
    _persist_scope_string_map(state.chat_pi_model_path, values)


def persist_chat_pi_providers(state: State) -> None:
    with state.lock:
        values = dict(state.chat_pi_providers)
    _persist_scope_string_map(state.chat_pi_provider_path, values)


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


def get_chat_gemma_model(state: State, scope_key: ScopeKey) -> Optional[str]:
    return _get_string_override(state, scope_key, state.chat_gemma_models)


def set_chat_codex_model(state: State, scope_key: ScopeKey, model_name: str) -> None:
    _set_string_override(
        state,
        scope_key,
        state.chat_codex_models,
        model_name,
        persist_chat_codex_models,
    )


def set_chat_gemma_model(state: State, scope_key: ScopeKey, model_name: str) -> None:
    _set_string_override(
        state,
        scope_key,
        state.chat_gemma_models,
        model_name,
        persist_chat_gemma_models,
    )


def clear_chat_codex_model(state: State, scope_key: ScopeKey) -> bool:
    return _clear_string_override(
        state,
        scope_key,
        state.chat_codex_models,
        persist_chat_codex_models,
    )


def clear_chat_gemma_model(state: State, scope_key: ScopeKey) -> bool:
    return _clear_string_override(
        state,
        scope_key,
        state.chat_gemma_models,
        persist_chat_gemma_models,
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
