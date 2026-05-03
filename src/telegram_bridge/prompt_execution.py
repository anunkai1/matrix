import logging
import time
from typing import Any, Dict, List, Optional, Tuple

try:
    from .engine_adapter import CodexEngineAdapter, EngineAdapter
    from .handler_models import DocumentPayload, PromptRequest
    from .memory_engine import MemoryEngine, TurnContext
    from .state_store import StateRepository
except ImportError:
    from engine_adapter import CodexEngineAdapter, EngineAdapter
    from handler_models import DocumentPayload, PromptRequest
    from memory_engine import MemoryEngine, TurnContext
    from state_store import StateRepository

def emit_phase_timing(
    *,
    chat_id: int,
    message_id: Optional[int],
    phase: str,
    started_at_monotonic: float,
    emit_event_fn,
    **extra_fields,
) -> None:
    fields = {
        "chat_id": chat_id,
        "message_id": message_id,
        "phase": phase,
        "duration_ms": int(max(0.0, (time.monotonic() - started_at_monotonic) * 1000.0)),
    }
    for key, value in extra_fields.items():
        if value is not None:
            fields[key] = value
    emit_event_fn("bridge.request_phase_timing", fields=fields)


def emit_request_processing_started(
    *,
    chat_id: int,
    message_id: Optional[int],
    prompt: str,
    photo_file_ids: Optional[List[str]],
    photo_file_id: Optional[str],
    voice_file_id: Optional[str],
    document: Optional[DocumentPayload],
    previous_thread_id: Optional[str],
    emit_event_fn,
) -> None:
    emit_event_fn(
        "bridge.request_processing_started",
        fields={
            "chat_id": chat_id,
            "message_id": message_id,
            "prompt_chars": len(prompt or ""),
            "has_photo": bool(photo_file_ids or photo_file_id),
            "has_voice": bool(voice_file_id),
            "has_document": document is not None,
            "has_previous_thread": bool(previous_thread_id),
        },
    )


def build_progress_reporter(
    client,
    config,
    chat_id: int,
    message_id: Optional[int],
    message_thread_id: Optional[int],
    progress_context_label: str,
    *,
    progress_reporter_cls,
    assistant_label_fn,
):
    return progress_reporter_cls(
        client,
        chat_id,
        message_id,
        message_thread_id,
        assistant_label_fn(config),
        getattr(config, "progress_label", ""),
        progress_context_label,
        getattr(config, "progress_elapsed_prefix", "Already"),
        getattr(config, "progress_elapsed_suffix", "s"),
    )


def build_prompt_progress_reporter(
    request: PromptRequest,
    active_engine: EngineAdapter,
    *,
    build_engine_runtime_config_fn,
    build_engine_progress_context_label_fn,
    progress_reporter_cls,
    assistant_label_fn,
):
    engine_config = build_engine_runtime_config_fn(
        request.state,
        request.config,
        request.scope_key,
        getattr(active_engine, "engine_name", ""),
    )
    return build_progress_reporter(
        request.client,
        request.config,
        request.chat_id,
        request.message_id,
        request.message_thread_id,
        build_engine_progress_context_label_fn(
            engine_config,
            getattr(active_engine, "engine_name", ""),
        ),
        progress_reporter_cls=progress_reporter_cls,
        assistant_label_fn=assistant_label_fn,
    )


_MEMORY_INJECTION_INTERVAL_TOKENS = 150000
_MEMORY_INJECTION_INTERVAL_SECONDS = 1800
_memory_injection: Dict[str, Tuple[float, int]] = {}

# Engines that always get a full memory turn (no throttling):
# - stateless calls have no session to carry forward
# - codex without a persisted thread has no LLM-side context
# - empty engine_name means old compatibility API (no throttling info available)
_UNTHROTTLED_ENGINE_NAMES: frozenset[str] = frozenset({"", "codex"})


def begin_memory_turn(
    memory_engine: Optional[MemoryEngine],
    state_repo: StateRepository,
    config,
    channel_name: str,
    scope_key: str,
    prompt_text: str,
    sender_name: str,
    stateless: bool,
    chat_id: int,
    *,
    resolve_memory_conversation_key_fn,
    resolve_shared_memory_archive_key_fn,
    engine_name: str = "",
    has_persisted_thread: bool = False,
) -> tuple[str, Optional[str], Optional[TurnContext]]:
    if memory_engine is None:
        return prompt_text, (None if stateless else state_repo.get_thread_id(scope_key)), None
    if stateless:
        return _do_memory_turn(memory_engine, state_repo, config, channel_name, scope_key,
                               prompt_text, sender_name, stateless, chat_id,
                               resolve_memory_conversation_key_fn,
                               resolve_shared_memory_archive_key_fn)

    if engine_name in _UNTHROTTLED_ENGINE_NAMES and not has_persisted_thread:
        return _do_memory_turn(memory_engine, state_repo, config, channel_name, scope_key,
                               prompt_text, sender_name, stateless, chat_id,
                               resolve_memory_conversation_key_fn,
                               resolve_shared_memory_archive_key_fn)

    now = time.time()
    prompt_tokens = len(prompt_text) // 4
    entry = _memory_injection.get(scope_key)

    if entry is not None:
        last_ts, token_count = entry
        token_count += prompt_tokens
        if token_count < _MEMORY_INJECTION_INTERVAL_TOKENS and (now - last_ts) < _MEMORY_INJECTION_INTERVAL_SECONDS:
            _memory_injection[scope_key] = (last_ts, token_count)
            return prompt_text, state_repo.get_thread_id(scope_key), None

    _memory_injection[scope_key] = (now, 0)
    return _do_memory_turn(memory_engine, state_repo, config, channel_name, scope_key,
                           prompt_text, sender_name, stateless, chat_id,
                           resolve_memory_conversation_key_fn,
                           resolve_shared_memory_archive_key_fn)


def _do_memory_turn(
    memory_engine: MemoryEngine,
    state_repo: StateRepository,
    config,
    channel_name: str,
    scope_key: str,
    prompt_text: str,
    sender_name: str,
    stateless: bool,
    chat_id: int,
    resolve_memory_conversation_key_fn,
    resolve_shared_memory_archive_key_fn,
) -> tuple[str, Optional[str], Optional[TurnContext]]:
    conversation_key = resolve_memory_conversation_key_fn(config, channel_name, scope_key)
    persisted_thread_id = state_repo.get_thread_id(scope_key)
    if not stateless:
        try:
            if persisted_thread_id:
                memory_engine.set_session_thread_id(conversation_key, persisted_thread_id)
            else:
                memory_engine.clear_session_thread_id(conversation_key)
        except Exception:
            logging.exception(
                "Failed to sync shared memory thread state for chat_id=%s",
                chat_id,
            )
    try:
        turn_context = memory_engine.begin_turn(
            conversation_key=conversation_key,
            channel=channel_name,
            sender_name=sender_name,
            user_input=prompt_text,
            stateless=stateless,
            background_conversation_key=resolve_shared_memory_archive_key_fn(
                config,
                channel_name,
            ),
            thread_id_override=persisted_thread_id,
        )
        return turn_context.prompt_text, persisted_thread_id, turn_context
    except Exception:
        logging.exception("Failed to prepare shared memory turn for chat_id=%s", chat_id)
        return prompt_text, persisted_thread_id, None


def clear_memory_injection_state(scope_key: str) -> None:
    _memory_injection.pop(scope_key, None)


def begin_affective_turn(
    affective_runtime,
    prompt_text: str,
    *,
    chat_id: int,
    message_id: Optional[int],
    emit_event_fn,
) -> tuple[str, bool]:
    if affective_runtime is None:
        return prompt_text, False
    affective_turn_started = False
    try:
        affective_runtime.begin_turn(prompt_text)
        affective_turn_started = True
        affective_prefix = (affective_runtime.prompt_prefix() or "").strip()
        if affective_prefix:
            prompt_text = f"{affective_prefix}\n\nUser request:\n{prompt_text}"
            emit_event_fn(
                "bridge.affective_prompt_applied",
                fields={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "prefix_chars": len(affective_prefix),
                },
            )
        return prompt_text, True
    except Exception:
        logging.exception(
            "Affective runtime begin_turn failed for chat_id=%s; continuing without prefix.",
            chat_id,
        )
        if affective_turn_started:
            try:
                affective_runtime.finish_turn(success=False)
            except Exception:
                logging.exception(
                    "Affective runtime rollback failed after begin_turn error for chat_id=%s",
                    chat_id,
                )
        return prompt_text, False


def process_prompt_request(
    request: PromptRequest,
    *,
    progress_reporter_cls,
    state_repository_cls=StateRepository,
    codex_engine_adapter_factory=CodexEngineAdapter,
    memory_engine_cls=MemoryEngine,
    assistant_label_fn,
    build_engine_runtime_config_fn,
    build_engine_progress_context_label_fn,
    refresh_runtime_auth_fingerprint_fn,
    prepare_prompt_input_request_fn,
    execute_prompt_with_retry_fn,
    finalize_prompt_success_fn,
    finalize_request_progress_fn,
    emit_event_fn,
    resolve_memory_conversation_key_fn,
    resolve_shared_memory_archive_key_fn,
) -> None:
    state = request.state
    config = request.config
    client = request.client
    engine = request.engine
    scope_key = request.scope_key
    chat_id = request.chat_id
    message_thread_id = request.message_thread_id
    message_id = request.message_id
    prompt = request.prompt
    photo_file_id = request.photo_file_id
    voice_file_id = request.voice_file_id
    document = request.document
    cancel_event = request.cancel_event
    stateless = request.stateless
    sender_name = request.sender_name
    photo_file_ids = request.photo_file_ids
    actor_user_id = request.actor_user_id
    total_started_at = time.monotonic()
    channel_name = getattr(client, "channel_name", "telegram")
    active_engine = engine or codex_engine_adapter_factory()
    assistant_name_label = assistant_label_fn(config)
    state_repo = state_repository_cls(state)
    memory_engine = state.memory_engine if isinstance(state.memory_engine, memory_engine_cls) else None
    engine_config = build_engine_runtime_config_fn(
        state,
        config,
        scope_key,
        getattr(active_engine, "engine_name", ""),
    )
    previous_thread_id: Optional[str] = None
    turn_context: Optional[TurnContext] = None
    image_path: Optional[str] = None
    image_paths: List[str] = []
    cleanup_paths: List[str] = []
    attachment_file_ids: List[str] = []
    attachment_store = getattr(state, "attachment_store", None)
    affective_runtime = getattr(state, "affective_runtime", None)
    affective_turn_started = False
    affective_turn_finished = False
    progress = build_prompt_progress_reporter(
        request,
        active_engine,
        build_engine_runtime_config_fn=build_engine_runtime_config_fn,
        build_engine_progress_context_label_fn=build_engine_progress_context_label_fn,
        progress_reporter_cls=progress_reporter_cls,
        assistant_label_fn=assistant_label_fn,
    )
    try:
        progress.start()
        auth_reset_result = refresh_runtime_auth_fingerprint_fn(state)
        if auth_reset_result["applied"]:
            counts = auth_reset_result["counts"]
            logging.warning(
                "Auth fingerprint changed mid-runtime; cleared stored thread state for %s "
                "(threads=%s worker_sessions=%s canonical_sessions=%s memory_sessions=%s).",
                assistant_name_label,
                counts["threads"],
                counts["worker_sessions"],
                counts["canonical_sessions"],
                counts["memory_sessions"],
            )
            emit_event_fn(
                "bridge.thread_state_reset_for_auth_change",
                level=logging.WARNING,
                fields={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "thread_count": counts["threads"],
                    "worker_session_count": counts["worker_sessions"],
                    "canonical_session_count": counts["canonical_sessions"],
                    "memory_session_count": counts["memory_sessions"],
                },
            )
        prepare_started_at = time.monotonic()
        prepared = prepare_prompt_input_request_fn(request, progress)
        emit_phase_timing(
            chat_id=chat_id,
            message_id=message_id,
            phase="prepare_prompt_input",
            started_at_monotonic=prepare_started_at,
            emit_event_fn=emit_event_fn,
            has_prepared_prompt=prepared is not None,
        )
        if prepared is None:
            return
        image_path = prepared.image_path
        image_paths = list(prepared.image_paths)
        cleanup_paths = list(prepared.cleanup_paths)
        attachment_file_ids = list(prepared.attachment_file_ids)
        prompt_text = prepared.prompt_text
        memory_started_at = time.monotonic()
        engine_name = getattr(active_engine, "engine_name", "")
        has_persisted_thread = bool(state_repo.get_thread_id(scope_key)) if not stateless else False
        prompt_text, previous_thread_id, turn_context = begin_memory_turn(
            memory_engine=memory_engine,
            state_repo=state_repo,
            config=config,
            channel_name=channel_name,
            scope_key=scope_key,
            prompt_text=prompt_text,
            sender_name=sender_name,
            stateless=stateless,
            chat_id=chat_id,
            resolve_memory_conversation_key_fn=resolve_memory_conversation_key_fn,
            resolve_shared_memory_archive_key_fn=resolve_shared_memory_archive_key_fn,
            engine_name=engine_name,
            has_persisted_thread=has_persisted_thread,
        )
        emit_phase_timing(
            chat_id=chat_id,
            message_id=message_id,
            phase="begin_memory_turn",
            started_at_monotonic=memory_started_at,
            emit_event_fn=emit_event_fn,
            memory_enabled=memory_engine is not None,
            stateless=stateless,
            reused_thread=bool(previous_thread_id),
        )
        affective_started_at = time.monotonic()
        prompt_text, affective_turn_started = begin_affective_turn(
            affective_runtime,
            prompt_text,
            chat_id=chat_id,
            message_id=message_id,
            emit_event_fn=emit_event_fn,
        )
        emit_phase_timing(
            chat_id=chat_id,
            message_id=message_id,
            phase="begin_affective_turn",
            started_at_monotonic=affective_started_at,
            emit_event_fn=emit_event_fn,
            affective_enabled=affective_runtime is not None,
            affective_applied=affective_turn_started,
        )
        emit_request_processing_started(
            chat_id=chat_id,
            message_id=message_id,
            prompt=prompt,
            photo_file_ids=photo_file_ids,
            photo_file_id=photo_file_id,
            voice_file_id=voice_file_id,
            document=document,
            previous_thread_id=previous_thread_id,
            emit_event_fn=emit_event_fn,
        )
        progress.set_phase(f"Sending request to {assistant_name_label}.")
        execute_started_at = time.monotonic()
        result = execute_prompt_with_retry_fn(
            state_repo=state_repo,
            config=engine_config,
            client=client,
            engine=active_engine,
            scope_key=scope_key,
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            message_id=message_id,
            prompt_text=prompt_text,
            previous_thread_id=previous_thread_id,
            image_path=image_path,
            image_paths=image_paths or ([image_path] if image_path else []),
            actor_user_id=actor_user_id,
            progress=progress,
            cancel_event=cancel_event,
            session_continuity_enabled=not stateless,
        )
        emit_phase_timing(
            chat_id=chat_id,
            message_id=message_id,
            phase="execute_prompt_with_retry",
            started_at_monotonic=execute_started_at,
            emit_event_fn=emit_event_fn,
            success=result is not None,
        )
        if result is None:
            return
        finalize_started_at = time.monotonic()
        new_thread_id, output = finalize_prompt_success_fn(
            state_repo=state_repo,
            config=config,
            client=client,
            scope_key=scope_key,
            chat_id=chat_id,
            message_id=message_id,
            result=result,
            progress=progress,
        )
        emit_phase_timing(
            chat_id=chat_id,
            message_id=message_id,
            phase="finalize_prompt_success",
            started_at_monotonic=finalize_started_at,
            emit_event_fn=emit_event_fn,
            new_thread_id=bool(new_thread_id),
            output_chars=len(output),
        )
        if stateless:
            state_repo.clear_thread_id(scope_key)
        if attachment_store is not None:
            for attachment_file_id in attachment_file_ids:
                try:
                    attachment_store.update_summary(channel_name, attachment_file_id, output)
                except Exception:
                    logging.exception(
                        "Failed to persist attachment summary for channel=%s file_id=%s",
                        channel_name,
                        attachment_file_id,
                    )
        if affective_turn_started:
            try:
                affective_runtime.finish_turn(success=True)
                affective_turn_finished = True
            except Exception:
                logging.exception(
                    "Affective runtime finish_turn(success=True) failed for chat_id=%s",
                    chat_id,
                )
        if memory_engine is not None and turn_context is not None:
            if stateless:
                state_repo.clear_thread_id(scope_key)
            try:
                memory_engine.finish_turn(
                    turn_context,
                    channel=channel_name,
                    assistant_text=output,
                    new_thread_id=new_thread_id,
                    assistant_name=assistant_name_label,
                )
            except Exception:
                logging.exception("Failed to finish shared memory turn for chat_id=%s", chat_id)
    finally:
        if affective_turn_started and not affective_turn_finished and affective_runtime is not None:
            try:
                affective_runtime.finish_turn(success=False)
            except Exception:
                logging.exception(
                    "Affective runtime finish_turn(success=False) failed for chat_id=%s",
                    chat_id,
                )
        finalize_request_progress_fn(
            progress=progress,
            state=state,
            client=client,
            scope_key=scope_key,
            chat_id=chat_id,
            message_id=message_id,
            cancel_event=cancel_event,
            cleanup_paths=cleanup_paths,
        )
        emit_phase_timing(
            chat_id=chat_id,
            message_id=message_id,
            phase="process_prompt_total",
            started_at_monotonic=total_started_at,
            emit_event_fn=emit_event_fn,
        )
