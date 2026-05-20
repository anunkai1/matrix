import logging
import subprocess
from typing import Callable, Dict, Optional, Tuple

from telegram_bridge.channel_adapter import ChannelAdapter
from telegram_bridge import command_callback_routing
from telegram_bridge import command_known_routing
from telegram_bridge import control_commands
from telegram_bridge.diary_processing import build_diary_queue_status, build_diary_today_status
from telegram_bridge.diary_store import diary_mode_enabled
from telegram_bridge import engine_controls
from telegram_bridge import goal_loop
from telegram_bridge.handler_common import build_help_text, build_status_text, extract_callback_query_context
from telegram_bridge.handler_models import CallbackActionContext, CallbackActionResult, KnownCommandContext
from telegram_bridge import remember_commands
from telegram_bridge.runtime_profile import CANCEL_COMMAND_ALIASES, HELP_COMMAND_ALIASES, start_command_message
from telegram_bridge.state_store import State
from telegram_bridge import voice_alias_commands

KnownCommandFn = Callable[[KnownCommandContext], bool]
CallbackActionFn = Callable[[CallbackActionContext], CallbackActionResult]
DISHFRAMED_RETIRED_MESSAGE = (
    "DishFramed has been retired on Server3. `/dishframed` is no longer available."
)


def _reply_to_known_command(
    ctx: KnownCommandContext,
    text: str,
    *,
    include_thread: bool = False,
) -> bool:
    ctx.client.send_message(
        ctx.chat_id,
        text,
        reply_to_message_id=ctx.message_id,
        message_thread_id=ctx.message_thread_id if include_thread else None,
    )
    return True


def _handle_start_known_command(ctx: KnownCommandContext) -> bool:
    return _reply_to_known_command(
        ctx,
        start_command_message(ctx.config),
    )

def _handle_help_known_command(ctx: KnownCommandContext) -> bool:
    return _reply_to_known_command(
        ctx,
        build_help_text(ctx.config),
    )

def _handle_status_known_command(ctx: KnownCommandContext) -> bool:
    return _reply_to_known_command(
        ctx,
        build_status_text(ctx.state, ctx.config, chat_id=ctx.chat_id, scope_key=ctx.scope_key),
        include_thread=True,
    )

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

def _handle_goal_known_command(ctx: KnownCommandContext) -> bool:
    return goal_loop.handle_goal_command(
        state=ctx.state,
        config=ctx.config,
        client=ctx.client,
        scope_key=ctx.scope_key,
        chat_id=ctx.chat_id,
        message_thread_id=ctx.message_thread_id,
        message_id=ctx.message_id,
        raw_text=ctx.raw_text,
    )

def _handle_remember_known_command(ctx: KnownCommandContext) -> bool:
    return remember_commands.handle_remember_command(
        state=ctx.state,
        scope_key=ctx.scope_key,
        client=ctx.client,
        chat_id=ctx.chat_id,
        message_id=ctx.message_id,
        raw_text=ctx.raw_text,
    )

def _handle_subgoal_known_command(ctx: KnownCommandContext) -> bool:
    return goal_loop.handle_subgoal_command(
        state=ctx.state,
        client=ctx.client,
        scope_key=ctx.scope_key,
        chat_id=ctx.chat_id,
        message_thread_id=ctx.message_thread_id,
        message_id=ctx.message_id,
        raw_text=ctx.raw_text,
    )

def _handle_dishframed_known_command(ctx: KnownCommandContext) -> bool:
    return _reply_to_known_command(
        ctx,
        DISHFRAMED_RETIRED_MESSAGE,
    )

def _handle_diary_today_known_command(ctx: KnownCommandContext) -> bool:
    return _reply_to_known_command(
        ctx,
        build_diary_today_status(ctx.state, ctx.config, ctx.scope_key),
    )

def _handle_diary_queue_known_command(ctx: KnownCommandContext) -> bool:
    return _reply_to_known_command(
        ctx,
        build_diary_queue_status(ctx.state, ctx.scope_key),
    )

KNOWN_COMMAND_HANDLERS: Dict[str, KnownCommandFn] = {
    "/start": _handle_start_known_command,
    "/status": _handle_status_known_command,
    "/restart": _handle_restart_known_command,
    "/engine": _handle_engine_known_command,
    "/model": _handle_model_known_command,
    "/effort": _handle_effort_known_command,
    "/pi": _handle_pi_known_command,
    "/reset": _handle_reset_known_command,
    "/goal": _handle_goal_known_command,
    "/remember": _handle_remember_known_command,
    "/subgoal": _handle_subgoal_known_command,
    "/dishframed": _handle_dishframed_known_command,
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
    return command_known_routing.handle_known_command(
        state,
        config,
        client,
        scope_key,
        chat_id,
        message_thread_id,
        message_id,
        command,
        raw_text,
        known_command_context_cls=KnownCommandContext,
        help_command_aliases=HELP_COMMAND_ALIASES,
        cancel_command_aliases=CANCEL_COMMAND_ALIASES,
        handle_help_known_command=_handle_help_known_command,
        handle_cancel_known_command=_handle_cancel_known_command,
        known_command_handlers=KNOWN_COMMAND_HANDLERS,
        diary_mode_enabled=diary_mode_enabled,
        diary_command_handlers=DIARY_COMMAND_HANDLERS,
    )

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

def _handle_remember_callback_action(ctx: CallbackActionContext) -> CallbackActionResult:
    return remember_commands.handle_remember_callback_action(
        state=ctx.state,
        scope_key=ctx.scope_key,
        action=ctx.action,
        token=ctx.value,
    )

CALLBACK_ACTION_HANDLERS: Dict[Tuple[str, Optional[str]], CallbackActionFn] = {
    ("engine", None): _handle_engine_callback_action,
    ("provider", "pi"): _handle_pi_provider_callback_action,
    ("model", None): _handle_model_callback_action,
    ("effort", "codex"): _handle_codex_effort_callback_action,
    ("remember", None): _handle_remember_callback_action,
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
