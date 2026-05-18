"""Tests for Misc — auto-split from test_bridge_core.py."""

import io
import json
import logging
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
from telegram_bridge.state_store import PendingTextBatch


class TestMisc(unittest.TestCase):
    def test_trigger_restart_async_starts_restart_worker_with_positional_args(self):
        with mock.patch.object(bridge_session_manager, "start_daemon_thread") as start_thread:
            bridge_session_manager.trigger_restart_async("state", "client", 1, 2, 3)

        start_thread.assert_called_once_with(
            bridge_session_manager.run_restart_script,
            "state",
            "client",
            1,
            2,
            3,
        )

    def test_override_engine_for_mavali_handoff_swaps_codex_engine(self):
        config = make_config(assistant_name="Mavali ETH", engine_plugin="mavali_eth")
        active_engine = bridge_engine_adapter.CodexEngineAdapter()

        runtime_engine = bridge_prompt_execution._override_engine_for_mavali_handoff(
            active_engine,
            config,
            "Current User Message:\nStatus",
        )

        self.assertIsInstance(runtime_engine, bridge_engine_adapter.MavaliEthEngineAdapter)

    def test_override_engine_for_mavali_handoff_routes_backburner_commands(self):
        config = make_config(assistant_name="Mavali ETH", engine_plugin="mavali_eth")
        active_engine = bridge_engine_adapter.CodexEngineAdapter()

        runtime_engine = bridge_prompt_execution._override_engine_for_mavali_handoff(
            active_engine,
            config,
            "Current User Message:\nDisarm xagusdt backburner",
        )

        self.assertIsInstance(runtime_engine, bridge_engine_adapter.MavaliEthEngineAdapter)

    def test_compute_poll_timeout_seconds_shortens_while_waiting_for_album_tail(self):
        state = bridge.State()
        state.pending_media_groups["1:album-1"] = bridge.PendingMediaGroup(
            chat_id=1,
            media_group_id="album-1",
            updates=[
                {
                    "update_id": 101,
                    "message": {
                        "message_id": 11,
                        "media_group_id": "album-1",
                        "chat": {"id": 1},
                    },
                }
            ],
            started_at=100.0,
            last_seen_at=100.0,
        )

        config = make_config(poll_timeout_seconds=30)
        self.assertEqual(bridge.compute_poll_timeout_seconds(state, config, now=100.1), 2)
        self.assertEqual(bridge.compute_poll_timeout_seconds(state, config, now=101.2), 1)

    def test_compute_poll_timeout_seconds_shortens_while_waiting_for_text_batch_tail(self):
        state = bridge.State()
        state.pending_text_batches["tg:1"] = PendingTextBatch(
            scope_key="tg:1",
            chat_id=1,
            message_thread_id=None,
            actor_user_id=7,
            updates=[
                {
                    "update_id": 201,
                    "message": {
                        "message_id": 21,
                        "chat": {"id": 1, "type": "private"},
                        "from": {"id": 7},
                        "text": "part one",
                    },
                }
            ],
            started_at=100.0,
            last_seen_at=100.0,
        )

        config = make_config(poll_timeout_seconds=30)
        self.assertEqual(bridge.compute_poll_timeout_seconds(state, config, now=100.1), 1)
        self.assertEqual(bridge.compute_poll_timeout_seconds(state, config, now=101.3), 1)

    def test_buffer_pending_text_updates_batches_same_scope_plain_text_turns(self):
        state = bridge.State()
        updates = [
            {
                "update_id": 301,
                "message": {
                    "message_id": 31,
                    "chat": {"id": 1, "type": "private"},
                    "from": {"id": 9, "first_name": "User"},
                    "text": "first part",
                },
            },
            {
                "update_id": 302,
                "message": {
                    "message_id": 32,
                    "chat": {"id": 1, "type": "private"},
                    "from": {"id": 9, "first_name": "User"},
                    "text": "second part",
                },
            },
        ]

        immediate = bridge.buffer_pending_text_updates(state, updates, now=100.0)
        flushed = bridge.flush_ready_text_batch_updates(state, now=100.4)

        self.assertEqual(immediate, [])
        self.assertEqual(len(flushed), 1)
        merged_message = flushed[0]["message"]
        self.assertEqual(merged_message["text"], "first part\n\nsecond part")
        self.assertEqual(merged_message["message_id"], 32)
        self.assertEqual(len(merged_message["coalesced_text_messages"]), 2)

    def test_buffer_pending_text_updates_flushes_before_non_batchable_same_scope_update(self):
        state = bridge.State()
        first = {
            "update_id": 401,
            "message": {
                "message_id": 41,
                "chat": {"id": -100, "type": "supergroup"},
                "message_thread_id": 88,
                "from": {"id": 3, "first_name": "User"},
                "text": "first part",
            },
        }
        second = {
            "update_id": 402,
            "message": {
                "message_id": 42,
                "chat": {"id": -100, "type": "supergroup"},
                "message_thread_id": 88,
                "from": {"id": 3, "first_name": "User"},
                "reply_to_message": {"message_id": 40},
                "text": "reply target",
            },
        }

        self.assertEqual(bridge.buffer_pending_text_updates(state, [first], now=200.0), [])
        immediate = bridge.buffer_pending_text_updates(state, [second], now=200.1)

        self.assertEqual(len(immediate), 2)
        self.assertEqual(immediate[0]["message"]["text"], "first part")
        self.assertEqual(immediate[1]["message"]["text"], "reply target")
        self.assertEqual(state.pending_text_batches, {})

    def test_buffer_pending_text_updates_splits_batches_when_sender_changes(self):
        state = bridge.State()
        first = {
            "update_id": 501,
            "message": {
                "message_id": 51,
                "chat": {"id": -100, "type": "supergroup"},
                "from": {"id": 11, "first_name": "Alice"},
                "text": "alice one",
            },
        }
        second = {
            "update_id": 502,
            "message": {
                "message_id": 52,
                "chat": {"id": -100, "type": "supergroup"},
                "from": {"id": 22, "first_name": "Bob"},
                "text": "bob one",
            },
        }

        self.assertEqual(bridge.buffer_pending_text_updates(state, [first], now=300.0), [])
        immediate = bridge.buffer_pending_text_updates(state, [second], now=300.1)
        flushed = bridge.flush_ready_text_batch_updates(state, now=300.5)

        self.assertEqual(len(immediate), 1)
        self.assertEqual(immediate[0]["message"]["text"], "alice one")
        self.assertEqual(len(flushed), 1)
        self.assertEqual(flushed[0]["message"]["text"], "bob one")

    @mock.patch.object(bridge_handlers, "transcribe_voice")
    @mock.patch.object(bridge_handlers, "download_voice_to_temp")
    def test_transcribe_voice_for_chat_blocks_low_confidence(self, download_voice_to_temp, transcribe_voice):
        with tempfile.NamedTemporaryFile(suffix=".oga", delete=False) as handle:
            voice_path = handle.name
        download_voice_to_temp.return_value = voice_path
        transcribe_voice.return_value = ("turn off master broom air con", 0.20)

        client = FakeTelegramClient()
        config = make_config(
            voice_transcribe_cmd=["/bin/echo"],
            voice_alias_replacements=[("master broom", "master bedroom"), ("air con", "aircon")],
            voice_low_confidence_confirmation_enabled=True,
            voice_low_confidence_threshold=0.45,
        )
        try:
            transcript = bridge_handlers.transcribe_voice_for_chat(
                state=bridge.State(),
                config=config,
                client=client,
                chat_id=1,
                message_id=99,
                voice_file_id="voice-1",
                echo_transcript=True,
            )
        finally:
            Path(voice_path).unlink(missing_ok=True)

        self.assertIsNone(transcript)
        self.assertEqual(len(client.messages), 1)
        self.assertEqual(client.messages[0][1], "Voice transcript confidence is low, resend")

    @mock.patch.object(bridge_handlers, "transcribe_voice")
    @mock.patch.object(bridge_handlers, "download_voice_to_temp")
    def test_transcribe_voice_for_chat_applies_aliases_on_success(self, download_voice_to_temp, transcribe_voice):
        with tempfile.NamedTemporaryFile(suffix=".oga", delete=False) as handle:
            voice_path = handle.name
        download_voice_to_temp.return_value = voice_path
        transcribe_voice.return_value = ("turn on master broom air con", 0.91)

        client = FakeTelegramClient()
        config = make_config(
            voice_transcribe_cmd=["/bin/echo"],
            voice_alias_replacements=[("master broom", "master bedroom"), ("air con", "aircon")],
            voice_low_confidence_confirmation_enabled=True,
            voice_low_confidence_threshold=0.45,
        )
        try:
            transcript = bridge_handlers.transcribe_voice_for_chat(
                state=bridge.State(),
                config=config,
                client=client,
                chat_id=1,
                message_id=100,
                voice_file_id="voice-2",
                echo_transcript=True,
            )
        finally:
            Path(voice_path).unlink(missing_ok=True)

        self.assertEqual(transcript, "turn on master bedroom aircon")
        self.assertEqual(len(client.messages), 1)
        self.assertIn("confidence 0.91", client.messages[0][1])
        self.assertIn("master bedroom aircon", client.messages[0][1])

    def test_json_log_formatter_includes_event_and_fields(self):
        record = logging.LogRecord(
            "telegram_bridge",
            logging.INFO,
            __file__,
            1,
            "bridge.request_succeeded",
            args=(),
            exc_info=None,
        )
        record.event = "bridge.request_succeeded"
        record.fields = {"chat_id": 1, "message_id": 2}
        payload = json.loads(bridge_structured_logging.JsonLogFormatter().format(record))
        self.assertEqual(payload["event"], "bridge.request_succeeded")
        self.assertEqual(payload["chat_id"], 1)
        self.assertEqual(payload["message_id"], 2)
