import logging
import subprocess
from typing import Callable, Dict, Optional, Tuple

from telegram_bridge.handler_models import CallbackActionContext, CallbackActionResult

CallbackActionFn = Callable[[CallbackActionContext], CallbackActionResult]


def _answer_callback_query(client, callback_query_id: str, text: str) -> bool:
    client.answer_callback_query(callback_query_id, text=text)
    return True


def _deliver_callback_result(
    client,
    *,
    chat_id: int,
    message_thread_id,
    message_id,
    callback_query_id: str,
    result: CallbackActionResult,
) -> bool:
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


def resolve_callback_action_handler(
    kind: str,
    engine_name: str,
    *,
    callback_action_handlers: Dict[Tuple[str, Optional[str]], CallbackActionFn],
):
    return callback_action_handlers.get((kind, engine_name)) or callback_action_handlers.get((kind, None))


def handle_callback_query(
    state,
    config,
    client,
    update: Dict[str, object],
    *,
    extract_callback_query_context: Callable,
    resolve_callback_action_handler_fn: Callable,
    callback_action_context_cls: Callable,
    callback_action_result_cls: Callable,
    brief_health_error: Callable,
) -> bool:
    message, conversation_scope, message_id, callback_query_id, callback_data = extract_callback_query_context(update)
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
        return _answer_callback_query(client, callback_query_id, "Access denied.")

    parts = callback_data.split("|", 4)
    if len(parts) < 4 or parts[0] != "cfg":
        return _answer_callback_query(client, callback_query_id, "Unknown action.")
    kind = parts[1]
    engine_name = parts[2]
    action = parts[3]
    value = parts[4] if len(parts) > 4 else ""
    ctx = callback_action_context_cls(
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
    handler = resolve_callback_action_handler_fn(kind, engine_name)

    try:
        if handler is not None:
            result = handler(ctx)
        else:
            result = callback_action_result_cls(
                text="Unsupported action.",
                toast_text="Unsupported action.",
            )
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        result = callback_action_result_cls(
            text=f"Action failed.\nError: {brief_health_error(exc)}",
            toast_text="Action failed.",
        )

    return _deliver_callback_result(
        client,
        chat_id=chat_id,
        message_thread_id=message_thread_id,
        message_id=message_id,
        callback_query_id=callback_query_id,
        result=result,
    )
