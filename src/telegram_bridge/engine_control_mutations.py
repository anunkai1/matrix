import copy
from typing import Callable


def set_engine_for_scope(
    state,
    config,
    scope_key: str,
    engine_name: str,
    *,
    display_engine_name: Callable,
    normalize_engine_name: Callable,
    selectable_engine_plugins: Callable,
    set_chat_engine: Callable,
) -> str:
    normalized_engine = normalize_engine_name(engine_name)
    if normalized_engine == "venice" and not str(getattr(config, "venice_api_key", "") or "").strip():
        return "Venice engine is configured in the bridge, but VENICE_API_KEY is missing."
    allowed = selectable_engine_plugins(config)
    if normalized_engine not in allowed:
        return (
            f"Unknown or unavailable engine: {display_engine_name(normalized_engine)}\n"
            f"Selectable engines: {', '.join(display_engine_name(name) for name in allowed)}"
        )
    set_chat_engine(state, scope_key, normalized_engine)
    return f"This chat now uses engine: {display_engine_name(normalized_engine)}"


def reset_engine_for_scope(
    state,
    config,
    scope_key: str,
    *,
    clear_chat_engine: Callable,
    configured_default_engine: Callable,
    display_engine_name: Callable,
) -> str:
    removed = clear_chat_engine(state, scope_key)
    suffix = "removed" if removed else "already using default"
    return (
        f"Engine override {suffix}. "
        f"This chat now uses {display_engine_name(configured_default_engine(config))}."
    )


def set_codex_model_for_scope(
    state,
    config,
    scope_key: str,
    model_name: str,
    *,
    resolve_codex_model_candidate: Callable,
    set_chat_codex_model: Callable,
    build_engine_runtime_config: Callable,
    configured_codex_model: Callable,
    configured_codex_reasoning_effort: Callable,
    resolve_codex_effort_candidate: Callable,
    supported_codex_efforts_for_model: Callable,
    set_chat_codex_effort: Callable,
    build_codex_model_source_text: Callable,
) -> str:
    resolved_model = resolve_codex_model_candidate(model_name)
    set_chat_codex_model(state, scope_key, resolved_model)
    updated_config = build_engine_runtime_config(state, config, scope_key, "codex")
    current_effort = configured_codex_reasoning_effort(updated_config)
    if current_effort and resolve_codex_effort_candidate(resolved_model, current_effort) is None:
        supported_efforts = supported_codex_efforts_for_model(resolved_model)
        if supported_efforts:
            set_chat_codex_effort(state, scope_key, supported_efforts[0])
            updated_config = build_engine_runtime_config(state, config, scope_key, "codex")
    return (
        f"Codex model for this chat is now {configured_codex_model(updated_config) or '(default)'} "
        f"({build_codex_model_source_text(state, scope_key)})."
    )


def set_gemma_model_for_scope(
    state,
    config,
    scope_key: str,
    model_name: str,
    *,
    build_engine_runtime_config: Callable,
    gemma_model_names: Callable,
    resolve_gemma_model_candidate: Callable,
    set_chat_gemma_model: Callable,
    configured_gemma_model: Callable,
    build_gemma_model_source_text: Callable,
) -> str:
    display_config = build_engine_runtime_config(state, config, scope_key, "gemma")
    available_models = gemma_model_names(display_config)
    resolved_model = resolve_gemma_model_candidate(available_models, model_name)
    if resolved_model is None:
        return (
            f"Model not available for Ollama (S4): `{model_name}`\n"
            "Use /model list to see the allowed model names."
        )
    set_chat_gemma_model(state, scope_key, resolved_model)
    updated_config = build_engine_runtime_config(state, config, scope_key, "gemma")
    return (
        f"Ollama (S4) model for this chat is now {configured_gemma_model(updated_config)} "
        f"({build_gemma_model_source_text(state, scope_key)})."
    )


def reset_model_for_scope(
    state,
    config,
    scope_key: str,
    active_engine: str,
    *,
    clear_chat_codex_model: Callable,
    clear_chat_gemma_model: Callable,
    clear_chat_pi_model: Callable,
    build_engine_runtime_config: Callable,
    configured_codex_model: Callable,
    configured_gemma_model: Callable,
    configured_pi_model: Callable,
    build_codex_model_source_text: Callable,
    build_gemma_model_source_text: Callable,
    build_pi_model_source_text: Callable,
    build_model_status_text: Callable,
) -> str:
    if active_engine == "gemma":
        removed = clear_chat_gemma_model(state, scope_key)
        updated_config = build_engine_runtime_config(state, config, scope_key, "gemma")
        source = "chat override cleared" if removed else "no chat override was set"
        return (
            f"{source}. Ollama (S4) model is now {configured_gemma_model(updated_config)} "
            f"({build_gemma_model_source_text(state, scope_key)})."
        )
    if active_engine == "codex":
        removed = clear_chat_codex_model(state, scope_key)
        updated_config = build_engine_runtime_config(state, config, scope_key, "codex")
        source = "chat override cleared" if removed else "no chat override was set"
        return (
            f"{source}. Codex model is now {configured_codex_model(updated_config) or '(default)'} "
            f"({build_codex_model_source_text(state, scope_key)})."
        )
    if active_engine == "pi":
        removed = clear_chat_pi_model(state, scope_key)
        updated_config = build_engine_runtime_config(state, config, scope_key, "pi")
        source = "chat override cleared" if removed else "no chat override was set"
        return (
            f"{source}. Pi model is now {configured_pi_model(updated_config)} "
            f"({build_pi_model_source_text(state, scope_key)})."
        )
    return build_model_status_text(state, config, scope_key)


def set_pi_provider_for_scope(
    state,
    config,
    scope_key: str,
    provider_name: str,
    *,
    normalize_pi_provider_name: Callable,
    pi_provider_model_names: Callable,
    get_chat_pi_model: Callable,
    resolve_pi_model_candidate: Callable,
    set_chat_pi_provider: Callable,
    set_chat_pi_model: Callable,
) -> str:
    normalized_provider = normalize_pi_provider_name(provider_name)
    temp_config = copy.copy(config)
    temp_config.pi_provider = normalized_provider
    available_models = pi_provider_model_names(temp_config)
    if not available_models:
        return (
            f"Provider `{normalized_provider}` did not report any models.\n"
            "Pi provider was not changed."
        )
    current_model = get_chat_pi_model(state, scope_key)
    resolved_model = resolve_pi_model_candidate(available_models, current_model or "")
    if resolved_model is None:
        resolved_model = available_models[0]
    set_chat_pi_provider(state, scope_key, normalized_provider)
    set_chat_pi_model(state, scope_key, resolved_model)
    return (
        f"Pi provider for this chat is now {normalized_provider}. "
        f"Pi model is now {resolved_model}."
    )


def set_pi_model_for_scope(
    state,
    config,
    scope_key: str,
    model_name: str,
    *,
    build_engine_runtime_config: Callable,
    pi_provider_model_names: Callable,
    resolve_pi_model_candidate: Callable,
    configured_pi_provider: Callable,
    set_chat_pi_model: Callable,
    configured_pi_model: Callable,
    build_pi_model_source_text: Callable,
) -> str:
    display_config = build_engine_runtime_config(state, config, scope_key, "pi")
    available_models = pi_provider_model_names(display_config)
    resolved_model = resolve_pi_model_candidate(available_models, model_name)
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
        f"({build_pi_model_source_text(state, scope_key)})."
    )


def set_codex_effort_for_scope(
    state,
    config,
    scope_key: str,
    effort_name: str,
    *,
    build_engine_runtime_config: Callable,
    configured_codex_model: Callable,
    resolve_codex_effort_candidate: Callable,
    set_chat_codex_effort: Callable,
    configured_codex_reasoning_effort: Callable,
    build_codex_effort_source_text: Callable,
) -> str:
    display_config = build_engine_runtime_config(state, config, scope_key, "codex")
    current_model = configured_codex_model(display_config)
    resolved_effort = resolve_codex_effort_candidate(current_model, effort_name)
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
        f"({build_codex_effort_source_text(state, scope_key)})."
    )


def reset_codex_effort_for_scope(
    state,
    config,
    scope_key: str,
    *,
    clear_chat_codex_effort: Callable,
    build_engine_runtime_config: Callable,
    configured_codex_reasoning_effort: Callable,
    build_codex_effort_source_text: Callable,
) -> str:
    removed = clear_chat_codex_effort(state, scope_key)
    updated_config = build_engine_runtime_config(state, config, scope_key, "codex")
    source = "chat override cleared" if removed else "no chat override was set"
    return (
        f"{source}. Codex reasoning effort is now "
        f"{configured_codex_reasoning_effort(updated_config) or '(default)'} "
        f"({build_codex_effort_source_text(state, scope_key)})."
    )


def resolve_engine_for_scope(
    state,
    config,
    scope_key: str,
    default_engine,
    *,
    get_chat_engine: Callable,
    normalize_engine_name: Callable,
    build_default_plugin_registry: Callable,
    configured_default_engine: Callable,
):
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
