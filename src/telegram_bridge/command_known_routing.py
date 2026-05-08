from typing import Callable, Dict, Optional

from telegram_bridge.handler_models import KnownCommandContext

KnownCommandFn = Callable[[KnownCommandContext], bool]


def handle_known_command(
    state,
    config,
    client,
    scope_key: str,
    chat_id: int,
    message_thread_id,
    message_id,
    command: Optional[str],
    raw_text: str,
    *,
    known_command_context_cls: Callable,
    help_command_aliases,
    cancel_command_aliases,
    handle_help_known_command: Callable,
    handle_cancel_known_command: Callable,
    known_command_handlers: Dict[str, KnownCommandFn],
    diary_mode_enabled: Callable,
    diary_command_handlers: Dict[str, KnownCommandFn],
) -> bool:
    if command is None:
        return False

    ctx = known_command_context_cls(
        state=state,
        config=config,
        client=client,
        scope_key=scope_key,
        chat_id=chat_id,
        message_thread_id=message_thread_id,
        message_id=message_id,
        raw_text=raw_text,
    )

    if command in help_command_aliases:
        return handle_help_known_command(ctx)
    if command in cancel_command_aliases:
        return handle_cancel_known_command(ctx)

    handler = known_command_handlers.get(command)
    if handler is not None:
        return handler(ctx)

    if diary_mode_enabled(config):
        diary_handler = diary_command_handlers.get(command)
        if diary_handler is not None:
            return diary_handler(ctx)

    return False
