import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    from .channel_adapter import ChannelAdapter
    from .engine_adapter import EngineAdapter
    from .state_store import State
except ImportError:
    from channel_adapter import ChannelAdapter
    from engine_adapter import EngineAdapter
    from state_store import State


@dataclass
class DocumentPayload:
    file_id: str
    file_name: str
    mime_type: str


@dataclass
class PreparedPromptInput:
    prompt_text: str
    image_path: Optional[str] = None
    image_paths: List[str] = field(default_factory=list)
    document_path: Optional[str] = None
    cleanup_paths: List[str] = field(default_factory=list)
    attachment_file_ids: List[str] = field(default_factory=list)


@dataclass
class OutboundMediaDirective:
    media_ref: str
    as_voice: bool


@dataclass(frozen=True)
class KnownCommandContext:
    state: State
    config: Any
    client: ChannelAdapter
    scope_key: str
    chat_id: int
    message_thread_id: Optional[int]
    message_id: Optional[int]
    raw_text: str


@dataclass(frozen=True)
class CallbackActionContext:
    state: State
    config: Any
    client: ChannelAdapter
    scope_key: str
    chat_id: int
    message_thread_id: Optional[int]
    message_id: Optional[int]
    callback_query_id: str
    kind: str
    engine_name: str
    action: str
    value: str


@dataclass(frozen=True)
class CallbackActionResult:
    text: str
    reply_markup: Optional[Dict[str, object]] = None
    toast_text: str = "Updated."


@dataclass(frozen=True)
class PromptRequest:
    state: State
    config: Any
    client: ChannelAdapter
    engine: Optional[EngineAdapter]
    scope_key: str
    chat_id: int
    message_thread_id: Optional[int]
    message_id: Optional[int]
    prompt: str
    photo_file_id: Optional[str]
    voice_file_id: Optional[str]
    document: Optional[DocumentPayload]
    cancel_event: Optional[threading.Event] = None
    stateless: bool = False
    sender_name: str = "Telegram User"
    photo_file_ids: Optional[List[str]] = None
    actor_user_id: Optional[int] = None
    enforce_voice_prefix_from_transcript: bool = False


@dataclass(frozen=True)
class YoutubeRequest:
    state: State
    config: Any
    client: ChannelAdapter
    engine: Optional[EngineAdapter]
    scope_key: str
    chat_id: int
    message_thread_id: Optional[int]
    message_id: Optional[int]
    request_text: str
    youtube_url: str
    actor_user_id: Optional[int] = None
    cancel_event: Optional[threading.Event] = None


@dataclass(frozen=True)
class DishframedRequest:
    state: State
    config: Any
    client: ChannelAdapter
    scope_key: str
    chat_id: int
    message_thread_id: Optional[int]
    message_id: Optional[int]
    photo_file_ids: List[str]
    cancel_event: Optional[threading.Event] = None


@dataclass(frozen=True)
class UpdateDispatchRequest:
    state: State
    config: Any
    client: ChannelAdapter
    engine: Optional[EngineAdapter]
    scope_key: str
    chat_id: int
    message_thread_id: Optional[int]
    message_id: Optional[int]
    prompt: str
    raw_prompt: str
    photo_file_ids: List[str]
    voice_file_id: Optional[str]
    document: Optional[DocumentPayload]
    actor_user_id: Optional[int]
    sender_name: str
    stateless: bool
    enforce_voice_prefix_from_transcript: bool
    youtube_route_url: Optional[str] = None
    handle_update_started_at: Optional[float] = None


@dataclass(frozen=True)
class IncomingUpdateContext:
    update: Dict[str, object]
    message: Dict[str, object]
    chat_id: int
    message_thread_id: Optional[int]
    scope_key: str
    message_id: Optional[int]
    actor_user_id: Optional[int]
    is_private_chat: bool
    update_id: Optional[int]


@dataclass(frozen=True)
class PreparedUpdateRequest:
    ctx: IncomingUpdateContext
    prompt_input: Optional[str]
    photo_file_ids: List[str]
    voice_file_id: Optional[str]
    document: Optional[DocumentPayload]
    reply_context_prompt: str
    telegram_context_prompt: str
    enforce_voice_prefix_from_transcript: bool
    sender_name: str
    command: Optional[str]


@dataclass
class UpdateFlowState:
    state: State
    config: Any
    client: ChannelAdapter
    engine: Optional[EngineAdapter]
    ctx: IncomingUpdateContext
    prompt_input: Optional[str]
    photo_file_ids: List[str]
    voice_file_id: Optional[str]
    document: Optional[DocumentPayload]
    reply_context_prompt: str
    telegram_context_prompt: str
    enforce_voice_prefix_from_transcript: bool
    sender_name: str
    command: Optional[str]
    stateless: bool = False
    priority_keyword_mode: bool = False
    youtube_route_url: Optional[str] = None


def build_prompt_request(
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
) -> PromptRequest:
    return PromptRequest(
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


def build_youtube_request(
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
) -> YoutubeRequest:
    return YoutubeRequest(
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


def build_dishframed_request(
    state: State,
    config,
    client: ChannelAdapter,
    scope_key: str,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    photo_file_ids: List[str],
    cancel_event: Optional[threading.Event] = None,
) -> DishframedRequest:
    return DishframedRequest(
        state=state,
        config=config,
        client=client,
        scope_key=scope_key,
        chat_id=chat_id,
        message_thread_id=message_thread_id,
        message_id=message_id,
        photo_file_ids=list(photo_file_ids),
        cancel_event=cancel_event,
    )
