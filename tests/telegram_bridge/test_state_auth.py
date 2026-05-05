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
            cleared = json.loads(Path(state.in_flight_path).read_text(encoding="utf-8"))
            self.assertEqual(cleared, {})

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

            def worker(seed: int) -> None:
                for i in range(120):
                    chat_id = ((seed * 7) + i) % 12 + 1
                    try:
                        repo.mark_in_flight_request(chat_id, i)
                        repo.clear_in_flight_request(chat_id)
                    except Exception as exc:  # pragma: no cover - regression guard
                        with errors_lock:
                            errors.append(repr(exc))
                        return

            threads = [threading.Thread(target=worker, args=(idx,)) for idx in range(16)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(errors, [])

