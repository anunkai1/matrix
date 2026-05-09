import logging
import inspect
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import List, Optional

from telegram_bridge.channel_adapter import ChannelAdapter
from telegram_bridge.engine_adapter import EngineAdapter
from telegram_bridge.executor import ExecutorCancelledError
from telegram_bridge.state_store import StateRepository


@dataclass(frozen=True)
class PromptRuntimeHooks:
    build_scope_key_fn: object
    emit_event_fn: object
    emit_phase_timing_fn: object
    send_canceled_response_fn: object
    send_executor_failure_message_fn: object
    extract_executor_failure_message_fn: object
    should_reset_thread_after_resume_failure_fn: object
    resume_retry_phase_fn: object
    parse_executor_output_fn: object
    output_contains_control_directive_fn: object
    trim_output_fn: object
    deliver_output_and_emit_success_fn: object
    retry_with_new_session_phase: str


def _handlers():
    import telegram_bridge.handlers as handlers

    return handlers


def build_prompt_runtime_hooks() -> PromptRuntimeHooks:
    handlers = _handlers()
    return PromptRuntimeHooks(
        build_scope_key_fn=handlers.build_telegram_scope_key,
        emit_event_fn=handlers.emit_event,
        emit_phase_timing_fn=handlers.emit_phase_timing,
        send_canceled_response_fn=handlers.send_canceled_response,
        send_executor_failure_message_fn=handlers.send_executor_failure_message,
        extract_executor_failure_message_fn=handlers.extract_executor_failure_message,
        should_reset_thread_after_resume_failure_fn=handlers.should_reset_thread_after_resume_failure,
        resume_retry_phase_fn=handlers.resume_retry_phase,
        parse_executor_output_fn=handlers.parse_executor_output,
        output_contains_control_directive_fn=handlers.output_contains_control_directive,
        trim_output_fn=handlers.trim_output,
        deliver_output_and_emit_success_fn=handlers.deliver_output_and_emit_success,
        retry_with_new_session_phase=handlers.RETRY_WITH_NEW_SESSION_PHASE,
    )


_EXTENDED_ENGINE_RUN_KWARGS = (
    "session_key",
    "channel_name",
    "actor_chat_id",
    "actor_user_id",
    "image_paths",
)
_ENGINE_RUN_EXTENDED_KWARGS_SUPPORT_CACHE: dict[object, bool] = {}


def _engine_run_signature_target(engine_run: object) -> object:
    return getattr(engine_run, "__func__", engine_run)


def _engine_run_supports_extended_kwargs(engine_run: object) -> bool:
    signature_target = _engine_run_signature_target(engine_run)
    cached = _ENGINE_RUN_EXTENDED_KWARGS_SUPPORT_CACHE.get(signature_target)
    if cached is not None:
        return cached
    try:
        signature = inspect.signature(signature_target)
    except (TypeError, ValueError):
        _ENGINE_RUN_EXTENDED_KWARGS_SUPPORT_CACHE[signature_target] = True
        return True
    parameters = signature.parameters.values()
    if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters):
        _ENGINE_RUN_EXTENDED_KWARGS_SUPPORT_CACHE[signature_target] = True
        return True
    parameter_names = {parameter.name for parameter in parameters}
    supports_extended_kwargs = all(name in parameter_names for name in _EXTENDED_ENGINE_RUN_KWARGS)
    _ENGINE_RUN_EXTENDED_KWARGS_SUPPORT_CACHE[signature_target] = supports_extended_kwargs
    return supports_extended_kwargs


def execute_prompt_with_retry(
    state_repo: StateRepository,
    config,
    client: ChannelAdapter,
    engine: EngineAdapter,
    chat_id: int,
    prompt_text: str,
    previous_thread_id: Optional[str],
    progress,
    message_thread_id: Optional[int] = None,
    message_id: Optional[int] = None,
    scope_key: Optional[str] = None,
    image_path: Optional[str] = None,
    image_paths: Optional[List[str]] = None,
    actor_user_id: Optional[int] = None,
    cancel_event: Optional[threading.Event] = None,
    session_continuity_enabled: bool = True,
    runtime_hooks: Optional[PromptRuntimeHooks] = None,
) -> Optional[subprocess.CompletedProcess[str]]:
    runtime_hooks = runtime_hooks or build_prompt_runtime_hooks()
    if scope_key is None:
        scope_key = runtime_hooks.build_scope_key_fn(chat_id, message_thread_id=message_thread_id)
    allow_automatic_retry = config.persistent_workers_enabled
    retry_attempted = False
    attempt_thread_id: Optional[str] = previous_thread_id
    attempt = 0
    normalized_image_paths = list(image_paths or [])
    if image_path and image_path not in normalized_image_paths:
        normalized_image_paths.insert(0, image_path)

    while True:
        if cancel_event is not None and cancel_event.is_set():
            runtime_hooks.emit_event_fn(
                "bridge.request_cancelled",
                fields={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "phase": "before_executor_attempt",
                    "attempt": attempt + 1,
                },
            )
            progress.mark_failure("Execution canceled.")
            runtime_hooks.send_canceled_response_fn(client, chat_id, message_id, message_thread_id)
            return None

        attempt += 1
        runtime_hooks.emit_event_fn(
            "bridge.executor_attempt",
            fields={
                "chat_id": chat_id,
                "message_id": message_id,
                "attempt": attempt,
                "resume_mode": bool(attempt_thread_id),
                "automatic_retry_enabled": allow_automatic_retry,
            },
        )
        engine_started_at = time.monotonic()
        try:
            run_supports_extended_kwargs = _engine_run_supports_extended_kwargs(engine.run)
            if run_supports_extended_kwargs:
                result = engine.run(
                    config=config,
                    prompt=prompt_text,
                    thread_id=attempt_thread_id,
                    session_key=scope_key,
                    channel_name=getattr(client, "channel_name", "telegram"),
                    actor_chat_id=chat_id,
                    actor_user_id=actor_user_id,
                    image_paths=normalized_image_paths,
                    progress_callback=progress.handle_executor_event,
                    cancel_event=cancel_event,
                )
                runtime_hooks.emit_phase_timing_fn(
                    chat_id=chat_id,
                    message_id=message_id,
                    phase="engine_run",
                    started_at_monotonic=engine_started_at,
                    attempt=attempt,
                    success=True,
                    returncode=result.returncode,
                )
            else:
                result = engine.run(
                    config=config,
                    prompt=prompt_text,
                    thread_id=attempt_thread_id,
                    image_path=normalized_image_paths[0] if normalized_image_paths else None,
                    progress_callback=progress.handle_executor_event,
                    cancel_event=cancel_event,
                )
                runtime_hooks.emit_phase_timing_fn(
                    chat_id=chat_id,
                    message_id=message_id,
                    phase="engine_run",
                    started_at_monotonic=engine_started_at,
                    attempt=attempt,
                    success=True,
                    returncode=result.returncode,
                    fallback_signature=True,
                )
        except ExecutorCancelledError:
            runtime_hooks.emit_phase_timing_fn(
                chat_id=chat_id,
                message_id=message_id,
                phase="engine_run",
                started_at_monotonic=engine_started_at,
                attempt=attempt,
                success=False,
                error_type="ExecutorCancelledError",
            )
            logging.info("Executor canceled for chat_id=%s", chat_id)
            runtime_hooks.emit_event_fn(
                "bridge.request_cancelled",
                fields={"chat_id": chat_id, "message_id": message_id, "attempt": attempt},
            )
            progress.mark_failure("Execution canceled.")
            runtime_hooks.send_canceled_response_fn(client, chat_id, message_id, message_thread_id)
            return None
        except subprocess.TimeoutExpired:
            runtime_hooks.emit_phase_timing_fn(
                chat_id=chat_id,
                message_id=message_id,
                phase="engine_run",
                started_at_monotonic=engine_started_at,
                attempt=attempt,
                success=False,
                error_type="TimeoutExpired",
            )
            logging.warning("Executor timeout for chat_id=%s", chat_id)
            runtime_hooks.emit_event_fn(
                "bridge.request_timeout",
                level=logging.WARNING,
                fields={"chat_id": chat_id, "message_id": message_id, "attempt": attempt},
            )
            progress.mark_failure("Execution timed out.")
            client.send_message(
                chat_id,
                config.timeout_message,
                reply_to_message_id=message_id,
                message_thread_id=message_thread_id,
            )
            return None
        except FileNotFoundError:
            runtime_hooks.emit_phase_timing_fn(
                chat_id=chat_id,
                message_id=message_id,
                phase="engine_run",
                started_at_monotonic=engine_started_at,
                attempt=attempt,
                success=False,
                error_type="FileNotFoundError",
            )
            logging.exception("Executor command not found: %s", config.executor_cmd)
            runtime_hooks.emit_event_fn(
                "bridge.executor_missing",
                level=logging.ERROR,
                fields={"chat_id": chat_id, "message_id": message_id},
            )
            progress.mark_failure("Executor command not found.")
            client.send_message(
                chat_id,
                config.generic_error_message,
                reply_to_message_id=message_id,
                message_thread_id=message_thread_id,
            )
            return None
        except Exception:
            runtime_hooks.emit_phase_timing_fn(
                chat_id=chat_id,
                message_id=message_id,
                phase="engine_run",
                started_at_monotonic=engine_started_at,
                attempt=attempt,
                success=False,
                error_type="Exception",
            )
            logging.exception("Unexpected executor error for chat_id=%s", chat_id)
            runtime_hooks.emit_event_fn(
                "bridge.executor_exception",
                level=logging.WARNING,
                fields={"chat_id": chat_id, "message_id": message_id, "attempt": attempt},
            )
            if allow_automatic_retry and not retry_attempted:
                retry_attempted = True
                if session_continuity_enabled:
                    state_repo.clear_thread_id(scope_key)
                attempt_thread_id = None
                progress.set_phase(runtime_hooks.retry_with_new_session_phase)
                runtime_hooks.emit_event_fn(
                    "bridge.request_retry_scheduled",
                    level=logging.WARNING,
                    fields={
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "attempt": attempt,
                        "reason": "executor_exception",
                    },
                )
                continue
            progress.mark_failure("Execution failed before completion.")
            runtime_hooks.send_executor_failure_message_fn(
                client=client,
                config=config,
                chat_id=chat_id,
                message_id=message_id,
                allow_automatic_retry=allow_automatic_retry,
                message_thread_id=message_thread_id,
            )
            return None

        if result.returncode == 0:
            runtime_hooks.emit_event_fn(
                "bridge.executor_completed",
                fields={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "attempt": attempt,
                },
            )
            return result

        reset_and_retry_new = False
        failure_message = runtime_hooks.extract_executor_failure_message_fn(
            result.stdout or "",
            result.stderr or "",
        )
        if attempt_thread_id and runtime_hooks.should_reset_thread_after_resume_failure_fn(
            result.stderr or "",
            result.stdout or "",
        ):
            logging.warning(
                "Executor failed for chat_id=%s on resume due to invalid thread; "
                "clearing thread and retrying as new. stderr=%r",
                chat_id,
                (result.stderr or "")[-1000:],
            )
            reset_and_retry_new = True
            progress.set_phase(runtime_hooks.resume_retry_phase_fn(config))
            runtime_hooks.emit_event_fn(
                "bridge.request_retry_scheduled",
                level=logging.WARNING,
                fields={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "attempt": attempt,
                    "reason": "invalid_resume_thread",
                },
            )
        elif failure_message:
            logging.warning(
                "Executor failed for chat_id=%s with surfaced failure=%r",
                chat_id,
                failure_message,
            )
        # Generic nonzero exits are often long-running Codex failures that will
        # simply repeat on a fresh session. Only pay the retry cost when the
        # stored resume thread itself is invalid and a new session can help.

        if reset_and_retry_new:
            if session_continuity_enabled:
                state_repo.clear_thread_id(scope_key)
            attempt_thread_id = None
            retry_attempted = True
            continue

        logging.error(
            "Executor failed for chat_id=%s returncode=%s stderr=%r",
            chat_id,
            result.returncode,
            (result.stderr or "")[-1000:],
        )
        runtime_hooks.emit_event_fn(
            "bridge.request_failed",
            level=logging.WARNING,
            fields={
                "chat_id": chat_id,
                "message_id": message_id,
                "attempt": attempt,
                "returncode": result.returncode,
            },
        )
        progress.mark_failure("Execution failed.")
        runtime_hooks.send_executor_failure_message_fn(
            client=client,
            config=config,
            chat_id=chat_id,
            message_id=message_id,
            allow_automatic_retry=retry_attempted,
            failure_message=failure_message,
            message_thread_id=message_thread_id,
        )
        return None


def finalize_prompt_success(
    state_repo: StateRepository,
    config,
    client: ChannelAdapter,
    chat_id: int,
    message_id: Optional[int],
    result: subprocess.CompletedProcess[str],
    progress,
    scope_key: Optional[str] = None,
    message_thread_id: Optional[int] = None,
    runtime_hooks: Optional[PromptRuntimeHooks] = None,
) -> tuple[Optional[str], str]:
    runtime_hooks = runtime_hooks or build_prompt_runtime_hooks()
    if scope_key is None:
        scope_key = runtime_hooks.build_scope_key_fn(chat_id, message_thread_id=message_thread_id)
    new_thread_id, output = runtime_hooks.parse_executor_output_fn(result.stdout or "")
    if new_thread_id:
        state_repo.set_thread_id(scope_key, new_thread_id)
    if not output:
        output = config.empty_output_message
    if not runtime_hooks.output_contains_control_directive_fn(output):
        output = runtime_hooks.trim_output_fn(output, config.max_output_chars)
    progress.mark_success()
    delivered_output = runtime_hooks.deliver_output_and_emit_success_fn(
        client=client,
        chat_id=chat_id,
        message_id=message_id,
        output=output,
        message_thread_id=message_thread_id,
        new_thread_id=bool(new_thread_id),
    )
    return new_thread_id, delivered_output
