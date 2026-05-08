import logging
from telegram_bridge.handler_models import UpdateDispatchRequest, UpdateFlowState
from telegram_bridge.update_preparation import (
    allow_update_chat,
    build_update_flow_state,
    extract_incoming_update_context,
    prepare_update_dispatch_request,
    prepare_update_request,
)


def _handlers():
    import telegram_bridge.handlers as handlers

    return handlers


def _state_store():
    import telegram_bridge.state_store as state_store

    return state_store

def start_dishframed_dispatch(request: UpdateDispatchRequest) -> bool:
    handlers = _handlers()
    photo_file_ids = list(request.photo_file_ids)
    if not photo_file_ids:
        photo_file_ids = handlers.get_recent_scope_photos(request.state, request.scope_key)
    if not photo_file_ids:
        request.client.send_message(
            request.chat_id,
            handlers.DISHFRAMED_USAGE_MESSAGE,
            reply_to_message_id=request.message_id,
            message_thread_id=request.message_thread_id,
        )
        return False
    if not handlers.mark_busy(request.state, request.scope_key):
        handlers.emit_event(
            "bridge.request_rejected",
            level=logging.WARNING,
            fields={
                "chat_id": request.chat_id,
                "message_id": request.message_id,
                "reason": "chat_busy",
            },
        )
        request.client.send_message(
            request.chat_id,
            request.config.busy_message,
            reply_to_message_id=request.message_id,
            message_thread_id=request.message_thread_id,
        )
        return False
    cancel_event = handlers.register_cancel_event(request.state, request.scope_key)
    _state_store().mark_in_flight_request(request.state, request.scope_key, request.message_id)
    handlers.emit_event(
        "bridge.request_accepted",
        fields={
            "chat_id": request.chat_id,
            "message_id": request.message_id,
            "scope_key": request.scope_key,
            "has_photo": True,
            "has_voice": False,
            "has_document": False,
            "stateless": True,
            "route": "dishframed",
        },
    )
    handlers.start_dishframed_worker(
        state=request.state,
        config=request.config,
        client=request.client,
        scope_key=request.scope_key,
        chat_id=request.chat_id,
        message_thread_id=request.message_thread_id,
        message_id=request.message_id,
        photo_file_ids=photo_file_ids,
        cancel_event=cancel_event,
    )
    handlers.emit_event(
        "bridge.worker_started",
        fields={"chat_id": request.chat_id, "message_id": request.message_id, "route": "dishframed"},
    )
    return True

def start_standard_dispatch(request: UpdateDispatchRequest) -> bool:
    handlers = _handlers()
    try:
        active_engine = handlers.resolve_engine_for_scope(
            request.state,
            request.config,
            request.scope_key,
            request.engine,
        )
    except Exception as exc:
        logging.exception("Failed to resolve engine for scope=%s", request.scope_key)
        request.client.send_message(
            request.chat_id,
            f"Engine selection failed: {exc}",
            reply_to_message_id=request.message_id,
            message_thread_id=request.message_thread_id,
        )
        return False

    if not request.stateless:
        if not handlers.ensure_chat_worker_session(
            request.state,
            request.config,
            request.client,
            request.scope_key,
            request.chat_id,
            request.message_thread_id,
            request.message_id,
        ):
            handlers.emit_event(
                "bridge.request_rejected",
                level=logging.WARNING,
                fields={
                    "chat_id": request.chat_id,
                    "message_id": request.message_id,
                    "reason": "worker_capacity",
                },
            )
            return False

    if not handlers.mark_busy(request.state, request.scope_key):
        handlers.emit_event(
            "bridge.request_rejected",
            level=logging.WARNING,
            fields={
                "chat_id": request.chat_id,
                "message_id": request.message_id,
                "reason": "chat_busy",
            },
        )
        request.client.send_message(
            request.chat_id,
            request.config.busy_message,
            reply_to_message_id=request.message_id,
        )
        return False

    cancel_event = handlers.register_cancel_event(request.state, request.scope_key)
    _state_store().mark_in_flight_request(request.state, request.scope_key, request.message_id)
    handlers.emit_event(
        "bridge.request_accepted",
        fields={
            "chat_id": request.chat_id,
            "message_id": request.message_id,
            "scope_key": request.scope_key,
            "has_photo": bool(request.photo_file_ids),
            "has_voice": bool(request.voice_file_id),
            "has_document": request.document is not None,
            "stateless": request.stateless,
        },
    )
    if request.youtube_route_url:
        handlers.start_youtube_worker(
            state=request.state,
            config=request.config,
            client=request.client,
            engine=active_engine,
            scope_key=request.scope_key,
            chat_id=request.chat_id,
            message_thread_id=request.message_thread_id,
            message_id=request.message_id,
            request_text=request.raw_prompt,
            youtube_url=request.youtube_route_url,
            actor_user_id=request.actor_user_id,
            cancel_event=cancel_event,
        )
    else:
        handlers.start_message_worker(
            state=request.state,
            config=request.config,
            client=request.client,
            engine=active_engine,
            scope_key=request.scope_key,
            chat_id=request.chat_id,
            message_thread_id=request.message_thread_id,
            message_id=request.message_id,
            prompt=request.prompt,
            photo_file_id=request.photo_file_ids[0] if request.photo_file_ids else None,
            photo_file_ids=request.photo_file_ids,
            voice_file_id=request.voice_file_id,
            document=request.document,
            cancel_event=cancel_event,
            stateless=request.stateless,
            sender_name=request.sender_name,
            enforce_voice_prefix_from_transcript=request.enforce_voice_prefix_from_transcript,
            actor_user_id=request.actor_user_id,
        )
    handlers.emit_event(
        "bridge.worker_started",
        fields={"chat_id": request.chat_id, "message_id": request.message_id},
    )
    if request.handle_update_started_at is not None:
        handlers.emit_phase_timing(
            chat_id=request.chat_id,
            message_id=request.message_id,
            phase="handle_update_pre_worker",
            started_at_monotonic=request.handle_update_started_at,
            routed_youtube=bool(request.youtube_route_url),
            stateless=request.stateless,
        )
    return True

def maybe_handle_diary_update_flow(flow: UpdateFlowState) -> bool:
    handlers = _handlers()
    if not handlers.diary_mode_enabled(flow.config):
        return False
    if handlers.handle_known_command(
        flow.state,
        flow.config,
        flow.client,
        flow.ctx.scope_key,
        flow.ctx.chat_id,
        flow.ctx.message_thread_id,
        flow.ctx.message_id,
        flow.command,
        flow.prompt_input or "",
    ):
        handlers.emit_event(
            "bridge.command_handled",
            fields={
                "chat_id": flow.ctx.chat_id,
                "message_id": flow.ctx.message_id,
                "command": flow.command or "",
            },
        )
        return True
    handlers.queue_diary_capture(
        state=flow.state,
        config=flow.config,
        client=flow.client,
        scope_key=flow.ctx.scope_key,
        chat_id=flow.ctx.chat_id,
        message_thread_id=flow.ctx.message_thread_id,
        message_id=flow.ctx.message_id,
        sender_name=flow.sender_name,
        actor_user_id=flow.ctx.actor_user_id,
        message=flow.ctx.message,
    )
    return True
