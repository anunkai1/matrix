import logging
from typing import Dict, Optional

from telegram_bridge.channel_adapter import ChannelAdapter
from telegram_bridge.engine_adapter import EngineAdapter
from telegram_bridge.handler_common import RATE_LIMIT_MESSAGE, extract_chat_context, normalize_command, strip_required_prefix
from telegram_bridge.handler_models import (
    IncomingUpdateContext,
    PreparedUpdateRequest,
    UpdateDispatchRequest,
    UpdateFlowState,
)
from telegram_bridge.message_inputs import (
    build_reply_context_prompt,
    build_telegram_context_prompt,
    extract_message_photo_file_ids,
    extract_prompt_and_media,
    extract_sender_name,
    normalize_telegram_context_injection_policy,
    remember_recent_scope_photos,
    should_include_delivery_guardrails,
    should_include_telegram_context_prompt,
)
from telegram_bridge.prompt_inputs import prewarm_attachment_archive_for_message
from telegram_bridge.response_delivery import send_input_too_long, send_prompt_trimmed_warning
from telegram_bridge.runtime_profile import PREFIX_HELP_MESSAGE
from telegram_bridge.runtime_routing import apply_priority_keyword_routing, apply_required_prefix_gate
from telegram_bridge.session_manager import is_rate_limited
from telegram_bridge.state_store import State, get_chat_engine, get_thread_id
from telegram_bridge.structured_logging import emit_event
from telegram_bridge.command_routing import handle_known_command
from telegram_bridge.voice_alias_commands import maybe_process_voice_alias_learning_confirmation
from telegram_bridge.engine_catalog import configured_default_engine, normalize_engine_name


def _core_config(config):
    return getattr(config, "core", config)


def _session_config(config):
    return getattr(config, "session", config)


def _identity_config(config):
    return getattr(config, "identity", config)


def _build_current_sender_prompt(sender_name: str) -> str:
    normalized = (sender_name or "").strip()
    if not normalized or normalized == "Telegram User":
        return ""
    return f"Author: {normalized}"


def _context_injection_policy_for_scope(state: State, config, scope_key: str) -> str:
    configured_policy = normalize_telegram_context_injection_policy(
        getattr(config, "telegram_context_injection_policy", ""),
        default="",
    )
    if configured_policy:
        return configured_policy
    selected_engine = get_chat_engine(state, scope_key) or configured_default_engine(config)
    if normalize_engine_name(selected_engine) == "codex":
        return "continuation_skip"
    return "always"


def _reject_input_too_long(flow: UpdateFlowState, actual_length: int) -> None:
    emit_event(
        "bridge.request_rejected",
        level=logging.WARNING,
        fields={
            "chat_id": flow.ctx.chat_id,
            "message_id": flow.ctx.message_id,
            "reason": "input_too_long",
        },
    )
    send_input_too_long(
        client=flow.client,
        chat_id=flow.ctx.chat_id,
        message_id=flow.ctx.message_id,
        actual_length=actual_length,
        max_input_chars=flow.config.max_input_chars,
    )


def _build_prompt_with_diagnostics(
    *,
    raw_prompt: str,
    telegram_context_prompt: str,
    reply_context_prompt: str,
    sender_name: str,
    max_input_chars: int,
) -> Dict[str, object]:
    current_sender_prompt = _build_current_sender_prompt(sender_name)
    user_message_label = "Current User Message:\n" if raw_prompt else ""
    wrapper_breaks = 0
    if telegram_context_prompt:
        wrapper_breaks += 2
    if reply_context_prompt and (telegram_context_prompt or current_sender_prompt):
        wrapper_breaks += 2
    if current_sender_prompt and (telegram_context_prompt or reply_context_prompt):
        wrapper_breaks += 2
    if user_message_label and (telegram_context_prompt or reply_context_prompt or current_sender_prompt):
        wrapper_breaks += 2
    wrapper_overhead = len(user_message_label) + wrapper_breaks

    original_prompt_parts = []
    if telegram_context_prompt:
        original_prompt_parts.append(telegram_context_prompt)
    if reply_context_prompt:
        original_prompt_parts.append(reply_context_prompt)
    if current_sender_prompt:
        original_prompt_parts.append(current_sender_prompt)
    if raw_prompt:
        original_prompt_parts.append(f"{user_message_label}{raw_prompt}")
    original_prompt = "\n\n".join(original_prompt_parts).strip()
    original_length = len(original_prompt)

    dropped_sections: list[str] = []
    trimmed_user_chars = 0
    final_reply_context = reply_context_prompt
    final_sender_prompt = current_sender_prompt
    final_raw_prompt = raw_prompt

    def assemble_prompt(*, reply_context: str, sender_prompt: str, user_prompt: str) -> str:
        parts = []
        if telegram_context_prompt:
            parts.append(telegram_context_prompt)
        if reply_context:
            parts.append(reply_context)
        if sender_prompt:
            parts.append(sender_prompt)
        if user_prompt:
            parts.append(f"{user_message_label}{user_prompt}")
        return "\n\n".join(parts).strip()

    prompt = assemble_prompt(
        reply_context=final_reply_context,
        sender_prompt=final_sender_prompt,
        user_prompt=final_raw_prompt,
    )
    if len(prompt) > max_input_chars and final_sender_prompt:
        dropped_sections.append("current_sender")
        final_sender_prompt = ""
        prompt = assemble_prompt(
            reply_context=final_reply_context,
            sender_prompt=final_sender_prompt,
            user_prompt=final_raw_prompt,
        )
    if len(prompt) > max_input_chars and final_reply_context:
        dropped_sections.append("reply_context")
        final_reply_context = ""
        prompt = assemble_prompt(
            reply_context=final_reply_context,
            sender_prompt=final_sender_prompt,
            user_prompt=final_raw_prompt,
        )
    if len(prompt) > max_input_chars and final_raw_prompt:
        base_prompt = assemble_prompt(
            reply_context=final_reply_context,
            sender_prompt=final_sender_prompt,
            user_prompt="",
        )
        available_for_user = max_input_chars - len(base_prompt)
        if base_prompt:
            available_for_user -= 2
        available_for_user -= len(user_message_label)
        if available_for_user < 1:
            available_for_user = 0
        if len(final_raw_prompt) > available_for_user:
            trimmed_user_chars = len(final_raw_prompt) - available_for_user
            final_raw_prompt = final_raw_prompt[:available_for_user]
            prompt = assemble_prompt(
                reply_context=final_reply_context,
                sender_prompt=final_sender_prompt,
                user_prompt=final_raw_prompt,
            )
    final_length = len(prompt)
    return {
        "prompt": prompt,
        "original_length": original_length,
        "final_length": final_length,
        "telegram_context_length": len(telegram_context_prompt or ""),
        "reply_context_length": len(reply_context_prompt or ""),
        "sender_prompt_length": len(current_sender_prompt or ""),
        "raw_prompt_length": len(raw_prompt or ""),
        "user_message_label_length": len(user_message_label),
        "wrapper_overhead": wrapper_overhead,
        "dropped_sections": dropped_sections,
        "trimmed_user_chars": trimmed_user_chars,
        "trimmed": bool(dropped_sections or trimmed_user_chars),
        "trimmed_reply_context_length": len(final_reply_context or ""),
        "trimmed_sender_prompt_length": len(final_sender_prompt or ""),
        "trimmed_raw_prompt_length": len(final_raw_prompt or ""),
    }


def extract_incoming_update_context(update: Dict[str, object]) -> Optional[IncomingUpdateContext]:
    message, conversation_scope, message_id = extract_chat_context(update)
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
    core = _core_config(config)
    session = _session_config(config)
    identity = _identity_config(config)
    allow_private_unlisted = bool(getattr(session, "allow_private_chats_unlisted", False))
    allow_group_unlisted = bool(getattr(session, "allow_group_chats_unlisted", False))
    if ctx.chat_id in core.allowed_chat_ids:
        return True
    if allow_private_unlisted and ctx.is_private_chat:
        return True
    if allow_group_unlisted and not ctx.is_private_chat:
        return True

    logging.warning("Denied non-allowlisted chat_id=%s", ctx.chat_id)
    emit_event(
        "bridge.request_denied",
        level=logging.WARNING,
        fields={
            "chat_id": ctx.chat_id,
            "message_id": ctx.message_id,
            "reason": "chat_not_allowlisted",
        },
    )
    if identity.channel_plugin != "whatsapp":
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
    prompt_input, photo_file_ids, voice_file_id, document = extract_prompt_and_media(ctx.message)
    if prompt_input is None and not photo_file_ids and voice_file_id is None and document is None:
        return None

    explicit_photo_file_ids = extract_message_photo_file_ids(ctx.message)
    if explicit_photo_file_ids:
        remember_recent_scope_photos(
            state=state,
            scope_key=ctx.scope_key,
            message_id=ctx.message_id,
            photo_file_ids=explicit_photo_file_ids,
        )

    prewarm_attachment_archive_for_message(
        state=state,
        config=config,
        client=client,
        chat_id=ctx.chat_id,
        message=ctx.message,
    )

    reply_context_prompt = build_reply_context_prompt(ctx.message)
    telegram_context_prompt = ""
    context_injection_policy = _context_injection_policy_for_scope(
        state,
        config,
        ctx.scope_key,
    )
    has_existing_thread = bool(get_thread_id(state, ctx.scope_key))
    has_request_payload = bool(
        (prompt_input or "").strip()
        or photo_file_ids
        or voice_file_id is not None
        or document is not None
    )
    if should_include_telegram_context_prompt(
        prompt_input,
        reply_context_prompt,
        getattr(client, "channel_name", "telegram"),
        injection_policy=context_injection_policy,
        has_existing_thread=has_existing_thread,
        has_request_payload=has_request_payload,
    ):
        include_delivery_guardrails = should_include_delivery_guardrails(
            prompt_input,
            reply_context_prompt,
            getattr(client, "channel_name", "telegram"),
        ) or not has_existing_thread
        telegram_context_prompt = build_telegram_context_prompt(
            chat_id=ctx.chat_id,
            message_thread_id=ctx.message_thread_id,
            scope_key=ctx.scope_key,
            message_id=ctx.message_id,
            message=ctx.message,
            include_delivery_guardrails=include_delivery_guardrails,
        )

    prefix_result = apply_required_prefix_gate(
        client=client,
        config=config,
        prompt_input=prompt_input,
        has_reply_context=bool(reply_context_prompt),
        voice_file_id=voice_file_id,
        document=document,
        is_private_chat=ctx.is_private_chat,
        normalize_command=normalize_command,
        strip_required_prefix=strip_required_prefix,
    )
    prompt_input = prefix_result.prompt_input
    if prefix_result.ignored:
        emit_event(
            "bridge.request_ignored",
            fields={
                "chat_id": ctx.chat_id,
                "message_id": ctx.message_id,
                "reason": prefix_result.rejection_reason,
            },
        )
        return None
    if prefix_result.rejection_reason:
        emit_event(
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
            prefix_result.rejection_message or PREFIX_HELP_MESSAGE,
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
        sender_name=extract_sender_name(ctx.message),
        command=normalize_command(prompt_input or ""),
    )


def build_update_flow_state(
    state: State,
    config,
    client: ChannelAdapter,
    engine: Optional[EngineAdapter],
    prepared: PreparedUpdateRequest,
    dependencies,
) -> UpdateFlowState:
    return UpdateFlowState(
        state=state,
        config=config,
        client=client,
        engine=engine,
        dependencies=dependencies,
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


def prepare_update_dispatch_request(
    flow: UpdateFlowState,
    handle_update_started_at: float,
) -> Optional[UpdateDispatchRequest]:
    keyword_result = apply_priority_keyword_routing(
        config=flow.config,
        prompt_input=flow.prompt_input,
        command=flow.command,
        chat_id=flow.ctx.chat_id,
    )
    if keyword_result.rejection_reason:
        emit_event(
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
            keyword_result.rejection_message or PREFIX_HELP_MESSAGE,
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
        emit_event(
            keyword_result.routed_event or "bridge.keyword_routed",
            fields={"chat_id": flow.ctx.chat_id, "message_id": flow.ctx.message_id},
        )

    if flow.prompt_input:
        maybe_process_voice_alias_learning_confirmation(
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

    if handle_known_command(
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
        emit_event(
            "bridge.command_handled",
            fields={
                "chat_id": flow.ctx.chat_id,
                "message_id": flow.ctx.message_id,
                "command": flow.command or "",
            },
        )
        return None

    raw_prompt = (flow.prompt_input or "").strip()
    prompt_details = _build_prompt_with_diagnostics(
        raw_prompt=raw_prompt,
        telegram_context_prompt=flow.telegram_context_prompt,
        reply_context_prompt=flow.reply_context_prompt,
        sender_name=flow.sender_name,
        max_input_chars=flow.config.max_input_chars,
    )
    prompt = str(prompt_details["prompt"] or "")
    if not prompt and not flow.voice_file_id and flow.document is None:
        return None

    if prompt and len(prompt) > flow.config.max_input_chars:
        _reject_input_too_long(flow, len(prompt))
        return None

    if bool(prompt_details.get("trimmed")):
        emit_event(
            "bridge.prompt_trimmed",
            level=logging.WARNING,
            fields={
                "chat_id": flow.ctx.chat_id,
                "message_id": flow.ctx.message_id,
                "original_length": int(prompt_details["original_length"]),
                "final_length": int(prompt_details["final_length"]),
                "dropped_sections": list(prompt_details["dropped_sections"]),
                "trimmed_user_chars": int(prompt_details["trimmed_user_chars"]),
            },
        )
        send_prompt_trimmed_warning(
            client=flow.client,
            chat_id=flow.ctx.chat_id,
            message_id=flow.ctx.message_id,
            original_length=int(prompt_details["original_length"]),
            final_length=int(prompt_details["final_length"]),
            max_input_chars=flow.config.max_input_chars,
            dropped_sections=list(prompt_details["dropped_sections"]),
            trimmed_user_chars=int(prompt_details["trimmed_user_chars"]),
        )

    if is_rate_limited(flow.state, flow.config, flow.ctx.scope_key):
        emit_event(
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
            RATE_LIMIT_MESSAGE,
            reply_to_message_id=flow.ctx.message_id,
        )
        return None

    return UpdateDispatchRequest(
        state=flow.state,
        config=flow.config,
        client=flow.client,
        engine=flow.engine,
        dependencies=flow.dependencies,
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
        prompt_diagnostics=prompt_details,
    )
