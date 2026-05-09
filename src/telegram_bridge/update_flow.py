import logging
from dataclasses import dataclass
from typing import Any, Optional

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

@dataclass(frozen=True)
class DispatchAcceptance:
    cancel_event: Any


@dataclass(frozen=True)
class StandardDispatchPlan:
    active_engine: Any


def _resolve_dishframed_photo_file_ids(request: UpdateDispatchRequest) -> list[str]:
    handlers = _handlers()
    photo_file_ids = list(request.photo_file_ids)
    if photo_file_ids:
        return photo_file_ids
    return handlers.get_recent_scope_photos(request.state, request.scope_key)


def _accept_dispatch_request(
    request: UpdateDispatchRequest,
    *,
    route: Optional[str] = None,
) -> Optional[DispatchAcceptance]:
    handlers = _handlers()
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
        return None

    cancel_event = handlers.register_cancel_event(request.state, request.scope_key)
    _state_store().mark_in_flight_request(request.state, request.scope_key, request.message_id)
    accepted_fields = {
        "chat_id": request.chat_id,
        "message_id": request.message_id,
        "scope_key": request.scope_key,
        "has_photo": bool(request.photo_file_ids),
        "has_voice": bool(request.voice_file_id),
        "has_document": request.document is not None,
        "stateless": request.stateless,
    }
    if route is not None:
        accepted_fields["route"] = route
    handlers.emit_event("bridge.request_accepted", fields=accepted_fields)
    return DispatchAcceptance(cancel_event=cancel_event)


def _start_dishframed_worker(
    request: UpdateDispatchRequest,
    *,
    photo_file_ids: list[str],
    acceptance: DispatchAcceptance,
) -> None:
    handlers = _handlers()
    handlers.start_dishframed_worker(
        state=request.state,
        config=request.config,
        client=request.client,
        scope_key=request.scope_key,
        chat_id=request.chat_id,
        message_thread_id=request.message_thread_id,
        message_id=request.message_id,
        photo_file_ids=photo_file_ids,
        cancel_event=acceptance.cancel_event,
    )
    handlers.emit_event(
        "bridge.worker_started",
        fields={"chat_id": request.chat_id, "message_id": request.message_id, "route": "dishframed"},
    )


def _resolve_standard_dispatch_plan(request: UpdateDispatchRequest) -> Optional[StandardDispatchPlan]:
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
        return None

    if request.youtube_route_url:
        return StandardDispatchPlan(active_engine=active_engine)
    return StandardDispatchPlan(active_engine=active_engine)


def _ensure_standard_dispatch_capacity(request: UpdateDispatchRequest) -> bool:
    handlers = _handlers()
    if request.stateless:
        return True
    if handlers.ensure_chat_worker_session(
        request.state,
        request.config,
        request.client,
        request.scope_key,
        request.chat_id,
        request.message_thread_id,
        request.message_id,
    ):
        return True
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


def _run_standard_dispatch_worker(
    request: UpdateDispatchRequest,
    plan: StandardDispatchPlan,
    acceptance: DispatchAcceptance,
) -> None:
    handlers = _handlers()
    if request.youtube_route_url:
        handlers.start_youtube_worker(
            state=request.state,
            config=request.config,
            client=request.client,
            engine=plan.active_engine,
            scope_key=request.scope_key,
            chat_id=request.chat_id,
            message_thread_id=request.message_thread_id,
            message_id=request.message_id,
            request_text=request.raw_prompt,
            youtube_url=request.youtube_route_url,
            actor_user_id=request.actor_user_id,
            cancel_event=acceptance.cancel_event,
        )
    else:
        handlers.start_message_worker(
            state=request.state,
            config=request.config,
            client=request.client,
            engine=plan.active_engine,
            scope_key=request.scope_key,
            chat_id=request.chat_id,
            message_thread_id=request.message_thread_id,
            message_id=request.message_id,
            prompt=request.prompt,
            photo_file_id=request.photo_file_ids[0] if request.photo_file_ids else None,
            photo_file_ids=request.photo_file_ids,
            voice_file_id=request.voice_file_id,
            document=request.document,
            cancel_event=acceptance.cancel_event,
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


def start_dishframed_dispatch(request: UpdateDispatchRequest) -> bool:
    photo_file_ids = _resolve_dishframed_photo_file_ids(request)
    if not photo_file_ids:
        handlers = _handlers()
        request.client.send_message(
            request.chat_id,
            handlers.DISHFRAMED_USAGE_MESSAGE,
            reply_to_message_id=request.message_id,
            message_thread_id=request.message_thread_id,
        )
        return False

    acceptance = _accept_dispatch_request(request, route="dishframed")
    if acceptance is None:
        return False
    _start_dishframed_worker(request, photo_file_ids=photo_file_ids, acceptance=acceptance)
    return True

def start_standard_dispatch(request: UpdateDispatchRequest) -> bool:
    plan = _resolve_standard_dispatch_plan(request)
    if plan is None:
        return False

    if not _ensure_standard_dispatch_capacity(request):
        return False

    acceptance = _accept_dispatch_request(request)
    if acceptance is None:
        return False

    _run_standard_dispatch_worker(request, plan, acceptance)
    return True

def maybe_handle_diary_update_flow(flow: UpdateFlowState) -> bool:
    if not _is_diary_mode_enabled(flow):
        return False
    if _handle_diary_known_command(flow):
        return True
    _queue_diary_message(flow)
    return True


def _is_diary_mode_enabled(flow: UpdateFlowState) -> bool:
    return _handlers().diary_mode_enabled(flow.config)


def _handle_diary_known_command(flow: UpdateFlowState) -> bool:
    handlers = _handlers()
    if not handlers.handle_known_command(
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
        return False
    handlers.emit_event(
        "bridge.command_handled",
        fields={
            "chat_id": flow.ctx.chat_id,
            "message_id": flow.ctx.message_id,
            "command": flow.command or "",
        },
    )
    return True


def _queue_diary_message(flow: UpdateFlowState) -> None:
    _handlers().queue_diary_capture(
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
