"""Tests for Sessions — auto-split from test_bridge_core.py."""

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


class TestSessions(unittest.TestCase):
    def test_ensure_chat_worker_session_rejects_when_all_workers_busy(self):
        state = bridge.State(
            chat_threads={2: "thread-busy"},
            worker_sessions={
                2: bridge.WorkerSession(
                    created_at=1.0,
                    last_used_at=10.0,
                    thread_id="thread-busy",
                    policy_fingerprint="fp",
                )
            },
        )
        state.busy_chats.add(2)
        client = FakeTelegramClient()
        config = make_config(
            persistent_workers_enabled=True,
            persistent_workers_max=1,
            persistent_workers_idle_timeout_seconds=3600,
        )

        allowed = bridge.ensure_chat_worker_session(state, config, client, chat_id=1, message_id=99)
        self.assertFalse(allowed)
        self.assertTrue(client.messages)
        self.assertIn("workers are currently in use", client.messages[-1][1])

    def test_build_canonical_sessions_from_legacy(self):
        worker = bridge.WorkerSession(
            created_at=1.0,
            last_used_at=2.0,
            thread_id="thread-2",
            policy_fingerprint="fp",
        )
        sessions = bridge.build_canonical_sessions_from_legacy(
            chat_threads={1: "thread-1", 2: "thread-2"},
            worker_sessions={2: worker},
            in_flight_requests={3: {"started_at": 9.0, "message_id": 88}},
        )
        self.assertIn(1, sessions)
        self.assertIn(2, sessions)
        self.assertIn(3, sessions)
        self.assertEqual(sessions[1].thread_id, "thread-1")
        self.assertEqual(sessions[2].worker_policy_fingerprint, "fp")
        self.assertEqual(sessions[3].in_flight_message_id, 88)

    def test_state_repository_syncs_canonical_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = bridge.State(
                chat_thread_path=str(Path(tmpdir) / "chat_threads.json"),
                worker_sessions_path=str(Path(tmpdir) / "worker_sessions.json"),
                in_flight_path=str(Path(tmpdir) / "in_flight_requests.json"),
                chat_sessions_path=str(Path(tmpdir) / "chat_sessions.json"),
                canonical_sessions_enabled=True,
            )
            repo = bridge.StateRepository(state)
            repo.set_thread_id(7, "thread-7")
            repo.mark_in_flight_request(7, 700)

            sessions = bridge.load_canonical_sessions(state.chat_sessions_path)
            self.assertIn("tg:7", sessions)
            self.assertEqual(sessions["tg:7"].thread_id, "thread-7")
            self.assertEqual(sessions["tg:7"].in_flight_message_id, 700)

    def test_state_repository_syncs_canonical_to_sqlite_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = str(Path(tmpdir) / "chat_sessions.sqlite3")
            json_path = str(Path(tmpdir) / "chat_sessions.json")
            state = bridge.State(
                chat_thread_path=str(Path(tmpdir) / "chat_threads.json"),
                worker_sessions_path=str(Path(tmpdir) / "worker_sessions.json"),
                in_flight_path=str(Path(tmpdir) / "in_flight_requests.json"),
                chat_sessions_path=json_path,
                canonical_sessions_enabled=True,
                canonical_sqlite_enabled=True,
                canonical_sqlite_path=sqlite_path,
                canonical_json_mirror_enabled=False,
            )
            repo = bridge.StateRepository(state)
            repo.set_thread_id(12, "thread-12")
            repo.mark_in_flight_request(12, 1200)

            sessions = bridge.load_canonical_sessions_sqlite(sqlite_path)
            self.assertIn("tg:12", sessions)
            self.assertEqual(sessions["tg:12"].thread_id, "thread-12")
            self.assertEqual(sessions["tg:12"].in_flight_message_id, 1200)
            self.assertFalse(Path(json_path).exists())

    def test_canonical_sqlite_json_mirror_writes_json_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = str(Path(tmpdir) / "chat_sessions.sqlite3")
            json_path = str(Path(tmpdir) / "chat_sessions.json")
            state = bridge.State(
                chat_thread_path=str(Path(tmpdir) / "chat_threads.json"),
                worker_sessions_path=str(Path(tmpdir) / "worker_sessions.json"),
                in_flight_path=str(Path(tmpdir) / "in_flight_requests.json"),
                chat_sessions_path=json_path,
                canonical_sessions_enabled=True,
                canonical_sqlite_enabled=True,
                canonical_sqlite_path=sqlite_path,
                canonical_json_mirror_enabled=True,
            )
            repo = bridge.StateRepository(state)
            repo.set_thread_id(13, "thread-13")

            sqlite_sessions = bridge.load_canonical_sessions_sqlite(sqlite_path)
            json_sessions = bridge.load_canonical_sessions(json_path)
            self.assertEqual(sqlite_sessions["tg:13"].thread_id, "thread-13")
            self.assertEqual(json_sessions["tg:13"].thread_id, "thread-13")

    def test_load_or_import_canonical_sessions_sqlite_imports_only_when_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = str(Path(tmpdir) / "chat_sessions.sqlite3")
            initial_sessions = {
                1: bridge.CanonicalSession(thread_id="thread-initial"),
            }
            loaded, imported = bridge.load_or_import_canonical_sessions_sqlite(
                sqlite_path,
                import_sessions=initial_sessions,
            )
            self.assertTrue(imported)
            self.assertEqual(loaded["tg:1"].thread_id, "thread-initial")

            replacement_sessions = {
                1: bridge.CanonicalSession(thread_id="thread-replacement"),
                2: bridge.CanonicalSession(thread_id="thread-two"),
            }
            loaded_again, imported_again = bridge.load_or_import_canonical_sessions_sqlite(
                sqlite_path,
                import_sessions=replacement_sessions,
            )
            self.assertFalse(imported_again)
            self.assertEqual(loaded_again["tg:1"].thread_id, "thread-initial")
            self.assertNotIn("tg:2", loaded_again)

    def test_build_legacy_from_canonical(self):
        canonical = {
            "tg:9": bridge.CanonicalSession(
                thread_id="thread-9",
                worker_created_at=1.0,
                worker_last_used_at=2.0,
                worker_policy_fingerprint="fp",
                in_flight_started_at=3.0,
                in_flight_message_id=90,
            )
        }
        chat_threads, worker_sessions, in_flight = bridge.build_legacy_from_canonical(canonical)
        self.assertEqual(chat_threads["tg:9"], "thread-9")
        self.assertEqual(worker_sessions["tg:9"].policy_fingerprint, "fp")
        self.assertEqual(in_flight["tg:9"]["message_id"], 90)

    def test_canonical_first_set_thread_and_clear_worker_mirrors_legacy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = bridge.State(
                chat_thread_path=str(Path(tmpdir) / "chat_threads.json"),
                worker_sessions_path=str(Path(tmpdir) / "worker_sessions.json"),
                in_flight_path=str(Path(tmpdir) / "in_flight_requests.json"),
                chat_sessions_path=str(Path(tmpdir) / "chat_sessions.json"),
                canonical_sessions_enabled=True,
                canonical_legacy_mirror_enabled=True,
                chat_sessions={
                    "tg:5": bridge.CanonicalSession(
                        thread_id="old-thread",
                        worker_created_at=1.0,
                        worker_last_used_at=1.0,
                        worker_policy_fingerprint="old",
                    )
                },
            )
            bridge.persist_canonical_sessions(state)
            bridge.mirror_legacy_from_canonical(state, persist=True)

            repo = bridge.StateRepository(state)
            repo.set_thread_id(5, "new-thread")
            repo.clear_worker_session(5)

            sessions = bridge.load_canonical_sessions(state.chat_sessions_path)
            self.assertEqual(sessions["tg:5"].thread_id, "new-thread")
            self.assertIsNone(sessions["tg:5"].worker_created_at)

            threads = json.loads(Path(state.chat_thread_path).read_text(encoding="utf-8"))
            workers = json.loads(Path(state.worker_sessions_path).read_text(encoding="utf-8"))
            self.assertEqual(threads["tg:5"], "new-thread")
            self.assertEqual(workers, {})

    def test_canonical_first_without_legacy_mirror_skips_legacy_persist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state = bridge.State(
                chat_thread_path=str(Path(tmpdir) / "chat_threads.json"),
                worker_sessions_path=str(Path(tmpdir) / "worker_sessions.json"),
                in_flight_path=str(Path(tmpdir) / "in_flight_requests.json"),
                chat_sessions_path=str(Path(tmpdir) / "chat_sessions.json"),
                canonical_sessions_enabled=True,
                canonical_legacy_mirror_enabled=False,
            )
            repo = bridge.StateRepository(state)
            repo.set_thread_id(11, "thread-11")

            sessions = bridge.load_canonical_sessions(state.chat_sessions_path)
            self.assertEqual(sessions["tg:11"].thread_id, "thread-11")
            self.assertFalse(Path(state.chat_thread_path).exists())

    def test_ensure_chat_worker_session_canonical_rejects_when_all_workers_busy(self):
        state = bridge.State(
            canonical_sessions_enabled=True,
            chat_sessions={
                "tg:2": bridge.CanonicalSession(
                    thread_id="thread-busy",
                    worker_created_at=1.0,
                    worker_last_used_at=10.0,
                    worker_policy_fingerprint="fp",
                )
            },
        )
        state.busy_chats.add(2)
        client = FakeTelegramClient()
        config = make_config(
            persistent_workers_enabled=True,
            persistent_workers_max=1,
            canonical_sessions_enabled=True,
        )

        allowed = bridge.ensure_chat_worker_session(state, config, client, chat_id=1, message_id=99)
        self.assertFalse(allowed)
        self.assertTrue(client.messages)
        self.assertIn("workers are currently in use", client.messages[-1][1])

    def test_ensure_chat_worker_session_canonical_sends_policy_refresh_notice(self):
        state = bridge.State(
            canonical_sessions_enabled=True,
            chat_sessions={
                "tg:1": bridge.CanonicalSession(
                    thread_id="thread-old",
                    worker_created_at=1.0,
                    worker_last_used_at=2.0,
                    worker_policy_fingerprint="stale-fingerprint",
                )
            },
        )
        client = FakeTelegramClient()
        config = make_config(
            persistent_workers_enabled=True,
            persistent_workers_max=2,
            canonical_sessions_enabled=True,
        )

        allowed = bridge.ensure_chat_worker_session(state, config, client, chat_id=1, message_id=88)
        self.assertTrue(allowed)
        self.assertTrue(client.messages)
        self.assertIn("Policy/context files changed", client.messages[-1][1])
        self.assertIn("tg:1", state.chat_sessions)
        self.assertEqual(state.chat_sessions["tg:1"].thread_id, "")

    def test_finalize_chat_work_clears_busy_when_inflight_clear_fails(self):
        state = bridge.State()
        state.busy_chats.add(1)
        client = FakeTelegramClient()

        class FailingStateRepo:
            def __init__(self, _state):
                pass

            def clear_in_flight_request(self, _chat_id):
                raise RuntimeError("boom")

        with mock.patch.object(bridge_session_manager, "StateRepository", FailingStateRepo):
            bridge_session_manager.finalize_chat_work(state, client, chat_id=1)
        self.assertNotIn("tg:1", state.busy_chats)

if __name__ == "__main__":
    unittest.main()

