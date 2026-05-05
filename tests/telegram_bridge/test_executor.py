"""Tests for Executor — auto-split from test_bridge_core.py."""

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


class TestExecutor(unittest.TestCase):
    def test_parse_executor_output_json_stream(self):
        sample_stream = (
            '{"type":"thread.started","thread_id":"thread-123"}\n'
            '{"type":"item.completed","item":{"type":"agent_message","text":"hello"}}\n'
        )
        thread_id, output = bridge.parse_executor_output(sample_stream)
        self.assertEqual(thread_id, "thread-123")
        self.assertEqual(output, "hello")

    def test_bounded_text_buffer_marks_truncation(self):
        buffer = bridge.BoundedTextBuffer(
            64,
            head_chars=12,
            truncation_marker="\n...[truncated]...\n",
        )
        buffer.append("HEAD-SECTION-")
        buffer.append("x" * 200)
        rendered = buffer.render()
        self.assertLessEqual(len(rendered), 64)
        self.assertIn("...[truncated]...", rendered)
        self.assertTrue(rendered.startswith("HEAD-SECTION"))

    def test_to_telegram_chunks_uses_real_newline_prefix(self):
        chunks = bridge.to_telegram_chunks("x" * 5000)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(chunks[0].startswith("[1/2]\n"))
        self.assertNotIn("\\n", chunks[0][:10])

    def test_parse_stream_json_line_rejects_invalid_payloads(self):
        self.assertIsNone(bridge_executor.parse_stream_json_line("not-json"))
        self.assertIsNone(bridge_executor.parse_stream_json_line("[]"))
        self.assertIsNone(bridge_executor.parse_stream_json_line(""))

    def test_executor_script_uses_default_runtime_root_without_embedding_policy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            repo_root = temp_root / "govorunbot"
            script_dir = repo_root / "src" / "telegram_bridge"
            script_dir.mkdir(parents=True)
            script_path = script_dir / "executor.sh"
            script_path.write_text(
                (ROOT / "src" / "telegram_bridge" / "executor.sh").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            script_path.chmod(0o755)
            (repo_root / "AGENTS.md").write_text("TEMP_GOVORUN_POLICY\n", encoding="utf-8")

            bin_dir = temp_root / "bin"
            bin_dir.mkdir()
            fake_codex = bin_dir / "codex"
            fake_codex.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import json",
                        "import os",
                        "import sys",
                        "payload = sys.stdin.read()",
                        "print(json.dumps({",
                        "    'type': 'item.completed',",
                        "    'item': {",
                        "        'type': 'agent_message',",
                        "        'text': f'PWD={os.getcwd()}\\n{payload}',",
                        "    },",
                        "}))",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_codex.chmod(0o755)

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
            env["CODEX_BIN"] = str(fake_codex)
            env["CODEX_POLICY_FILE"] = "AGENTS.md"
            env.pop("TELEGRAM_RUNTIME_ROOT", None)
            env.pop("TELEGRAM_SHARED_CORE_ROOT", None)
            env.pop("TELEGRAM_CODEX_WORKDIR", None)

            result = subprocess.run(
                ["bash", str(script_path), "new"],
                input="hello from test\n",
                text=True,
                capture_output=True,
                cwd=str(ROOT),
                env=env,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn(f"PWD={repo_root}", result.stdout)
            self.assertNotIn("TEMP_GOVORUN_POLICY", result.stdout)
            self.assertIn("User request:\\nhello from test", result.stdout)

    def test_executor_script_runs_from_runtime_root_overlay_without_embedding_policy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            shared_root = temp_root / "matrix"
            script_dir = shared_root / "src" / "telegram_bridge"
            script_dir.mkdir(parents=True)
            script_path = script_dir / "executor.sh"
            script_path.write_text(
                (ROOT / "src" / "telegram_bridge" / "executor.sh").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            script_path.chmod(0o755)

            runtime_root = temp_root / "oraclebot"
            runtime_root.mkdir(parents=True)
            (runtime_root / "AGENTS.md").write_text("TEMP_ORACLE_POLICY\n", encoding="utf-8")

            bin_dir = temp_root / "bin"
            bin_dir.mkdir()
            fake_codex = bin_dir / "codex"
            fake_codex.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import json",
                        "import os",
                        "import sys",
                        "payload = sys.stdin.read()",
                        "print(json.dumps({",
                        "    'type': 'item.completed',",
                        "    'item': {",
                        "        'type': 'agent_message',",
                        "        'text': f'PWD={os.getcwd()}\\n{payload}',",
                        "    },",
                        "}))",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_codex.chmod(0o755)

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
            env["CODEX_BIN"] = str(fake_codex)
            env["CODEX_POLICY_FILE"] = "AGENTS.md"
            env.pop("TELEGRAM_SHARED_CORE_ROOT", None)
            env.pop("TELEGRAM_CODEX_WORKDIR", None)
            env["TELEGRAM_RUNTIME_ROOT"] = str(runtime_root)

            result = subprocess.run(
                ["bash", str(script_path), "new"],
                input="hello from overlay test\n",
                text=True,
                capture_output=True,
                cwd=str(ROOT),
                env=env,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn(f"PWD={runtime_root}", result.stdout)
            self.assertNotIn("TEMP_ORACLE_POLICY", result.stdout)
            self.assertIn("User request:\\nhello from overlay test", result.stdout)

    def test_executor_script_runs_auth_sync_hook_when_available(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            repo_root = temp_root / "matrix"
            script_dir = repo_root / "src" / "telegram_bridge"
            script_dir.mkdir(parents=True)
            script_path = script_dir / "executor.sh"
            script_path.write_text(
                (ROOT / "src" / "telegram_bridge" / "executor.sh").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            script_path.chmod(0o755)

            sync_dir = repo_root / "ops" / "codex"
            sync_dir.mkdir(parents=True)
            marker_path = repo_root / "auth-sync.marker"
            sync_script = sync_dir / "sync_shared_auth.sh"
            sync_script.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                f"printf 'synced\\n' > {str(marker_path)!r}\n",
                encoding="utf-8",
            )
            sync_script.chmod(0o755)

            bin_dir = temp_root / "bin"
            bin_dir.mkdir()
            fake_codex = bin_dir / "codex"
            fake_codex.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import json",
                        "import sys",
                        "payload = sys.stdin.read()",
                        "print(json.dumps({",
                        "    'type': 'item.completed',",
                        "    'item': {",
                        "        'type': 'agent_message',",
                        "        'text': payload,",
                        "    },",
                        "}))",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_codex.chmod(0o755)

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
            env["CODEX_BIN"] = str(fake_codex)

            result = subprocess.run(
                ["bash", str(script_path), "new"],
                input="hello with auth sync\n",
                text=True,
                capture_output=True,
                cwd=str(ROOT),
                env=env,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertEqual(marker_path.read_text(encoding="utf-8"), "synced\n")

    def test_send_executor_output_supports_structured_envelope(self):
        client = FakeTelegramClient()
        rendered = bridge_handlers.send_executor_output(
            client=client,
            chat_id=1,
            message_id=16,
            output=json.dumps(
                {
                    "telegram_outbound": {
                        "text": "photo caption",
                        "media_ref": "https://example.com/pic.jpg",
                    }
                }
            ),
        )
        self.assertEqual(rendered, "photo caption")
        self.assertEqual(len(client.photos), 1)
        self.assertEqual(client.photos[0][1], "https://example.com/pic.jpg")

    def test_send_executor_output_sends_whatsapp_plain_text_with_prefix(self):
        client = FakeTelegramClient(channel_name="whatsapp")
        rendered = bridge_handlers.send_executor_output(
            client=client,
            chat_id=1,
            message_id=116,
            output="hello there",
        )
        self.assertEqual(rendered, "Даю справку: hello there")
        self.assertEqual(client.messages[-1][1], "Даю справку: hello there")

    def test_send_executor_output_rewrites_whatsapp_legacy_prefix(self):
        client = FakeTelegramClient(channel_name="whatsapp")
        rendered = bridge_handlers.send_executor_output(
            client=client,
            chat_id=1,
            message_id=117,
            output="Говорун: already prefixed",
        )
        self.assertEqual(rendered, "Даю справку: already prefixed")
        self.assertEqual(client.messages[-1][1], "Даю справку: already prefixed")

    def test_send_executor_output_keeps_whatsapp_new_prefix_single(self):
        client = FakeTelegramClient(channel_name="whatsapp")
        rendered = bridge_handlers.send_executor_output(
            client=client,
            chat_id=1,
            message_id=117,
            output="Даю справку: already prefixed",
        )
        self.assertEqual(rendered, "Даю справку: already prefixed")
        self.assertEqual(client.messages[-1][1], "Даю справку: already prefixed")

    def test_send_executor_output_sends_whatsapp_media_caption_with_prefix(self):
        client = FakeTelegramClient(channel_name="whatsapp")
        rendered = bridge_handlers.send_executor_output(
            client=client,
            chat_id=1,
            message_id=118,
            output="[[media:https://example.com/pic.jpg]] caption",
        )
        self.assertEqual(rendered, "Даю справку: caption")
        self.assertEqual(client.photos[0][2], "Даю справку: caption")

    def test_send_executor_output_invalid_structured_payload_falls_back_to_raw_text(self):
        client = FakeTelegramClient()
        output = '{"telegram_outbound":"bad"}'
        rendered = bridge_handlers.send_executor_output(
            client=client,
            chat_id=1,
            message_id=17,
            output=output,
        )
        self.assertEqual(rendered, output)
        self.assertEqual(client.messages[-1][1], output)
        self.assertEqual(len(client.photos), 0)

    def test_send_executor_output_routes_audio_to_voice_when_requested(self):
        client = FakeTelegramClient()
        rendered = bridge_handlers.send_executor_output(
            client=client,
            chat_id=1,
            message_id=7,
            output="[[media:/tmp/note.ogg]] [[audio_as_voice]] voice caption",
        )
        self.assertEqual(rendered, "voice caption")
        self.assertEqual(len(client.voices), 1)
        self.assertEqual(len(client.audios), 0)
        self.assertEqual(client.chat_actions, [(1, "record_voice"), (1, "upload_voice")])

    def test_send_executor_output_falls_back_to_audio_when_voice_forbidden(self):
        client = FakeTelegramClient()
        client.raise_on_voice = RuntimeError(
            "Telegram API sendVoice failed: 400 Bad Request: VOICE_MESSAGES_FORBIDDEN"
        )
        rendered = bridge_handlers.send_executor_output(
            client=client,
            chat_id=1,
            message_id=8,
            output="[[media:/tmp/note.ogg]] [[audio_as_voice]] fallback caption",
        )
        self.assertEqual(rendered, "fallback caption")
        self.assertEqual(len(client.voices), 0)
        self.assertEqual(len(client.audios), 1)
        self.assertEqual(client.audios[0][2], "fallback caption")
        self.assertEqual(
            client.chat_actions,
            [(1, "record_voice"), (1, "upload_voice"), (1, "upload_audio")],
        )

    def test_send_executor_output_emits_delivery_events_for_voice_fallback(self):
        client = FakeTelegramClient()
        client.raise_on_voice = RuntimeError(
            "Telegram API sendVoice failed: 400 Bad Request: VOICE_MESSAGES_FORBIDDEN"
        )
        with mock.patch.object(bridge_handlers.response_delivery, "emit_event") as emit_mock:
            bridge_handlers.send_executor_output(
                client=client,
                chat_id=1,
                message_id=12,
                output="[[media:/tmp/note.ogg]] [[audio_as_voice]] fallback caption",
            )

        event_names = [call.args[0] for call in emit_mock.call_args_list]
        self.assertIn("bridge.outbound_delivery_attempt", event_names)
        self.assertIn("bridge.outbound_delivery_fallback", event_names)
        self.assertIn("bridge.outbound_delivery_succeeded", event_names)

    def test_send_executor_output_emits_failed_event_when_media_send_crashes(self):
        client = FakeTelegramClient()
        client.send_document = mock.Mock(side_effect=RuntimeError("disk gone"))
        with mock.patch.object(bridge_handlers.response_delivery, "emit_event") as emit_mock:
            rendered = bridge_handlers.send_executor_output(
                client=client,
                chat_id=1,
                message_id=13,
                output="[[media:https://example.com/file.pdf]] doc caption",
            )
        self.assertEqual(rendered, "doc caption")
        self.assertEqual(len(client.messages), 1)
        self.assertEqual(client.messages[0][1], "doc caption")
        event_names = [call.args[0] for call in emit_mock.call_args_list]
        self.assertIn("bridge.outbound_delivery_failed", event_names)

    def test_send_executor_output_routes_photo_and_document(self):
        client = FakeTelegramClient()
        rendered_photo = bridge_handlers.send_executor_output(
            client=client,
            chat_id=1,
            message_id=9,
            output="[[media:https://example.com/pic.jpg]] photo caption",
        )
        rendered_doc = bridge_handlers.send_executor_output(
            client=client,
            chat_id=1,
            message_id=10,
            output="[[media:https://example.com/file.pdf]] doc caption",
        )
        self.assertEqual(rendered_photo, "photo caption")
        self.assertEqual(rendered_doc, "doc caption")
        self.assertEqual(len(client.photos), 1)
        self.assertEqual(len(client.documents), 1)
        self.assertEqual(client.chat_actions, [(1, "upload_photo"), (1, "upload_document")])

    def test_send_executor_output_preserves_message_thread_id_for_documents(self):
        client = mock.Mock()
        client.channel_name = "telegram"

        rendered = bridge_handlers.send_executor_output(
            client=client,
            chat_id=-1003706836145,
            message_id=1374,
            output="[[media:/tmp/feed.html]] feed",
            message_thread_id=511,
        )

        self.assertEqual(rendered, "feed")
        client.send_chat_action.assert_called_once_with(
            -1003706836145,
            action="upload_document",
            message_thread_id=511,
        )
        client.send_document.assert_called_once_with(
            chat_id=-1003706836145,
            document="/tmp/feed.html",
            caption="feed",
            reply_to_message_id=1374,
            message_thread_id=511,
        )
        client.send_message.assert_not_called()

    def test_extract_prompt_and_media_prefers_media_payload_for_photo_with_caption(self):
        prompt, photo_file_ids, voice_file_id, document = bridge_handlers.extract_prompt_and_media(
            {
                "text": "photo caption",
                "caption": "photo caption",
                "photo": [
                    {"file_id": "p-small", "file_size": 10},
                    {"file_id": "p-large", "file_size": 20},
                ],
            }
        )
        self.assertEqual(prompt, "photo caption")
        self.assertEqual(photo_file_ids, ["p-large"])
        self.assertIsNone(voice_file_id)
        self.assertIsNone(document)

    def test_extract_prompt_and_media_uses_text_fallback_for_document_without_caption(self):
        prompt, photo_file_ids, voice_file_id, document = bridge_handlers.extract_prompt_and_media(
            {
                "text": "summarize this",
                "document": {
                    "file_id": "doc-1",
                    "file_name": "notes.txt",
                    "mime_type": "text/plain",
                },
            }
        )
        self.assertEqual(prompt, "summarize this")
        self.assertEqual(photo_file_ids, [])
        self.assertIsNone(voice_file_id)
        self.assertIsNotNone(document)
        self.assertEqual(document.file_id, "doc-1")

    def test_extract_prompt_and_media_combines_caption_and_text_for_voice(self):
        prompt, photo_file_ids, voice_file_id, document = bridge_handlers.extract_prompt_and_media(
            {
                "text": "extra context",
                "caption": "@helper execute this",
                "voice": {"file_id": "voice-3"},
            }
        )
        self.assertEqual(prompt, "@helper execute this\n\nextra context")
        self.assertEqual(photo_file_ids, [])
        self.assertEqual(voice_file_id, "voice-3")
        self.assertIsNone(document)

    def test_extract_prompt_and_media_uses_replied_photo_when_current_message_has_no_media(self):
        prompt, photo_file_ids, voice_file_id, document = bridge_handlers.extract_prompt_and_media(
            {
                "text": "what about the window?",
                "reply_to_message": {
                    "photo": [
                        {"file_id": "p-small", "file_size": 10},
                        {"file_id": "p-large", "file_size": 20},
                    ],
                },
            }
        )
        self.assertEqual(prompt, "what about the window?")
        self.assertEqual(photo_file_ids, ["p-large"])
        self.assertIsNone(voice_file_id)
        self.assertIsNone(document)

    def test_extract_prompt_and_media_uses_replied_document_when_current_message_has_no_media(self):
        prompt, photo_file_ids, voice_file_id, document = bridge_handlers.extract_prompt_and_media(
            {
                "text": "summarize the quoted file",
                "reply_to_message": {
                    "document": {
                        "file_id": "doc-reply-1",
                        "file_name": "quoted.txt",
                        "mime_type": "text/plain",
                    }
                },
            }
        )
        self.assertEqual(prompt, "summarize the quoted file")
        self.assertEqual(photo_file_ids, [])
        self.assertIsNone(voice_file_id)
        self.assertIsNotNone(document)
        self.assertEqual(document.file_id, "doc-reply-1")

    def test_extract_prompt_and_media_collects_album_photo_ids(self):
        prompt, photo_file_ids, voice_file_id, document = bridge_handlers.extract_prompt_and_media(
            {
                "caption": "Nextcloud add these 3 pics to diary111.docx",
                "media_group_messages": [
                    {
                        "caption": "Nextcloud add these 3 pics to diary111.docx",
                        "photo": [
                            {"file_id": "p1-small", "file_size": 10},
                            {"file_id": "p1-large", "file_size": 20},
                        ],
                    },
                    {
                        "photo": [
                            {"file_id": "p2-small", "file_size": 11},
                            {"file_id": "p2-large", "file_size": 21},
                        ],
                    },
                    {
                        "photo": [
                            {"file_id": "p3-small", "file_size": 12},
                            {"file_id": "p3-large", "file_size": 22},
                        ],
                    },
                ],
            }
        )
        self.assertEqual(prompt, "Nextcloud add these 3 pics to diary111.docx")
        self.assertEqual(photo_file_ids, ["p1-large", "p2-large", "p3-large"])
        self.assertIsNone(voice_file_id)
        self.assertIsNone(document)

    def test_extract_prompt_and_media_collects_whatsapp_flat_photo_ids(self):
        prompt, photo_file_ids, voice_file_id, document = bridge_handlers.extract_prompt_and_media(
            {
                "caption": "Please analyze these images.",
                "photo": [
                    {"file_id": "wa-p1", "file_size": 100, "mime_type": "image/jpeg"},
                    {"file_id": "wa-p2", "file_size": 120, "mime_type": "image/jpeg"},
                    {"file_id": "wa-p3", "file_size": 140, "mime_type": "image/jpeg"},
                ],
            }
        )
        self.assertEqual(prompt, "Please analyze these images.")
        self.assertEqual(photo_file_ids, ["wa-p1", "wa-p2", "wa-p3"])
        self.assertIsNone(voice_file_id)
        self.assertIsNone(document)

    def test_collapse_media_group_updates_merges_album_messages(self):
        updates = [
            {
                "update_id": 101,
                "message": {
                    "message_id": 11,
                    "media_group_id": "album-1",
                    "caption": "album caption",
                    "chat": {"id": 1},
                    "photo": [{"file_id": "p1", "file_size": 10}],
                },
            },
            {
                "update_id": 102,
                "message": {
                    "message_id": 12,
                    "media_group_id": "album-1",
                    "chat": {"id": 1},
                    "photo": [{"file_id": "p2", "file_size": 11}],
                },
            },
            {
                "update_id": 103,
                "message": {
                    "message_id": 13,
                    "chat": {"id": 1},
                    "text": "plain",
                },
            },
        ]

        collapsed = bridge_handlers.collapse_media_group_updates(updates)

        self.assertEqual(len(collapsed), 2)
        album_message = collapsed[0]["message"]
        self.assertEqual(album_message["caption"], "album caption")
        self.assertEqual(len(album_message["media_group_messages"]), 2)
        self.assertEqual(collapsed[1]["message"]["text"], "plain")

    def test_buffer_pending_media_group_updates_flushes_split_album_across_polls(self):
        state = bridge.State()
        first_batch = [
            {
                "update_id": 101,
                "message": {
                    "message_id": 11,
                    "media_group_id": "album-1",
                    "caption": "album caption",
                    "chat": {"id": 1},
                    "photo": [{"file_id": "p1", "file_size": 10}],
                },
            },
            {
                "update_id": 102,
                "message": {
                    "message_id": 12,
                    "chat": {"id": 1},
                    "text": "plain",
                },
            },
        ]

        immediate_updates = bridge.buffer_pending_media_group_updates(
            state,
            first_batch,
            now=100.0,
        )
        self.assertEqual(len(immediate_updates), 1)
        self.assertEqual(immediate_updates[0]["message"]["text"], "plain")
        self.assertEqual(len(state.pending_media_groups), 1)
        self.assertEqual(bridge.flush_ready_media_group_updates(state, now=101.0), [])

        second_batch = [
            {
                "update_id": 103,
                "message": {
                    "message_id": 13,
                    "media_group_id": "album-1",
                    "chat": {"id": 1},
                    "photo": [{"file_id": "p2", "file_size": 11}],
                },
            }
        ]
        immediate_updates = bridge.buffer_pending_media_group_updates(
            state,
            second_batch,
            now=101.0,
        )
        self.assertEqual(immediate_updates, [])

        flushed_updates = bridge.flush_ready_media_group_updates(state, now=103.1)
        self.assertEqual(len(flushed_updates), 1)
        self.assertEqual(len(state.pending_media_groups), 0)
        album_message = flushed_updates[0]["message"]
        self.assertEqual(album_message["caption"], "album caption")
        self.assertEqual(len(album_message["media_group_messages"]), 2)

    def test_execute_prompt_with_retry_handles_executor_cancelled(self):
        class CancelingEngine:
            engine_name = "canceling"

            def run(
                self,
                config,
                prompt,
                thread_id,
                image_path=None,
                progress_callback=None,
                cancel_event=None,
            ):
                raise bridge_handlers.ExecutorCancelledError("cancel")

        class FakeProgress:
            def __init__(self):
                self.last_failure = ""

            def handle_executor_event(self, _event):
                return None

            def set_phase(self, _phase):
                return None

            def mark_failure(self, detail):
                self.last_failure = detail

        state = bridge.State()
        state_repo = bridge.StateRepository(state)
        client = FakeTelegramClient()
        config = make_config()
        progress = FakeProgress()

        result = bridge_handlers.execute_prompt_with_retry(
            state_repo=state_repo,
            config=config,
            client=client,
            engine=CancelingEngine(),
            chat_id=1,
            message_id=50,
            prompt_text="hello",
            previous_thread_id=None,
            image_path=None,
            progress=progress,
            cancel_event=threading.Event(),
            session_continuity_enabled=True,
        )

        self.assertIsNone(result)
        self.assertEqual(progress.last_failure, "Execution canceled.")
        self.assertTrue(client.messages)
        self.assertEqual(client.messages[-1][1], "Request canceled.")

