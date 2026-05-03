import logging
from typing import Dict, Optional

try:
    from .channel_adapter import ChannelAdapter
    from .engine_adapter import EngineAdapter
    from .handler_models import (
        IncomingUpdateContext,
        PreparedUpdateRequest,
        UpdateDispatchRequest,
        UpdateFlowState,
    )
    from .state_store import State
except ImportError:
    from channel_adapter import ChannelAdapter
    from engine_adapter import EngineAdapter
    from handler_models import (
        IncomingUpdateContext,
        PreparedUpdateRequest,
        UpdateDispatchRequest,
        UpdateFlowState,
    )
    from state_store import State


try:
    from . import bridge_deps as handlers
except ImportError:
    import bridge_deps as handlers


def start_dishframed_dispatch(request: UpdateDispatchRequest) -> bool:
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
    handlers.StateRepository(request.state).mark_in_flight_request(request.scope_key, request.message_id)
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
    state_repo = handlers.StateRepository(request.state)
    state_repo.mark_in_flight_request(request.scope_key, request.message_id)
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


def extract_incoming_update_context(update: Dict[str, object]) -> Optional[IncomingUpdateContext]:
    message, conversation_scope, message_id = handlers.extract_chat_context(update)
    if message is None or conversation_scope is None:
        return None
    chat_id = conversation_scope.chat_id
    message_thread_id = conversation_scope.message_thread_id
    scope_key = conversation_scope.scope_key
    from_obj = message.get("from")
    actor_user_id = (
        from_obj.get("id")
        if isinstance(from_obj, dict) and isinstance(from_obj.get("id"), int)
        else None
    )
    update_id = update.get("update_id")
    update_id_int = update_id if isinstance(update_id, int) else None
    chat_obj = message.get("chat")
    chat_type = chat_obj.get("type") if isinstance(chat_obj, dict) else None
    is_private_chat = isinstance(chat_type, str) and chat_type == "private"
    return IncomingUpdateContext(
        update=update,
        message=message,
        chat_id=chat_id,
        message_thread_id=message_thread_id,
        scope_key=scope_key,
        message_id=message_id,
        actor_user_id=actor_user_id,
        is_private_chat=is_private_chat,
        update_id=update_id_int,
    )


def allow_update_chat(
    ctx: IncomingUpdateContext,
    config,
    client: ChannelAdapter,
) -> bool:
    allow_private_unlisted = bool(getattr(config, "allow_private_chats_unlisted", False))
    allow_group_unlisted = bool(getattr(config, "allow_group_chats_unlisted", False))
    if ctx.chat_id in config.allowed_chat_ids:
        return True
    if allow_private_unlisted and ctx.is_private_chat:
        return True
    if allow_group_unlisted and not ctx.is_private_chat:
        return True

    logging.warning("Denied non-allowlisted chat_id=%s", ctx.chat_id)
    handlers.emit_event(
        "bridge.request_denied",
        level=logging.WARNING,
        fields={
            "chat_id": ctx.chat_id,
            "message_id": ctx.message_id,
            "reason": "chat_not_allowlisted",
        },
    )
    if config.channel_plugin != "whatsapp":
        client.send_message(
            ctx.chat_id,
            config.denied_message,
            reply_to_message_id=ctx.message_id,
        )
    return False


def prepare_update_request(
    state: State,
    config,
    client: ChannelAdapter,
    ctx: IncomingUpdateContext,
) -> Optional[PreparedUpdateRequest]:
    prompt_input, photo_file_ids, voice_file_id, document = handlers.extract_prompt_and_media(ctx.message)
    if prompt_input is None and not photo_file_ids and voice_file_id is None and document is None:
        return None

    explicit_photo_file_ids = handlers.extract_message_photo_file_ids(ctx.message)
    if explicit_photo_file_ids:
        handlers.remember_recent_scope_photos(
            state=state,
            scope_key=ctx.scope_key,
            message_id=ctx.message_id,
            photo_file_ids=explicit_photo_file_ids,
        )

    handlers.prewarm_attachment_archive_for_message(
        state=state,
        config=config,
        client=client,
        chat_id=ctx.chat_id,
        message=ctx.message,
    )

    reply_context_prompt = handlers.build_reply_context_prompt(ctx.message)
    telegram_context_prompt = ""
    if handlers.should_include_telegram_context_prompt(
        prompt_input,
        reply_context_prompt,
        getattr(client, "channel_name", "telegram"),
    ):
        telegram_context_prompt = handlers.build_telegram_context_prompt(
            chat_id=ctx.chat_id,
            message_thread_id=ctx.message_thread_id,
            scope_key=ctx.scope_key,
            message_id=ctx.message_id,
            message=ctx.message,
        )

    prefix_result = handlers.apply_required_prefix_gate(
        client=client,
        config=config,
        prompt_input=prompt_input,
        has_reply_context=bool(reply_context_prompt),
        voice_file_id=voice_file_id,
        document=document,
        is_private_chat=ctx.is_private_chat,
        normalize_command=handlers.normalize_command,
        strip_required_prefix=handlers.strip_required_prefix,
    )
    prompt_input = prefix_result.prompt_input
    if prefix_result.ignored:
        handlers.emit_event(
            "bridge.request_ignored",
            fields={
                "chat_id": ctx.chat_id,
                "message_id": ctx.message_id,
                "reason": prefix_result.rejection_reason,
            },
        )
        return None
    if prefix_result.rejection_reason:
        handlers.emit_event(
            "bridge.request_rejected",
            level=logging.WARNING,
            fields={
                "chat_id": ctx.chat_id,
                "message_id": ctx.message_id,
                "reason": prefix_result.rejection_reason,
            },
        )
        client.send_message(
            ctx.chat_id,
            prefix_result.rejection_message or handlers.PREFIX_HELP_MESSAGE,
            reply_to_message_id=ctx.message_id,
        )
        return None

    return PreparedUpdateRequest(
        ctx=ctx,
        prompt_input=prompt_input,
        photo_file_ids=list(photo_file_ids),
        voice_file_id=voice_file_id,
        document=document,
        reply_context_prompt=reply_context_prompt,
        telegram_context_prompt=telegram_context_prompt,
        enforce_voice_prefix_from_transcript=prefix_result.enforce_voice_prefix_from_transcript,
        sender_name=handlers.extract_sender_name(ctx.message),
        command=handlers.normalize_command(prompt_input or ""),
    )


def build_update_flow_state(
    state: State,
    config,
    client: ChannelAdapter,
    engine: Optional[EngineAdapter],
    prepared: PreparedUpdateRequest,
) -> UpdateFlowState:
    return UpdateFlowState(
        state=state,
        config=config,
        client=client,
        engine=engine,
        ctx=prepared.ctx,
        prompt_input=prepared.prompt_input,
        photo_file_ids=list(prepared.photo_file_ids),
        voice_file_id=prepared.voice_file_id,
        document=prepared.document,
        reply_context_prompt=prepared.reply_context_prompt,
        telegram_context_prompt=prepared.telegram_context_prompt,
        enforce_voice_prefix_from_transcript=prepared.enforce_voice_prefix_from_transcript,
        sender_name=prepared.sender_name,
        command=prepared.command,
    )


def maybe_handle_diary_update_flow(flow: UpdateFlowState) -> bool:
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


def prepare_update_dispatch_request(
    flow: UpdateFlowState,
    handle_update_started_at: float,
) -> Optional[UpdateDispatchRequest]:
    keyword_result = handlers.apply_priority_keyword_routing(
        config=flow.config,
        prompt_input=flow.prompt_input,
        command=flow.command,
        chat_id=flow.ctx.chat_id,
    )
    if keyword_result.rejection_reason:
        handlers.emit_event(
            "bridge.request_rejected",
            level=logging.WARNING,
            fields={
                "chat_id": flow.ctx.chat_id,
                "message_id": flow.ctx.message_id,
                "reason": keyword_result.rejection_reason,
            },
        )
        flow.client.send_message(
            flow.ctx.chat_id,
            keyword_result.rejection_message or handlers.PREFIX_HELP_MESSAGE,
            reply_to_message_id=flow.ctx.message_id,
        )
        return None
    flow.prompt_input = keyword_result.prompt_input
    flow.command = keyword_result.command
    if keyword_result.priority_keyword_mode:
        flow.stateless = keyword_result.stateless
        flow.priority_keyword_mode = True
        if keyword_result.route_kind == "youtube_link":
            flow.youtube_route_url = keyword_result.route_value
        handlers.emit_event(
            keyword_result.routed_event or "bridge.keyword_routed",
            fields={"chat_id": flow.ctx.chat_id, "message_id": flow.ctx.message_id},
        )

    if flow.prompt_input:
        handlers.maybe_process_voice_alias_learning_confirmation(
            state=flow.state,
            config=flow.config,
            client=flow.client,
            chat_id=flow.ctx.chat_id,
            message_id=flow.ctx.message_id,
            prompt_input=flow.prompt_input,
            command=flow.command,
            priority_keyword_mode=flow.priority_keyword_mode,
            photo_file_id=flow.photo_file_ids[0] if flow.photo_file_ids else None,
            photo_file_ids=flow.photo_file_ids,
            voice_file_id=flow.voice_file_id,
            document=flow.document,
        )

    memory_engine = flow.state.memory_engine if isinstance(flow.state.memory_engine, handlers.MemoryEngine) else None
    memory_channel = getattr(flow.client, "channel_name", "telegram")
    if memory_engine is not None and flow.prompt_input and not flow.priority_keyword_mode:
        cmd_result = handlers.handle_memory_command(
            engine=memory_engine,
            conversation_key=handlers.resolve_memory_conversation_key(
                flow.config,
                memory_channel,
                flow.ctx.scope_key,
            ),
            text=flow.prompt_input,
        )
        if cmd_result.handled:
            if cmd_result.response:
                flow.client.send_message(
                    flow.ctx.chat_id,
                    cmd_result.response,
                    reply_to_message_id=flow.ctx.message_id,
                )
            if cmd_result.run_prompt is None:
                handlers.emit_event(
                    "bridge.command_handled",
                    fields={
                        "chat_id": flow.ctx.chat_id,
                        "message_id": flow.ctx.message_id,
                        "command": flow.command or "",
                    },
                )
                return None
            flow.prompt_input = cmd_result.run_prompt
            flow.stateless = cmd_result.stateless
            flow.command = None

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
        return None

    if memory_engine is not None and flow.prompt_input and not flow.priority_keyword_mode and not flow.stateless:
        recall_response = handlers.handle_natural_language_memory_query(
            memory_engine,
            handlers.resolve_memory_conversation_key(flow.config, memory_channel, flow.ctx.scope_key),
            flow.prompt_input,
        )
        if recall_response:
            flow.client.send_message(
                flow.ctx.chat_id,
                recall_response,
                reply_to_message_id=flow.ctx.message_id,
            )
            handlers.emit_event(
                "bridge.command_handled",
                fields={
                    "chat_id": flow.ctx.chat_id,
                    "message_id": flow.ctx.message_id,
                    "command": "natural_language_memory_recall",
                },
            )
            return None

    prompt = (flow.prompt_input or "").strip()
    raw_prompt = prompt
    prompt_context_parts = []
    if flow.telegram_context_prompt:
        prompt_context_parts.append(flow.telegram_context_prompt)
    if flow.reply_context_prompt:
        prompt_context_parts.append(flow.reply_context_prompt)
    if prompt_context_parts:
        if prompt:
            prompt_context_parts.append("Current User Message:\n" f"{prompt}")
        prompt = "\n\n".join(prompt_context_parts)
    if not prompt and not flow.voice_file_id and flow.document is None:
        return None

    if prompt and len(prompt) > flow.config.max_input_chars:
        if prompt_context_parts and raw_prompt and len(raw_prompt) <= flow.config.max_input_chars:
            handlers.emit_event(
                "bridge.telegram_context_omitted",
                level=logging.WARNING,
                fields={
                    "chat_id": flow.ctx.chat_id,
                    "message_id": flow.ctx.message_id,
                    "reason": "max_input_chars",
                },
            )
            prompt = raw_prompt
        else:
            actual_length = (
                len(raw_prompt)
                if raw_prompt and len(raw_prompt) > flow.config.max_input_chars
                else len(prompt)
            )
            handlers.emit_event(
                "bridge.request_rejected",
                level=logging.WARNING,
                fields={
                    "chat_id": flow.ctx.chat_id,
                    "message_id": flow.ctx.message_id,
                    "reason": "input_too_long",
                },
            )
            handlers.send_input_too_long(
                client=flow.client,
                chat_id=flow.ctx.chat_id,
                message_id=flow.ctx.message_id,
                actual_length=actual_length,
                max_input_chars=flow.config.max_input_chars,
            )
            return None

    if prompt and len(prompt) > flow.config.max_input_chars:
        handlers.emit_event(
            "bridge.request_rejected",
            level=logging.WARNING,
            fields={
                "chat_id": flow.ctx.chat_id,
                "message_id": flow.ctx.message_id,
                "reason": "input_too_long",
            },
        )
        handlers.send_input_too_long(
            client=flow.client,
            chat_id=flow.ctx.chat_id,
            message_id=flow.ctx.message_id,
            actual_length=len(prompt),
            max_input_chars=flow.config.max_input_chars,
        )
        return None

    if handlers.is_rate_limited(flow.state, flow.config, flow.ctx.scope_key):
        handlers.emit_event(
            "bridge.request_rejected",
            level=logging.WARNING,
            fields={
                "chat_id": flow.ctx.chat_id,
                "message_id": flow.ctx.message_id,
                "reason": "rate_limited",
            },
        )
        flow.client.send_message(
            flow.ctx.chat_id,
            handlers.RATE_LIMIT_MESSAGE,
            reply_to_message_id=flow.ctx.message_id,
        )
        return None

    return UpdateDispatchRequest(
        state=flow.state,
        config=flow.config,
        client=flow.client,
        engine=flow.engine,
        scope_key=flow.ctx.scope_key,
        chat_id=flow.ctx.chat_id,
        message_thread_id=flow.ctx.message_thread_id,
        message_id=flow.ctx.message_id,
        prompt=prompt,
        raw_prompt=raw_prompt,
        photo_file_ids=list(flow.photo_file_ids),
        voice_file_id=flow.voice_file_id,
        document=flow.document,
        actor_user_id=flow.ctx.actor_user_id,
        sender_name=flow.sender_name,
        stateless=flow.stateless,
        enforce_voice_prefix_from_transcript=flow.enforce_voice_prefix_from_transcript,
        youtube_route_url=flow.youtube_route_url,
        handle_update_started_at=handle_update_started_at,
    )
