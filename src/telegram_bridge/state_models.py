import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from telegram_bridge.conversation_scope import normalize_scope_storage_key

ScopeKey = str

def normalize_scope_key(scope_key: object) -> ScopeKey:
    normalized = normalize_scope_storage_key(scope_key)
    if normalized is None:
        raise ValueError(f"Invalid scope key: {scope_key!r}")
    return normalized

@dataclass
class CanonicalSession:
    thread_id: str = ""
    worker_created_at: Optional[float] = None
    worker_last_used_at: Optional[float] = None
    worker_policy_fingerprint: str = ""
    in_flight_started_at: Optional[float] = None
    in_flight_message_id: Optional[int] = None

@dataclass
class WorkerSession:
    created_at: float
    last_used_at: float
    thread_id: str
    policy_fingerprint: str

@dataclass
class PendingMediaGroup:
    chat_id: int
    media_group_id: str
    updates: List[Dict[str, object]] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    last_seen_at: float = field(default_factory=time.time)

@dataclass
class PendingDiaryBatch:
    scope_key: str
    chat_id: int
    message_thread_id: Optional[int]
    latest_message_id: Optional[int]
    sender_name: str
    actor_user_id: Optional[int]
    messages: List[Dict[str, object]] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    last_seen_at: float = field(default_factory=time.time)
    worker_started: bool = False

@dataclass
class RecentPhotoSelection:
    photo_file_ids: List[str] = field(default_factory=list)
    message_id: Optional[int] = None
    captured_at: float = field(default_factory=time.time)

@dataclass
class State:
    started_at: float = field(default_factory=time.time)
    busy_chats: Set[ScopeKey] = field(default_factory=set)
    recent_requests: Dict[ScopeKey, List[float]] = field(default_factory=dict)
    chat_threads: Dict[ScopeKey, str] = field(default_factory=dict)
    chat_thread_path: str = ""
    chat_engines: Dict[ScopeKey, str] = field(default_factory=dict)
    chat_engine_path: str = ""
    chat_codex_models: Dict[ScopeKey, str] = field(default_factory=dict)
    chat_codex_model_path: str = ""
    chat_codex_efforts: Dict[ScopeKey, str] = field(default_factory=dict)
    chat_codex_effort_path: str = ""
    chat_pi_providers: Dict[ScopeKey, str] = field(default_factory=dict)
    chat_pi_provider_path: str = ""
    chat_pi_models: Dict[ScopeKey, str] = field(default_factory=dict)
    chat_pi_model_path: str = ""
    worker_sessions: Dict[ScopeKey, WorkerSession] = field(default_factory=dict)
    worker_sessions_path: str = ""
    in_flight_requests: Dict[ScopeKey, Dict[str, object]] = field(default_factory=dict)
    in_flight_path: str = ""
    canonical_sessions_enabled: bool = False
    canonical_legacy_mirror_enabled: bool = False
    canonical_sqlite_enabled: bool = False
    canonical_sqlite_path: str = ""
    canonical_json_mirror_enabled: bool = False
    chat_sessions: Dict[ScopeKey, CanonicalSession] = field(default_factory=dict)
    chat_sessions_path: str = ""
    restart_requested: bool = False
    restart_in_progress: bool = False
    restart_chat_id: Optional[int] = None
    restart_message_thread_id: Optional[int] = None
    restart_reply_to_message_id: Optional[int] = None
    affective_runtime: Optional[object] = None
    attachment_store: Optional[object] = None
    voice_alias_learning_store: Optional[object] = None
    cancel_events: Dict[ScopeKey, threading.Event] = field(default_factory=dict)
    pending_media_groups: Dict[str, PendingMediaGroup] = field(default_factory=dict)
    recent_scope_photos: Dict[ScopeKey, RecentPhotoSelection] = field(default_factory=dict)
    pending_diary_batches: Dict[ScopeKey, PendingDiaryBatch] = field(default_factory=dict)
    queued_diary_batches: Dict[ScopeKey, List[PendingDiaryBatch]] = field(default_factory=dict)
    diary_queue_processing_scopes: Set[ScopeKey] = field(default_factory=set)
    auth_fingerprint_path: str = ""
    auth_fingerprint: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock)
    auth_change_lock: threading.Lock = field(default_factory=threading.Lock)
