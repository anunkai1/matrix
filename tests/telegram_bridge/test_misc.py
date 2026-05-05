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


class TestMisc(unittest.TestCase):
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

