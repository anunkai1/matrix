"""Tests for Transport — auto-split from test_bridge_core.py."""

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


class TestTransport(unittest.TestCase):
    def test_whatsapp_help_text_is_minimal(self):
        cfg = make_config(channel_plugin="whatsapp")
        text = bridge_handlers.build_help_text(cfg)
        self.assertIn("Available commands:", text)
        self.assertIn("/start - verify bridge connectivity", text)
        self.assertIn("/help or /h - show this message", text)
        self.assertIn("/status - show bridge status and context", text)
        self.assertIn("/reset - clear saved context for this chat", text)
        self.assertIn("/cancel or /c - cancel current in-flight request for this chat", text)
        self.assertIn("/restart - queue a safe bridge restart", text)
        self.assertIn(
            "/voice-alias add <source> => <target> - add approved alias manually",
            text,
        )
        self.assertNotIn("/voice-alias list", text)
        self.assertNotIn("/voice-alias approve", text)
        self.assertNotIn("server3-tv-start", text)
        self.assertNotIn("Use `HA ...`", text)
        self.assertNotIn("/memory mode", text)

    def test_default_plugin_registry_whatsapp_disabled_fails_fast(self):
        registry = bridge_plugin_registry.build_default_plugin_registry()
        with self.assertRaises(RuntimeError):
            registry.build_channel("whatsapp", make_config())

    def test_default_plugin_registry_builds_whatsapp_adapter_when_enabled(self):
        registry = bridge_plugin_registry.build_default_plugin_registry()
        channel = registry.build_channel(
            "whatsapp",
            make_config(whatsapp_plugin_enabled=True),
        )
        self.assertIsInstance(channel, bridge_whatsapp_channel.WhatsAppChannelAdapter)

    def test_default_plugin_registry_builds_signal_adapter_when_enabled(self):
        registry = bridge_plugin_registry.build_default_plugin_registry()
        channel = registry.build_channel(
            "signal",
            make_config(signal_plugin_enabled=True),
        )
        self.assertIsInstance(channel, bridge_signal_channel.SignalChannelAdapter)

    def test_load_config_reads_whatsapp_plugin_settings(self):
        with mock.patch.dict(
            os.environ,
            {
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_ALLOWED_CHAT_IDS": "1",
                "WHATSAPP_PLUGIN_ENABLED": "true",
                "WHATSAPP_BRIDGE_API_BASE": "http://localhost:9876",
                "WHATSAPP_BRIDGE_AUTH_TOKEN": "secret",
                "WHATSAPP_POLL_TIMEOUT_SECONDS": "33",
            },
            clear=True,
        ):
            config = bridge.load_config()
        self.assertTrue(config.whatsapp_plugin_enabled)
        self.assertEqual(config.whatsapp_bridge_api_base, "http://localhost:9876")
        self.assertEqual(config.whatsapp_bridge_auth_token, "secret")
        self.assertEqual(config.whatsapp_poll_timeout_seconds, 33)

    def test_load_config_reads_signal_plugin_settings(self):
        with mock.patch.dict(
            os.environ,
            {
                "TELEGRAM_CHANNEL_PLUGIN": "signal",
                "SIGNAL_PLUGIN_ENABLED": "true",
                "SIGNAL_BRIDGE_API_BASE": "http://localhost:8797",
                "SIGNAL_BRIDGE_AUTH_TOKEN": "signal-secret",
                "SIGNAL_POLL_TIMEOUT_SECONDS": "21",
                "TELEGRAM_ALLOW_PRIVATE_CHATS_UNLISTED": "true",
                "TELEGRAM_ALLOW_GROUP_CHATS_UNLISTED": "true",
                "TELEGRAM_KEYWORD_ROUTING_ENABLED": "false",
            },
            clear=True,
        ):
            config = bridge.load_config()
        self.assertEqual(config.channel_plugin, "signal")
        self.assertTrue(config.signal_plugin_enabled)
        self.assertEqual(config.signal_bridge_api_base, "http://localhost:8797")
        self.assertEqual(config.signal_bridge_auth_token, "signal-secret")
        self.assertEqual(config.signal_poll_timeout_seconds, 21)
        self.assertTrue(config.allow_private_chats_unlisted)
        self.assertTrue(config.allow_group_chats_unlisted)
        self.assertFalse(config.keyword_routing_enabled)
        self.assertEqual(config.allowed_chat_ids, set())

    def test_load_config_defaults_signal_bridge_port_to_18797(self):
        with mock.patch.dict(
            os.environ,
            {
                "TELEGRAM_CHANNEL_PLUGIN": "signal",
                "SIGNAL_PLUGIN_ENABLED": "true",
                "TELEGRAM_ALLOW_PRIVATE_CHATS_UNLISTED": "true",
                "TELEGRAM_ALLOW_GROUP_CHATS_UNLISTED": "true",
            },
            clear=True,
        ):
            config = bridge.load_config()
        self.assertEqual(config.signal_bridge_api_base, "http://127.0.0.1:18797")

    def test_whatsapp_adapter_send_message_get_id_posts_json(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"ok": true, "result": {"message_id": 321}}'

        config = make_config(
            whatsapp_plugin_enabled=True,
            whatsapp_bridge_api_base="http://127.0.0.1:8787",
            whatsapp_bridge_auth_token="token-1",
        )
        adapter = bridge_whatsapp_channel.WhatsAppChannelAdapter(config)
        with mock.patch.object(bridge_http_channel, "urlopen", return_value=Response()) as mocked:
            message_id = adapter.send_message_get_id(
                chat_id=123,
                text="hello",
                reply_to_message_id=55,
            )

        self.assertEqual(message_id, 321)
        request = mocked.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.full_url, "http://127.0.0.1:8787/messages")
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["chat_id"], "123")
        self.assertEqual(payload["text"], "hello")
        self.assertEqual(payload["reply_to_message_id"], "55")
        self.assertEqual(request.get_header("Authorization"), "Bearer token-1")

    def test_whatsapp_adapter_send_voice_posts_media_payload(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"ok": true, "result": {"message_id": 654}}'

        config = make_config(
            whatsapp_plugin_enabled=True,
            whatsapp_bridge_api_base="http://127.0.0.1:8787",
            whatsapp_bridge_auth_token="token-2",
        )
        adapter = bridge_whatsapp_channel.WhatsAppChannelAdapter(config)
        with mock.patch.object(bridge_http_channel, "urlopen", return_value=Response()) as mocked:
            adapter.send_voice(
                chat_id=123,
                voice="https://example.com/note.ogg",
                caption="voice caption",
                reply_to_message_id=77,
            )

        request = mocked.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.full_url, "http://127.0.0.1:8787/media")
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["chat_id"], "123")
        self.assertEqual(payload["media_ref"], "https://example.com/note.ogg")
        self.assertEqual(payload["media_type"], "voice")
        self.assertEqual(payload["caption"], "voice caption")
        self.assertEqual(payload["reply_to_message_id"], "77")

    def test_signal_adapter_send_message_get_id_posts_json(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"ok": true, "result": {"message_id": 987}}'

        config = make_config(
            signal_plugin_enabled=True,
            signal_bridge_api_base="http://127.0.0.1:18797",
            signal_bridge_auth_token="signal-token",
        )
        adapter = bridge_signal_channel.SignalChannelAdapter(config)
        with mock.patch.object(bridge_http_channel, "urlopen", return_value=Response()) as mocked:
            message_id = adapter.send_message_get_id(chat_id=33, text="hi")

        self.assertEqual(message_id, 987)
        request = mocked.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:18797/messages")
        self.assertEqual(request.get_header("Authorization"), "Bearer signal-token")

    def test_signal_adapter_disables_message_edits(self):
        adapter = bridge_signal_channel.SignalChannelAdapter(
            make_config(signal_plugin_enabled=True),
        )
        self.assertFalse(adapter.supports_message_edits)
        with self.assertRaises(RuntimeError):
            adapter.edit_message(chat_id=1, message_id=2, text="ignored")

    def test_transport_send_media_remote_uses_request_payload(self):
        config = make_config()
        client = bridge.TelegramClient(config)
        with mock.patch.object(client, "_request", return_value={"ok": True}) as request_mock:
            with mock.patch.object(client, "_request_multipart", return_value={"ok": True}) as multipart_mock:
                client.send_voice(
                    chat_id=1,
                    voice="https://example.com/note.ogg",
                    caption="c",
                    reply_to_message_id=12,
                )
        self.assertTrue(request_mock.called)
        self.assertFalse(multipart_mock.called)
        method_name, payload = request_mock.call_args.args
        self.assertEqual(method_name, "sendVoice")
        self.assertEqual(payload["voice"], "https://example.com/note.ogg")

    def test_transport_send_media_local_file_uses_multipart(self):
        config = make_config()
        client = bridge.TelegramClient(config)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as handle:
            handle.write(b"test")
            voice_path = handle.name
        try:
            with mock.patch.object(client, "_request", return_value={"ok": True}) as request_mock:
                with mock.patch.object(
                    client,
                    "_request_multipart",
                    return_value={"ok": True},
                ) as multipart_mock:
                    client.send_voice(chat_id=1, voice=voice_path, caption="c", reply_to_message_id=2)
            self.assertFalse(request_mock.called)
            self.assertTrue(multipart_mock.called)
            kwargs = multipart_mock.call_args.kwargs
            self.assertEqual(kwargs["method"], "sendVoice")
            self.assertEqual(kwargs["file_field"], "voice")
        finally:
            Path(voice_path).unlink(missing_ok=True)

    def test_transport_retries_transient_http_error_then_succeeds(self):
        config = make_config()
        config.retry_sleep_seconds = 0.0
        setattr(config, "api_max_attempts", 3)
        client = bridge.TelegramClient(config)

        transient_body = json.dumps(
            {
                "ok": False,
                "error_code": 503,
                "description": "Service Unavailable",
            }
        ).encode("utf-8")

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"ok": true, "result": {"message_id": 1}}'

        transient_error = bridge_transport.HTTPError(
            url="https://api.telegram.org",
            code=503,
            msg="Service Unavailable",
            hdrs=None,
            fp=io.BytesIO(transient_body),
        )
        with mock.patch.object(bridge_transport, "urlopen", side_effect=[transient_error, Response()]) as mocked:
            client.send_message(chat_id=1, text="hello")

        self.assertEqual(mocked.call_count, 2)

    def test_transport_does_not_retry_non_transient_http_error(self):
        config = make_config()
        config.retry_sleep_seconds = 0.0
        setattr(config, "api_max_attempts", 3)
        client = bridge.TelegramClient(config)

        non_transient_body = json.dumps(
            {
                "ok": False,
                "error_code": 400,
                "description": "Bad Request",
            }
        ).encode("utf-8")
        non_transient_error = bridge_transport.HTTPError(
            url="https://api.telegram.org",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=io.BytesIO(non_transient_body),
        )
        with mock.patch.object(bridge_transport, "urlopen", side_effect=[non_transient_error]) as mocked:
            with self.assertRaises(bridge_transport.TelegramApiError):
                client.send_message(chat_id=1, text="hello")

        self.assertEqual(mocked.call_count, 1)

    def test_transport_emits_retry_events_for_transient_error(self):
        config = make_config()
        config.retry_sleep_seconds = 0.0
        setattr(config, "api_max_attempts", 3)
        client = bridge.TelegramClient(config)

        transient_body = json.dumps(
            {
                "ok": False,
                "error_code": 503,
                "description": "Service Unavailable",
            }
        ).encode("utf-8")

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"ok": true, "result": {"message_id": 9}}'

        transient_error = bridge_transport.HTTPError(
            url="https://api.telegram.org",
            code=503,
            msg="Service Unavailable",
            hdrs=None,
            fp=io.BytesIO(transient_body),
        )
        with (
            mock.patch.object(bridge_transport, "urlopen", side_effect=[transient_error, Response()]),
            mock.patch.object(bridge_transport, "emit_event") as emit_mock,
        ):
            client.send_message(chat_id=1, text="hello")

        event_names = [call.args[0] for call in emit_mock.call_args_list]
        self.assertIn("bridge.telegram_api_retry_scheduled", event_names)
        self.assertIn("bridge.telegram_api_retry_succeeded", event_names)

    def test_transport_emits_failed_event_when_retry_exhausted(self):
        config = make_config()
        config.retry_sleep_seconds = 0.0
        setattr(config, "api_max_attempts", 2)
        client = bridge.TelegramClient(config)

        transient_body = json.dumps(
            {
                "ok": False,
                "error_code": 503,
                "description": "Service Unavailable",
            }
        ).encode("utf-8")
        transient_error = bridge_transport.HTTPError(
            url="https://api.telegram.org",
            code=503,
            msg="Service Unavailable",
            hdrs=None,
            fp=io.BytesIO(transient_body),
        )
        with (
            mock.patch.object(bridge_transport, "urlopen", side_effect=[transient_error, transient_error]),
            mock.patch.object(bridge_transport, "emit_event") as emit_mock,
        ):
            with self.assertRaises(bridge_transport.TelegramApiError):
                client.send_message(chat_id=1, text="hello")

        event_names = [call.args[0] for call in emit_mock.call_args_list]
        self.assertIn("bridge.telegram_api_retry_scheduled", event_names)
        self.assertIn("bridge.telegram_api_failed", event_names)

    def test_progress_reporter_disables_whatsapp_edits_after_edit_failure(self):
        client = FakeProgressEditClient()
        reporter = bridge_handlers.ProgressReporter(
            client=client,
            chat_id=1,
            reply_to_message_id=5,
            message_thread_id=None,
            assistant_name="Architect",
            progress_label="Говорун размышляет",
        )
        reporter.progress_message_id = 101
        reporter.pending_update = True

        reporter._maybe_edit(force=True)

        self.assertIsNone(reporter.progress_message_id)

    def test_progress_reporter_skips_signal_edits_when_unsupported(self):
        client = FakeSignalProgressClient()
        reporter = bridge_handlers.ProgressReporter(
            client=client,
            chat_id=1,
            reply_to_message_id=5,
            message_thread_id=None,
            assistant_name="Oracle",
        )
        reporter.progress_message_id = 202
        reporter.pending_update = True

        reporter._maybe_edit(force=True)

        self.assertEqual(reporter.progress_message_id, 202)

    def test_download_helper_rejects_oversize(self):
        client = FakeDownloadClient({"file_path": "files/example.jpg", "file_size": 9999})
        spec = bridge.TelegramFileDownloadSpec(
            file_id="abc",
            max_bytes=1024,
            size_label="Image",
            temp_prefix="telegram-bridge-photo-",
            default_suffix=".jpg",
            too_large_label="Image",
        )
        with self.assertRaises(ValueError):
            bridge.download_telegram_file_to_temp(client, spec)
        self.assertEqual(client.download_calls, 0)

