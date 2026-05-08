import logging
import subprocess
from typing import Callable, Dict, Optional, Tuple

from telegram_bridge.channel_adapter import ChannelAdapter
from telegram_bridge import command_callback_routing
from telegram_bridge import control_commands
from telegram_bridge.diary_processing import build_diary_queue_status, build_diary_today_status
from telegram_bridge.diary_store import diary_mode_enabled
from telegram_bridge import engine_controls
from telegram_bridge.handler_common import build_help_text, build_status_text, extract_callback_query_context
from telegram_bridge.handler_models import CallbackActionContext, CallbackActionResult, KnownCommandContext
from telegram_bridge.runtime_profile import CANCEL_COMMAND_ALIASES, HELP_COMMAND_ALIASES, start_command_message
from telegram_bridge.state_store import State
from telegram_bridge import voice_alias_commands

KnownCommandFn = Callable[[KnownCommandContext], bool]
CallbackActionFn = Callable[[CallbackActionContext], CallbackActionResult]

def _handle_start_known_command(ctx: KnownCommandContext) -> bool:
    ctx.client.send_message(
        ctx.chat_id,
        start_command_message(ctx.config),
        reply_to_message_id=ctx.message_id,
    )
    return True

def _handle_help_known_command(ctx: KnownCommandContext) -> bool:
    ctx.client.send_message(
        ctx.chat_id,
        build_help_text(ctx.config),
        reply_to_message_id=ctx.message_id,
    )
    return True

def _handle_status_known_command(ctx: KnownCommandContext) -> bool:
    ctx.client.send_message(
        ctx.chat_id,
        build_status_text(ctx.state, ctx.config, chat_id=ctx.chat_id, scope_key=ctx.scope_key),
        reply_to_message_id=ctx.message_id,
        message_thread_id=ctx.message_thread_id,
    )
    return True

def _handle_restart_known_command(ctx: KnownCommandContext) -> bool:
    control_commands.handle_restart_command(
        ctx.state,
        ctx.client,
        ctx.chat_id,
        ctx.message_thread_id,
        ctx.message_id,
    )
    return True

def _handle_cancel_known_command(ctx: KnownCommandContext) -> bool:
    control_commands.handle_cancel_command(
        ctx.state,
        ctx.client,
        ctx.scope_key,
        ctx.chat_id,
        ctx.message_thread_id,
        ctx.message_id,
    )
    return True

def _handle_engine_known_command(ctx: KnownCommandContext) -> bool:
    return engine_controls.handle_engine_command(
        state=ctx.state,
        config=ctx.config,
        client=ctx.client,
        scope_key=ctx.scope_key,
        chat_id=ctx.chat_id,
        message_thread_id=ctx.message_thread_id,
        message_id=ctx.message_id,
        raw_text=ctx.raw_text,
    )

def _handle_model_known_command(ctx: KnownCommandContext) -> bool:
    return engine_controls.handle_model_command(
        state=ctx.state,
        config=ctx.config,
        client=ctx.client,
        scope_key=ctx.scope_key,
        chat_id=ctx.chat_id,
        message_thread_id=ctx.message_thread_id,
        message_id=ctx.message_id,
        raw_text=ctx.raw_text,
    )

def _handle_effort_known_command(ctx: KnownCommandContext) -> bool:
    return engine_controls.handle_effort_command(
        state=ctx.state,
        config=ctx.config,
        client=ctx.client,
        scope_key=ctx.scope_key,
        chat_id=ctx.chat_id,
        message_thread_id=ctx.message_thread_id,
        message_id=ctx.message_id,
        raw_text=ctx.raw_text,
    )

def _handle_pi_known_command(ctx: KnownCommandContext) -> bool:
    return engine_controls.handle_pi_command(
        state=ctx.state,
        config=ctx.config,
        client=ctx.client,
        scope_key=ctx.scope_key,
        chat_id=ctx.chat_id,
        message_thread_id=ctx.message_thread_id,
        message_id=ctx.message_id,
        raw_text=ctx.raw_text,
    )

def _handle_reset_known_command(ctx: KnownCommandContext) -> bool:
    control_commands.handle_reset_command(
        ctx.state,
        ctx.config,
        ctx.client,
        ctx.scope_key,
        ctx.chat_id,
        ctx.message_thread_id,
        ctx.message_id,
    )
    return True

def _handle_voice_alias_known_command(ctx: KnownCommandContext) -> bool:
    return voice_alias_commands.handle_voice_alias_command(
        state=ctx.state,
        config=ctx.config,
        client=ctx.client,
        chat_id=ctx.chat_id,
        message_id=ctx.message_id,
        raw_text=ctx.raw_text,
    )

def _handle_diary_today_known_command(ctx: KnownCommandContext) -> bool:
    ctx.client.send_message(
        ctx.chat_id,
        build_diary_today_status(ctx.state, ctx.config, ctx.scope_key),
        reply_to_message_id=ctx.message_id,
    )
    return True

def _handle_diary_queue_known_command(ctx: KnownCommandContext) -> bool:
    ctx.client.send_message(
        ctx.chat_id,
        build_diary_queue_status(ctx.state, ctx.scope_key),
        reply_to_message_id=ctx.message_id,
    )
    return True

KNOWN_COMMAND_HANDLERS: Dict[str, KnownCommandFn] = {
    "/start": _handle_start_known_command,
    "/status": _handle_status_known_command,
    "/restart": _handle_restart_known_command,
    "/engine": _handle_engine_known_command,
    "/model": _handle_model_known_command,
    "/effort": _handle_effort_known_command,
    "/pi": _handle_pi_known_command,
    "/reset": _handle_reset_known_command,
    "/voice-alias": _handle_voice_alias_known_command,
}

DIARY_COMMAND_HANDLERS: Dict[str, KnownCommandFn] = {
    "/today": _handle_diary_today_known_command,
    "/queue": _handle_diary_queue_known_command,
}

def handle_known_command(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    command: Optional[str],
    raw_text: str,
) -> bool:
    if command is None:
        return False

    ctx = KnownCommandContext(
        state=state,
        config=config,
        client=client,
        scope_key=scope_key,
        chat_id=chat_id,
        message_thread_id=message_thread_id,
        message_id=message_id,
        raw_text=raw_text,
    )

    if command in HELP_COMMAND_ALIASES:
        return _handle_help_known_command(ctx)
    if command in CANCEL_COMMAND_ALIASES:
        return _handle_cancel_known_command(ctx)

    handler = KNOWN_COMMAND_HANDLERS.get(command)
    if handler is not None:
        return handler(ctx)

    if diary_mode_enabled(config):
        diary_handler = DIARY_COMMAND_HANDLERS.get(command)
        if diary_handler is not None:
            return diary_handler(ctx)

    return False

def _handle_engine_callback_action(ctx: CallbackActionContext) -> CallbackActionResult:
    return engine_controls._build_engine_action_result(
        ctx.state,
        ctx.config,
        ctx.scope_key,
        ctx.action,
        ctx.engine_name,
    )

def _handle_pi_provider_callback_action(ctx: CallbackActionContext) -> CallbackActionResult:
    return engine_controls._build_pi_provider_action_result(
        ctx.state,
        ctx.config,
        ctx.scope_key,
        ctx.action,
        ctx.value,
    )

def _handle_model_callback_action(ctx: CallbackActionContext) -> CallbackActionResult:
    return engine_controls._build_model_action_result(
        ctx.state,
        ctx.config,
        ctx.scope_key,
        ctx.action,
        engine_name=ctx.engine_name,
        value=ctx.value,
        page_index=engine_controls._parse_page_index(ctx.value),
    )

def _handle_codex_effort_callback_action(ctx: CallbackActionContext) -> CallbackActionResult:
    return engine_controls._build_effort_action_result(
        ctx.state,
        ctx.config,
        ctx.scope_key,
        ctx.action,
        ctx.value,
    )

CALLBACK_ACTION_HANDLERS: Dict[Tuple[str, Optional[str]], CallbackActionFn] = {
    ("engine", None): _handle_engine_callback_action,
    ("provider", "pi"): _handle_pi_provider_callback_action,
    ("model", None): _handle_model_callback_action,
    ("effort", "codex"): _handle_codex_effort_callback_action,
}

def _resolve_callback_action_handler(
    kind: str,
    engine_name: str,
):
    return command_callback_routing.resolve_callback_action_handler(
        kind,
        engine_name,
        callback_action_handlers=CALLBACK_ACTION_HANDLERS,
    )

def handle_callback_query(
    state: State,
    config,
    client: ChannelAdapter,
    update: Dict[str, object],
) -> bool:
    return command_callback_routing.handle_callback_query(
        state,
        config,
        client,
        update,
        extract_callback_query_context=extract_callback_query_context,
        resolve_callback_action_handler_fn=_resolve_callback_action_handler,
        callback_action_context_cls=CallbackActionContext,
        callback_action_result_cls=CallbackActionResult,
        brief_health_error=engine_controls._brief_health_error,
    )
