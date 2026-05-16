import subprocess
from typing import Callable

from telegram_bridge.handler_models import CallbackActionResult


def send_control_result(
    client,
    chat_id: int,
    message_thread_id,
    message_id,
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


def handle_engine_command(
    state,
    config,
    client,
    scope_key: str,
    chat_id: int,
    message_thread_id,
    message_id,
    raw_text: str,
    *,
    normalize_engine_name: Callable,
    build_engine_action_result: Callable,
    send_control_result_fn: Callable,
) -> bool:
    pieces = raw_text.strip().split(maxsplit=1)
    tail = pieces[1].strip().lower() if len(pieces) > 1 else "status"
    tail = normalize_engine_name(tail)
    if tail in {"", "status"}:
        result = build_engine_action_result(state, config, scope_key, "status")
    elif tail == "reset":
        result = build_engine_action_result(state, config, scope_key, "reset")
    else:
        result = build_engine_action_result(state, config, scope_key, "set", tail)
    return send_control_result_fn(client, chat_id, message_thread_id, message_id, result)


def handle_pi_command(
    state,
    config,
    client,
    scope_key: str,
    chat_id: int,
    message_thread_id,
    message_id,
    raw_text: str,
    *,
    build_engine_runtime_config: Callable,
    build_pi_status_text: Callable,
    build_pi_provider_action_result: Callable,
    build_pi_models_text: Callable,
    brief_health_error: Callable,
    clear_chat_pi_provider: Callable,
    clear_chat_pi_model: Callable,
    configured_pi_provider: Callable,
    build_pi_provider_source_text: Callable,
    configured_pi_model: Callable,
    build_pi_model_source_text: Callable,
    pi_provider_model_names: Callable,
    resolve_pi_model_candidate: Callable,
    set_chat_pi_model: Callable,
    send_control_result_fn: Callable,
) -> bool:
    pieces = raw_text.strip().split(maxsplit=1)
    raw_tail = pieces[1].strip() if len(pieces) > 1 else "status"
    tail = raw_tail.lower()
    display_config = build_engine_runtime_config(state, config, scope_key, "pi")

    if tail in {"", "status"}:
        return send_control_result_fn(
            client,
            chat_id,
            message_thread_id,
            message_id,
            CallbackActionResult(text=build_pi_status_text(state, config, scope_key)),
        )
    if tail == "providers":
        return send_control_result_fn(
            client,
            chat_id,
            message_thread_id,
            message_id,
            build_pi_provider_action_result(state, config, scope_key, "menu"),
        )
    if tail == "models":
        try:
            text = build_pi_models_text(state, config, scope_key)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            text = "Failed to list Pi models.\n" f"Error: {brief_health_error(exc)}"
        else:
            text += (
                "\n\nDeprecated alias: `/pi models` still works for compatibility, "
                "but `/model list` is the canonical command."
            )
        return send_control_result_fn(
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
        source_text = (
            "chat overrides cleared" if (removed_provider or removed_model) else "no chat overrides were set"
        )
        return send_control_result_fn(
            client,
            chat_id,
            message_thread_id,
            message_id,
            CallbackActionResult(
                text=(
                    f"{source_text}. "
                    f"Pi provider is now {configured_pi_provider(effective_config)} "
                    f"({build_pi_provider_source_text(state, scope_key)}). "
                    f"Pi model is now {configured_pi_model(effective_config)} "
                    f"({build_pi_model_source_text(state, scope_key)})."
                )
            ),
        )
    if tail.startswith("provider"):
        provider_name = raw_tail[8:].strip() if len(raw_tail) >= 8 else ""
        if not provider_name:
            return send_control_result_fn(
                client,
                chat_id,
                message_thread_id,
                message_id,
                CallbackActionResult(
                    text="Usage: /pi provider <name>\nUse /pi providers to list available Pi providers."
                ),
            )
        try:
            result = build_pi_provider_action_result(state, config, scope_key, "set", provider_name)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            return send_control_result_fn(
                client,
                chat_id,
                message_thread_id,
                message_id,
                CallbackActionResult(
                    text="Failed to validate Pi provider.\n"
                    f"Error: {brief_health_error(exc)}"
                ),
            )
        return send_control_result_fn(client, chat_id, message_thread_id, message_id, result)
    if tail.startswith("model"):
        model_name = raw_tail[5:].strip() if len(raw_tail) >= 5 else ""
        if not model_name:
            return send_control_result_fn(
                client,
                chat_id,
                message_thread_id,
                message_id,
                CallbackActionResult(
                    text="Usage: /model <name>\nUse /model list to list available models for the current Pi provider."
                ),
            )
        try:
            available_models = pi_provider_model_names(display_config)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            return send_control_result_fn(
                client,
                chat_id,
                message_thread_id,
                message_id,
                CallbackActionResult(
                    text="Failed to validate Pi models.\n"
                    f"Error: {brief_health_error(exc)}"
                ),
            )
        resolved_model = resolve_pi_model_candidate(available_models, model_name)
        if resolved_model is None:
            provider = configured_pi_provider(display_config)
            return send_control_result_fn(
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
        return send_control_result_fn(
            client,
            chat_id,
            message_thread_id,
            message_id,
            CallbackActionResult(
                text=(
                    f"Pi model for this chat is now {configured_pi_model(updated_config)} "
                    f"({build_pi_model_source_text(state, scope_key)}).\n"
                    "Deprecated alias: `/pi model` still works for compatibility, "
                    "but `/model <name>` is the canonical command."
                )
            ),
        )
    return send_control_result_fn(
        client,
        chat_id,
        message_thread_id,
        message_id,
        CallbackActionResult(
            text="Unknown /pi command. Use /pi, /pi providers, /pi provider <name>, or /pi reset. Use /model list and /model <name> for Pi model selection."
        ),
    )


def handle_model_command(
    state,
    config,
    client,
    scope_key: str,
    chat_id: int,
    message_thread_id,
    message_id,
    raw_text: str,
    *,
    model_active_engine_name: Callable,
    build_model_action_result: Callable,
    build_model_list_text: Callable,
    brief_health_error: Callable,
    send_control_result_fn: Callable,
) -> bool:
    pieces = raw_text.strip().split(maxsplit=1)
    raw_tail = pieces[1].strip() if len(pieces) > 1 else "status"
    tail = raw_tail.lower()
    active_engine = model_active_engine_name(state, config, scope_key)

    if tail in {"", "status"}:
        result = build_model_action_result(state, config, scope_key, "status")
    elif tail == "list":
        try:
            text = build_model_list_text(state, config, scope_key)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            text = "Failed to list models.\n" f"Error: {brief_health_error(exc)}"
        result = CallbackActionResult(text=text)
    elif tail == "reset":
        result = build_model_action_result(
            state,
            config,
            scope_key,
            "reset",
            engine_name=active_engine,
        )
    else:
        if active_engine == "codex":
            result = build_model_action_result(
                state,
                config,
                scope_key,
                "set",
                engine_name=active_engine,
                value=raw_tail,
            )
        elif active_engine in {"gemma", "pi"}:
            try:
                result = build_model_action_result(
                    state,
                    config,
                    scope_key,
                    "set",
                    engine_name=active_engine,
                    value=raw_tail,
                )
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                engine_label = "Pi" if active_engine == "pi" else "Ollama (S4)"
                result = CallbackActionResult(
                    text=(
                        f"Failed to validate {engine_label} models.\n"
                        f"Error: {brief_health_error(exc)}"
                    )
                )
        else:
            result = build_model_action_result(state, config, scope_key, "status")
    return send_control_result_fn(client, chat_id, message_thread_id, message_id, result)


def handle_effort_command(
    state,
    config,
    client,
    scope_key: str,
    chat_id: int,
    message_thread_id,
    message_id,
    raw_text: str,
    *,
    model_active_engine_name: Callable,
    build_effort_action_result: Callable,
    build_effort_list_text: Callable,
    send_control_result_fn: Callable,
) -> bool:
    pieces = raw_text.strip().split(maxsplit=1)
    raw_tail = pieces[1].strip() if len(pieces) > 1 else "status"
    tail = raw_tail.lower()
    active_engine = model_active_engine_name(state, config, scope_key)

    if tail in {"", "status"}:
        result = build_effort_action_result(state, config, scope_key, "status")
    elif tail == "list":
        result = CallbackActionResult(text=build_effort_list_text(state, config, scope_key))
    elif tail == "reset":
        result = build_effort_action_result(state, config, scope_key, "reset")
    elif active_engine != "codex":
        result = build_effort_action_result(state, config, scope_key, "status")
    else:
        result = build_effort_action_result(state, config, scope_key, "set", raw_tail)
    return send_control_result_fn(client, chat_id, message_thread_id, message_id, result)
