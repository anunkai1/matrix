import threading
from typing import List, Optional

from telegram_bridge.channel_adapter import ChannelAdapter
from telegram_bridge import engine_controls
from telegram_bridge.engine_adapter import EngineAdapter
from telegram_bridge.handler_models import DocumentPayload
from telegram_bridge import request_worker_requests
from telegram_bridge.state_store import State

resolve_engine_for_scope = engine_controls.resolve_engine_for_scope


def _build_and_dispatch(build_fn, dispatch_fn, *args) -> None:
    dispatch_fn(build_fn(*args))


def _build_and_start(build_fn, start_fn, *args) -> None:
    start_fn(build_fn(*args))


def _prompt_worker_args(
    state: State,
    config,
    client: ChannelAdapter,
    engine: Optional[EngineAdapter],
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    prompt: str,
    raw_prompt: str,
    photo_file_id: Optional[str],
    voice_file_id: Optional[str],
    document: Optional[DocumentPayload],
    cancel_event: Optional[threading.Event],
    stateless: bool,
    sender_name: str,
    photo_file_ids: Optional[List[str]],
    actor_user_id: Optional[int],
    enforce_voice_prefix_from_transcript: bool,
    prompt_diagnostics,
    delivery_metadata,
):
    return (
        state,
        config,
        client,
        engine,
        scope_key,
        chat_id,
        message_thread_id,
        message_id,
        prompt,
        raw_prompt,
        photo_file_id,
        voice_file_id,
        document,
        cancel_event,
        stateless,
        sender_name,
        photo_file_ids,
        actor_user_id,
        enforce_voice_prefix_from_transcript,
        prompt_diagnostics,
        delivery_metadata,
    )


def process_prompt(
    state: State,
    config,
    client: ChannelAdapter,
    engine: Optional[EngineAdapter],
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    prompt: str,
    photo_file_id: Optional[str],
    voice_file_id: Optional[str],
    document: Optional[DocumentPayload],
    cancel_event: Optional[threading.Event] = None,
    stateless: bool = False,
    sender_name: str = "Telegram User",
    photo_file_ids: Optional[List[str]] = None,
    actor_user_id: Optional[int] = None,
    enforce_voice_prefix_from_transcript: bool = False,
    prompt_diagnostics=None,
    raw_prompt: str = "",
    delivery_metadata=None,
) -> None:
    _build_and_dispatch(
        request_worker_requests.build_prompt_worker_request,
        request_worker_requests.process_prompt,
        *_prompt_worker_args(
            state,
            config,
            client,
            engine,
            scope_key,
            chat_id,
            message_thread_id,
            message_id,
            prompt,
            raw_prompt,
            photo_file_id,
            voice_file_id,
            document,
            cancel_event,
            stateless,
            sender_name,
            photo_file_ids,
            actor_user_id,
            enforce_voice_prefix_from_transcript,
            prompt_diagnostics,
            delivery_metadata,
        ),
    )


def process_message_worker(
    state: State,
    config,
    client: ChannelAdapter,
    engine: Optional[EngineAdapter],
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    prompt: str,
    photo_file_id: Optional[str],
    voice_file_id: Optional[str],
    document: Optional[DocumentPayload],
    cancel_event: Optional[threading.Event] = None,
    stateless: bool = False,
    sender_name: str = "Telegram User",
    photo_file_ids: Optional[List[str]] = None,
    actor_user_id: Optional[int] = None,
    enforce_voice_prefix_from_transcript: bool = False,
    prompt_diagnostics=None,
    raw_prompt: str = "",
    delivery_metadata=None,
) -> None:
    _build_and_dispatch(
        request_worker_requests.build_prompt_worker_request,
        request_worker_requests.process_message_worker,
        *_prompt_worker_args(
            state,
            config,
            client,
            engine,
            scope_key,
            chat_id,
            message_thread_id,
            message_id,
            prompt,
            raw_prompt,
            photo_file_id,
            voice_file_id,
            document,
            cancel_event,
            stateless,
            sender_name,
            photo_file_ids,
            actor_user_id,
            enforce_voice_prefix_from_transcript,
            prompt_diagnostics,
            delivery_metadata,
        ),
    )


def start_message_worker(
    state: State,
    config,
    client: ChannelAdapter,
    engine: Optional[EngineAdapter],
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    prompt: str,
    photo_file_id: Optional[str],
    voice_file_id: Optional[str],
    document: Optional[DocumentPayload],
    cancel_event: Optional[threading.Event] = None,
    stateless: bool = False,
    sender_name: str = "Telegram User",
    photo_file_ids: Optional[List[str]] = None,
    actor_user_id: Optional[int] = None,
    enforce_voice_prefix_from_transcript: bool = False,
    prompt_diagnostics=None,
    raw_prompt: str = "",
    delivery_metadata=None,
) -> None:
    _build_and_start(
        request_worker_requests.build_prompt_worker_request,
        request_worker_requests.start_message_worker,
        *_prompt_worker_args(
            state,
            config,
            client,
            engine,
            scope_key,
            chat_id,
            message_thread_id,
            message_id,
            prompt,
            raw_prompt,
            photo_file_id,
            voice_file_id,
            document,
            cancel_event,
            stateless,
            sender_name,
            photo_file_ids,
            actor_user_id,
            enforce_voice_prefix_from_transcript,
            prompt_diagnostics,
            delivery_metadata,
        ),
    )


def process_youtube_request(
    state: State,
    config,
    client: ChannelAdapter,
    engine: Optional[EngineAdapter],
    chat_id: int,
    request_text: str,
    youtube_url: str,
    message_thread_id: Optional[int] = None,
    message_id: Optional[int] = None,
    scope_key: Optional[str] = None,
    actor_user_id: Optional[int] = None,
    cancel_event: Optional[threading.Event] = None,
) -> None:
    _build_and_dispatch(
        request_worker_requests.build_youtube_worker_request,
        request_worker_requests.process_youtube_request,
        state,
        config,
        client,
        engine,
        scope_key,
        chat_id,
        message_thread_id,
        message_id,
        request_text,
        youtube_url,
        actor_user_id,
        cancel_event,
    )


def process_youtube_worker(
    state: State,
    config,
    client: ChannelAdapter,
    engine: Optional[EngineAdapter],
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    request_text: str,
    youtube_url: str,
    actor_user_id: Optional[int] = None,
    cancel_event: Optional[threading.Event] = None,
) -> None:
    _build_and_dispatch(
        request_worker_requests.build_youtube_worker_request,
        request_worker_requests.process_youtube_worker,
        state,
        config,
        client,
        engine,
        scope_key,
        chat_id,
        message_thread_id,
        message_id,
        request_text,
        youtube_url,
        actor_user_id,
        cancel_event,
    )


def start_youtube_worker(
    state: State,
    config,
    client: ChannelAdapter,
    engine: Optional[EngineAdapter],
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    request_text: str,
    youtube_url: str,
    actor_user_id: Optional[int] = None,
    cancel_event: Optional[threading.Event] = None,
) -> None:
    _build_and_start(
        request_worker_requests.build_youtube_worker_request,
        request_worker_requests.start_youtube_worker,
        state,
        config,
        client,
        engine,
        scope_key,
        chat_id,
        message_thread_id,
        message_id,
        request_text,
        youtube_url,
        actor_user_id,
        cancel_event,
    )
