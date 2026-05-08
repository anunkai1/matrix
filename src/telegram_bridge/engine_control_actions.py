import subprocess
from typing import Callable, Dict, List, Optional, Tuple

from telegram_bridge.handler_models import CallbackActionResult


def build_engine_action_result(
    state,
    config,
    scope_key: str,
    action: str,
    engine_name: str = "",
    *,
    reset_engine_for_scope: Callable,
    set_engine_for_scope: Callable,
    build_engine_status_text: Callable,
    build_engine_picker_markup: Callable,
) -> CallbackActionResult:
    if action == "reset":
        text = reset_engine_for_scope(state, config, scope_key)
    elif action == "set":
        text = set_engine_for_scope(state, config, scope_key, engine_name)
    else:
        text = build_engine_status_text(state, config, scope_key)
    return CallbackActionResult(
        text=text,
        reply_markup=build_engine_picker_markup(state, config, scope_key),
    )


def build_pi_provider_action_result(
    state,
    config,
    scope_key: str,
    action: str,
    value: str = "",
    *,
    set_pi_provider_for_scope: Callable,
    build_engine_picker_markup: Callable,
    build_pi_providers_text: Callable,
    build_provider_picker_markup: Callable,
) -> CallbackActionResult:
    if action == "set":
        text = set_pi_provider_for_scope(state, config, scope_key, value)
        reply_markup = build_engine_picker_markup(state, config, scope_key)
    else:
        text = build_pi_providers_text(state, config, scope_key)
        reply_markup = build_provider_picker_markup(state, config, scope_key)
    return CallbackActionResult(text=text, reply_markup=reply_markup)


def build_model_action_result(
    state,
    config,
    scope_key: str,
    action: str,
    *,
    engine_name: str = "",
    value: str = "",
    page_index: Optional[int] = None,
    model_active_engine_name: Callable,
    reset_model_for_scope: Callable,
    set_codex_model_for_scope: Callable,
    set_pi_model_for_scope: Callable,
    build_model_status_text: Callable,
    build_model_picker_markup: Callable,
) -> CallbackActionResult:
    active_engine = engine_name or model_active_engine_name(state, config, scope_key)
    if action == "reset":
        text = reset_model_for_scope(state, config, scope_key, active_engine)
    elif action == "set":
        if active_engine == "codex":
            text = set_codex_model_for_scope(state, config, scope_key, value)
        elif active_engine == "pi":
            text = set_pi_model_for_scope(state, config, scope_key, value)
        else:
            text = build_model_status_text(state, config, scope_key)
    else:
        text = build_model_status_text(state, config, scope_key)
    return CallbackActionResult(
        text=text,
        reply_markup=build_model_picker_markup(
            state,
            config,
            scope_key,
            page_index=page_index,
        ),
    )


def build_effort_action_result(
    state,
    config,
    scope_key: str,
    action: str,
    value: str = "",
    *,
    reset_codex_effort_for_scope: Callable,
    set_codex_effort_for_scope: Callable,
    build_effort_status_text: Callable,
    build_effort_picker_markup: Callable,
) -> CallbackActionResult:
    if action == "reset":
        text = reset_codex_effort_for_scope(state, config, scope_key)
    elif action == "set":
        text = set_codex_effort_for_scope(state, config, scope_key, value)
    else:
        text = build_effort_status_text(state, config, scope_key)
    return CallbackActionResult(
        text=text,
        reply_markup=build_effort_picker_markup(state, config, scope_key),
    )


def build_model_picker_markup(
    state,
    config,
    scope_key: str,
    *,
    page_index: Optional[int] = None,
    view_builder: Callable,
) -> Optional[Dict[str, object]]:
    try:
        return view_builder(state, config, scope_key, page_index=page_index)
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        return None


def build_provider_picker_markup(
    state,
    config,
    scope_key: str,
    *,
    view_builder: Callable,
    build_engine_runtime_config: Callable,
    configured_pi_provider: Callable,
    provider_choices: List[Tuple[str, str]],
    provider_callback_data: Callable,
    compact_inline_keyboard: Callable,
    engine_callback_data: Callable,
) -> Optional[Dict[str, object]]:
    try:
        return view_builder(state, config, scope_key)
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        display_config = build_engine_runtime_config(state, config, scope_key, "pi")
        current_provider = configured_pi_provider(display_config)
        buttons: List[Tuple[str, str]] = []
        for provider_name, _description in provider_choices:
            label = f"{provider_name} *" if provider_name == current_provider else provider_name
            buttons.append((label, provider_callback_data("set", provider_name)))
        rows = compact_inline_keyboard(buttons, columns=2).get("inline_keyboard", [])
        rows.append(
            [
                {"text": "Back to Engine", "callback_data": engine_callback_data("pi", "menu")},
            ]
        )
        return {"inline_keyboard": rows} if rows else None


def build_effort_picker_markup(
    state,
    config,
    scope_key: str,
    *,
    view_builder: Callable,
) -> Optional[Dict[str, object]]:
    return view_builder(state, config, scope_key)
