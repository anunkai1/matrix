"""Tests for Prompt — auto-split from test_bridge_core.py."""

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


class TestPrompt(unittest.TestCase):
    def test_finalize_prompt_success_trims_plain_output(self):
        config = make_config(max_output_chars=20)
        config.empty_output_message = "(No output from Architect)"
        state_repo = mock.Mock()
        progress = mock.Mock()
        client = FakeTelegramClient()
        raw_output = "x" * 120
        result = bridge_handlers.subprocess.CompletedProcess(
            args=["/bin/echo"],
            returncode=0,
            stdout=raw_output,
            stderr="",
        )

        with (
            mock.patch.object(bridge_handlers, "parse_executor_output", return_value=(None, raw_output)),
            mock.patch.object(bridge_handlers, "send_executor_output", return_value="ok") as send_mock,
        ):
            bridge_handlers.finalize_prompt_success(
                state_repo=state_repo,
                config=config,
                client=client,
                chat_id=1,
                message_id=19,
                result=result,
                progress=progress,
            )

        sent_output = send_mock.call_args.kwargs["output"]
        self.assertLessEqual(len(sent_output), config.max_output_chars)
        self.assertIn("[output truncated]", sent_output)

    def test_build_telegram_context_prompt_includes_current_message_id(self):
        prompt = bridge_handlers.build_telegram_context_prompt(
            chat_id=-1003706836145,
            message_thread_id=498,
            scope_key="tg:-1003706836145:topic:498",
            message_id=570,
            message={},
        )

        self.assertIn("Current Telegram Context:", prompt)
        self.assertIn("- Chat ID: -1003706836145", prompt)
        self.assertIn("- Topic ID: 498", prompt)
        self.assertIn("- Current Message ID: 570", prompt)
        self.assertIn("- Scope Key: tg:-1003706836145:topic:498", prompt)
        self.assertIn("treat this current chat/topic as authoritative", prompt)
        self.assertIn("Never fall back to a different chat ID", prompt)

    def test_telegram_text_prompt_includes_delivery_target_guardrail(self):
        self.assertTrue(
            bridge_handlers.should_include_telegram_context_prompt(
                "2",
                "",
                "telegram",
            )
        )
        self.assertFalse(
            bridge_handlers.should_include_telegram_context_prompt(
                "2",
                "",
                "whatsapp",
            )
        )

    def test_process_prompt_request_delegates_to_prompt_execution_module(self):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()
        request = bridge_handlers.build_prompt_request(
            state=state,
            config=config,
            client=client,
            engine=None,
            scope_key="tg:1",
            chat_id=1,
            message_thread_id=None,
            message_id=55,
            prompt="hello",
            photo_file_id=None,
            voice_file_id=None,
            document=None,
        )

        with mock.patch.object(bridge_prompt_execution, "process_prompt_request") as process_prompt_request:
            bridge_handlers._process_prompt_request(request)

        process_prompt_request.assert_called_once()
        args, kwargs = process_prompt_request.call_args
        self.assertIs(args[0], request)
        self.assertIs(kwargs["progress_reporter_cls"], bridge_handlers.ProgressReporter)
        self.assertIs(kwargs["prepare_prompt_input_request_fn"], bridge_handlers._prepare_prompt_input_request)
        self.assertIs(kwargs["execute_prompt_with_retry_fn"], bridge_handlers.execute_prompt_with_retry)
        self.assertIs(kwargs["finalize_prompt_success_fn"], bridge_handlers.finalize_prompt_success)
        self.assertIs(kwargs["finalize_request_progress_fn"], bridge_handlers.finalize_request_progress)

    @mock.patch.object(bridge_handlers, "finalize_chat_work")
    @mock.patch.object(bridge_handlers, "run_dishframed_cli", return_value=("/tmp/menu_preview.png", "Rendered PNG preview"))
    @mock.patch.object(bridge_handlers, "prepare_prompt_input")
    def test_process_dishframed_request_sends_photo_when_png_output(
        self,
        prepare_prompt_input,
        run_dishframed_cli,
        finalize_chat_work,
    ):
        del finalize_chat_work
        prepare_prompt_input.return_value = SimpleNamespace(
            cleanup_paths=[],
            image_paths=["/tmp/incoming.jpg"],
        )
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()

        bridge_handlers.process_dishframed_request(
            state=state,
            config=config,
            client=client,
            scope_key="tg:1",
            chat_id=1,
            message_thread_id=None,
            message_id=99,
            photo_file_ids=["photo-file-id"],
            cancel_event=None,
        )

        self.assertEqual(client.photos[0][:3], (1, "/tmp/menu_preview.png", "Rendered PNG preview"))
        self.assertEqual(client.documents, [])
        run_dishframed_cli.assert_called_once()

    @mock.patch.object(bridge_handlers, "send_executor_output", return_value="unavailable")
    @mock.patch.object(bridge_handlers, "run_youtube_analyzer")
    def test_process_youtube_request_returns_unavailable_when_transcript_request_has_no_transcript(
        self,
        run_youtube_analyzer,
        send_executor_output,
    ):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()
        run_youtube_analyzer.return_value = {
            "ok": True,
            "request_mode": "transcript",
            "title": "Example Video",
            "channel": "Example Channel",
            "transcript_text": "",
            "transcript_source": "none",
            "transcript_language": "",
            "transcript_error": "captions missing",
        }

        bridge_handlers.process_youtube_request(
            state=state,
            config=config,
            client=client,
            engine=None,
            chat_id=1,
            message_id=301,
            request_text="full transcript https://www.youtube.com/watch?v=yD5DFL3xPmo",
            youtube_url="https://www.youtube.com/watch?v=yD5DFL3xPmo",
            cancel_event=None,
        )

        sent_output = send_executor_output.call_args.kwargs["output"]
        self.assertIn("could not obtain captions or a usable transcription", sent_output)
        self.assertIn("Example Video", sent_output)

    def test_process_youtube_request_delegates_to_special_request_processing_module(self):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()
        request = bridge_handlers.build_youtube_request(
            state=state,
            config=config,
            client=client,
            engine=None,
            scope_key="tg:1",
            chat_id=1,
            message_thread_id=None,
            message_id=401,
            request_text="summarize this",
            youtube_url="https://www.youtube.com/watch?v=abc",
        )

        with mock.patch.object(
            bridge_special_request_processing,
            "process_youtube_request",
        ) as process_youtube_request:
            bridge_handlers._process_youtube_request(request)

        process_youtube_request.assert_called_once()
        args, kwargs = process_youtube_request.call_args
        self.assertIs(args[0], request)
        self.assertIs(kwargs["build_progress_reporter_fn"], bridge_handlers.build_progress_reporter)
        self.assertIs(kwargs["execute_prompt_with_retry_fn"], bridge_handlers.execute_prompt_with_retry)
        self.assertIs(kwargs["finalize_prompt_success_fn"], bridge_handlers.finalize_prompt_success)
        self.assertIs(kwargs["finalize_request_progress_fn"], bridge_handlers.finalize_request_progress)

    def test_process_dishframed_request_delegates_to_special_request_processing_module(self):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()
        request = bridge_handlers.build_dishframed_request(
            state=state,
            config=config,
            client=client,
            scope_key="tg:1",
            chat_id=1,
            message_thread_id=None,
            message_id=402,
            photo_file_ids=["photo-1"],
        )

        with mock.patch.object(
            bridge_special_request_processing,
            "process_dishframed_request",
        ) as process_dishframed_request:
            bridge_handlers._process_dishframed_request(request)

        process_dishframed_request.assert_called_once()
        args, kwargs = process_dishframed_request.call_args
        self.assertIs(args[0], request)
        self.assertIs(kwargs["build_progress_reporter_fn"], bridge_handlers.build_progress_reporter)
        self.assertIs(kwargs["prepare_prompt_input_fn"], bridge_handlers.prepare_prompt_input)
        self.assertIs(kwargs["run_dishframed_cli_fn"], bridge_handlers.run_dishframed_cli)
        self.assertIs(kwargs["finalize_request_progress_fn"], bridge_handlers.finalize_request_progress)

    def test_build_youtube_summary_prompt_includes_basic_video_fields(self):
        prompt = bridge_handlers.build_youtube_summary_prompt(
            "https://www.youtube.com/watch?v=yD5DFL3xPmo",
            {
                "title": "Example Video",
                "channel": "Example Channel",
                "duration_seconds": 120,
                "transcript_source": "automatic_captions",
                "transcript_language": "en",
                "transcript_text": "hello world",
                "description": "example description",
                "chapters": [],
            },
        )

        self.assertIn("Video title: Example Video", prompt)
        self.assertIn("Channel: Example Channel", prompt)
        self.assertIn("Description:\nexample description", prompt)
        self.assertIn("Transcript source: automatic_captions", prompt)

    def test_execute_prompt_with_retry_surfaces_usage_limit_without_retry(self):
        class UsageLimitEngine:
            engine_name = "usage-limit"

            def __init__(self):
                self.calls = 0

            def run(
                self,
                config,
                prompt,
                thread_id,
                image_path=None,
                progress_callback=None,
                cancel_event=None,
            ):
                self.calls += 1
                return subprocess.CompletedProcess(
                    args=["codex", "exec"],
                    returncode=1,
                    stdout=(
                        "{\"type\":\"error\",\"message\":\"You've hit your usage limit. "
                        "Upgrade to Pro and try again at 2:00 PM.\"}\n"
                        "{\"type\":\"turn.failed\",\"error\":{\"message\":\"You've hit your usage "
                        "limit. Upgrade to Pro and try again at 2:00 PM.\"}}\n"
                    ),
                    stderr="",
                )

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
        config = make_config(persistent_workers_enabled=True)
        progress = FakeProgress()
        engine = UsageLimitEngine()

        result = bridge_handlers.execute_prompt_with_retry(
            state_repo=state_repo,
            config=config,
            client=client,
            engine=engine,
            chat_id=1,
            message_id=51,
            prompt_text="hello",
            previous_thread_id=None,
            image_path=None,
            progress=progress,
            cancel_event=threading.Event(),
            session_continuity_enabled=True,
        )

        self.assertIsNone(result)
        self.assertEqual(engine.calls, 1)
        self.assertEqual(progress.last_failure, "Execution failed.")
        self.assertTrue(client.messages)
        self.assertEqual(
            client.messages[-1][1],
            "The runtime has hit its usage limit. Try again after 2:00 PM.",
        )

    def test_execute_prompt_with_retry_falls_back_when_actor_identity_kwargs_unsupported(self):
        class LegacyEngine:
            engine_name = "legacy"

            def __init__(self):
                self.calls = 0

            def run(
                self,
                config,
                prompt,
                thread_id,
                image_path=None,
                progress_callback=None,
                cancel_event=None,
            ):
                del config, thread_id, image_path, progress_callback, cancel_event
                self.calls += 1
                stdout = json.dumps(
                    {
                        "type": "item.completed",
                        "item": {"type": "agent_message", "text": f"ok:{prompt}"},
                    }
                )
                return subprocess.CompletedProcess(args=["legacy"], returncode=0, stdout=stdout, stderr="")

        class FakeProgress:
            def handle_executor_event(self, _event):
                return None

            def set_phase(self, _phase):
                return None

            def mark_failure(self, _detail):
                return None

        state = bridge.State()
        state_repo = bridge.StateRepository(state)
        client = FakeTelegramClient()
        config = make_config()
        engine = LegacyEngine()

        result = bridge_handlers.execute_prompt_with_retry(
            state_repo=state_repo,
            config=config,
            client=client,
            engine=engine,
            scope_key="tg:1",
            chat_id=1,
            message_thread_id=None,
            message_id=52,
            prompt_text="hello",
            previous_thread_id=None,
            image_path=None,
            actor_user_id=123,
            progress=FakeProgress(),
            cancel_event=threading.Event(),
            session_continuity_enabled=True,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(engine.calls, 1)

