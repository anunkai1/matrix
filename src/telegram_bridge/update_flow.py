import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from telegram_bridge.handler_models import UpdateDispatchRequest, UpdateFlowState
from telegram_bridge.conversation_scope import parse_telegram_scope_key
from telegram_bridge.state_store import mark_in_flight_request
from telegram_bridge.update_preparation import (
    allow_update_chat,
    build_update_flow_state,
    extract_incoming_update_context,
    prepare_update_dispatch_request,
    prepare_update_request,
)


@dataclass(frozen=True)
class UpdateFlowDependencies:
    mark_busy: Callable[[Any, str], bool]
    emit_event: Callable[..., None]
    request_chat_cancel: Callable[[Any, str], str]
    register_cancel_event: Callable[[Any, str], Any]
    try_steer_live_codex_turn: Callable[..., bool]
    live_codex_turn_is_active: Callable[..., Optional[bool]]
    resolve_engine_for_scope: Callable[[Any, Any, str, Any], Any]
    ensure_chat_worker_session: Callable[..., bool]
    start_youtube_worker: Callable[..., None]
    start_message_worker: Callable[..., None]
    emit_phase_timing: Callable[..., None]
    diary_mode_enabled: Callable[[Any], bool]
    handle_known_command: Callable[..., bool]
    queue_diary_capture: Callable[..., None]

@dataclass(frozen=True)
class DispatchAcceptance:
    cancel_event: Any


@dataclass(frozen=True)
class DispatchResult:
    accepted: Optional[DispatchAcceptance] = None
    handled: bool = False


@dataclass(frozen=True)
class StandardDispatchPlan:
    active_engine: Any


STALE_BUSY_CANCEL_AFTER_SECONDS = 300.0
STALE_BUSY_CLEAR_WAIT_SECONDS = 3.0
LIVE_CODEX_STEER_FAILED_MESSAGE = (
    "A live Codex turn is already running for this chat/topic, but this follow-up "
    "could not be merged into it. Use /cancel or wait for the current turn to finish."
)
LIVE_CODEX_STEER_UNSUPPORTED_MESSAGE = (
    "A live Codex turn is already running for this chat/topic. During an active turn, "
    "follow-up steering only accepts plain-text messages. Use /cancel or wait for the "
    "current turn to finish."
)


def _scope_is_busy(state: Any, scope_key: str) -> bool:
    try:
        parsed_scope = parse_telegram_scope_key(scope_key)
    except ValueError:
        parsed_scope = None
    legacy_alias = (
        parsed_scope.chat_id
        if parsed_scope is not None and parsed_scope.message_thread_id is None
        else None
    )
    with state.lock:
        return scope_key in state.busy_chats or (
            legacy_alias is not None and legacy_alias in state.busy_chats
        )


def _scope_in_flight_started_at(state: Any, scope_key: str) -> Optional[float]:
    with state.lock:
        session = state.chat_sessions.get(scope_key)
        if session is not None and session.in_flight_started_at is not None:
            return float(session.in_flight_started_at)
        payload = state.in_flight_requests.get(scope_key)
        if isinstance(payload, dict):
            started_at = payload.get("started_at")
            if isinstance(started_at, (int, float)):
                return float(started_at)
    return None


def _wait_for_scope_busy_clear(state: Any, scope_key: str, *, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _scope_is_busy(state, scope_key):
            return True
        time.sleep(0.05)
    return not _scope_is_busy(state, scope_key)


def _build_dispatch_acceptance(
    request: UpdateDispatchRequest,
    dependencies: UpdateFlowDependencies,
    *,
    route: Optional[str] = None,
) -> DispatchAcceptance:
    cancel_event = dependencies.register_cancel_event(request.state, request.scope_key)
    mark_in_flight_request(request.state, request.scope_key, request.message_id)
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
    dependencies.emit_event("bridge.request_accepted", fields=accepted_fields)
    return DispatchAcceptance(cancel_event=cancel_event)


def _resolve_dependencies(dependencies: Optional[UpdateFlowDependencies]) -> UpdateFlowDependencies:
    if dependencies is not None:
        return dependencies
    from telegram_bridge.bridge_runtime_setup import build_update_flow_dependencies

    return build_update_flow_dependencies()


def _busy_live_codex_turn_follow_up_reason(
    request: UpdateDispatchRequest,
) -> Optional[str]:
    if request.stateless or request.youtube_route_url:
        return "stateless_route"
    if request.voice_file_id is not None:
        return "voice_message"
    if request.document is not None:
        return "document_message"
    if request.photo_file_ids:
        return "photo_message"
    if not (request.prompt or "").strip():
        return "empty_prompt"
    return None


def _maybe_handle_busy_live_codex_turn(
    request: UpdateDispatchRequest,
    plan: StandardDispatchPlan,
) -> bool:
    dependencies = _resolve_dependencies(request.dependencies)
    if getattr(plan.active_engine, "engine_name", "") != "codex":
        return False
    follow_up_reason = _busy_live_codex_turn_follow_up_reason(request)
    if follow_up_reason is None:
        if dependencies.try_steer_live_codex_turn(
            request.config,
            request.scope_key,
            request.raw_prompt,
        ):
            dependencies.emit_event(
                "bridge.request_steered",
                fields={
                    "chat_id": request.chat_id,
                    "message_id": request.message_id,
                    "scope_key": request.scope_key,
                },
            )
            return True
        if dependencies.live_codex_turn_is_active(
            request.config,
            request.scope_key,
        ) is not True:
            return False
        dependencies.emit_event(
            "bridge.request_steer_failed",
            level=logging.WARNING,
            fields={
                "chat_id": request.chat_id,
                "message_id": request.message_id,
                "scope_key": request.scope_key,
                "reason": "steer_call_failed",
            },
        )
        request.client.send_message(
            request.chat_id,
            LIVE_CODEX_STEER_FAILED_MESSAGE,
            reply_to_message_id=request.message_id,
            message_thread_id=request.message_thread_id,
        )
        return True
    if dependencies.live_codex_turn_is_active(
        request.config,
        request.scope_key,
    ) is not True:
        return False
    dependencies.emit_event(
        "bridge.request_steer_rejected",
        level=logging.WARNING,
        fields={
            "chat_id": request.chat_id,
            "message_id": request.message_id,
            "scope_key": request.scope_key,
            "reason": follow_up_reason,
        },
    )
    request.client.send_message(
        request.chat_id,
        LIVE_CODEX_STEER_UNSUPPORTED_MESSAGE,
        reply_to_message_id=request.message_id,
        message_thread_id=request.message_thread_id,
    )
    return True


def _wait_for_post_turn_busy_clear(
    request: UpdateDispatchRequest,
    plan: StandardDispatchPlan,
) -> bool:
    dependencies = _resolve_dependencies(request.dependencies)
    if getattr(plan.active_engine, "engine_name", "") != "codex":
        return False
    if request.stateless:
        return False
    if not _scope_is_busy(request.state, request.scope_key):
        return False
    live_turn_active = dependencies.live_codex_turn_is_active(
        request.config,
        request.scope_key,
    )
    if live_turn_active is not False:
        return False
    return _wait_for_scope_busy_clear(
        request.state,
        request.scope_key,
        timeout_seconds=STALE_BUSY_CLEAR_WAIT_SECONDS,
    )


def _maybe_recover_stale_busy_scope(
    request: UpdateDispatchRequest,
    plan: StandardDispatchPlan,
) -> bool:
    dependencies = _resolve_dependencies(request.dependencies)
    in_flight_started_at = _scope_in_flight_started_at(request.state, request.scope_key)
    if in_flight_started_at is None:
        return False
    request_age_seconds = max(0.0, time.time() - in_flight_started_at)
    if request_age_seconds < STALE_BUSY_CANCEL_AFTER_SECONDS:
        return False
    live_turn_active = dependencies.live_codex_turn_is_active(
        request.config,
        request.scope_key,
    )
    if live_turn_active is True:
        return False
    cancel_status = dependencies.request_chat_cancel(request.state, request.scope_key)
    dependencies.emit_event(
        "bridge.stale_busy_recovery_attempted",
        level=logging.WARNING,
        fields={
            "chat_id": request.chat_id,
            "message_id": request.message_id,
            "scope_key": request.scope_key,
            "request_age_seconds": int(request_age_seconds),
            "cancel_status": cancel_status,
            "live_turn_active": live_turn_active,
        },
    )
    if cancel_status not in {"requested", "already_requested", "idle"}:
        return False
    return _wait_for_scope_busy_clear(
        request.state,
        request.scope_key,
        timeout_seconds=STALE_BUSY_CLEAR_WAIT_SECONDS,
    )


def _accept_dispatch_request(
    request: UpdateDispatchRequest,
    *,
    route: Optional[str] = None,
) -> DispatchResult:
    dependencies = _resolve_dependencies(request.dependencies)
    if not dependencies.mark_busy(request.state, request.scope_key):
        plan = _resolve_standard_dispatch_plan(request)
        if plan is not None and _maybe_handle_busy_live_codex_turn(request, plan):
            return DispatchResult(handled=True)
        if plan is not None and _wait_for_post_turn_busy_clear(request, plan):
            if dependencies.mark_busy(request.state, request.scope_key):
                return DispatchResult(
                    accepted=_build_dispatch_acceptance(request, dependencies, route=route)
                )
        if plan is not None and _maybe_recover_stale_busy_scope(request, plan):
            if dependencies.mark_busy(request.state, request.scope_key):
                return DispatchResult(
                    accepted=_build_dispatch_acceptance(request, dependencies, route=route)
                )
        dependencies.emit_event(
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
        return DispatchResult()

    return DispatchResult(
        accepted=_build_dispatch_acceptance(request, dependencies, route=route)
    )

def _resolve_standard_dispatch_plan(request: UpdateDispatchRequest) -> Optional[StandardDispatchPlan]:
    dependencies = _resolve_dependencies(request.dependencies)
    try:
        active_engine = dependencies.resolve_engine_for_scope(
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

    return StandardDispatchPlan(active_engine=active_engine)


def _ensure_standard_dispatch_capacity(request: UpdateDispatchRequest) -> bool:
    dependencies = _resolve_dependencies(request.dependencies)
    if request.stateless:
        return True
    if dependencies.ensure_chat_worker_session(
        request.state,
        request.config,
        request.client,
        request.scope_key,
        request.chat_id,
        request.message_thread_id,
        request.message_id,
    ):
        return True
    dependencies.emit_event(
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
    dependencies = _resolve_dependencies(request.dependencies)
    if request.youtube_route_url:
        dependencies.start_youtube_worker(
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
        dependencies.start_message_worker(
            state=request.state,
            config=request.config,
            client=request.client,
            engine=plan.active_engine,
            scope_key=request.scope_key,
            chat_id=request.chat_id,
            message_thread_id=request.message_thread_id,
            message_id=request.message_id,
            prompt=request.prompt,
            raw_prompt=request.raw_prompt,
            photo_file_id=request.photo_file_ids[0] if request.photo_file_ids else None,
            photo_file_ids=request.photo_file_ids,
            voice_file_id=request.voice_file_id,
            document=request.document,
            cancel_event=acceptance.cancel_event,
            stateless=request.stateless,
            sender_name=request.sender_name,
            enforce_voice_prefix_from_transcript=request.enforce_voice_prefix_from_transcript,
            actor_user_id=request.actor_user_id,
            prompt_diagnostics=request.prompt_diagnostics,
            delivery_metadata=request.delivery_metadata,
        )
    dependencies.emit_event(
        "bridge.worker_started",
        fields={"chat_id": request.chat_id, "message_id": request.message_id},
    )
    if request.handle_update_started_at is not None:
        dependencies.emit_phase_timing(
            chat_id=request.chat_id,
            message_id=request.message_id,
            phase="handle_update_pre_worker",
            started_at_monotonic=request.handle_update_started_at,
            routed_youtube=bool(request.youtube_route_url),
            stateless=request.stateless,
        )


def start_standard_dispatch(request: UpdateDispatchRequest) -> bool:
    plan = _resolve_standard_dispatch_plan(request)
    if plan is None:
        return False

    if _maybe_handle_busy_live_codex_turn(request, plan):
        return True

    if not _ensure_standard_dispatch_capacity(request):
        return False

    _wait_for_post_turn_busy_clear(request, plan)

    dispatch_result = _accept_dispatch_request(request)
    if dispatch_result.handled:
        return True
    acceptance = dispatch_result.accepted
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
    dependencies = _resolve_dependencies(flow.dependencies)
    return dependencies.diary_mode_enabled(flow.config)


def _handle_diary_known_command(flow: UpdateFlowState) -> bool:
    dependencies = _resolve_dependencies(flow.dependencies)
    if not dependencies.handle_known_command(
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
    dependencies.emit_event(
        "bridge.command_handled",
        fields={
            "chat_id": flow.ctx.chat_id,
            "message_id": flow.ctx.message_id,
            "command": flow.command or "",
        },
    )
    return True


def _queue_diary_message(flow: UpdateFlowState) -> None:
    dependencies = _resolve_dependencies(flow.dependencies)
    dependencies.queue_diary_capture(
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
