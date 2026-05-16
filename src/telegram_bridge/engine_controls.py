import subprocess
from typing import Dict, List, Optional, Tuple

from telegram_bridge.channel_adapter import ChannelAdapter
from telegram_bridge import engine_control_actions
from telegram_bridge import engine_control_commands
from telegram_bridge import engine_control_views
from telegram_bridge import engine_control_mutations
from telegram_bridge.engine_catalog import (
    ENGINE_NAME_ALIASES,
    PI_PROVIDER_ALIASES,
    PI_PROVIDER_CHOICES,
    configured_codex_model,
    configured_codex_reasoning_effort,
    configured_default_engine,
    configured_gemma_model,
    configured_pi_model,
    configured_pi_provider,
    display_engine_name,
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
    build_gemma_model_source_text as _build_gemma_model_source_text,
    build_pi_model_source_text as _build_pi_model_source_text,
    build_pi_models_text,
    build_pi_provider_source_text as _build_pi_provider_source_text,
    build_pi_providers_text,
    build_pi_status_text,
    check_chatgpt_web_health,
    check_gemma_health,
    check_pi_health,
    check_venice_health,
    gemma_model_names as _gemma_model_names,
    GEMMA_HEALTH_CURL_TIMEOUT_SECONDS,
    GEMMA_HEALTH_TIMEOUT_SECONDS,
    model_active_engine_name as _model_active_engine_name,
    pi_available_provider_names as _pi_available_provider_names,
    pi_provider_model_names as _pi_provider_model_names,
    resolve_gemma_model_candidate as _resolve_gemma_model_candidate,
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
    clear_chat_gemma_model,
    clear_chat_pi_model,
    clear_chat_pi_provider,
    get_chat_codex_effort,
    get_chat_codex_model,
    get_chat_engine,
    get_chat_gemma_model,
    get_chat_pi_model,
    get_chat_pi_provider,
    set_chat_codex_effort,
    set_chat_codex_model,
    set_chat_engine,
    set_chat_gemma_model,
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
    return engine_control_mutations.set_engine_for_scope(
        state,
        config,
        scope_key,
        engine_name,
        display_engine_name=display_engine_name,
        normalize_engine_name=normalize_engine_name,
        selectable_engine_plugins=selectable_engine_plugins,
        set_chat_engine=set_chat_engine,
    )

def _reset_engine_for_scope(state: State, config, scope_key: str) -> str:
    return engine_control_mutations.reset_engine_for_scope(
        state,
        config,
        scope_key,
        clear_chat_engine=clear_chat_engine,
        configured_default_engine=configured_default_engine,
        display_engine_name=display_engine_name,
    )

def _send_control_result(
    client: ChannelAdapter,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    result: CallbackActionResult,
) -> bool:
    return engine_control_commands.send_control_result(
        client,
        chat_id,
        message_thread_id,
        message_id,
        result,
    )

def _build_engine_action_result(
    state: State,
    config,
    scope_key: str,
    action: str,
    engine_name: str = "",
) -> CallbackActionResult:
    return engine_control_actions.build_engine_action_result(
        state,
        config,
        scope_key,
        action,
        engine_name,
        reset_engine_for_scope=_reset_engine_for_scope,
        set_engine_for_scope=_set_engine_for_scope,
        build_engine_status_text=build_engine_status_text,
        build_engine_picker_markup=_build_engine_picker_markup,
    )

def _build_pi_provider_action_result(
    state: State,
    config,
    scope_key: str,
    action: str,
    value: str = "",
) -> CallbackActionResult:
    return engine_control_actions.build_pi_provider_action_result(
        state,
        config,
        scope_key,
        action,
        value,
        set_pi_provider_for_scope=_set_pi_provider_for_scope,
        build_engine_picker_markup=_build_engine_picker_markup,
        build_pi_providers_text=build_pi_providers_text,
        build_provider_picker_markup=_build_provider_picker_markup,
    )

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
    return engine_control_actions.build_model_action_result(
        state,
        config,
        scope_key,
        action,
        engine_name=engine_name,
        value=value,
        page_index=page_index,
        model_active_engine_name=_model_active_engine_name,
        reset_model_for_scope=_reset_model_for_scope,
        set_codex_model_for_scope=_set_codex_model_for_scope,
        set_gemma_model_for_scope=_set_gemma_model_for_scope,
        set_pi_model_for_scope=_set_pi_model_for_scope,
        build_model_status_text=build_model_status_text,
        build_model_picker_markup=_build_model_picker_markup,
    )

def _build_effort_action_result(
    state: State,
    config,
    scope_key: str,
    action: str,
    value: str = "",
) -> CallbackActionResult:
    return engine_control_actions.build_effort_action_result(
        state,
        config,
        scope_key,
        action,
        value,
        reset_codex_effort_for_scope=_reset_codex_effort_for_scope,
        set_codex_effort_for_scope=_set_codex_effort_for_scope,
        build_effort_status_text=build_effort_status_text,
        build_effort_picker_markup=_build_effort_picker_markup,
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
    return engine_control_commands.handle_engine_command(
        state,
        config,
        client,
        scope_key,
        chat_id,
        message_thread_id,
        message_id,
        raw_text,
        normalize_engine_name=normalize_engine_name,
        build_engine_action_result=_build_engine_action_result,
        send_control_result_fn=_send_control_result,
    )

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
    return engine_control_commands.handle_pi_command(
        state,
        config,
        client,
        scope_key,
        chat_id,
        message_thread_id,
        message_id,
        raw_text,
        build_engine_runtime_config=build_engine_runtime_config,
        build_pi_status_text=build_pi_status_text,
        build_pi_provider_action_result=_build_pi_provider_action_result,
        build_pi_models_text=build_pi_models_text,
        brief_health_error=_brief_health_error,
        clear_chat_pi_provider=clear_chat_pi_provider,
        clear_chat_pi_model=clear_chat_pi_model,
        configured_pi_provider=configured_pi_provider,
        build_pi_provider_source_text=_build_pi_provider_source_text,
        configured_pi_model=configured_pi_model,
        build_pi_model_source_text=_build_pi_model_source_text,
        pi_provider_model_names=_pi_provider_model_names,
        resolve_pi_model_candidate=_resolve_pi_model_candidate,
        set_chat_pi_model=set_chat_pi_model,
        send_control_result_fn=_send_control_result,
    )

def _build_model_picker_markup(
    state: State,
    config,
    scope_key: str,
    *,
    page_index: Optional[int] = None,
) -> Optional[Dict[str, object]]:
    return engine_control_actions.build_model_picker_markup(
        state,
        config,
        scope_key,
        page_index=page_index,
        view_builder=lambda current_state, current_config, current_scope_key, *, page_index=None: engine_control_views.build_model_picker_markup(
            current_state,
            current_config,
            current_scope_key,
            page_index=page_index,
            model_active_engine_name=_model_active_engine_name,
            build_engine_runtime_config=build_engine_runtime_config,
            gemma_model_names=_gemma_model_names,
            configured_codex_model=configured_codex_model,
            configured_gemma_model=configured_gemma_model,
            load_codex_model_choices=_load_codex_model_choices,
            pi_provider_model_names=_pi_provider_model_names,
            configured_pi_model=configured_pi_model,
        ),
    )

def _build_provider_picker_markup(state: State, config, scope_key: str) -> Optional[Dict[str, object]]:
    return engine_control_actions.build_provider_picker_markup(
        state,
        config,
        scope_key,
        view_builder=lambda current_state, current_config, current_scope_key: engine_control_views.build_provider_picker_markup(
            current_state,
            current_config,
            current_scope_key,
            build_engine_runtime_config=build_engine_runtime_config,
            configured_pi_provider=configured_pi_provider,
            pi_available_provider_names=_pi_available_provider_names,
        ),
        build_engine_runtime_config=build_engine_runtime_config,
        configured_pi_provider=configured_pi_provider,
        provider_choices=PI_PROVIDER_CHOICES,
        provider_callback_data=_provider_callback_data,
        compact_inline_keyboard=_compact_inline_keyboard,
        engine_callback_data=_engine_callback_data,
    )

def _build_effort_picker_markup(state: State, config, scope_key: str) -> Optional[Dict[str, object]]:
    return engine_control_actions.build_effort_picker_markup(
        state,
        config,
        scope_key,
        view_builder=lambda current_state, current_config, current_scope_key: engine_control_views.build_effort_picker_markup(
            current_state,
            current_config,
            current_scope_key,
            model_active_engine_name=_model_active_engine_name,
            build_engine_runtime_config=build_engine_runtime_config,
            configured_codex_model=configured_codex_model,
            configured_codex_reasoning_effort=configured_codex_reasoning_effort,
            supported_codex_efforts_for_model=_supported_codex_efforts_for_model,
        ),
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
        configured_gemma_model=configured_gemma_model,
        configured_pi_provider=configured_pi_provider,
        configured_pi_model=configured_pi_model,
        build_codex_model_source_text=_build_codex_model_source_text,
        build_codex_effort_source_text=_build_codex_effort_source_text,
        build_gemma_model_source_text=_build_gemma_model_source_text,
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
    return engine_control_mutations.set_codex_model_for_scope(
        state,
        config,
        scope_key,
        model_name,
        resolve_codex_model_candidate=_resolve_codex_model_candidate,
        set_chat_codex_model=set_chat_codex_model,
        build_engine_runtime_config=build_engine_runtime_config,
        configured_codex_model=configured_codex_model,
        configured_codex_reasoning_effort=configured_codex_reasoning_effort,
        resolve_codex_effort_candidate=_resolve_codex_effort_candidate,
        supported_codex_efforts_for_model=_supported_codex_efforts_for_model,
        set_chat_codex_effort=set_chat_codex_effort,
        build_codex_model_source_text=_build_codex_model_source_text,
    )

def _reset_model_for_scope(state: State, config, scope_key: str, active_engine: str) -> str:
    return engine_control_mutations.reset_model_for_scope(
        state,
        config,
        scope_key,
        active_engine,
        clear_chat_codex_model=clear_chat_codex_model,
        clear_chat_gemma_model=clear_chat_gemma_model,
        clear_chat_pi_model=clear_chat_pi_model,
        build_engine_runtime_config=build_engine_runtime_config,
        configured_codex_model=configured_codex_model,
        configured_gemma_model=configured_gemma_model,
        configured_pi_model=configured_pi_model,
        build_codex_model_source_text=_build_codex_model_source_text,
        build_gemma_model_source_text=_build_gemma_model_source_text,
        build_pi_model_source_text=_build_pi_model_source_text,
        build_model_status_text=build_model_status_text,
    )

def _set_pi_provider_for_scope(state: State, config, scope_key: str, provider_name: str) -> str:
    return engine_control_mutations.set_pi_provider_for_scope(
        state,
        config,
        scope_key,
        provider_name,
        normalize_pi_provider_name=normalize_pi_provider_name,
        pi_provider_model_names=_pi_provider_model_names,
        get_chat_pi_model=get_chat_pi_model,
        resolve_pi_model_candidate=_resolve_pi_model_candidate,
        set_chat_pi_provider=set_chat_pi_provider,
        set_chat_pi_model=set_chat_pi_model,
    )

def _set_gemma_model_for_scope(state: State, config, scope_key: str, model_name: str) -> str:
    return engine_control_mutations.set_gemma_model_for_scope(
        state,
        config,
        scope_key,
        model_name,
        build_engine_runtime_config=build_engine_runtime_config,
        gemma_model_names=_gemma_model_names,
        resolve_gemma_model_candidate=_resolve_gemma_model_candidate,
        set_chat_gemma_model=set_chat_gemma_model,
        configured_gemma_model=configured_gemma_model,
        build_gemma_model_source_text=_build_gemma_model_source_text,
    )

def _set_pi_model_for_scope(state: State, config, scope_key: str, model_name: str) -> str:
    return engine_control_mutations.set_pi_model_for_scope(
        state,
        config,
        scope_key,
        model_name,
        build_engine_runtime_config=build_engine_runtime_config,
        pi_provider_model_names=_pi_provider_model_names,
        resolve_pi_model_candidate=_resolve_pi_model_candidate,
        configured_pi_provider=configured_pi_provider,
        set_chat_pi_model=set_chat_pi_model,
        configured_pi_model=configured_pi_model,
        build_pi_model_source_text=_build_pi_model_source_text,
    )

def _set_codex_effort_for_scope(state: State, config, scope_key: str, effort_name: str) -> str:
    return engine_control_mutations.set_codex_effort_for_scope(
        state,
        config,
        scope_key,
        effort_name,
        build_engine_runtime_config=build_engine_runtime_config,
        configured_codex_model=configured_codex_model,
        resolve_codex_effort_candidate=_resolve_codex_effort_candidate,
        set_chat_codex_effort=set_chat_codex_effort,
        configured_codex_reasoning_effort=configured_codex_reasoning_effort,
        build_codex_effort_source_text=_build_codex_effort_source_text,
    )

def _reset_codex_effort_for_scope(state: State, config, scope_key: str) -> str:
    return engine_control_mutations.reset_codex_effort_for_scope(
        state,
        config,
        scope_key,
        clear_chat_codex_effort=clear_chat_codex_effort,
        build_engine_runtime_config=build_engine_runtime_config,
        configured_codex_reasoning_effort=configured_codex_reasoning_effort,
        build_codex_effort_source_text=_build_codex_effort_source_text,
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
        configured_gemma_model=configured_gemma_model,
        configured_codex_model=configured_codex_model,
        load_codex_model_choices=_load_codex_model_choices,
        gemma_model_names=_gemma_model_names,
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
    return engine_control_commands.handle_model_command(
        state,
        config,
        client,
        scope_key,
        chat_id,
        message_thread_id,
        message_id,
        raw_text,
        model_active_engine_name=_model_active_engine_name,
        build_model_action_result=_build_model_action_result,
        build_model_list_text=build_model_list_text,
        brief_health_error=_brief_health_error,
        send_control_result_fn=_send_control_result,
    )

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
    return engine_control_commands.handle_effort_command(
        state,
        config,
        client,
        scope_key,
        chat_id,
        message_thread_id,
        message_id,
        raw_text,
        model_active_engine_name=_model_active_engine_name,
        build_effort_action_result=_build_effort_action_result,
        build_effort_list_text=build_effort_list_text,
        send_control_result_fn=_send_control_result,
    )

def resolve_engine_for_scope(
    state: State,
    config,
    scope_key: str,
    default_engine: Optional[EngineAdapter],
) -> EngineAdapter:
    return engine_control_mutations.resolve_engine_for_scope(
        state,
        config,
        scope_key,
        default_engine,
        get_chat_engine=get_chat_engine,
        normalize_engine_name=normalize_engine_name,
        build_default_plugin_registry=build_default_plugin_registry,
        configured_default_engine=configured_default_engine,
    )
