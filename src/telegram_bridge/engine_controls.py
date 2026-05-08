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
from telegram_bridge.engine_control_status import (
    brief_health_error as _brief_health_error,
    build_codex_effort_source_text as _build_codex_effort_source_text,
    build_codex_model_source_text as _build_codex_model_source_text,
    build_engine_runtime_config,
    build_engine_status_text,
    build_pi_model_source_text as _build_pi_model_source_text,
    build_pi_models_text,
    build_pi_provider_source_text as _build_pi_provider_source_text,
    build_pi_providers_text,
    build_pi_status_text,
    check_chatgpt_web_health,
    check_gemma_health,
    check_pi_health,
    check_venice_health,
    GEMMA_HEALTH_CURL_TIMEOUT_SECONDS,
    GEMMA_HEALTH_TIMEOUT_SECONDS,
    model_active_engine_name as _model_active_engine_name,
    pi_available_provider_names as _pi_available_provider_names,
    pi_provider_model_names as _pi_provider_model_names,
    resolve_pi_model_candidate as _resolve_pi_model_candidate,
)
from telegram_bridge.engine_adapter import EngineAdapter
from telegram_bridge.handler_models import CallbackActionResult
from telegram_bridge.plugin_registry import build_default_plugin_registry
from telegram_bridge.state_store import (
    State,
    clear_chat_codex_effort,
    clear_chat_codex_model,
    clear_chat_engine,
    clear_chat_pi_model,
    clear_chat_pi_provider,
    get_chat_codex_effort,
    get_chat_codex_model,
    get_chat_engine,
    get_chat_pi_model,
    get_chat_pi_provider,
    set_chat_codex_effort,
    set_chat_codex_model,
    set_chat_engine,
    set_chat_pi_model,
    set_chat_pi_provider,
)
def _engine_callback_data(engine_name: str, action: str) -> str:
    return engine_control_views.engine_callback_data(engine_name, action)

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
    set_chat_engine(state, scope_key, normalized_engine)
    return f"This chat now uses engine: {normalized_engine}"

def _reset_engine_for_scope(state: State, config, scope_key: str) -> str:
    removed = clear_chat_engine(state, scope_key)
    suffix = "removed" if removed else "already using default"
    return f"Engine override {suffix}. This chat now uses {configured_default_engine(config)}."

def _send_control_result(
    client: ChannelAdapter,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    result: CallbackActionResult,
) -> bool:
    client.send_message(
        chat_id,
        result.text,
        reply_to_message_id=message_id,
        message_thread_id=message_thread_id,
        reply_markup=result.reply_markup,
    )
    return True

def _build_engine_action_result(
    state: State,
    config,
    scope_key: str,
    action: str,
    engine_name: str = "",
) -> CallbackActionResult:
    if action == "reset":
        text = _reset_engine_for_scope(state, config, scope_key)
    elif action == "set":
        text = _set_engine_for_scope(state, config, scope_key, engine_name)
    else:
        text = build_engine_status_text(state, config, scope_key)
    return CallbackActionResult(
        text=text,
        reply_markup=_build_engine_picker_markup(state, config, scope_key),
    )

def _build_pi_provider_action_result(
    state: State,
    config,
    scope_key: str,
    action: str,
    value: str = "",
) -> CallbackActionResult:
    if action == "set":
        text = _set_pi_provider_for_scope(state, config, scope_key, value)
        reply_markup = _build_engine_picker_markup(state, config, scope_key)
    else:
        text = build_pi_providers_text(state, config, scope_key)
        reply_markup = _build_provider_picker_markup(state, config, scope_key)
    return CallbackActionResult(text=text, reply_markup=reply_markup)

def _build_model_action_result(
    state: State,
    config,
    scope_key: str,
    action: str,
    *,
    engine_name: str = "",
    value: str = "",
    page_index: Optional[int] = None,
) -> CallbackActionResult:
    active_engine = engine_name or _model_active_engine_name(state, config, scope_key)
    if action == "reset":
        text = _reset_model_for_scope(state, config, scope_key, active_engine)
    elif action == "set":
        if active_engine == "codex":
            text = _set_codex_model_for_scope(state, config, scope_key, value)
        elif active_engine == "pi":
            text = _set_pi_model_for_scope(state, config, scope_key, value)
        else:
            text = build_model_status_text(state, config, scope_key)
    else:
        text = build_model_status_text(state, config, scope_key)
    return CallbackActionResult(
        text=text,
        reply_markup=_build_model_picker_markup(
            state,
            config,
            scope_key,
            page_index=page_index,
        ),
    )

def _build_effort_action_result(
    state: State,
    config,
    scope_key: str,
    action: str,
    value: str = "",
) -> CallbackActionResult:
    if action == "reset":
        text = _reset_codex_effort_for_scope(state, config, scope_key)
    elif action == "set":
        text = _set_codex_effort_for_scope(state, config, scope_key, value)
    else:
        text = build_effort_status_text(state, config, scope_key)
    return CallbackActionResult(
        text=text,
        reply_markup=_build_effort_picker_markup(state, config, scope_key),
    )

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
    if tail in {"", "status"}:
        result = _build_engine_action_result(state, config, scope_key, "status")
    elif tail == "reset":
        result = _build_engine_action_result(state, config, scope_key, "reset")
    else:
        result = _build_engine_action_result(state, config, scope_key, "set", tail)
    return _send_control_result(client, chat_id, message_thread_id, message_id, result)

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
    display_config = build_engine_runtime_config(state, config, scope_key, "pi")

    if tail in {"", "status"}:
        return _send_control_result(
            client,
            chat_id,
            message_thread_id,
            message_id,
            CallbackActionResult(text=build_pi_status_text(state, config, scope_key)),
        )
    if tail == "providers":
        return _send_control_result(
            client,
            chat_id,
            message_thread_id,
            message_id,
            _build_pi_provider_action_result(state, config, scope_key, "menu"),
        )
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
        return _send_control_result(
            client,
            chat_id,
            message_thread_id,
            message_id,
            CallbackActionResult(text=text),
        )
    if tail == "reset":
        removed_provider = clear_chat_pi_provider(state, scope_key)
        removed_model = clear_chat_pi_model(state, scope_key)
        effective_config = build_engine_runtime_config(state, config, scope_key, "pi")
        source_text = "chat overrides cleared" if (removed_provider or removed_model) else "no chat overrides were set"
        return _send_control_result(
            client,
            chat_id,
            message_thread_id,
            message_id,
            CallbackActionResult(
                text=(
                f"{source_text}. "
                f"Pi provider is now {configured_pi_provider(effective_config)} "
                f"({_build_pi_provider_source_text(state, scope_key)}). "
                f"Pi model is now {configured_pi_model(effective_config)} "
                f"({_build_pi_model_source_text(state, scope_key)})."
                )
            ),
        )
    if tail.startswith("provider"):
        provider_name = raw_tail[8:].strip() if len(raw_tail) >= 8 else ""
        if not provider_name:
            return _send_control_result(
                client,
                chat_id,
                message_thread_id,
                message_id,
                CallbackActionResult(
                    text="Usage: /pi provider <name>\nUse /pi providers to list available Pi providers."
                ),
            )
        try:
            result = _build_pi_provider_action_result(state, config, scope_key, "set", provider_name)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            return _send_control_result(
                client,
                chat_id,
                message_thread_id,
                message_id,
                CallbackActionResult(
                    text="Failed to validate Pi provider.\n"
                    f"Error: {_brief_health_error(exc)}"
                ),
            )
        return _send_control_result(client, chat_id, message_thread_id, message_id, result)
    if tail.startswith("model"):
        model_name = raw_tail[5:].strip() if len(raw_tail) >= 5 else ""
        if not model_name:
            return _send_control_result(
                client,
                chat_id,
                message_thread_id,
                message_id,
                CallbackActionResult(
                    text="Usage: /model <name>\nUse /model list to list available models for the current Pi provider."
                ),
            )
        try:
            available_models = _pi_provider_model_names(display_config)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            return _send_control_result(
                client,
                chat_id,
                message_thread_id,
                message_id,
                CallbackActionResult(
                    text="Failed to validate Pi models.\n"
                    f"Error: {_brief_health_error(exc)}"
                ),
            )
        resolved_model = _resolve_pi_model_candidate(available_models, model_name)
        if resolved_model is None:
            provider = configured_pi_provider(display_config)
            return _send_control_result(
                client,
                chat_id,
                message_thread_id,
                message_id,
                CallbackActionResult(
                    text=(
                    f"Model not available for Pi provider `{provider}`: `{model_name}`\n"
                    "Use /model list to see the allowed model names."
                    )
                ),
            )
        set_chat_pi_model(state, scope_key, resolved_model)
        updated_config = build_engine_runtime_config(state, config, scope_key, "pi")
        return _send_control_result(
            client,
            chat_id,
            message_thread_id,
            message_id,
            CallbackActionResult(
                text=(
                f"Pi model for this chat is now {configured_pi_model(updated_config)} "
                f"({_build_pi_model_source_text(state, scope_key)}).\n"
                "Deprecated alias: `/pi model` still works for compatibility, "
                "but `/model <name>` is the canonical command."
                )
            ),
        )
    return _send_control_result(
        client,
        chat_id,
        message_thread_id,
        message_id,
        CallbackActionResult(
            text="Unknown /pi command. Use /pi, /pi providers, /pi provider <name>, or /pi reset. Use /model list and /model <name> for Pi model selection."
        ),
    )

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
    resolved_model = _resolve_codex_model_candidate(model_name)
    set_chat_codex_model(state, scope_key, resolved_model)
    updated_config = build_engine_runtime_config(state, config, scope_key, "codex")
    current_effort = configured_codex_reasoning_effort(updated_config)
    if current_effort and _resolve_codex_effort_candidate(resolved_model, current_effort) is None:
        supported_efforts = _supported_codex_efforts_for_model(resolved_model)
        if supported_efforts:
            set_chat_codex_effort(state, scope_key, supported_efforts[0])
            updated_config = build_engine_runtime_config(state, config, scope_key, "codex")
    return (
        f"Codex model for this chat is now {configured_codex_model(updated_config) or '(default)'} "
        f"({_build_codex_model_source_text(state, scope_key)})."
    )

def _reset_model_for_scope(state: State, config, scope_key: str, active_engine: str) -> str:
    if active_engine == "codex":
        removed = clear_chat_codex_model(state, scope_key)
        updated_config = build_engine_runtime_config(state, config, scope_key, "codex")
        source = "chat override cleared" if removed else "no chat override was set"
        return (
            f"{source}. Codex model is now {configured_codex_model(updated_config) or '(default)'} "
            f"({_build_codex_model_source_text(state, scope_key)})."
        )
    if active_engine == "pi":
        removed = clear_chat_pi_model(state, scope_key)
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
    current_model = get_chat_pi_model(state, scope_key)
    resolved_model = _resolve_pi_model_candidate(available_models, current_model or "")
    if resolved_model is None:
        resolved_model = available_models[0]
    set_chat_pi_provider(state, scope_key, normalized_provider)
    set_chat_pi_model(state, scope_key, resolved_model)
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
    set_chat_pi_model(state, scope_key, resolved_model)
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
    set_chat_codex_effort(state, scope_key, resolved_effort)
    updated_config = build_engine_runtime_config(state, config, scope_key, "codex")
    return (
        f"Codex reasoning effort for this chat is now "
        f"{configured_codex_reasoning_effort(updated_config) or '(default)'} "
        f"({_build_codex_effort_source_text(state, scope_key)})."
    )

def _reset_codex_effort_for_scope(state: State, config, scope_key: str) -> str:
    removed = clear_chat_codex_effort(state, scope_key)
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

    if tail in {"", "status"}:
        result = _build_model_action_result(state, config, scope_key, "status")
    elif tail == "list":
        try:
            text = build_model_list_text(state, config, scope_key)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            text = "Failed to list models.\n" f"Error: {_brief_health_error(exc)}"
        result = CallbackActionResult(text=text)
    elif tail == "reset":
        result = _build_model_action_result(
            state,
            config,
            scope_key,
            "reset",
            engine_name=active_engine,
        )
    else:
        if active_engine == "codex":
            result = _build_model_action_result(
                state,
                config,
                scope_key,
                "set",
                engine_name=active_engine,
                value=raw_tail,
            )
        elif active_engine == "pi":
            try:
                result = _build_model_action_result(
                    state,
                    config,
                    scope_key,
                    "set",
                    engine_name=active_engine,
                    value=raw_tail,
                )
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                result = CallbackActionResult(
                    text="Failed to validate Pi models.\n" f"Error: {_brief_health_error(exc)}"
                )
        else:
            result = _build_model_action_result(state, config, scope_key, "status")
    return _send_control_result(client, chat_id, message_thread_id, message_id, result)

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

    if tail in {"", "status"}:
        result = _build_effort_action_result(state, config, scope_key, "status")
    elif tail == "list":
        result = CallbackActionResult(text=build_effort_list_text(state, config, scope_key))
    elif tail == "reset":
        result = _build_effort_action_result(state, config, scope_key, "reset")
    elif active_engine != "codex":
        result = _build_effort_action_result(state, config, scope_key, "status")
    else:
        result = _build_effort_action_result(state, config, scope_key, "set", raw_tail)
    return _send_control_result(client, chat_id, message_thread_id, message_id, result)

def resolve_engine_for_scope(
    state: State,
    config,
    scope_key: str,
    default_engine: Optional[EngineAdapter],
) -> EngineAdapter:
    selected = get_chat_engine(state, scope_key)
    if not selected:
        if default_engine is not None:
            return default_engine
        return build_default_plugin_registry().build_engine(configured_default_engine(config))
    engine_name = normalize_engine_name(selected)
    if default_engine is not None and getattr(default_engine, "engine_name", "") == engine_name:
        return default_engine
    registry = build_default_plugin_registry()
    return registry.build_engine(engine_name)
