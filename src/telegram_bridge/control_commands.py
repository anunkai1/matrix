import logging
from typing import Optional

from telegram_bridge.channel_adapter import ChannelAdapter
from telegram_bridge.engine_adapter import PiEngineAdapter
from telegram_bridge.session_manager import request_safe_restart, trigger_restart_async
from telegram_bridge.state_store import State, StateRepository
from telegram_bridge.structured_logging import emit_event
from telegram_bridge import response_delivery
from telegram_bridge import prompt_execution

CANCEL_REQUESTED_MESSAGE = "Cancel requested. Stopping current request."
CANCEL_ALREADY_REQUESTED_MESSAGE = (
    "Cancel is already in progress. Waiting for current request to stop."
)
CANCEL_NO_ACTIVE_MESSAGE = "No active request to cancel."

request_chat_cancel = response_delivery.request_chat_cancel

def handle_reset_command(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
) -> None:
    state_repo = StateRepository(state)
    removed_thread = state_repo.clear_thread_id(scope_key)
    removed_worker = state_repo.clear_worker_session(scope_key) if config.persistent_workers_enabled else False
    try:
        PiEngineAdapter.clear_scope_session_files(config, scope_key)
    except Exception:
        logging.exception("Failed to clear Pi session files for scope=%s", scope_key)
    if removed_thread or removed_worker:
        client.send_message(
            chat_id,
            "Context reset. Your next message starts a new conversation.",
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return
    client.send_message(
        chat_id,
        "No saved context was found for this chat.",
        reply_to_message_id=message_id,
        message_thread_id=message_thread_id,
    )

def handle_restart_command(
    state: State,
    client: ChannelAdapter,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
) -> None:
    status, busy_count = request_safe_restart(state, chat_id, message_thread_id, message_id)
    emit_event(
        "bridge.restart_requested",
        fields={
            "chat_id": chat_id,
            "message_id": message_id,
            "status": status,
            "busy_count": busy_count,
        },
    )
    if status == "in_progress":
        client.send_message(
            chat_id,
            "Restart is already in progress.",
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return
    if status == "already_queued":
        client.send_message(
            chat_id,
            "Restart is already queued and will run after current work completes.",
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return
    if status == "queued":
        client.send_message(
            chat_id,
            f"Safe restart queued. Waiting for {busy_count} active request(s) to finish.",
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return

    client.send_message(
        chat_id,
        "No active request. Restarting bridge now.",
        reply_to_message_id=message_id,
        message_thread_id=message_thread_id,
    )
    trigger_restart_async(state, client, chat_id, message_thread_id, message_id)

def handle_cancel_command(
    state: State,
    client: ChannelAdapter,
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
) -> None:
    status = request_chat_cancel(state, scope_key)
    emit_event(
        "bridge.cancel_requested",
        fields={"chat_id": chat_id, "message_id": message_id, "status": status},
    )
    if status == "requested":
        client.send_message(
            chat_id,
            CANCEL_REQUESTED_MESSAGE,
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return
    if status == "already_requested":
        client.send_message(
            chat_id,
            CANCEL_ALREADY_REQUESTED_MESSAGE,
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return
    if status == "unavailable":
        client.send_message(
            chat_id,
            "Active request cannot be canceled at this stage. Please wait a few seconds and retry.",
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return
    client.send_message(
        chat_id,
        CANCEL_NO_ACTIVE_MESSAGE,
        reply_to_message_id=message_id,
        message_thread_id=message_thread_id,
    )
