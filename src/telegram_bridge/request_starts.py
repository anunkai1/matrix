import threading
from typing import List, Optional

from telegram_bridge.channel_adapter import ChannelAdapter
from telegram_bridge import engine_controls
from telegram_bridge.engine_adapter import EngineAdapter
from telegram_bridge.handler_models import (
    DocumentPayload,
)
from telegram_bridge import request_worker_requests
from telegram_bridge.state_store import State

resolve_engine_for_scope = engine_controls.resolve_engine_for_scope


def _build_prompt_worker_request(
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
    cancel_event: Optional[threading.Event],
    stateless: bool,
    sender_name: str,
    photo_file_ids: Optional[List[str]],
    actor_user_id: Optional[int],
    enforce_voice_prefix_from_transcript: bool,
):
    return request_worker_requests.build_prompt_worker_request(
        state,
        config,
        client,
        engine,
        scope_key,
        chat_id,
        message_thread_id,
        message_id,
        prompt,
        photo_file_id,
        voice_file_id,
        document,
        cancel_event,
        stateless,
        sender_name,
        photo_file_ids,
        actor_user_id,
        enforce_voice_prefix_from_transcript,
    )


def _build_youtube_worker_request(
    state: State,
    config,
    client: ChannelAdapter,
    engine: Optional[EngineAdapter],
    scope_key: Optional[str],
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    request_text: str,
    youtube_url: str,
    actor_user_id: Optional[int],
    cancel_event: Optional[threading.Event],
):
    return request_worker_requests.build_youtube_worker_request(
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


def _build_dishframed_worker_request(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    photo_file_ids: List[str],
    cancel_event: Optional[threading.Event],
):
    return request_worker_requests.build_dishframed_worker_request(
        state,
        config,
        client,
        scope_key,
        chat_id,
        message_thread_id,
        message_id,
        photo_file_ids,
        cancel_event,
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
) -> None:
    request_worker_requests.process_prompt(
        _build_prompt_worker_request(
            state,
            config,
            client,
            engine,
            scope_key,
            chat_id,
            message_thread_id,
            message_id,
            prompt,
            photo_file_id,
            voice_file_id,
            document,
            cancel_event,
            stateless,
            sender_name,
            photo_file_ids,
            actor_user_id,
            enforce_voice_prefix_from_transcript,
        )
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
) -> None:
    request_worker_requests.process_message_worker(
        _build_prompt_worker_request(
            state,
            config,
            client,
            engine,
            scope_key,
            chat_id,
            message_thread_id,
            message_id,
            prompt,
            photo_file_id,
            voice_file_id,
            document,
            cancel_event,
            stateless,
            sender_name,
            photo_file_ids,
            actor_user_id,
            enforce_voice_prefix_from_transcript,
        )
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
) -> None:
    request = _build_prompt_worker_request(
        state,
        config,
        client,
        engine,
        scope_key,
        chat_id,
        message_thread_id,
        message_id,
        prompt,
        photo_file_id,
        voice_file_id,
        document,
        cancel_event,
        stateless,
        sender_name,
        photo_file_ids,
        actor_user_id,
        enforce_voice_prefix_from_transcript,
    )
    request_worker_requests.start_message_worker(request)


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
    request_worker_requests.process_youtube_request(
        _build_youtube_worker_request(
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
    request_worker_requests.process_youtube_worker(
        _build_youtube_worker_request(
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
    request_worker_requests.start_youtube_worker(
        _build_youtube_worker_request(
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
    )


def process_dishframed_request(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    photo_file_ids: List[str],
    cancel_event: Optional[threading.Event] = None,
) -> None:
    request_worker_requests.process_dishframed_request(
        _build_dishframed_worker_request(
            state,
            config,
            client,
            scope_key,
            chat_id,
            message_thread_id,
            message_id,
            photo_file_ids,
            cancel_event,
        )
    )


def process_dishframed_worker(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    photo_file_ids: List[str],
    cancel_event: Optional[threading.Event] = None,
) -> None:
    request_worker_requests.process_dishframed_worker(
        _build_dishframed_worker_request(
            state,
            config,
            client,
            scope_key,
            chat_id,
            message_thread_id,
            message_id,
            photo_file_ids,
            cancel_event,
        )
    )


def start_dishframed_worker(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    photo_file_ids: List[str],
    cancel_event: Optional[threading.Event] = None,
) -> None:
    request_worker_requests.start_dishframed_worker(
        _build_dishframed_worker_request(
            state,
            config,
            client,
            scope_key,
            chat_id,
            message_thread_id,
            message_id,
            photo_file_ids,
            cancel_event,
        )
    )
