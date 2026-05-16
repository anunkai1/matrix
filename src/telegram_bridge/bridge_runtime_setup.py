import logging
import os
import time
from dataclasses import dataclass
from typing import Dict, Optional

from telegram_bridge.affective_runtime import build_affective_runtime
from telegram_bridge.auth_state import (
    apply_auth_change_thread_reset,
    build_auth_fingerprint_state_path,
    clear_loaded_thread_state,
    compute_current_auth_fingerprint,
)
from telegram_bridge.attachment_store import AttachmentStore
from telegram_bridge.bridge_state_bootstrap import (
    build_bridge_state_paths,
    build_policy_fingerprint_state_path,
    load_bridge_state_mappings,
    load_canonical_session_bootstrap,
    load_saved_policy_fingerprint,
    persist_saved_policy_fingerprint,
)
from telegram_bridge.runtime_config import Config
from telegram_bridge.session_manager import compute_policy_fingerprint
from telegram_bridge.state_store import (
    CanonicalSession,
    State,
    WorkerSession,
    build_canonical_sessions_from_legacy,
    ensure_state_dir,
    persist_canonical_sessions,
    persist_chat_threads,
    persist_worker_sessions,
)
from telegram_bridge.structured_logging import emit_event
from telegram_bridge.update_flow import UpdateFlowDependencies
from telegram_bridge.voice_alias_learning import VoiceAliasLearningStore


@dataclass
class RuntimeBootstrap:
    state: State
    state_paths: Dict[str, str]
    loaded_threads: Dict[int, str]
    loaded_worker_sessions: Dict[int, WorkerSession]
    loaded_in_flight: Dict[int, Dict[str, object]]
    canonical_bootstrap_source: str
    affective_runtime: object
    voice_alias_learning_store: Optional[VoiceAliasLearningStore]
    update_flow_dependencies: Optional[UpdateFlowDependencies] = None


def build_update_flow_dependencies() -> UpdateFlowDependencies:
    from telegram_bridge import handlers

    return UpdateFlowDependencies(
        get_recent_scope_photos=handlers.get_recent_scope_photos,
        mark_busy=handlers.mark_busy,
        emit_event=handlers.emit_event,
        register_cancel_event=handlers.register_cancel_event,
        start_dishframed_worker=handlers.start_dishframed_worker,
        resolve_engine_for_scope=handlers.resolve_engine_for_scope,
        ensure_chat_worker_session=handlers.ensure_chat_worker_session,
        start_youtube_worker=handlers.start_youtube_worker,
        start_message_worker=handlers.start_message_worker,
        emit_phase_timing=handlers.emit_phase_timing,
        dishframed_usage_message=handlers.DISHFRAMED_USAGE_MESSAGE,
        diary_mode_enabled=handlers.diary_mode_enabled,
        handle_known_command=handlers.handle_known_command,
        queue_diary_capture=handlers.queue_diary_capture,
    )


def clear_thread_state_for_policy_change(
    loaded_threads: Dict[int, str],
    loaded_worker_sessions: Dict[int, WorkerSession],
    loaded_canonical_sessions: Dict[int, CanonicalSession],
) -> Dict[str, int]:
    return clear_loaded_thread_state(
        loaded_threads,
        loaded_worker_sessions,
        loaded_canonical_sessions,
    )


def apply_policy_change_thread_reset(
    state_dir: str,
    current_policy_fingerprint: str,
    loaded_threads: Dict[int, str],
    loaded_worker_sessions: Dict[int, WorkerSession],
    loaded_canonical_sessions: Dict[int, CanonicalSession],
) -> Dict[str, object]:
    if not current_policy_fingerprint.strip():
        return {
            "applied": False,
            "previous_policy_fingerprint": "",
            "counts": {"threads": 0, "worker_sessions": 0, "canonical_sessions": 0},
        }

    state_path = build_policy_fingerprint_state_path(state_dir)
    previous_policy_fingerprint = load_saved_policy_fingerprint(state_path)
    reset_counts = {"threads": 0, "worker_sessions": 0, "canonical_sessions": 0}
    applied = False

    if (
        previous_policy_fingerprint
        and previous_policy_fingerprint != current_policy_fingerprint
    ):
        reset_counts = clear_thread_state_for_policy_change(
            loaded_threads,
            loaded_worker_sessions,
            loaded_canonical_sessions,
        )
        applied = any(reset_counts.values())

    persist_saved_policy_fingerprint(state_path, current_policy_fingerprint)
    return {
        "applied": applied,
        "previous_policy_fingerprint": previous_policy_fingerprint,
        "counts": reset_counts,
    }


def initialize_voice_alias_learning_store(
    config: Config,
) -> Optional[VoiceAliasLearningStore]:
    if not config.voice_alias_learning_enabled:
        return None
    try:
        return VoiceAliasLearningStore(
            path=config.voice_alias_learning_path,
            min_examples=config.voice_alias_learning_min_examples,
            confirmation_window_seconds=config.voice_alias_learning_confirmation_window_seconds,
        )
    except Exception:
        logging.exception(
            "Failed to initialize voice alias learning store at %s; continuing without learning.",
            config.voice_alias_learning_path,
        )
        return None


def _log_thread_reset(
    *,
    reason: str,
    counts: Dict[str, int],
) -> None:
    logging.warning(
        "%s fingerprint changed; cleared stored thread state "
        "(threads=%s worker_sessions=%s canonical_sessions=%s).",
        reason,
        counts["threads"],
        counts["worker_sessions"],
        counts["canonical_sessions"],
    )
    emit_event(
        f"bridge.thread_state_reset_for_{reason.lower()}_change",
        level=logging.WARNING,
        fields={
            "thread_count": counts["threads"],
            "worker_session_count": counts["worker_sessions"],
            "canonical_session_count": counts["canonical_sessions"],
        },
    )


def build_runtime_bootstrap(config: Config) -> RuntimeBootstrap:
    ensure_state_dir(config.state_dir)
    attachment_store = AttachmentStore(
        os.path.join(config.state_dir, "attachments.sqlite3"),
        os.path.join(config.state_dir, "attachments"),
        retention_seconds=config.attachment_retention_seconds,
        max_total_bytes=config.attachment_max_total_bytes,
    )
    affective_runtime = build_affective_runtime(config)
    state_paths = build_bridge_state_paths(config.state_dir)
    loaded_state = load_bridge_state_mappings(state_paths)
    loaded_threads = loaded_state["threads"]
    loaded_engines = loaded_state["engines"]
    loaded_gemma_models = loaded_state["gemma_models"]
    loaded_codex_models = loaded_state["codex_models"]
    loaded_codex_efforts = loaded_state["codex_efforts"]
    loaded_pi_models = loaded_state["pi_models"]
    loaded_pi_providers = loaded_state["pi_providers"]
    loaded_worker_sessions = loaded_state["worker_sessions"]
    loaded_in_flight = loaded_state["in_flight"]
    loaded_canonical_sessions, canonical_bootstrap_source = load_canonical_session_bootstrap(
        config,
        state_paths,
        loaded_threads,
        loaded_worker_sessions,
        loaded_in_flight,
    )

    current_policy_fingerprint = ""
    if config.persistent_workers_policy_files:
        current_policy_fingerprint = compute_policy_fingerprint(
            config.persistent_workers_policy_files
        )
        policy_reset_result = apply_policy_change_thread_reset(
            state_dir=config.state_dir,
            current_policy_fingerprint=current_policy_fingerprint,
            loaded_threads=loaded_threads,
            loaded_worker_sessions=loaded_worker_sessions,
            loaded_canonical_sessions=loaded_canonical_sessions,
        )
        if policy_reset_result["applied"]:
            _log_thread_reset(
                reason="Policy",
                counts=policy_reset_result["counts"],
            )

    current_auth_fingerprint = compute_current_auth_fingerprint()
    auth_reset_result = apply_auth_change_thread_reset(
        state_dir=config.state_dir,
        current_auth_fingerprint=current_auth_fingerprint,
        loaded_threads=loaded_threads,
        loaded_worker_sessions=loaded_worker_sessions,
        loaded_canonical_sessions=loaded_canonical_sessions,
    )
    if auth_reset_result["applied"]:
        _log_thread_reset(
            reason="Auth",
            counts=auth_reset_result["counts"],
        )

    if config.persistent_workers_enabled and not config.canonical_sessions_enabled:
        now = time.time()
        if not current_policy_fingerprint:
            current_policy_fingerprint = compute_policy_fingerprint(
                config.persistent_workers_policy_files
            )
        if not loaded_worker_sessions and loaded_threads:
            loaded_worker_sessions = {
                chat_id: WorkerSession(
                    created_at=now,
                    last_used_at=now,
                    thread_id=thread_id,
                    policy_fingerprint=current_policy_fingerprint,
                )
                for chat_id, thread_id in loaded_threads.items()
            }
        for chat_id, session in loaded_worker_sessions.items():
            if session.thread_id:
                loaded_threads[chat_id] = session.thread_id

    voice_alias_learning_store = initialize_voice_alias_learning_store(config)
    state = State(
        chat_threads=loaded_threads if not config.canonical_sessions_enabled else {},
        chat_thread_path=state_paths["chat_threads"],
        chat_engines=loaded_engines,
        chat_engine_path=state_paths["chat_engines"],
        chat_gemma_models=loaded_gemma_models,
        chat_gemma_model_path=state_paths["chat_gemma_models"],
        chat_codex_models=loaded_codex_models,
        chat_codex_model_path=state_paths["chat_codex_models"],
        chat_codex_efforts=loaded_codex_efforts,
        chat_codex_effort_path=state_paths["chat_codex_efforts"],
        chat_pi_providers=loaded_pi_providers,
        chat_pi_provider_path=state_paths["chat_pi_providers"],
        chat_pi_models=loaded_pi_models,
        chat_pi_model_path=state_paths["chat_pi_models"],
        worker_sessions=loaded_worker_sessions if not config.canonical_sessions_enabled else {},
        worker_sessions_path=state_paths["worker_sessions"],
        in_flight_requests=loaded_in_flight if not config.canonical_sessions_enabled else {},
        in_flight_path=state_paths["in_flight_requests"],
        canonical_sessions_enabled=config.canonical_sessions_enabled,
        canonical_legacy_mirror_enabled=config.canonical_legacy_mirror_enabled,
        canonical_sqlite_enabled=(
            config.canonical_sessions_enabled and config.canonical_sqlite_enabled
        ),
        canonical_sqlite_path=config.canonical_sqlite_path,
        canonical_json_mirror_enabled=config.canonical_json_mirror_enabled,
        chat_sessions=loaded_canonical_sessions,
        chat_sessions_path=state_paths["chat_sessions"],
        affective_runtime=affective_runtime,
        attachment_store=attachment_store,
        voice_alias_learning_store=voice_alias_learning_store,
        auth_fingerprint_path=build_auth_fingerprint_state_path(config.state_dir),
        auth_fingerprint=current_auth_fingerprint,
    )
    return RuntimeBootstrap(
        state=state,
        state_paths=state_paths,
        loaded_threads=loaded_threads,
        loaded_worker_sessions=loaded_worker_sessions,
        loaded_in_flight=loaded_in_flight,
        canonical_bootstrap_source=canonical_bootstrap_source,
        affective_runtime=affective_runtime,
        voice_alias_learning_store=voice_alias_learning_store,
        update_flow_dependencies=build_update_flow_dependencies(),
    )


def persist_bootstrap_state(config: Config, bootstrap: RuntimeBootstrap) -> None:
    if config.persistent_workers_enabled and not config.canonical_sessions_enabled:
        persist_chat_threads(bootstrap.state)
        persist_worker_sessions(bootstrap.state)
    if config.canonical_sessions_enabled:
        if not bootstrap.state.chat_sessions:
            bootstrap.state.chat_sessions = build_canonical_sessions_from_legacy(
                bootstrap.loaded_threads,
                bootstrap.loaded_worker_sessions,
                bootstrap.loaded_in_flight,
            )
        persist_canonical_sessions(bootstrap.state)
