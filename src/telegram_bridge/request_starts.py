import threading
from typing import List, Optional

try:
    from . import engine_controls
    from .handler_models import DocumentPayload
    from .handler_models import build_dishframed_request, build_prompt_request, build_youtube_request
    from .channel_adapter import ChannelAdapter
    from .engine_adapter import EngineAdapter
    from .state_store import State
    from . import response_delivery
except ImportError:
    import engine_controls
    from handler_models import DocumentPayload
    from handler_models import build_dishframed_request, build_prompt_request, build_youtube_request
    from channel_adapter import ChannelAdapter
    from engine_adapter import EngineAdapter
    from state_store import State
    import response_delivery


start_background_worker = response_delivery.start_background_worker
resolve_engine_for_scope = engine_controls.resolve_engine_for_scope


try:
    from . import bridge_deps as handlers
except ImportError:
    import bridge_deps as handlers


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
    handlers._process_prompt_request(
        build_prompt_request(
            state=state,
            config=config,
            client=client,
            engine=engine,
            scope_key=scope_key,
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            message_id=message_id,
            prompt=prompt,
            photo_file_id=photo_file_id,
            voice_file_id=voice_file_id,
            document=document,
            cancel_event=cancel_event,
            stateless=stateless,
            sender_name=sender_name,
            photo_file_ids=photo_file_ids,
            actor_user_id=actor_user_id,
            enforce_voice_prefix_from_transcript=enforce_voice_prefix_from_transcript,
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
    handlers._process_message_worker_request(
        build_prompt_request(
            state=state,
            config=config,
            client=client,
            engine=engine,
            scope_key=scope_key,
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            message_id=message_id,
            prompt=prompt,
            photo_file_id=photo_file_id,
            voice_file_id=voice_file_id,
            document=document,
            cancel_event=cancel_event,
            stateless=stateless,
            sender_name=sender_name,
            photo_file_ids=photo_file_ids,
            actor_user_id=actor_user_id,
            enforce_voice_prefix_from_transcript=enforce_voice_prefix_from_transcript,
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
    request = build_prompt_request(
        state=state,
        config=config,
        client=client,
        engine=engine,
        scope_key=scope_key,
        chat_id=chat_id,
        message_thread_id=message_thread_id,
        message_id=message_id,
        prompt=prompt,
        photo_file_id=photo_file_id,
        voice_file_id=voice_file_id,
        document=document,
        cancel_event=cancel_event,
        stateless=stateless,
        sender_name=sender_name,
        photo_file_ids=photo_file_ids,
        actor_user_id=actor_user_id,
        enforce_voice_prefix_from_transcript=enforce_voice_prefix_from_transcript,
    )
    start_background_worker(handlers._process_message_worker_request, request)


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
    if scope_key is None:
        scope_key = handlers.build_telegram_scope_key(chat_id, message_thread_id=message_thread_id)
    handlers._process_youtube_request(
        build_youtube_request(
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
    handlers._process_youtube_worker_request(
        build_youtube_request(
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
    start_background_worker(
        handlers._process_youtube_worker_request,
        build_youtube_request(
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
        ),
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
    handlers._process_dishframed_request(
        build_dishframed_request(
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
    handlers._process_dishframed_worker_request(
        build_dishframed_request(
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
    start_background_worker(
        handlers._process_dishframed_worker_request,
        build_dishframed_request(
            state=state,
            config=config,
            client=client,
            scope_key=scope_key,
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            message_id=message_id,
            photo_file_ids=photo_file_ids,
            cancel_event=cancel_event,
        ),
    )
