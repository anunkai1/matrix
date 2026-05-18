import threading
from typing import List, Optional

from telegram_bridge.channel_adapter import ChannelAdapter
from telegram_bridge.conversation_scope import build_telegram_scope_key
from telegram_bridge.engine_adapter import EngineAdapter
from telegram_bridge.handler_models import (
    DocumentPayload,
    build_dishframed_request,
    build_prompt_request,
    build_youtube_request,
)
from telegram_bridge.request_processing import (
    _process_dishframed_request,
    _process_dishframed_worker_request,
    _process_message_worker_request,
    _process_prompt_request,
    _process_youtube_request,
    _process_youtube_worker_request,
)
from telegram_bridge.response_delivery import start_background_worker
from telegram_bridge.state_store import State


def _start_worker(processor, request) -> None:
    start_background_worker(processor, request)


def build_prompt_worker_request(
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
    prompt_diagnostics=None,
    delivery_metadata=None,
):
    return build_prompt_request(
        state=state,
        config=config,
        client=client,
        engine=engine,
        scope_key=scope_key,
        chat_id=chat_id,
        message_thread_id=message_thread_id,
        message_id=message_id,
        prompt=prompt,
        raw_prompt=raw_prompt,
        photo_file_id=photo_file_id,
        voice_file_id=voice_file_id,
        document=document,
        cancel_event=cancel_event,
        stateless=stateless,
        sender_name=sender_name,
        photo_file_ids=photo_file_ids,
        actor_user_id=actor_user_id,
        enforce_voice_prefix_from_transcript=enforce_voice_prefix_from_transcript,
        prompt_diagnostics=prompt_diagnostics,
        delivery_metadata=delivery_metadata,
    )


def build_youtube_worker_request(
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
    if scope_key is None:
        scope_key = build_telegram_scope_key(chat_id, message_thread_id=message_thread_id)
    return build_youtube_request(
        state=state,
        config=config,
        client=client,
        engine=engine,
        scope_key=scope_key,
        chat_id=chat_id,
        message_thread_id=message_thread_id,
        message_id=message_id,
        request_text=request_text,
        youtube_url=youtube_url,
        actor_user_id=actor_user_id,
        cancel_event=cancel_event,
    )


def build_dishframed_worker_request(
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
    return build_dishframed_request(
        state=state,
        config=config,
        client=client,
        scope_key=scope_key,
        chat_id=chat_id,
        message_thread_id=message_thread_id,
        message_id=message_id,
        photo_file_ids=photo_file_ids,
        cancel_event=cancel_event,
    )


def process_prompt(request) -> None:
    _process_prompt_request(request)


def process_message_worker(request) -> None:
    _process_message_worker_request(request)


def start_message_worker(request) -> None:
    _start_worker(_process_message_worker_request, request)


def process_youtube_request(request) -> None:
    _process_youtube_request(request)


def process_youtube_worker(request) -> None:
    _process_youtube_worker_request(request)


def start_youtube_worker(request) -> None:
    _start_worker(_process_youtube_worker_request, request)


def process_dishframed_request(request) -> None:
    _process_dishframed_request(request)


def process_dishframed_worker(request) -> None:
    _process_dishframed_worker_request(request)


def start_dishframed_worker(request) -> None:
    _start_worker(_process_dishframed_worker_request, request)
