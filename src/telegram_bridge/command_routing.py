import importlib
import logging
import subprocess
from typing import Dict, Optional, Tuple

try:
    from .channel_adapter import ChannelAdapter
    from .handler_models import CallbackActionContext, CallbackActionResult, KnownCommandContext
    from .state_store import State
except ImportError:
    from channel_adapter import ChannelAdapter
    from handler_models import CallbackActionContext, CallbackActionResult, KnownCommandContext
    from state_store import State


def _handlers_module():
    if __package__:
        return importlib.import_module(".handlers", __package__)
    return importlib.import_module("handlers")


def _handle_start_known_command(ctx: KnownCommandContext) -> bool:
    handlers = _handlers_module()
    ctx.client.send_message(
        ctx.chat_id,
        handlers.start_command_message(ctx.config),
        reply_to_message_id=ctx.message_id,
    )
    return True


def _handle_help_known_command(ctx: KnownCommandContext) -> bool:
    handlers = _handlers_module()
    ctx.client.send_message(
        ctx.chat_id,
        handlers.build_help_text(ctx.config),
        reply_to_message_id=ctx.message_id,
    )
    return True


def _handle_status_known_command(ctx: KnownCommandContext) -> bool:
    handlers = _handlers_module()
    ctx.client.send_message(
        ctx.chat_id,
        handlers.build_status_text(ctx.state, ctx.config, chat_id=ctx.chat_id, scope_key=ctx.scope_key),
        reply_to_message_id=ctx.message_id,
        message_thread_id=ctx.message_thread_id,
    )
    return True


def _handle_restart_known_command(ctx: KnownCommandContext) -> bool:
    handlers = _handlers_module()
    handlers.handle_restart_command(
        ctx.state,
        ctx.client,
        ctx.chat_id,
        ctx.message_thread_id,
        ctx.message_id,
    )
    return True


def _handle_cancel_known_command(ctx: KnownCommandContext) -> bool:
    handlers = _handlers_module()
    handlers.handle_cancel_command(
        ctx.state,
        ctx.client,
        ctx.scope_key,
        ctx.chat_id,
        ctx.message_thread_id,
        ctx.message_id,
    )
    return True


def _handle_engine_known_command(ctx: KnownCommandContext) -> bool:
    handlers = _handlers_module()
    return handlers.handle_engine_command(
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
    handlers = _handlers_module()
    return handlers.handle_model_command(
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
    handlers = _handlers_module()
    return handlers.handle_effort_command(
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
    handlers = _handlers_module()
    return handlers.handle_pi_command(
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
    handlers = _handlers_module()
    handlers.handle_reset_command(
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
    handlers = _handlers_module()
    return handlers.handle_voice_alias_command(
        state=ctx.state,
        config=ctx.config,
        client=ctx.client,
        chat_id=ctx.chat_id,
        message_id=ctx.message_id,
        raw_text=ctx.raw_text,
    )


def _handle_diary_today_known_command(ctx: KnownCommandContext) -> bool:
    handlers = _handlers_module()
    ctx.client.send_message(
        ctx.chat_id,
        handlers.build_diary_today_status(ctx.state, ctx.config, ctx.scope_key),
        reply_to_message_id=ctx.message_id,
    )
    return True


def _handle_diary_queue_known_command(ctx: KnownCommandContext) -> bool:
    handlers = _handlers_module()
    ctx.client.send_message(
        ctx.chat_id,
        handlers.build_diary_queue_status(ctx.state, ctx.scope_key),
        reply_to_message_id=ctx.message_id,
    )
    return True


KNOWN_COMMAND_HANDLERS = {
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

DIARY_COMMAND_HANDLERS = {
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
    handlers = _handlers_module()
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

    if command in handlers.HELP_COMMAND_ALIASES:
        return _handle_help_known_command(ctx)
    if command in handlers.CANCEL_COMMAND_ALIASES:
        return _handle_cancel_known_command(ctx)

    handler = KNOWN_COMMAND_HANDLERS.get(command)
    if handler is not None:
        return handler(ctx)

    if handlers.diary_mode_enabled(config):
        diary_handler = DIARY_COMMAND_HANDLERS.get(command)
        if diary_handler is not None:
            return diary_handler(ctx)

    return False


def _handle_engine_callback_action(ctx: CallbackActionContext) -> CallbackActionResult:
    handlers = _handlers_module()
    if ctx.action == "reset":
        text = handlers._reset_engine_for_scope(ctx.state, ctx.config, ctx.scope_key)
    elif ctx.action == "set":
        text = handlers._set_engine_for_scope(ctx.state, ctx.config, ctx.scope_key, ctx.engine_name)
    else:
        text = handlers.build_engine_status_text(ctx.state, ctx.config, ctx.scope_key)
    return CallbackActionResult(
        text=text,
        reply_markup=handlers._build_engine_picker_markup(ctx.state, ctx.config, ctx.scope_key),
    )


def _handle_pi_provider_callback_action(ctx: CallbackActionContext) -> CallbackActionResult:
    handlers = _handlers_module()
    if ctx.action == "set":
        text = handlers._set_pi_provider_for_scope(ctx.state, ctx.config, ctx.scope_key, ctx.value)
        reply_markup = handlers._build_engine_picker_markup(ctx.state, ctx.config, ctx.scope_key)
    else:
        text = handlers.build_pi_providers_text(ctx.state, ctx.config, ctx.scope_key)
        reply_markup = handlers._build_provider_picker_markup(ctx.state, ctx.config, ctx.scope_key)
    return CallbackActionResult(text=text, reply_markup=reply_markup)


def _handle_model_callback_action(ctx: CallbackActionContext) -> CallbackActionResult:
    handlers = _handlers_module()
    requested_page = handlers._parse_page_index(ctx.value)
    if ctx.action == "reset":
        text = handlers._reset_model_for_scope(ctx.state, ctx.config, ctx.scope_key, ctx.engine_name)
    elif ctx.action == "set":
        if ctx.engine_name == "codex":
            text = handlers._set_codex_model_for_scope(ctx.state, ctx.config, ctx.scope_key, ctx.value)
        elif ctx.engine_name == "pi":
            text = handlers._set_pi_model_for_scope(ctx.state, ctx.config, ctx.scope_key, ctx.value)
        else:
            text = handlers.build_model_status_text(ctx.state, ctx.config, ctx.scope_key)
    else:
        text = handlers.build_model_status_text(ctx.state, ctx.config, ctx.scope_key)
    return CallbackActionResult(
        text=text,
        reply_markup=handlers._build_model_picker_markup(
            ctx.state,
            ctx.config,
            ctx.scope_key,
            page_index=requested_page,
        ),
    )


def _handle_codex_effort_callback_action(ctx: CallbackActionContext) -> CallbackActionResult:
    handlers = _handlers_module()
    if ctx.action == "reset":
        text = handlers._reset_codex_effort_for_scope(ctx.state, ctx.config, ctx.scope_key)
    elif ctx.action == "set":
        text = handlers._set_codex_effort_for_scope(ctx.state, ctx.config, ctx.scope_key, ctx.value)
    else:
        text = handlers.build_effort_status_text(ctx.state, ctx.config, ctx.scope_key)
    return CallbackActionResult(
        text=text,
        reply_markup=handlers._build_effort_picker_markup(ctx.state, ctx.config, ctx.scope_key),
    )


CALLBACK_ACTION_HANDLERS: Dict[Tuple[str, Optional[str]], object] = {
    ("engine", None): _handle_engine_callback_action,
    ("provider", "pi"): _handle_pi_provider_callback_action,
    ("model", None): _handle_model_callback_action,
    ("effort", "codex"): _handle_codex_effort_callback_action,
}


def _resolve_callback_action_handler(
    kind: str,
    engine_name: str,
):
    return CALLBACK_ACTION_HANDLERS.get((kind, engine_name)) or CALLBACK_ACTION_HANDLERS.get((kind, None))


def handle_callback_query(
    state: State,
    config,
    client: ChannelAdapter,
    update: Dict[str, object],
) -> bool:
    handlers = _handlers_module()
    message, conversation_scope, message_id, callback_query_id, callback_data = handlers.extract_callback_query_context(update)
    if message is None or conversation_scope is None or not callback_query_id or not callback_data:
        return False
    chat_id = conversation_scope.chat_id
    message_thread_id = conversation_scope.message_thread_id
    scope_key = conversation_scope.scope_key
    chat_obj = message.get("chat")
    chat_type = chat_obj.get("type") if isinstance(chat_obj, dict) else None
    is_private_chat = isinstance(chat_type, str) and chat_type == "private"
    allow_private_unlisted = bool(getattr(config, "allow_private_chats_unlisted", False))
    allow_group_unlisted = bool(getattr(config, "allow_group_chats_unlisted", False))
    if chat_id not in config.allowed_chat_ids and not (
        (allow_private_unlisted and is_private_chat) or (allow_group_unlisted and not is_private_chat)
    ):
        client.answer_callback_query(callback_query_id, text="Access denied.")
        return True

    parts = callback_data.split("|", 4)
    if len(parts) < 4 or parts[0] != "cfg":
        client.answer_callback_query(callback_query_id, text="Unknown action.")
        return True
    kind = parts[1]
    engine_name = parts[2]
    action = parts[3]
    value = parts[4] if len(parts) > 4 else ""
    ctx = CallbackActionContext(
        state=state,
        config=config,
        client=client,
        scope_key=scope_key,
        chat_id=chat_id,
        message_thread_id=message_thread_id,
        message_id=message_id,
        callback_query_id=callback_query_id,
        kind=kind,
        engine_name=engine_name,
        action=action,
        value=value,
    )
    handler = _resolve_callback_action_handler(kind, engine_name)

    try:
        if handler is not None:
            result = handler(ctx)
        else:
            result = CallbackActionResult(
                text="Unsupported action.",
                toast_text="Unsupported action.",
            )
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        result = CallbackActionResult(
            text=f"Action failed.\nError: {handlers._brief_health_error(exc)}",
            toast_text="Action failed.",
        )

    client.answer_callback_query(callback_query_id, text=result.toast_text)
    if isinstance(message_id, int):
        try:
            client.edit_message(chat_id, message_id, result.text, reply_markup=result.reply_markup)
            return True
        except Exception:
            logging.exception("Failed to edit callback menu message for chat_id=%s", chat_id)
    client.send_message(
        chat_id,
        result.text,
        reply_to_message_id=message_id,
        message_thread_id=message_thread_id,
        reply_markup=result.reply_markup,
    )
    return True
