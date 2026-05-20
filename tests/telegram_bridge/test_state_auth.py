"""Tests for State/Auth — auto-split from test_bridge_core.py."""

import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
from types import SimpleNamespace
from unittest import mock

from tests.telegram_bridge.helpers import (
    FakeDownloadClient,
    FakeProgressEditClient,
    FakeSignalProgressClient,
    FakeTelegramClient,
    make_config,
)

import telegram_bridge.auth_state as bridge_auth_state
import telegram_bridge.channel_adapter as bridge_channel_adapter
import telegram_bridge.command_routing as bridge_command_routing
import telegram_bridge.control_commands as bridge_control_commands
import telegram_bridge.engine_adapter as bridge_engine_adapter
import telegram_bridge.executor as bridge_executor
import telegram_bridge.handlers as bridge_handlers
import telegram_bridge.http_channel as bridge_http_channel
import telegram_bridge.main as bridge
import telegram_bridge.plugin_registry as bridge_plugin_registry
import telegram_bridge.prompt_execution as bridge_prompt_execution
import telegram_bridge.session_manager as bridge_session_manager
import telegram_bridge.signal_channel as bridge_signal_channel
import telegram_bridge.special_request_processing as bridge_special_request_processing
import telegram_bridge.structured_logging as bridge_structured_logging
import telegram_bridge.transport as bridge_transport
import telegram_bridge.voice_alias_commands as bridge_voice_alias_commands
import telegram_bridge.whatsapp_channel as bridge_whatsapp_channel


class TestStateAuth(unittest.TestCase):
    def test_should_reset_thread_after_resume_failure_markers(self):
        self.assertTrue(
            bridge_executor.should_reset_thread_after_resume_failure(
                "Thread not found for resume",
                "",
            )
        )
        self.assertFalse(
            bridge_executor.should_reset_thread_after_resume_failure(
                "permission denied",
                "generic error",
            )
        )

    def test_state_repository_persists_thread_and_inflight_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = bridge.State(
                chat_thread_path=str(Path(tmpdir) / "chat_threads.json"),
                worker_sessions_path=str(Path(tmpdir) / "worker_sessions.json"),
                in_flight_path=str(Path(tmpdir) / "in_flight_requests.json"),
                worker_sessions={
                    "tg:1": bridge.WorkerSession(
                        created_at=1.0,
                        last_used_at=1.0,
                        thread_id="",
                        policy_fingerprint="",
                    )
                },
            )
            repo = bridge.StateRepository(state)

            repo.set_thread_id(1, "thread-xyz")
            threads = json.loads(Path(state.chat_thread_path).read_text(encoding="utf-8"))
            sessions = json.loads(Path(state.worker_sessions_path).read_text(encoding="utf-8"))
            self.assertEqual(threads, {"tg:1": "thread-xyz"})
            self.assertEqual(sessions["tg:1"]["thread_id"], "thread-xyz")

            repo.mark_in_flight_request(1, 55)
            in_flight = json.loads(Path(state.in_flight_path).read_text(encoding="utf-8"))
            self.assertEqual(in_flight["tg:1"]["message_id"], 55)

            repo.clear_in_flight_request(1)
            self.assertFalse(Path(state.in_flight_path).exists())

            repo.clear_thread_id(1)
            threads_after = json.loads(Path(state.chat_thread_path).read_text(encoding="utf-8"))
            self.assertEqual(threads_after, {})

    def test_state_repository_concurrent_inflight_persistence_is_safe(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = bridge.State(
                chat_thread_path=str(Path(tmpdir) / "chat_threads.json"),
                worker_sessions_path=str(Path(tmpdir) / "worker_sessions.json"),
                in_flight_path=str(Path(tmpdir) / "in_flight_requests.json"),
            )
            repo = bridge.StateRepository(state)
            errors = []
            errors_lock = threading.Lock()
            thread_count = 8
            iterations_per_thread = 30

            def worker(seed: int) -> None:
                for i in range(iterations_per_thread):
                    chat_id = ((seed * 7) + i) % 12 + 1
                    try:
                        repo.mark_in_flight_request(chat_id, i)
                        repo.clear_in_flight_request(chat_id)
                    except Exception as exc:  # pragma: no cover - regression guard
                        with errors_lock:
                            errors.append(repr(exc))
                        return

            threads = [threading.Thread(target=worker, args=(idx,)) for idx in range(thread_count)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30.0)

            alive_threads = [index for index, thread in enumerate(threads) if thread.is_alive()]
            for index in alive_threads:
                threads[index].join(timeout=5.0)

            self.assertEqual(alive_threads, [], f"Concurrent persistence workers did not finish: {alive_threads}")
            self.assertEqual(errors, [])

    def test_apply_auth_change_thread_reset_does_not_clear_state_when_no_saved_fingerprint_exists(self):
        loaded_threads = {1: "thread-1"}
        loaded_worker_sessions = {
            "tg:1": bridge.WorkerSession(
                created_at=1.0,
                last_used_at=2.0,
                thread_id="thread-1",
                policy_fingerprint="fp",
            )
        }
        loaded_canonical_sessions = {
            "tg:1": bridge.CanonicalSession(
                thread_id="thread-1",
                worker_created_at=1.0,
                worker_last_used_at=2.0,
                worker_policy_fingerprint="fp",
            )
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            result = bridge_auth_state.apply_auth_change_thread_reset(
                state_dir=tmpdir,
                current_auth_fingerprint="auth-fp",
                loaded_threads=loaded_threads,
                loaded_worker_sessions=loaded_worker_sessions,
                loaded_canonical_sessions=loaded_canonical_sessions,
            )

            self.assertFalse(result["applied"])
            self.assertEqual(result["previous_auth_fingerprint"], "")
            self.assertEqual(result["counts"], {"threads": 0, "worker_sessions": 0, "canonical_sessions": 0})
            self.assertEqual(loaded_threads, {1: "thread-1"})
            self.assertIn("tg:1", loaded_worker_sessions)
            self.assertIn("tg:1", loaded_canonical_sessions)
            saved = bridge_auth_state.load_saved_auth_fingerprint(
                str(Path(tmpdir) / "auth_fingerprint.txt")
            )
            self.assertEqual(saved, "auth-fp")

    def test_apply_auth_change_thread_reset_clears_state_when_saved_fingerprint_changes(self):
        loaded_threads = {1: "thread-1"}
        loaded_worker_sessions = {
            "tg:1": bridge.WorkerSession(
                created_at=1.0,
                last_used_at=2.0,
                thread_id="thread-1",
                policy_fingerprint="fp",
            )
        }
        loaded_canonical_sessions = {
            "tg:1": bridge.CanonicalSession(
                thread_id="thread-1",
                worker_created_at=1.0,
                worker_last_used_at=2.0,
                worker_policy_fingerprint="fp",
            )
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            fingerprint_path = Path(tmpdir) / "auth_fingerprint.txt"
            fingerprint_path.write_text("old-auth-fp\n", encoding="utf-8")

            result = bridge_auth_state.apply_auth_change_thread_reset(
                state_dir=tmpdir,
                current_auth_fingerprint="new-auth-fp",
                loaded_threads=loaded_threads,
                loaded_worker_sessions=loaded_worker_sessions,
                loaded_canonical_sessions=loaded_canonical_sessions,
            )

            self.assertTrue(result["applied"])
            self.assertEqual(result["previous_auth_fingerprint"], "old-auth-fp")
            self.assertEqual(result["counts"], {"threads": 1, "worker_sessions": 1, "canonical_sessions": 1})
            self.assertEqual(loaded_threads, {})
            self.assertEqual(loaded_worker_sessions, {})
            self.assertEqual(loaded_canonical_sessions, {})
            self.assertEqual(
                bridge_auth_state.load_saved_auth_fingerprint(str(fingerprint_path)),
                "new-auth-fp",
            )
