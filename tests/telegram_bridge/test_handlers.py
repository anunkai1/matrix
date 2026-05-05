"""Tests for Handlers — auto-split from test_bridge_core.py."""

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


class TestHandlers(unittest.TestCase):
    def test_should_resume_saved_update_offset_for_non_telegram_only(self):
        self.assertFalse(bridge.should_resume_saved_update_offset(make_config(channel_plugin="telegram")))
        self.assertTrue(bridge.should_resume_saved_update_offset(make_config(channel_plugin="whatsapp")))
        self.assertTrue(bridge.should_resume_saved_update_offset(make_config(channel_plugin="signal")))

    def test_should_reset_saved_update_offset_only_when_queue_counter_rolls_back(self):
        self.assertFalse(bridge.should_reset_saved_update_offset(0, 3))
        self.assertFalse(bridge.should_reset_saved_update_offset(10, None))
        self.assertFalse(bridge.should_reset_saved_update_offset(10, 9))
        self.assertTrue(bridge.should_reset_saved_update_offset(10, 2))

    def test_load_saved_update_offset_ignores_invalid_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            offset_path = Path(tmpdir) / "offset.txt"
            offset_path.write_text("bad-value\n", encoding="utf-8")
            self.assertEqual(bridge.load_saved_update_offset(str(offset_path)), 0)
            offset_path.write_text("-7\n", encoding="utf-8")
            self.assertEqual(bridge.load_saved_update_offset(str(offset_path)), 0)

    def test_compute_initial_update_offset_resets_when_queue_counter_restarts(self):
        config = make_config(channel_plugin="whatsapp", state_dir=tempfile.mkdtemp())
        offset_path = Path(config.state_dir) / "whatsapp_update_offset.txt"
        bridge.persist_saved_update_offset(str(offset_path), 40)

        class FakeClient:
            def get_updates(self, offset, timeout_seconds=0):
                self.last_offset = offset
                self.last_timeout_seconds = timeout_seconds
                return [
                    {"update_id": 1, "message": {}},
                    {"update_id": 2, "message": {}},
                    {"update_id": 3, "message": {}},
                ]

        client = FakeClient()
        offset, state_path = bridge.compute_initial_update_offset(config, client)
        self.assertEqual(offset, 0)
        self.assertEqual(state_path, str(offset_path))
        self.assertEqual(client.last_offset, 0)
        self.assertEqual(client.last_timeout_seconds, 0)

    def test_compute_initial_update_offset_reuses_saved_offset_with_live_queue(self):
        config = make_config(channel_plugin="whatsapp", state_dir=tempfile.mkdtemp())
        offset_path = Path(config.state_dir) / "whatsapp_update_offset.txt"
        bridge.persist_saved_update_offset(str(offset_path), 10)

        class FakeClient:
            def get_updates(self, offset, timeout_seconds=0):
                return [
                    {"update_id": 8, "message": {}},
                    {"update_id": 9, "message": {}},
                ]

        offset, state_path = bridge.compute_initial_update_offset(config, FakeClient())
        self.assertEqual(offset, 10)
        self.assertEqual(state_path, str(offset_path))

    def test_load_config_reads_require_prefix_in_private_override(self):
        with mock.patch.dict(
            os.environ,
            {
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_ALLOWED_CHAT_IDS": "1",
                "TELEGRAM_REQUIRED_PREFIXES": "@tank",
                "TELEGRAM_REQUIRE_PREFIX_IN_PRIVATE": "false",
            },
            clear=True,
        ):
            config = bridge.load_config()
        self.assertEqual(config.required_prefixes, ["@tank"])
        self.assertFalse(config.require_prefix_in_private)

    def test_extract_ha_keyword_request_variants(self):
        self.assertEqual(bridge_handlers.extract_ha_keyword_request("HA open garage"), (True, "open garage"))
        self.assertEqual(
            bridge_handlers.extract_ha_keyword_request("Home Assistant: turn off light"),
            (True, "turn off light"),
        )
        self.assertEqual(bridge_handlers.extract_ha_keyword_request("ha"), (True, ""))
        self.assertEqual(bridge_handlers.extract_ha_keyword_request("happy path"), (False, ""))

    def test_extract_server3_keyword_request_variants(self):
        self.assertEqual(
            bridge_handlers.extract_server3_keyword_request("Server3 TV open Firefox"),
            (True, "open Firefox"),
        )
        self.assertEqual(
            bridge_handlers.extract_server3_keyword_request("server3 tv: play youtube top result"),
            (True, "play youtube top result"),
        )
        self.assertEqual(bridge_handlers.extract_server3_keyword_request("server3 tv"), (True, ""))
        self.assertEqual(bridge_handlers.extract_server3_keyword_request("server3 status"), (False, ""))

    def test_extract_nextcloud_keyword_request_variants(self):
        self.assertEqual(
            bridge_handlers.extract_nextcloud_keyword_request("Nextcloud list files"),
            (True, "list files"),
        )
        self.assertEqual(
            bridge_handlers.extract_nextcloud_keyword_request("nextcloud: create event tomorrow"),
            (True, "create event tomorrow"),
        )
        self.assertEqual(bridge_handlers.extract_nextcloud_keyword_request("nextcloud"), (True, ""))
        self.assertEqual(bridge_handlers.extract_nextcloud_keyword_request("nextcloudx"), (False, ""))

    def test_strip_required_prefix_variants(self):
        prefixes = ["@helper", "helper:"]
        self.assertEqual(
            bridge_handlers.strip_required_prefix("@helper summarize this", prefixes, True),
            (True, "summarize this"),
        )
        self.assertEqual(
            bridge_handlers.strip_required_prefix("HELPER: summarize this", prefixes, True),
            (True, "summarize this"),
        )
        self.assertEqual(
            bridge_handlers.strip_required_prefix("@helperbot should not match", prefixes, True),
            (False, "@helperbot should not match"),
        )
        self.assertEqual(
            bridge_handlers.strip_required_prefix("@helper\u00a0summarize this", prefixes, True),
            (True, "summarize this"),
        )
        self.assertEqual(
            bridge_handlers.strip_required_prefix("@helper\u00a0", prefixes, True),
            (True, ""),
        )
        self.assertEqual(
            bridge_handlers.strip_required_prefix("@helper, summarize this", prefixes, True),
            (True, "summarize this"),
        )
        self.assertEqual(
            bridge_handlers.strip_required_prefix("@helper. summarize this", prefixes, True),
            (True, "summarize this"),
        )

    def test_build_reply_context_prompt_from_reply_to_message_text(self):
        prompt = bridge_handlers.build_reply_context_prompt(
            {
                "text": "Это про что",
                "reply_to_message": {
                    "message_id": 77,
                    "text": "Доброе утро, Путиловы! ☀️\n\nДаю справку: ...",
                    "from": {"username": "Govorun TPG 2026"},
                },
            }
        )
        self.assertIn("Reply Context:", prompt)
        self.assertIn("Original Message Author: Govorun TPG 2026", prompt)
        self.assertIn("Original Telegram Message ID: 77", prompt)
        self.assertIn("Message User Replied To:", prompt)
        self.assertIn("Доброе утро, Путиловы!", prompt)

    def test_build_reply_context_prompt_mentions_reply_media_without_text(self):
        prompt = bridge_handlers.build_reply_context_prompt(
            {
                "text": "А это что?",
                "reply_to_message": {
                    "message_id": 91,
                    "photo": [{"file_id": "photo-1", "file_size": 100}],
                    "from": {"username": "Telegram User"},
                },
            }
        )
        self.assertIn("Reply Context:", prompt)
        self.assertIn("Original Telegram Message ID: 91", prompt)
        self.assertIn("В исходном сообщении было изображение.", prompt)

    @mock.patch.object(bridge_handlers, "transcribe_voice_for_chat", return_value="turn on the light")
    def test_prepare_prompt_input_rejects_voice_transcript_without_required_prefix(
        self, transcribe_voice_for_chat
    ):
        client = FakeTelegramClient()
        config = make_config(required_prefixes=["@helper"])
        progress = mock.Mock()

        prepared = bridge_handlers.prepare_prompt_input(
            state=bridge.State(),
            config=config,
            client=client,
            chat_id=1,
            message_id=11,
            prompt="",
            photo_file_id=None,
            voice_file_id="voice-1",
            document=None,
            progress=progress,
            enforce_voice_prefix_from_transcript=True,
        )

        self.assertIsNone(prepared)
        self.assertEqual(len(client.messages), 1)
        self.assertIn("Helper mode needs a prefixed prompt.", client.messages[0][1])
        transcribe_voice_for_chat.assert_called_once()

    @mock.patch.object(bridge_handlers, "transcribe_voice_for_chat", return_value="turn on the light")
    def test_prepare_prompt_input_ignores_whatsapp_voice_transcript_without_prefix(
        self, transcribe_voice_for_chat
    ):
        client = FakeTelegramClient(channel_name="whatsapp")
        config = make_config(required_prefixes=["@helper"])
        progress = mock.Mock()

        prepared = bridge_handlers.prepare_prompt_input(
            state=bridge.State(),
            config=config,
            client=client,
            chat_id=1,
            message_id=110,
            prompt="",
            photo_file_id=None,
            voice_file_id="voice-wa-1",
            document=None,
            progress=progress,
            enforce_voice_prefix_from_transcript=True,
        )

        self.assertIsNone(prepared)
        self.assertEqual(client.messages, [])
        transcribe_voice_for_chat.assert_called_once()

    @mock.patch.object(bridge_handlers, "transcribe_voice_for_chat", return_value="@helper")
    def test_prepare_prompt_input_ignores_whatsapp_voice_prefix_without_action(
        self, transcribe_voice_for_chat
    ):
        client = FakeTelegramClient(channel_name="whatsapp")
        config = make_config(required_prefixes=["@helper"])
        progress = mock.Mock()

        prepared = bridge_handlers.prepare_prompt_input(
            state=bridge.State(),
            config=config,
            client=client,
            chat_id=1,
            message_id=111,
            prompt="",
            photo_file_id=None,
            voice_file_id="voice-wa-2",
            document=None,
            progress=progress,
            enforce_voice_prefix_from_transcript=True,
        )

        self.assertIsNone(prepared)
        self.assertEqual(client.messages, [])
        transcribe_voice_for_chat.assert_called_once()

    @mock.patch.object(bridge_handlers, "transcribe_voice_for_chat", return_value="govoron you ok")
    def test_prepare_prompt_input_whatsapp_voice_prefix_miss_creates_alias_suggestion(
        self, transcribe_voice_for_chat
    ):
        client = FakeTelegramClient(channel_name="whatsapp")
        config = make_config(required_prefixes=["govorun"])
        progress = mock.Mock()
        state = bridge.State()
        state.voice_alias_learning_store = mock.Mock()
        state.voice_alias_learning_store.get_approved_replacements.return_value = []
        state.voice_alias_learning_store.observe_pair.return_value = [
            SimpleNamespace(
                suggestion_id=7,
                source="govoron",
                target="govorun",
                count=2,
            )
        ]

        prepared = bridge_handlers.prepare_prompt_input(
            state=state,
            config=config,
            client=client,
            chat_id=1,
            message_id=113,
            prompt="",
            photo_file_id=None,
            voice_file_id="voice-wa-3",
            document=None,
            progress=progress,
            enforce_voice_prefix_from_transcript=True,
        )

        self.assertIsNone(prepared)
        state.voice_alias_learning_store.observe_pair.assert_called_once_with(
            source="govoron",
            target="govorun",
        )
        self.assertEqual(len(client.messages), 1)
        self.assertIn("Voice correction learning suggestion(s):", client.messages[0][1])
        self.assertIn("Approve with: `/voice-alias approve <id>`", client.messages[0][1])
        transcribe_voice_for_chat.assert_called_once()

    @mock.patch.object(bridge_handlers, "transcribe_voice_for_chat", return_value="@helper turn on the light")
    def test_prepare_prompt_input_accepts_voice_transcript_with_required_prefix(
        self, transcribe_voice_for_chat
    ):
        client = FakeTelegramClient()
        config = make_config(required_prefixes=["@helper"])
        progress = mock.Mock()

        prepared = bridge_handlers.prepare_prompt_input(
            state=bridge.State(),
            config=config,
            client=client,
            chat_id=1,
            message_id=12,
            prompt="",
            photo_file_id=None,
            voice_file_id="voice-2",
            document=None,
            progress=progress,
            enforce_voice_prefix_from_transcript=True,
        )

        self.assertIsNotNone(prepared)
        self.assertEqual(prepared.prompt_text, "turn on the light")
        self.assertEqual(client.messages, [])
        transcribe_voice_for_chat.assert_called_once()

    def test_handle_update_routes_status_command(self):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()
        update = {
            "update_id": 1,
            "message": {
                "message_id": 10,
                "chat": {"id": 1},
                "text": "/status",
            },
        }

        bridge.handle_update(state, config, client, update)
        self.assertTrue(client.messages)
        self.assertIn("Bridge status: online", client.messages[-1][1])

    def test_handle_update_routes_help_alias_with_bot_suffix(self):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()
        update = {
            "update_id": 1,
            "message": {
                "message_id": 20,
                "chat": {"id": 1},
                "text": "/h@architect_bot",
            },
        }

        bridge.handle_update(state, config, client, update)
        self.assertTrue(client.messages)
        self.assertIn("Available commands:", client.messages[-1][1])
        self.assertIn("server3-tv-start", client.messages[-1][1])
        self.assertIn("server3-tv-stop", client.messages[-1][1])
        self.assertIn("Use `Server3 TV ...`", client.messages[-1][1])
        self.assertIn("Mention `server2` or `staker2`", client.messages[-1][1])
        self.assertIn("Use `Nextcloud ...`", client.messages[-1][1])
        self.assertIn("Use `SRO ...`", client.messages[-1][1])
        self.assertIn("/cancel or /c", client.messages[-1][1])
        self.assertIn("/voice-alias add <source> => <target>", client.messages[-1][1])

    def test_handle_update_routes_cancel_when_no_active_request(self):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()
        update = {
            "update_id": 2,
            "message": {
                "message_id": 21,
                "chat": {"id": 1},
                "text": "/cancel",
            },
        }

        bridge.handle_update(state, config, client, update)
        self.assertTrue(client.messages)
        self.assertEqual(client.messages[-1][1], "No active request to cancel.")

    def test_handle_update_routes_cancel_when_request_active(self):
        state = bridge.State()
        with state.lock:
            state.busy_chats.add(1)
            state.cancel_events[1] = threading.Event()
        client = FakeTelegramClient()
        config = make_config()
        update = {
            "update_id": 3,
            "message": {
                "message_id": 22,
                "chat": {"id": 1},
                "text": "/cancel",
            },
        }

        bridge.handle_update(state, config, client, update)
        self.assertTrue(client.messages)
        self.assertEqual(client.messages[-1][1], "Cancel requested. Stopping current request.")
        with state.lock:
            self.assertTrue(state.cancel_events["tg:1"].is_set())

    def test_handle_update_routes_c_alias_when_request_active(self):
        state = bridge.State()
        with state.lock:
            state.busy_chats.add(1)
            state.cancel_events[1] = threading.Event()
        client = FakeTelegramClient()
        config = make_config()
        update = {
            "update_id": 4,
            "message": {
                "message_id": 23,
                "chat": {"id": 1},
                "text": "/c",
            },
        }

        bridge.handle_update(state, config, client, update)
        self.assertTrue(client.messages)
        self.assertEqual(client.messages[-1][1], "Cancel requested. Stopping current request.")
        with state.lock:
            self.assertTrue(state.cancel_events["tg:1"].is_set())

    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_ignores_non_prefixed_when_required(self, start_message_worker):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config(required_prefixes=["@helper"])
        update = {
            "update_id": 100,
            "message": {
                "message_id": 200,
                "chat": {"id": 1},
                "text": "hello there",
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertFalse(start_message_worker.called)
        self.assertEqual(client.messages, [])

    def test_handle_update_accepts_prefixed_status_command_when_required(self):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config(required_prefixes=["@helper"])
        update = {
            "update_id": 101,
            "message": {
                "message_id": 201,
                "chat": {"id": 1},
                "text": "@helper /status",
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertTrue(client.messages)
        self.assertIn("Bridge status: online", client.messages[-1][1])

    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_whatsapp_voice_alias_command_bypasses_prefix_requirement(
        self, start_message_worker
    ):
        state = bridge.State()
        state.voice_alias_learning_store = mock.Mock()
        state.voice_alias_learning_store.list_pending.return_value = []
        client = FakeTelegramClient(channel_name="whatsapp")
        config = make_config(required_prefixes=["govorun"], channel_plugin="whatsapp")
        update = {
            "update_id": 1011,
            "message": {
                "message_id": 2011,
                "chat": {"id": 1, "type": "group"},
                "text": "/voice-alias list",
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertFalse(start_message_worker.called)
        self.assertEqual(len(client.messages), 1)
        self.assertIn("No pending learned voice alias suggestions.", client.messages[0][1])

    def test_handle_update_rejects_prefix_without_action(self):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config(required_prefixes=["@helper"])
        update = {
            "update_id": 102,
            "message": {
                "message_id": 202,
                "chat": {"id": 1},
                "text": "@helper",
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertEqual(len(client.messages), 1)
        self.assertIn("Helper mode needs a prefixed prompt.", client.messages[0][1])

    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_allows_prefix_only_reply_to_use_reply_context(self, start_message_worker):
        state = bridge.State()
        client = FakeTelegramClient(channel_name="whatsapp")
        config = make_config(required_prefixes=["говорун"], channel_plugin="whatsapp")
        update = {
            "update_id": 1024,
            "message": {
                "message_id": 2024,
                "chat": {"id": 1, "type": "group"},
                "text": "говорун",
                "reply_to_message": {
                    "text": "Посмотри на это и ответь по сути.",
                    "from": {"username": "Vlad"},
                },
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertTrue(start_message_worker.called)
        kwargs = start_message_worker.call_args.kwargs
        self.assertIn("Reply Context:", kwargs["prompt"])
        self.assertIn("Original Message Author: Vlad", kwargs["prompt"])
        self.assertIn("Посмотри на это и ответь по сути.", kwargs["prompt"])
        self.assertEqual(client.messages, [])

    @mock.patch.object(bridge_handlers, "start_message_worker")
    @mock.patch.object(bridge_handlers, "archive_media_path", return_value="/tmp/archive.jpg")
    @mock.patch.object(bridge_handlers, "download_photo_to_temp", return_value="/tmp/incoming.jpg")
    @mock.patch("telegram_bridge.handlers.os.remove")
    def test_handle_update_prewarms_attachment_archive_for_unprefixed_photo(
        self,
        remove_mock,
        download_photo_to_temp,
        archive_media_path,
        start_message_worker,
    ):
        attachment_store = mock.Mock()
        attachment_store.get_record.return_value = None
        attachment_store.get_summary.return_value = ""
        state = bridge.State(attachment_store=attachment_store)
        client = FakeTelegramClient(channel_name="whatsapp")
        config = make_config(required_prefixes=["govorun"], channel_plugin="whatsapp")
        update = {
            "update_id": 1025,
            "message": {
                "message_id": 2025,
                "chat": {"id": 1, "type": "group"},
                "photo": [{"file_id": "photo-archive-1", "file_size": 100}],
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertFalse(start_message_worker.called)
        download_photo_to_temp.assert_called_once()
        archive_media_path.assert_called_once()
        remove_mock.assert_called_once_with("/tmp/incoming.jpg")

    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_defers_voice_prefix_check_to_transcript_when_required(
        self, start_message_worker
    ):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config(required_prefixes=["@helper"])
        update = {
            "update_id": 103,
            "message": {
                "message_id": 203,
                "chat": {"id": 1},
                "voice": {"file_id": "voice-1"},
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertTrue(start_message_worker.called)
        kwargs = start_message_worker.call_args.kwargs
        self.assertEqual(kwargs["prompt"], "")
        self.assertEqual(kwargs["voice_file_id"], "voice-1")
        self.assertTrue(kwargs["enforce_voice_prefix_from_transcript"])
        self.assertEqual(client.messages, [])

    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_mixed_whatsapp_photo_payload_keeps_photo(self, start_message_worker):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()
        update = {
            "update_id": 150,
            "message": {
                "message_id": 250,
                "chat": {"id": 1},
                "text": "photo caption",
                "caption": "photo caption",
                "photo": [{"file_id": "photo-1", "file_size": 100}],
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertTrue(start_message_worker.called)
        kwargs = start_message_worker.call_args.kwargs
        self.assertIn("Current Telegram Context:", kwargs["prompt"])
        self.assertIn("Current User Message:\nphoto caption", kwargs["prompt"])
        self.assertEqual(kwargs["photo_file_id"], "photo-1")
        self.assertIsNone(kwargs["voice_file_id"])

    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_whatsapp_multi_photo_payload_keeps_all_photos(self, start_message_worker):
        state = bridge.State()
        client = FakeTelegramClient(channel_name="whatsapp")
        config = make_config(channel_plugin="whatsapp")
        update = {
            "update_id": 152,
            "message": {
                "message_id": 252,
                "chat": {"id": 1},
                "caption": "Please analyze these images.",
                "photo": [
                    {"file_id": "wa-photo-1", "file_size": 101, "mime_type": "image/jpeg"},
                    {"file_id": "wa-photo-2", "file_size": 102, "mime_type": "image/jpeg"},
                    {"file_id": "wa-photo-3", "file_size": 103, "mime_type": "image/jpeg"},
                ],
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertTrue(start_message_worker.called)
        kwargs = start_message_worker.call_args.kwargs
        self.assertEqual(kwargs["prompt"], "Please analyze these images.")
        self.assertEqual(kwargs["photo_file_id"], "wa-photo-1")
        self.assertEqual(kwargs["photo_file_ids"], ["wa-photo-1", "wa-photo-2", "wa-photo-3"])
        self.assertIsNone(kwargs["voice_file_id"])

    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_text_message_never_routes_to_voice_transcribe_path(self, start_message_worker):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()
        update = {
            "update_id": 151,
            "message": {
                "message_id": 251,
                "chat": {"id": 1},
                "text": "@helper status",
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertTrue(start_message_worker.called)
        kwargs = start_message_worker.call_args.kwargs
        self.assertEqual(kwargs["voice_file_id"], None)
        self.assertFalse(kwargs["enforce_voice_prefix_from_transcript"])

    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_accepts_prefixed_voice_caption_when_required(self, start_message_worker):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config(required_prefixes=["@helper"])
        update = {
            "update_id": 104,
            "message": {
                "message_id": 204,
                "chat": {"id": 1},
                "voice": {"file_id": "voice-2"},
                "caption": "@helper transcribe this",
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertTrue(start_message_worker.called)
        kwargs = start_message_worker.call_args.kwargs
        self.assertIn("Current Telegram Context:", kwargs["prompt"])
        self.assertIn("Current User Message:\ntranscribe this", kwargs["prompt"])
        self.assertEqual(kwargs["voice_file_id"], "voice-2")
        self.assertFalse(kwargs["enforce_voice_prefix_from_transcript"])

    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_allows_unprefixed_private_message_when_configured(
        self, start_message_worker
    ):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config(
            required_prefixes=["@helper"],
            require_prefix_in_private=False,
        )
        update = {
            "update_id": 105,
            "message": {
                "message_id": 205,
                "chat": {"id": 1, "type": "private"},
                "text": "hello there",
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertTrue(start_message_worker.called)
        kwargs = start_message_worker.call_args.kwargs
        self.assertIn("Current Telegram Context:", kwargs["prompt"])
        self.assertIn("Current User Message:\nhello there", kwargs["prompt"])
        self.assertFalse(kwargs["enforce_voice_prefix_from_transcript"])

    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_includes_reply_context_in_prompt(self, start_message_worker):
        state = bridge.State()
        client = FakeTelegramClient(channel_name="whatsapp")
        config = make_config(channel_plugin="whatsapp")
        update = {
            "update_id": 1051,
            "message": {
                "message_id": 2051,
                "chat": {"id": 1, "type": "private"},
                "text": "Это про что",
                "reply_to_message": {
                    "message_id": 99,
                    "text": "Доброе утро, Путиловы! ☀️\n\nДаю справку: В Эрмитаже живут коты.",
                    "from": {"username": "Govorun TPG 2026"},
                },
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertTrue(start_message_worker.called)
        kwargs = start_message_worker.call_args.kwargs
        self.assertIn("Current Telegram Context:", kwargs["prompt"])
        self.assertIn("- Current Message ID: 2051", kwargs["prompt"])
        self.assertIn("Reply Context:", kwargs["prompt"])
        self.assertIn("Original Telegram Message ID: 99", kwargs["prompt"])
        self.assertIn("Original Message Author: Govorun TPG 2026", kwargs["prompt"])
        self.assertIn("Current User Message:\nЭто про что", kwargs["prompt"])
        self.assertFalse(kwargs["enforce_voice_prefix_from_transcript"])

    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_includes_current_telegram_context_for_message_id_targeting(
        self, start_message_worker
    ):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()
        update = {
            "update_id": 1052,
            "message": {
                "message_id": 2052,
                "chat": {"id": 1, "type": "group"},
                "message_thread_id": 498,
                "is_topic_message": True,
                "text": "Send it to this chat message id not another one",
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertTrue(start_message_worker.called)
        kwargs = start_message_worker.call_args.kwargs
        self.assertIn("Current Telegram Context:", kwargs["prompt"])
        self.assertIn("- Current Message ID: 2052", kwargs["prompt"])
        self.assertIn("- Topic ID: 498", kwargs["prompt"])
        self.assertIn("- Chat ID: 1", kwargs["prompt"])
        self.assertIn(
            'default to Current Message ID unless they specify another numeric target.',
            kwargs["prompt"],
        )
        self.assertIn(
            "Current User Message:\nSend it to this chat message id not another one",
            kwargs["prompt"],
        )

    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_keeps_prefix_required_in_group_when_private_bypass_enabled(
        self, start_message_worker
    ):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config(
            required_prefixes=["@helper"],
            require_prefix_in_private=False,
        )
        update = {
            "update_id": 106,
            "message": {
                "message_id": 206,
                "chat": {"id": 1, "type": "group"},
                "text": "hello there",
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertFalse(start_message_worker.called)
        self.assertEqual(client.messages, [])

    @mock.patch.object(bridge_handlers, "start_youtube_worker")
    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_routes_bare_youtube_link_without_prefix_in_group(
        self,
        start_message_worker,
        start_youtube_worker,
    ):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config(
            required_prefixes=["@helper"],
            require_prefix_in_private=False,
        )
        update = {
            "update_id": 107,
            "message": {
                "message_id": 207,
                "chat": {"id": 1, "type": "group"},
                "text": "https://www.youtube.com/watch?v=yD5DFL3xPmo\nsummarise this",
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertFalse(start_message_worker.called)
        self.assertTrue(start_youtube_worker.called)
        kwargs = start_youtube_worker.call_args.kwargs
        self.assertEqual(kwargs["request_text"], "https://www.youtube.com/watch?v=yD5DFL3xPmo\nsummarise this")
        self.assertEqual(kwargs["youtube_url"], "https://www.youtube.com/watch?v=yD5DFL3xPmo")
        self.assertEqual(client.messages, [])

    @mock.patch.object(bridge_handlers, "start_dishframed_worker")
    @mock.patch.object(bridge_handlers, "register_cancel_event", return_value=threading.Event())
    @mock.patch.object(bridge_handlers, "mark_busy", return_value=True)
    def test_handle_update_routes_dishframed_command_with_photo(
        self,
        mark_busy,
        register_cancel_event,
        start_dishframed_worker,
    ):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()
        update = {
            "update_id": 181,
            "message": {
                "message_id": 281,
                "chat": {"id": 1, "type": "private"},
                "caption": "/dishframed",
                "photo": [{"file_id": "small"}, {"file_id": "large"}],
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertTrue(start_dishframed_worker.called)
        kwargs = start_dishframed_worker.call_args.kwargs
        self.assertEqual(kwargs["photo_file_ids"], ["large"])
        mark_busy.assert_called_once()
        register_cancel_event.assert_called_once()

    def test_handle_update_rejects_dishframed_without_photo(self):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()
        update = {
            "update_id": 182,
            "message": {
                "message_id": 282,
                "chat": {"id": 1, "type": "private"},
                "text": "/dishframed",
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertEqual(
            client.messages[-1][:3],
            (1, bridge_handlers.DISHFRAMED_USAGE_MESSAGE, 282),
        )

    @mock.patch.object(bridge_handlers, "start_dishframed_worker")
    @mock.patch.object(bridge_handlers, "register_cancel_event", return_value=threading.Event())
    @mock.patch.object(bridge_handlers, "mark_busy", return_value=True)
    def test_handle_update_routes_dishframed_command_with_recent_scope_photo(
        self,
        mark_busy,
        register_cancel_event,
        start_dishframed_worker,
    ):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()

        bridge_handlers.remember_recent_scope_photos(
            state=state,
            scope_key="tg:1:topic:1712",
            message_id=283,
            photo_file_ids=["large"],
        )

        bridge.handle_update(
            state,
            config,
            client,
            {
                "update_id": 184,
                "message": {
                    "message_id": 284,
                    "chat": {"id": 1, "type": "supergroup"},
                    "is_topic_message": True,
                    "message_thread_id": 1712,
                    "text": "/dishframed",
                },
            },
        )

        self.assertTrue(start_dishframed_worker.called)
        kwargs = start_dishframed_worker.call_args.kwargs
        self.assertEqual(kwargs["photo_file_ids"], ["large"])
        mark_busy.assert_called_once()
        register_cancel_event.assert_called_once()

    @mock.patch.object(bridge_handlers, "start_youtube_worker")
    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_does_not_auto_route_non_request_text_with_youtube_link(
        self,
        start_message_worker,
        start_youtube_worker,
    ):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config(
            required_prefixes=["@helper"],
            require_prefix_in_private=False,
        )
        update = {
            "update_id": 108,
            "message": {
                "message_id": 208,
                "chat": {"id": 1, "type": "group"},
                "text": "watch this https://www.youtube.com/watch?v=yD5DFL3xPmo",
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertFalse(start_message_worker.called)
        self.assertFalse(start_youtube_worker.called)
        self.assertEqual(client.messages, [])

    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_routes_ha_keyword_prompt_stateless(self, start_message_worker):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()
        update = {
            "update_id": 10,
            "message": {
                "message_id": 40,
                "chat": {"id": 1},
                "text": "Home Assistant turn on masters AC to dry mode at 9:25am",
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertTrue(start_message_worker.called)
        kwargs = start_message_worker.call_args.kwargs
        self.assertTrue(kwargs["stateless"])
        self.assertIn("Home Assistant priority mode is active.", kwargs["prompt"])
        self.assertIn("User request: turn on masters AC to dry mode at 9:25am", kwargs["prompt"])
        self.assertEqual(client.messages, [])

    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_routes_server3_keyword_prompt_stateless(self, start_message_worker):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()
        update = {
            "update_id": 12,
            "message": {
                "message_id": 42,
                "chat": {"id": 1},
                "text": "Server3 TV open desktop and play top youtube result for deephouse 2026",
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertTrue(start_message_worker.called)
        kwargs = start_message_worker.call_args.kwargs
        self.assertTrue(kwargs["stateless"])
        self.assertIn("Server3 TV operations priority mode is active.", kwargs["prompt"])
        self.assertIn(
            "User request: open desktop and play top youtube result for deephouse 2026",
            kwargs["prompt"],
        )
        self.assertEqual(client.messages, [])

    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_rejects_server3_keyword_without_action(self, start_message_worker):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()
        update = {
            "update_id": 13,
            "message": {
                "message_id": 43,
                "chat": {"id": 1},
                "text": "Server3 TV",
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertFalse(start_message_worker.called)
        self.assertEqual(len(client.messages), 1)
        self.assertIn("Server3 TV mode needs an action.", client.messages[0][1])

    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_routes_nextcloud_keyword_prompt_stateless(self, start_message_worker):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()
        update = {
            "update_id": 14,
            "message": {
                "message_id": 44,
                "chat": {"id": 1},
                "text": "Nextcloud list files in Documents",
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertTrue(start_message_worker.called)
        kwargs = start_message_worker.call_args.kwargs
        self.assertTrue(kwargs["stateless"])
        self.assertIn("Nextcloud operations priority mode is active.", kwargs["prompt"])
        self.assertIn("User request: list files in Documents", kwargs["prompt"])
        self.assertEqual(client.messages, [])

    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_rejects_nextcloud_keyword_without_action(self, start_message_worker):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()
        update = {
            "update_id": 15,
            "message": {
                "message_id": 45,
                "chat": {"id": 1},
                "text": "Nextcloud",
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertFalse(start_message_worker.called)
        self.assertEqual(len(client.messages), 1)
        self.assertIn("Nextcloud mode needs an action.", client.messages[0][1])

    @mock.patch.object(bridge_handlers, "start_message_worker")
    def test_handle_update_rejects_ha_keyword_without_action(self, start_message_worker):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()
        update = {
            "update_id": 11,
            "message": {
                "message_id": 41,
                "chat": {"id": 1},
                "text": "HA",
            },
        }

        bridge.handle_update(state, config, client, update)

        self.assertFalse(start_message_worker.called)
        self.assertEqual(len(client.messages), 1)
        self.assertIn("HA mode needs an action.", client.messages[0][1])

    def test_handle_update_rejects_too_long_input_before_worker_dispatch(self):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config(max_input_chars=10)
        update = {
            "update_id": 2,
            "message": {
                "message_id": 30,
                "chat": {"id": 1},
                "text": "x" * 11,
            },
        }

        bridge.handle_update(state, config, client, update)
        self.assertEqual(len(client.messages), 1)
        self.assertIn("Input too long (11 chars). Max is 10.", client.messages[0][1])

    def test_handle_update_denies_non_allowlisted_chat(self):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config(allowed_chat_ids={1})
        update = {
            "update_id": 3,
            "message": {
                "message_id": 31,
                "chat": {"id": 2},
                "text": "hello",
            },
        }

        bridge.handle_update(state, config, client, update)
        self.assertEqual(len(client.messages), 1)
        self.assertEqual(client.messages[0][1], config.denied_message)

    def test_handle_update_allows_private_chat_when_unlisted_allowed(self):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config(
            allowed_chat_ids={1},
            allow_private_chats_unlisted=True,
        )
        update = {
            "update_id": 4,
            "message": {
                "message_id": 31,
                "chat": {"id": 2, "type": "private"},
                "text": "hello",
            },
        }

        with mock.patch.object(bridge_handlers, "start_message_worker") as start_message_worker:
            bridge.handle_update(state, config, client, update)

        self.assertTrue(start_message_worker.called)
        self.assertEqual(client.messages, [])

    def test_handle_update_rejects_when_chat_busy(self):
        state = bridge.State()
        state.busy_chats.add(1)
        client = FakeTelegramClient()
        config = make_config()
        update = {
            "update_id": 4,
            "message": {
                "message_id": 32,
                "chat": {"id": 1},
                "text": "run now",
            },
        }

        bridge.handle_update(state, config, client, update)
        self.assertEqual(len(client.messages), 1)
        self.assertEqual(client.messages[0][1], config.busy_message)

