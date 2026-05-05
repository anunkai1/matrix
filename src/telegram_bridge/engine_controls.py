import copy
import subprocess
from typing import Dict, List, Optional, Tuple

from telegram_bridge.channel_adapter import ChannelAdapter
from telegram_bridge import engine_control_views
from telegram_bridge.engine_catalog import (
    ENGINE_NAME_ALIASES,
    PI_PROVIDER_ALIASES,
    PI_PROVIDER_CHOICES,
    configured_codex_model,
    configured_codex_reasoning_effort,
    configured_default_engine,
    configured_pi_model,
    configured_pi_provider,
    normalize_engine_name,
    normalize_pi_provider_name,
    pi_provider_uses_ollama_tunnel,
    resolve_codex_effort_candidate as _resolve_codex_effort_candidate,
    resolve_codex_model_candidate as _resolve_codex_model_candidate,
    selectable_engine_plugins,
    supported_codex_efforts_for_model as _supported_codex_efforts_for_model,
    load_codex_model_catalog as _load_codex_model_catalog,
    load_codex_model_choices as _load_codex_model_choices,
)
from telegram_bridge.engine_adapter import EngineAdapter
from telegram_bridge import engine_health
from telegram_bridge import engine_pi_catalog
from telegram_bridge.plugin_registry import build_default_plugin_registry
from telegram_bridge.state_store import State, StateRepository

GEMMA_HEALTH_TIMEOUT_SECONDS = 6
GEMMA_HEALTH_CURL_TIMEOUT_SECONDS = 5

_brief_health_error = engine_health._brief_health_error

def build_engine_runtime_config(state, config, scope_key: str, engine_name: str):
    runtime_config = copy.copy(config)
    normalized_engine = normalize_engine_name(engine_name)
    if normalized_engine == "codex":
        override_model = StateRepository(state).get_chat_codex_model(scope_key)
        override_effort = StateRepository(state).get_chat_codex_effort(scope_key)
        if not override_model and not override_effort:
            return config
        if override_model:
            runtime_config.codex_model = override_model
        if override_effort:
            runtime_config.codex_reasoning_effort = override_effort
        return runtime_config
    if normalized_engine != "pi":
        return config
    override_provider = StateRepository(state).get_chat_pi_provider(scope_key)
    override_model = StateRepository(state).get_chat_pi_model(scope_key)
    if not override_provider and not override_model:
        return config
    if override_provider:
        runtime_config.pi_provider = override_provider
    if override_model:
        runtime_config.pi_model = override_model
    return runtime_config

def _build_codex_model_source_text(state: State, scope_key: str) -> str:
    if StateRepository(state).get_chat_codex_model(scope_key):
        return "chat override"
    return "global default"

def _build_codex_effort_source_text(state: State, scope_key: str) -> str:
    if StateRepository(state).get_chat_codex_effort(scope_key):
        return "chat override"
    return "global default"

def _build_pi_provider_source_text(state: State, scope_key: str) -> str:
    if StateRepository(state).get_chat_pi_provider(scope_key):
        return "chat override"
    return "global default"

def _build_pi_model_source_text(state: State, scope_key: str) -> str:
    if StateRepository(state).get_chat_pi_model(scope_key):
        return "chat override"
    return "global default"

def _pi_provider_choice_lines(current_provider: str) -> List[str]:
    return engine_pi_catalog.pi_provider_choice_lines(current_provider)

def _pi_provider_description(provider_name: str) -> str:
    return engine_pi_catalog.pi_provider_description(provider_name)

def _pi_available_provider_names(config) -> List[str]:
    return engine_pi_catalog.pi_available_provider_names(config)

def build_pi_providers_text(state: State, config, scope_key: str) -> str:
    try:
        return engine_control_views.build_pi_providers_text(
            state,
            config,
            scope_key,
            build_engine_runtime_config=build_engine_runtime_config,
            configured_pi_provider=configured_pi_provider,
            build_pi_provider_source_text=_build_pi_provider_source_text,
            pi_available_provider_names=_pi_available_provider_names,
            pi_provider_description=_pi_provider_description,
            pi_provider_choice_lines=_pi_provider_choice_lines,
        )
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        display_config = build_engine_runtime_config(state, config, scope_key, "pi")
        provider = configured_pi_provider(display_config)
        lines = [
            f"Pi provider: {provider}",
            f"Pi provider source: {_build_pi_provider_source_text(state, scope_key)}",
            "Available Pi providers:",
        ]
        lines.extend(_pi_provider_choice_lines(provider))
        lines.append("Use /pi provider <name> to switch this chat.")
        return "\n".join(lines)

def _run_pi_command(config, command: str) -> subprocess.CompletedProcess[str]:
    return engine_pi_catalog.run_pi_command(config, command)

def _parse_pi_model_rows(payload: str) -> List[Tuple[str, str]]:
    return engine_pi_catalog.parse_pi_model_rows(payload)

def _pi_model_rows(config) -> List[Tuple[str, str]]:
    return engine_pi_catalog.pi_model_rows(config)

def _pi_provider_model_names(config) -> List[str]:
    return engine_pi_catalog.pi_provider_model_names(config)

def _resolve_pi_model_candidate(available_models: List[str], requested_model: str) -> Optional[str]:
    return engine_pi_catalog.resolve_pi_model_candidate(available_models, requested_model)

def build_pi_models_text(state: State, config, scope_key: str) -> str:
    return engine_control_views.build_pi_models_text(
        state,
        config,
        scope_key,
        build_engine_runtime_config=build_engine_runtime_config,
        configured_pi_provider=configured_pi_provider,
        configured_pi_model=configured_pi_model,
        build_pi_provider_source_text=_build_pi_provider_source_text,
        build_pi_model_source_text=_build_pi_model_source_text,
        pi_provider_model_names=_pi_provider_model_names,
    )

def build_pi_status_text(state: State, config, scope_key: str) -> str:
    return engine_control_views.build_pi_status_text(
        state,
        config,
        scope_key,
        build_engine_runtime_config=build_engine_runtime_config,
        configured_pi_provider=configured_pi_provider,
        configured_pi_model=configured_pi_model,
        build_pi_provider_source_text=_build_pi_provider_source_text,
        build_pi_model_source_text=_build_pi_model_source_text,
    )

def check_gemma_health(config) -> Dict[str, object]:
    return engine_health.check_gemma_health(
        config,
        health_timeout_seconds=GEMMA_HEALTH_TIMEOUT_SECONDS,
        curl_timeout_seconds=GEMMA_HEALTH_CURL_TIMEOUT_SECONDS,
    )

def check_venice_health(config) -> Dict[str, object]:
    return engine_health.check_venice_health(
        config,
        health_timeout_seconds=GEMMA_HEALTH_TIMEOUT_SECONDS,
    )

def check_pi_health(config) -> Dict[str, object]:
    return engine_health.check_pi_health(
        config,
        provider=configured_pi_provider(config),
        run_pi_command_fn=_run_pi_command,
        parse_pi_model_rows_fn=_parse_pi_model_rows,
    )

def check_chatgpt_web_health(config) -> Dict[str, object]:
    return engine_health.check_chatgpt_web_health(config)

def build_engine_status_text(state: State, config, scope_key: str) -> str:
    return engine_control_views.build_engine_status_text(
        state,
        config,
        scope_key,
        state_repo=StateRepository(state),
        normalize_engine_name=normalize_engine_name,
        configured_default_engine=configured_default_engine,
        selectable_engine_plugins=selectable_engine_plugins,
        build_engine_runtime_config=build_engine_runtime_config,
        configured_codex_reasoning_effort=configured_codex_reasoning_effort,
        build_pi_provider_source_text=_build_pi_provider_source_text,
        build_pi_model_source_text=_build_pi_model_source_text,
        pi_provider_uses_ollama_tunnel=pi_provider_uses_ollama_tunnel,
        check_gemma_health=check_gemma_health,
        check_venice_health=check_venice_health,
        check_pi_health=check_pi_health,
        check_chatgpt_web_health=check_chatgpt_web_health,
    )

def _engine_callback_data(engine_name: str, action: str) -> str:
    return engine_control_views.engine_callback_data(engine_name, action)

def _model_active_engine_name(state: State, config, scope_key: str) -> str:
    selected = StateRepository(state).get_chat_engine(scope_key)
    return normalize_engine_name(selected or configured_default_engine(config))

def _compact_inline_keyboard(
    buttons: List[Tuple[str, str]],
    *,
    columns: int = 2,
) -> Dict[str, object]:
    return engine_control_views.compact_inline_keyboard(buttons, columns=columns)

def _model_callback_data(engine_name: str, action: str, value: str = "") -> str:
    return engine_control_views.model_callback_data(engine_name, action, value)

def _provider_callback_data(action: str, value: str = "") -> str:
    return engine_control_views.provider_callback_data(action, value)

def _effort_callback_data(action: str, value: str = "") -> str:
    return engine_control_views.effort_callback_data(action, value)

def _pi_model_page_for_selection(model_names: List[str], current_model: str, page_size: int) -> int:
    return engine_control_views.pi_model_page_for_selection(model_names, current_model, page_size)

def _clamp_page_index(page_index: Optional[int], total_items: int, page_size: int) -> int:
    return engine_control_views.clamp_page_index(page_index, total_items, page_size)

def _build_engine_picker_markup(state: State, config, scope_key: str) -> Optional[Dict[str, object]]:
    return engine_control_views.build_engine_picker_markup(
        state,
        config,
        scope_key,
        model_active_engine_name=_model_active_engine_name,
        selectable_engine_plugins=selectable_engine_plugins,
    )

def _set_engine_for_scope(state: State, config, scope_key: str, engine_name: str) -> str:
    normalized_engine = normalize_engine_name(engine_name)
    if normalized_engine == "venice" and not str(getattr(config, "venice_api_key", "") or "").strip():
        return "Venice engine is configured in the bridge, but VENICE_API_KEY is missing."
    allowed = selectable_engine_plugins(config)
    if normalized_engine not in allowed:
        return f"Unknown or unavailable engine: {normalized_engine}\nSelectable engines: {', '.join(allowed)}"
    StateRepository(state).set_chat_engine(scope_key, normalized_engine)
    return f"This chat now uses engine: {normalized_engine}"

def _reset_engine_for_scope(state: State, config, scope_key: str) -> str:
    removed = StateRepository(state).clear_chat_engine(scope_key)
    suffix = "removed" if removed else "already using default"
    return f"Engine override {suffix}. This chat now uses {configured_default_engine(config)}."

def handle_engine_command(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    raw_text: str,
) -> bool:
    pieces = raw_text.strip().split(maxsplit=1)
    tail = pieces[1].strip().lower() if len(pieces) > 1 else "status"
    tail = normalize_engine_name(tail)
    reply_markup: Optional[Dict[str, object]] = None
    if tail in {"", "status"}:
        text = build_engine_status_text(state, config, scope_key)
        reply_markup = _build_engine_picker_markup(state, config, scope_key)
    elif tail == "reset":
        text = _reset_engine_for_scope(state, config, scope_key)
        reply_markup = _build_engine_picker_markup(state, config, scope_key)
    else:
        text = _set_engine_for_scope(state, config, scope_key, tail)
        reply_markup = _build_engine_picker_markup(state, config, scope_key)
    client.send_message(
        chat_id,
        text,
        reply_to_message_id=message_id,
        message_thread_id=message_thread_id,
        reply_markup=reply_markup,
    )
    return True

def handle_pi_command(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    raw_text: str,
) -> bool:
    pieces = raw_text.strip().split(maxsplit=1)
    raw_tail = pieces[1].strip() if len(pieces) > 1 else "status"
    tail = raw_tail.lower()
    state_repo = StateRepository(state)
    display_config = build_engine_runtime_config(state, config, scope_key, "pi")

    if tail in {"", "status"}:
        client.send_message(
            chat_id,
            build_pi_status_text(state, config, scope_key),
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return True
    if tail == "providers":
        client.send_message(
            chat_id,
            build_pi_providers_text(state, config, scope_key),
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
            reply_markup=_build_provider_picker_markup(state, config, scope_key),
        )
        return True
    if tail == "models":
        try:
            text = build_pi_models_text(state, config, scope_key)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            text = "Failed to list Pi models.\n" f"Error: {_brief_health_error(exc)}"
        else:
            text += (
                "\n\nDeprecated alias: `/pi models` still works for compatibility, "
                "but `/model list` is the canonical command."
            )
        client.send_message(
            chat_id,
            text,
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return True
    if tail == "reset":
        removed_provider = state_repo.clear_chat_pi_provider(scope_key)
        removed_model = state_repo.clear_chat_pi_model(scope_key)
        effective_config = build_engine_runtime_config(state, config, scope_key, "pi")
        source_text = "chat overrides cleared" if (removed_provider or removed_model) else "no chat overrides were set"
        client.send_message(
            chat_id,
            (
                f"{source_text}. "
                f"Pi provider is now {configured_pi_provider(effective_config)} "
                f"({_build_pi_provider_source_text(state, scope_key)}). "
                f"Pi model is now {configured_pi_model(effective_config)} "
                f"({_build_pi_model_source_text(state, scope_key)})."
            ),
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return True
    if tail.startswith("provider"):
        provider_name = raw_tail[8:].strip() if len(raw_tail) >= 8 else ""
        if not provider_name:
            client.send_message(
                chat_id,
                "Usage: /pi provider <name>\nUse /pi providers to list available Pi providers.",
                reply_to_message_id=message_id,
                message_thread_id=message_thread_id,
            )
            return True
        try:
            text = _set_pi_provider_for_scope(state, config, scope_key, provider_name)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            client.send_message(
                chat_id,
                "Failed to validate Pi provider.\n"
                f"Error: {_brief_health_error(exc)}",
                reply_to_message_id=message_id,
                message_thread_id=message_thread_id,
            )
            return True
        client.send_message(
            chat_id,
            text,
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return True
    if tail.startswith("model"):
        model_name = raw_tail[5:].strip() if len(raw_tail) >= 5 else ""
        if not model_name:
            client.send_message(
                chat_id,
                "Usage: /model <name>\nUse /model list to list available models for the current Pi provider.",
                reply_to_message_id=message_id,
                message_thread_id=message_thread_id,
            )
            return True
        try:
            available_models = _pi_provider_model_names(display_config)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            client.send_message(
                chat_id,
                "Failed to validate Pi models.\n"
                f"Error: {_brief_health_error(exc)}",
                reply_to_message_id=message_id,
                message_thread_id=message_thread_id,
            )
            return True
        resolved_model = _resolve_pi_model_candidate(available_models, model_name)
        if resolved_model is None:
            provider = configured_pi_provider(display_config)
            client.send_message(
                chat_id,
                (
                    f"Model not available for Pi provider `{provider}`: `{model_name}`\n"
                    "Use /model list to see the allowed model names."
                ),
                reply_to_message_id=message_id,
                message_thread_id=message_thread_id,
            )
            return True
        state_repo.set_chat_pi_model(scope_key, resolved_model)
        updated_config = build_engine_runtime_config(state, config, scope_key, "pi")
        client.send_message(
            chat_id,
            (
                f"Pi model for this chat is now {configured_pi_model(updated_config)} "
                f"({_build_pi_model_source_text(state, scope_key)}).\n"
                "Deprecated alias: `/pi model` still works for compatibility, "
                "but `/model <name>` is the canonical command."
            ),
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return True
    client.send_message(
        chat_id,
        "Unknown /pi command. Use /pi, /pi providers, /pi provider <name>, or /pi reset. Use /model list and /model <name> for Pi model selection.",
        reply_to_message_id=message_id,
        message_thread_id=message_thread_id,
    )
    return True

def _build_model_picker_markup(
    state: State,
    config,
    scope_key: str,
    *,
    page_index: Optional[int] = None,
) -> Optional[Dict[str, object]]:
    try:
        return engine_control_views.build_model_picker_markup(
            state,
            config,
            scope_key,
            page_index=page_index,
            model_active_engine_name=_model_active_engine_name,
            build_engine_runtime_config=build_engine_runtime_config,
            configured_codex_model=configured_codex_model,
            load_codex_model_choices=_load_codex_model_choices,
            pi_provider_model_names=_pi_provider_model_names,
            configured_pi_model=configured_pi_model,
        )
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        return None

def _build_provider_picker_markup(state: State, config, scope_key: str) -> Optional[Dict[str, object]]:
    try:
        return engine_control_views.build_provider_picker_markup(
            state,
            config,
            scope_key,
            build_engine_runtime_config=build_engine_runtime_config,
            configured_pi_provider=configured_pi_provider,
            pi_available_provider_names=_pi_available_provider_names,
        )
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        display_config = build_engine_runtime_config(state, config, scope_key, "pi")
        current_provider = configured_pi_provider(display_config)
        provider_names = [provider for provider, _description in PI_PROVIDER_CHOICES]
        buttons: List[Tuple[str, str]] = []
        for provider_name in provider_names:
            label = f"{provider_name} *" if provider_name == current_provider else provider_name
            buttons.append((label, _provider_callback_data("set", provider_name)))
        rows = _compact_inline_keyboard(buttons, columns=2).get("inline_keyboard", [])
        rows.append(
            [
                {"text": "Back to Engine", "callback_data": _engine_callback_data("pi", "menu")},
            ]
        )
        return {"inline_keyboard": rows} if rows else None

def _build_effort_picker_markup(state: State, config, scope_key: str) -> Optional[Dict[str, object]]:
    return engine_control_views.build_effort_picker_markup(
        state,
        config,
        scope_key,
        model_active_engine_name=_model_active_engine_name,
        build_engine_runtime_config=build_engine_runtime_config,
        configured_codex_model=configured_codex_model,
        configured_codex_reasoning_effort=configured_codex_reasoning_effort,
        supported_codex_efforts_for_model=_supported_codex_efforts_for_model,
    )

def build_model_status_text(state: State, config, scope_key: str) -> str:
    return engine_control_views.build_model_status_text(
        state,
        config,
        scope_key,
        model_active_engine_name=_model_active_engine_name,
        build_engine_runtime_config=build_engine_runtime_config,
        configured_codex_model=configured_codex_model,
        configured_codex_reasoning_effort=configured_codex_reasoning_effort,
        configured_pi_provider=configured_pi_provider,
        configured_pi_model=configured_pi_model,
        build_codex_model_source_text=_build_codex_model_source_text,
        build_codex_effort_source_text=_build_codex_effort_source_text,
        build_pi_model_source_text=_build_pi_model_source_text,
    )

def build_effort_status_text(state: State, config, scope_key: str) -> str:
    return engine_control_views.build_effort_status_text(
        state,
        config,
        scope_key,
        model_active_engine_name=_model_active_engine_name,
        build_engine_runtime_config=build_engine_runtime_config,
        configured_codex_model=configured_codex_model,
        configured_codex_reasoning_effort=configured_codex_reasoning_effort,
        build_codex_effort_source_text=_build_codex_effort_source_text,
    )

def build_effort_list_text(state: State, config, scope_key: str) -> str:
    return engine_control_views.build_effort_list_text(
        state,
        config,
        scope_key,
        model_active_engine_name=_model_active_engine_name,
        build_engine_runtime_config=build_engine_runtime_config,
        configured_codex_model=configured_codex_model,
        configured_codex_reasoning_effort=configured_codex_reasoning_effort,
        supported_codex_efforts_for_model=_supported_codex_efforts_for_model,
    )

def _set_codex_model_for_scope(state: State, config, scope_key: str, model_name: str) -> str:
    state_repo = StateRepository(state)
    resolved_model = _resolve_codex_model_candidate(model_name)
    state_repo.set_chat_codex_model(scope_key, resolved_model)
    updated_config = build_engine_runtime_config(state, config, scope_key, "codex")
    current_effort = configured_codex_reasoning_effort(updated_config)
    if current_effort and _resolve_codex_effort_candidate(resolved_model, current_effort) is None:
        supported_efforts = _supported_codex_efforts_for_model(resolved_model)
        if supported_efforts:
            state_repo.set_chat_codex_effort(scope_key, supported_efforts[0])
            updated_config = build_engine_runtime_config(state, config, scope_key, "codex")
    return (
        f"Codex model for this chat is now {configured_codex_model(updated_config) or '(default)'} "
        f"({_build_codex_model_source_text(state, scope_key)})."
    )

def _reset_model_for_scope(state: State, config, scope_key: str, active_engine: str) -> str:
    state_repo = StateRepository(state)
    if active_engine == "codex":
        removed = state_repo.clear_chat_codex_model(scope_key)
        updated_config = build_engine_runtime_config(state, config, scope_key, "codex")
        source = "chat override cleared" if removed else "no chat override was set"
        return (
            f"{source}. Codex model is now {configured_codex_model(updated_config) or '(default)'} "
            f"({_build_codex_model_source_text(state, scope_key)})."
        )
    if active_engine == "pi":
        removed = state_repo.clear_chat_pi_model(scope_key)
        updated_config = build_engine_runtime_config(state, config, scope_key, "pi")
        source = "chat override cleared" if removed else "no chat override was set"
        return (
            f"{source}. Pi model is now {configured_pi_model(updated_config)} "
            f"({_build_pi_model_source_text(state, scope_key)})."
        )
    return build_model_status_text(state, config, scope_key)

def _set_pi_provider_for_scope(state: State, config, scope_key: str, provider_name: str) -> str:
    normalized_provider = normalize_pi_provider_name(provider_name)
    temp_config = copy.copy(config)
    temp_config.pi_provider = normalized_provider
    available_models = _pi_provider_model_names(temp_config)
    if not available_models:
        return (
            f"Provider `{normalized_provider}` did not report any models.\n"
            "Pi provider was not changed."
        )
    state_repo = StateRepository(state)
    current_model = state_repo.get_chat_pi_model(scope_key)
    resolved_model = _resolve_pi_model_candidate(available_models, current_model or "")
    if resolved_model is None:
        resolved_model = available_models[0]
    state_repo.set_chat_pi_provider(scope_key, normalized_provider)
    state_repo.set_chat_pi_model(scope_key, resolved_model)
    return (
        f"Pi provider for this chat is now {normalized_provider}. "
        f"Pi model is now {resolved_model}."
    )

def _set_pi_model_for_scope(state: State, config, scope_key: str, model_name: str) -> str:
    display_config = build_engine_runtime_config(state, config, scope_key, "pi")
    available_models = _pi_provider_model_names(display_config)
    resolved_model = _resolve_pi_model_candidate(available_models, model_name)
    if resolved_model is None:
        provider = configured_pi_provider(display_config)
        return (
            f"Model not available for Pi provider `{provider}`: `{model_name}`\n"
            "Use /model list to see the allowed model names."
        )
    StateRepository(state).set_chat_pi_model(scope_key, resolved_model)
    updated_config = build_engine_runtime_config(state, config, scope_key, "pi")
    return (
        f"Pi model for this chat is now {configured_pi_model(updated_config)} "
        f"({_build_pi_model_source_text(state, scope_key)})."
    )

def _set_codex_effort_for_scope(state: State, config, scope_key: str, effort_name: str) -> str:
    display_config = build_engine_runtime_config(state, config, scope_key, "codex")
    current_model = configured_codex_model(display_config)
    resolved_effort = _resolve_codex_effort_candidate(current_model, effort_name)
    if resolved_effort is None:
        return (
            f"Reasoning effort not supported for Codex model `{current_model or '(default)'}`: "
            f"`{effort_name}`\nUse /effort list to see the allowed effort names."
        )
    StateRepository(state).set_chat_codex_effort(scope_key, resolved_effort)
    updated_config = build_engine_runtime_config(state, config, scope_key, "codex")
    return (
        f"Codex reasoning effort for this chat is now "
        f"{configured_codex_reasoning_effort(updated_config) or '(default)'} "
        f"({_build_codex_effort_source_text(state, scope_key)})."
    )

def _reset_codex_effort_for_scope(state: State, config, scope_key: str) -> str:
    removed = StateRepository(state).clear_chat_codex_effort(scope_key)
    updated_config = build_engine_runtime_config(state, config, scope_key, "codex")
    source = "chat override cleared" if removed else "no chat override was set"
    return (
        f"{source}. Codex reasoning effort is now "
        f"{configured_codex_reasoning_effort(updated_config) or '(default)'} "
        f"({_build_codex_effort_source_text(state, scope_key)})."
    )

def _parse_page_index(raw_value: str) -> Optional[int]:
    return engine_control_views.parse_page_index(raw_value)

def build_model_list_text(state: State, config, scope_key: str) -> str:
    return engine_control_views.build_model_list_text(
        state,
        config,
        scope_key,
        model_active_engine_name=_model_active_engine_name,
        build_engine_runtime_config=build_engine_runtime_config,
        configured_codex_model=configured_codex_model,
        load_codex_model_choices=_load_codex_model_choices,
        build_pi_models_text=build_pi_models_text,
    )

def handle_model_command(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    raw_text: str,
) -> bool:
    pieces = raw_text.strip().split(maxsplit=1)
    raw_tail = pieces[1].strip() if len(pieces) > 1 else "status"
    tail = raw_tail.lower()
    active_engine = _model_active_engine_name(state, config, scope_key)
    reply_markup: Optional[Dict[str, object]] = None

    if tail in {"", "status"}:
        text = build_model_status_text(state, config, scope_key)
        reply_markup = _build_model_picker_markup(state, config, scope_key)
    elif tail == "list":
        try:
            text = build_model_list_text(state, config, scope_key)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            text = "Failed to list models.\n" f"Error: {_brief_health_error(exc)}"
    elif tail == "reset":
        text = _reset_model_for_scope(state, config, scope_key, active_engine)
        reply_markup = _build_model_picker_markup(state, config, scope_key)
    else:
        if active_engine == "codex":
            text = _set_codex_model_for_scope(state, config, scope_key, raw_tail)
            reply_markup = _build_model_picker_markup(state, config, scope_key)
        elif active_engine == "pi":
            try:
                text = _set_pi_model_for_scope(state, config, scope_key, raw_tail)
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                text = "Failed to validate Pi models.\n" f"Error: {_brief_health_error(exc)}"
            reply_markup = _build_model_picker_markup(state, config, scope_key)
        else:
            text = build_model_status_text(state, config, scope_key)

    client.send_message(
        chat_id,
        text,
        reply_to_message_id=message_id,
        message_thread_id=message_thread_id,
        reply_markup=reply_markup,
    )
    return True

def handle_effort_command(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    raw_text: str,
) -> bool:
    pieces = raw_text.strip().split(maxsplit=1)
    raw_tail = pieces[1].strip() if len(pieces) > 1 else "status"
    tail = raw_tail.lower()
    active_engine = _model_active_engine_name(state, config, scope_key)
    reply_markup: Optional[Dict[str, object]] = None

    if tail in {"", "status"}:
        text = build_effort_status_text(state, config, scope_key)
        reply_markup = _build_effort_picker_markup(state, config, scope_key)
    elif tail == "list":
        text = build_effort_list_text(state, config, scope_key)
    elif tail == "reset":
        text = _reset_codex_effort_for_scope(state, config, scope_key)
        reply_markup = _build_effort_picker_markup(state, config, scope_key)
    elif active_engine != "codex":
        text = build_effort_status_text(state, config, scope_key)
    else:
        text = _set_codex_effort_for_scope(state, config, scope_key, raw_tail)
        reply_markup = _build_effort_picker_markup(state, config, scope_key)

    client.send_message(
        chat_id,
        text,
        reply_to_message_id=message_id,
        message_thread_id=message_thread_id,
        reply_markup=reply_markup,
    )
    return True

def resolve_engine_for_scope(
    state: State,
    config,
    scope_key: str,
    default_engine: Optional[EngineAdapter],
) -> EngineAdapter:
    selected = StateRepository(state).get_chat_engine(scope_key)
    if not selected:
        if default_engine is not None:
            return default_engine
        return build_default_plugin_registry().build_engine(configured_default_engine(config))
    engine_name = normalize_engine_name(selected)
    if default_engine is not None and getattr(default_engine, "engine_name", "") == engine_name:
        return default_engine
    registry = build_default_plugin_registry()
    return registry.build_engine(engine_name)
