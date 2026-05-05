"""Tests for Config — auto-split from test_bridge_core.py."""

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


class TestConfig(unittest.TestCase):
    def test_load_config_reads_allow_private_chats_unlisted_override(self):
        with mock.patch.dict(
            os.environ,
            {
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_ALLOWED_CHAT_IDS": "1",
                "TELEGRAM_ALLOW_PRIVATE_CHATS_UNLISTED": "true",
            },
            clear=True,
        ):
            config = bridge.load_config()
        self.assertTrue(config.allow_private_chats_unlisted)

    def test_load_config_reads_busy_message_override(self):
        with mock.patch.dict(
            os.environ,
            {
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_ALLOWED_CHAT_IDS": "1",
                "TELEGRAM_BUSY_MESSAGE": "Даю справку: уже занят предыдущим запросом.",
            },
            clear=True,
        ):
            config = bridge.load_config()
        self.assertEqual(
            config.busy_message,
            "Даю справку: уже занят предыдущим запросом.",
        )

    def test_parse_outbound_media_directive_extracts_media_and_voice_flag(self):
        text, directive = bridge_handlers.parse_outbound_media_directive(
            "[[media:/tmp/note.ogg]] [[audio_as_voice]] hello there"
        )
        self.assertEqual(text, "hello there")
        self.assertIsNotNone(directive)
        self.assertEqual(directive.media_ref, "/tmp/note.ogg")
        self.assertTrue(directive.as_voice)

    def test_parse_structured_outbound_payload_extracts_media_and_text(self):
        parsed, error = bridge_handlers.parse_structured_outbound_payload(
            json.dumps(
                {
                    "telegram_outbound": {
                        "text": "caption one",
                        "media_ref": "https://example.com/note.ogg",
                        "as_voice": True,
                    }
                }
            )
        )
        self.assertIsNone(error)
        self.assertIsNotNone(parsed)
        rendered_text, directive = parsed
        self.assertEqual(rendered_text, "caption one")
        self.assertIsNotNone(directive)
        self.assertEqual(directive.media_ref, "https://example.com/note.ogg")
        self.assertTrue(directive.as_voice)

    def test_parse_structured_outbound_payload_reports_schema_error(self):
        parsed, error = bridge_handlers.parse_structured_outbound_payload(
            '{"telegram_outbound":"bad"}'
        )
        self.assertIsNone(parsed)
        self.assertEqual(error, "invalid_schema:telegram_outbound_not_object")

    def test_parse_voice_confidence(self):
        self.assertEqual(
            bridge_handlers.parse_voice_confidence("VOICE_CONFIDENCE=0.723\n"),
            0.723,
        )
        self.assertIsNone(bridge_handlers.parse_voice_confidence("no marker"))

    def test_load_config_preserves_blank_progress_elapsed_fields(self):
        env = {
            "TELEGRAM_BOT_TOKEN": "token",
            "TELEGRAM_ALLOWED_CHAT_IDS": "1",
            "TELEGRAM_PROGRESS_ELAPSED_PREFIX": "",
            "TELEGRAM_PROGRESS_ELAPSED_SUFFIX": "",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            cfg = bridge.load_config()
        self.assertEqual(cfg.progress_elapsed_prefix, "")
        self.assertEqual(cfg.progress_elapsed_suffix, "")

    def test_build_low_confidence_voice_message_uses_configured_text(self):
        config = make_config(voice_low_confidence_message="Voice transcript confidence is low, resend")
        message = bridge_handlers.build_low_confidence_voice_message(
            config,
            transcript="govorun test",
            confidence=0.2,
        )
        self.assertEqual(message, "Voice transcript confidence is low, resend")

    def test_policy_fingerprint_cache_reuses_value_within_ttl(self):
        bridge_session_manager._policy_fingerprint_cache.clear()
        with mock.patch.object(
            bridge_session_manager,
            "compute_policy_fingerprint",
            side_effect=["fp-a", "fp-b"],
        ) as compute:
            first = bridge_session_manager.get_cached_policy_fingerprint(
                ["/tmp/policy-a"],
                now=100.0,
            )
            second = bridge_session_manager.get_cached_policy_fingerprint(
                ["/tmp/policy-a"],
                now=105.0,
            )
            third = bridge_session_manager.get_cached_policy_fingerprint(
                ["/tmp/policy-a"],
                now=111.0,
            )
        self.assertEqual(first, "fp-a")
        self.assertEqual(second, "fp-a")
        self.assertEqual(third, "fp-b")
        self.assertEqual(compute.call_count, 2)

    def test_policy_fingerprint_cache_normalizes_order_and_duplicates(self):
        bridge_session_manager._policy_fingerprint_cache.clear()
        with mock.patch.object(
            bridge_session_manager,
            "compute_policy_fingerprint",
            return_value="fp-stable",
        ) as compute:
            first = bridge_session_manager.get_cached_policy_fingerprint(
                ["/tmp/policy-b", "/tmp/policy-a", "/tmp/policy-a"],
                now=100.0,
            )
            second = bridge_session_manager.get_cached_policy_fingerprint(
                ["/tmp/policy-a", "/tmp/policy-b"],
                now=105.0,
            )

        self.assertEqual(first, "fp-stable")
        self.assertEqual(second, "fp-stable")
        compute.assert_called_once_with(["/tmp/policy-a", "/tmp/policy-b"])

    def test_apply_policy_change_thread_reset_clears_stale_threads_and_persists_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            fingerprint_path = Path(bridge.build_policy_fingerprint_state_path(str(state_dir)))
            fingerprint_path.write_text("old-fingerprint\n", encoding="utf-8")
            loaded_threads = {1: "thread-1", 2: "thread-2"}
            loaded_worker_sessions = {
                2: bridge.WorkerSession(
                    created_at=1.0,
                    last_used_at=2.0,
                    thread_id="thread-2",
                    policy_fingerprint="old-fingerprint",
                )
            }
            loaded_canonical_sessions = {
                1: bridge.CanonicalSession(thread_id="thread-1"),
                2: bridge.CanonicalSession(
                    thread_id="thread-2",
                    worker_created_at=10.0,
                    worker_last_used_at=20.0,
                    worker_policy_fingerprint="old-fingerprint",
                ),
                3: bridge.CanonicalSession(in_flight_started_at=30.0, in_flight_message_id=300),
            }

            result = bridge.apply_policy_change_thread_reset(
                state_dir=str(state_dir),
                current_policy_fingerprint="new-fingerprint",
                loaded_threads=loaded_threads,
                loaded_worker_sessions=loaded_worker_sessions,
                loaded_canonical_sessions=loaded_canonical_sessions,
            )

            self.assertTrue(result["applied"])
            self.assertEqual(result["counts"]["threads"], 2)
            self.assertEqual(result["counts"]["worker_sessions"], 1)
            self.assertEqual(result["counts"]["canonical_sessions"], 2)
            self.assertEqual(loaded_threads, {})
            self.assertEqual(loaded_worker_sessions, {})
            self.assertNotIn(1, loaded_canonical_sessions)
            self.assertNotIn(2, loaded_canonical_sessions)
            self.assertIn(3, loaded_canonical_sessions)
            self.assertEqual(
                fingerprint_path.read_text(encoding="utf-8").strip(),
                "new-fingerprint",
            )

