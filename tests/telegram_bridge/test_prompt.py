"""Tests for Prompt — auto-split from test_bridge_core.py."""

import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
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
import telegram_bridge.codex_app_server as bridge_codex_app_server
import telegram_bridge.prompt_execution as bridge_prompt_execution
import telegram_bridge.prompt_runtime as bridge_prompt_runtime
import telegram_bridge.request_processing as bridge_request_processing
import telegram_bridge.session_manager as bridge_session_manager
import telegram_bridge.signal_channel as bridge_signal_channel
import telegram_bridge.special_request_processing as bridge_special_request_processing
import telegram_bridge.structured_logging as bridge_structured_logging
import telegram_bridge.transport as bridge_transport
import telegram_bridge.voice_alias_commands as bridge_voice_alias_commands
import telegram_bridge.whatsapp_channel as bridge_whatsapp_channel
from telegram_bridge.handler_models import TelegramDeliveryMetadata


class TestPrompt(unittest.TestCase):
    def test_emit_request_processing_started_includes_prompt_diagnostics(self):
        emit_event = mock.Mock()

        bridge_prompt_execution.emit_request_processing_started(
            chat_id=1,
            message_id=99,
            prompt="hello",
            photo_file_ids=[],
            photo_file_id=None,
            voice_file_id=None,
            document=None,
            previous_thread_id=None,
            prompt_diagnostics={
                "telegram_context_length": 648,
                "reply_context_length": 0,
                "sender_prompt_length": 32,
                "raw_prompt_length": 5,
                "user_message_label_length": 22,
                "wrapper_overhead": 28,
                "original_length": 711,
                "final_length": 711,
                "trimmed_user_chars": 0,
                "dropped_sections": [],
                "trimmed": False,
            },
            emit_event_fn=emit_event,
        )

        fields = emit_event.call_args.kwargs["fields"]
        self.assertEqual(fields["prompt_chars"], 5)
        self.assertEqual(fields["telegram_context_length"], 648)
        self.assertEqual(fields["wrapper_overhead"], 28)
        self.assertEqual(fields["final_length"], 711)
        self.assertEqual(fields["dropped_sections"], [])
        self.assertFalse(fields["prompt_trimmed"])

    def test_codex_app_server_enabled_accepts_grouped_engine_config(self):
        config = SimpleNamespace(
            engines=SimpleNamespace(
                codex_app_server_enabled=True,
                codex_model="gpt-5.5",
                codex_reasoning_effort="high",
            )
        )

        self.assertTrue(bridge_codex_app_server._enabled(config))
        self.assertEqual(bridge_codex_app_server._model_value(config), "gpt-5.5")
        self.assertEqual(bridge_codex_app_server._reasoning_effort_value(config), "high")

    def test_codex_app_server_try_steer_waits_briefly_for_active_turn_id(self):
        session = bridge_codex_app_server.CodexAppServerSession(
            scope_key="tg:1",
            config=make_config(),
        )
        pending_turn = bridge_codex_app_server._PendingTurn(original_prompt="original request")
        session._pending_turn = pending_turn
        session._thread_id = "thread-1"

        def populate_turn_id(_seconds):
            pending_turn.active_turn_id = "turn-1"

        with (
            mock.patch.object(bridge_codex_app_server, "FOLLOW_UP_STEER_DEBOUNCE_SECONDS", 0.0),
            mock.patch.object(bridge_codex_app_server, "FOLLOW_UP_STEER_IDLE_GRACE_SECONDS", 0.0),
            mock.patch.object(bridge_codex_app_server, "FOLLOW_UP_STEER_MAX_WAIT_SECONDS", 0.0),
            mock.patch.object(session, "_ensure_process"),
            mock.patch.object(session, "_call", return_value={}) as call_mock,
            mock.patch("telegram_bridge.codex_app_server.time.sleep", side_effect=populate_turn_id),
        ):
            steered = session.try_steer("follow up")

        self.assertTrue(steered)
        call_mock.assert_called_once_with(
            "turn/steer",
            {
                "threadId": "thread-1",
                "expectedTurnId": "turn-1",
                "input": [
                    {
                        "type": "text",
                        "text": "\n".join(
                            [
                                "Continue the same in-progress request.",
                                "Do not drop the original request.",
                                "Answer the original request and the follow-up below in one coherent reply.",
                                "",
                                "Original request:",
                                "original request",
                                "",
                                "Follow-up message:",
                                "follow up",
                            ]
                        ),
                    }
                ],
            },
        )

    def test_codex_app_server_try_steer_accumulates_follow_ups_in_order(self):
        session = bridge_codex_app_server.CodexAppServerSession(
            scope_key="tg:1",
            config=make_config(),
        )
        pending_turn = bridge_codex_app_server._PendingTurn(
            active_turn_id="turn-1",
            original_prompt="first question",
        )
        session._pending_turn = pending_turn
        session._thread_id = "thread-1"

        with (
            mock.patch.object(bridge_codex_app_server, "FOLLOW_UP_STEER_DEBOUNCE_SECONDS", 0.0),
            mock.patch.object(bridge_codex_app_server, "FOLLOW_UP_STEER_IDLE_GRACE_SECONDS", 0.0),
            mock.patch.object(bridge_codex_app_server, "FOLLOW_UP_STEER_MAX_WAIT_SECONDS", 0.0),
            mock.patch.object(session, "_ensure_process"),
            mock.patch.object(session, "_call", return_value={}) as call_mock,
        ):
            first_steer = session.try_steer("or not?")
            second_steer = session.try_steer("say cow")

        self.assertTrue(first_steer)
        self.assertTrue(second_steer)
        self.assertEqual(call_mock.call_count, 2)
        first_prompt = call_mock.call_args_list[0].args[1]["input"][0]["text"]
        self.assertIn("Original request:", first_prompt)
        self.assertIn("first question", first_prompt)
        self.assertIn("Follow-up message:", first_prompt)
        self.assertIn("or not?", first_prompt)
        second_prompt = call_mock.call_args_list[1].args[1]["input"][0]["text"]
        self.assertIn("Continue the same in-progress request.", second_prompt)
        self.assertIn("Do not drop the original request or any earlier follow-up messages.", second_prompt)
        self.assertIn("Answer every unresolved item below in one coherent reply.", second_prompt)
        self.assertIn("Original request:", second_prompt)
        self.assertIn("first question", second_prompt)
        self.assertIn("1. or not?", second_prompt)
        self.assertIn("2. say cow", second_prompt)

    def test_codex_app_server_try_steer_coalesces_nearby_follow_ups_into_one_send(self):
        session = bridge_codex_app_server.CodexAppServerSession(
            scope_key="tg:1",
            config=make_config(),
        )
        session._pending_turn = bridge_codex_app_server._PendingTurn(
            active_turn_id="turn-1",
            original_prompt="first question",
        )
        session._thread_id = "thread-1"
        recorded_calls = []

        def run_first_follow_up():
            self.assertTrue(session.try_steer("or not?"))

        with (
            mock.patch.object(bridge_codex_app_server, "FOLLOW_UP_STEER_DEBOUNCE_SECONDS", 0.05),
            mock.patch.object(bridge_codex_app_server, "FOLLOW_UP_STEER_IDLE_GRACE_SECONDS", 0.0),
            mock.patch.object(bridge_codex_app_server, "FOLLOW_UP_STEER_MAX_WAIT_SECONDS", 0.2),
            mock.patch.object(session, "_ensure_process"),
            mock.patch.object(
                session,
                "_call",
                side_effect=lambda method, params: recorded_calls.append((method, params)) or {},
            ),
        ):
            worker = threading.Thread(target=run_first_follow_up)
            worker.start()
            time.sleep(0.01)
            self.assertTrue(session.try_steer("say cow"))
            worker.join(timeout=1.0)

        self.assertEqual(len(recorded_calls), 1)
        only_prompt = recorded_calls[0][1]["input"][0]["text"]
        self.assertIn("Original request:", only_prompt)
        self.assertIn("first question", only_prompt)
        self.assertIn("1. or not?", only_prompt)
        self.assertIn("2. say cow", only_prompt)

    def test_codex_engine_adapter_does_not_fall_back_to_legacy_executor_when_live_path_fails(self):
        engine = bridge_engine_adapter.CodexEngineAdapter()
        config = make_config(codex_app_server_enabled=True)

        with (
            mock.patch(
                "telegram_bridge.engines.codex.run_live_codex_turn",
                side_effect=RuntimeError("app-server down"),
            ),
            mock.patch("telegram_bridge.engines.codex.run_executor") as run_executor,
        ):
            with self.assertRaisesRegex(RuntimeError, "app-server down"):
                engine.run(
                    config=config,
                    prompt="hello",
                    thread_id=None,
                    session_key="tg:1",
                )

        run_executor.assert_not_called()

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
            mock.patch.object(
                bridge_request_processing.request_prompt_processing.response_delivery,
                "send_executor_output",
                return_value="ok",
            ) as send_mock,
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

    def test_process_prompt_request_uses_current_message_as_reply_anchor(self):
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
            message_thread_id=77,
            message_id=55,
            prompt="hello",
            raw_prompt="hello",
            photo_file_id=None,
            voice_file_id=None,
            document=None,
            delivery_metadata=TelegramDeliveryMetadata(
                chat_id=1,
                scope_key="tg:1",
                message_thread_id=77,
                current_message_id=55,
                reply_to_message_id=44,
            ),
        )
        finalize_calls = []

        runtime = bridge_prompt_execution.build_prompt_execution_runtime(
            progress_reporter_cls=bridge_handlers.ProgressReporter,
            state_repository_cls=bridge_handlers.StateRepository,
            codex_engine_adapter_factory=bridge_handlers.CodexEngineAdapter,
            assistant_label_fn=bridge_handlers.assistant_label,
            build_engine_runtime_config_fn=bridge_handlers.build_engine_runtime_config,
            build_engine_progress_context_label_fn=bridge_handlers.build_engine_progress_context_label,
            refresh_runtime_auth_fingerprint_fn=lambda _state: {"applied": False, "counts": {}},
            prepare_prompt_input_request_fn=lambda _request, _progress: bridge_handlers.PreparedPromptInput(
                prompt_text="hello"
            ),
            execute_prompt_with_retry_fn=lambda **_kwargs: bridge_handlers.subprocess.CompletedProcess(
                args=["/bin/echo"],
                returncode=0,
                stdout="hello",
                stderr="",
            ),
            finalize_prompt_success_fn=lambda **kwargs: finalize_calls.append(kwargs) or (None, "hello"),
            finalize_request_progress_fn=lambda **_kwargs: None,
            emit_event_fn=lambda *args, **kwargs: None,
        )

        bridge_prompt_execution.process_prompt_request(request, runtime=runtime)

        self.assertEqual(finalize_calls[0]["reply_to_message_id"], 55)

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
        self.assertIn("use this chat/topic only", prompt)
        self.assertIn("Never guess another chat ID", prompt)

    def test_build_telegram_context_prompt_can_omit_delivery_guardrails(self):
        prompt = bridge_handlers.build_telegram_context_prompt(
            chat_id=1,
            message_thread_id=None,
            scope_key="tg:1",
            message_id=570,
            message={},
            include_delivery_guardrails=False,
        )

        self.assertIn("Current Telegram Context:", prompt)
        self.assertIn("- Chat ID: 1", prompt)
        self.assertIn("- Current Message ID: 570", prompt)
        self.assertNotIn("use this chat/topic only", prompt)
        self.assertNotIn("Never guess another chat ID", prompt)

    def test_telegram_text_prompt_includes_delivery_target_guardrail(self):
        self.assertTrue(
            bridge_handlers.should_include_telegram_context_prompt(
                "2",
                "",
                "telegram",
                injection_policy="continuation_skip",
                has_existing_thread=False,
            )
        )
        self.assertFalse(
            bridge_handlers.should_include_telegram_context_prompt(
                "2",
                "",
                "whatsapp",
                injection_policy="continuation_skip",
                has_existing_thread=False,
            )
        )

    def test_delivery_guardrails_only_apply_to_delivery_sensitive_prompts(self):
        self.assertFalse(
            bridge_handlers.should_include_delivery_guardrails(
                "hello",
                "",
                "telegram",
            )
        )
        self.assertTrue(
            bridge_handlers.should_include_delivery_guardrails(
                "reply here with the file",
                "",
                "telegram",
            )
        )
        self.assertTrue(
            bridge_handlers.should_include_delivery_guardrails(
                "570",
                "",
                "telegram",
            )
        )

    def test_should_include_telegram_context_prompt_skips_continuations_under_continuation_skip(self):
        self.assertFalse(
            bridge_handlers.should_include_telegram_context_prompt(
                "hello",
                "",
                "telegram",
                injection_policy="continuation_skip",
                has_existing_thread=True,
            )
        )
        self.assertTrue(
            bridge_handlers.should_include_telegram_context_prompt(
                "hello",
                "",
                "telegram",
                injection_policy="continuation_skip",
                has_existing_thread=False,
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
        runtime = kwargs["runtime"]
        self.assertIsInstance(runtime, bridge_prompt_execution.PromptExecutionRuntime)
        self.assertIs(runtime.progress_reporter_cls, bridge_handlers.ProgressReporter)
        self.assertIs(
            runtime.prepare_prompt_input_request_fn,
            bridge_handlers._prepare_prompt_input_request,
        )
        self.assertIs(runtime.execute_prompt_with_retry_fn, bridge_handlers.execute_prompt_with_retry)
        self.assertIs(runtime.finalize_prompt_success_fn, bridge_handlers.finalize_prompt_success)
        self.assertIs(runtime.finalize_request_progress_fn, bridge_handlers.finalize_request_progress)

    def test_process_prompt_request_web_context_failure_falls_back_to_plain_prompt(self):
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
            prompt="latest news",
            photo_file_id=None,
            voice_file_id=None,
            document=None,
        )
        engine_prompts = []
        events = []

        runtime = bridge_prompt_execution.build_prompt_execution_runtime(
            progress_reporter_cls=bridge_handlers.ProgressReporter,
            state_repository_cls=bridge_handlers.StateRepository,
            codex_engine_adapter_factory=bridge_handlers.CodexEngineAdapter,
            assistant_label_fn=bridge_handlers.assistant_label,
            build_engine_runtime_config_fn=bridge_handlers.build_engine_runtime_config,
            build_engine_progress_context_label_fn=bridge_handlers.build_engine_progress_context_label,
            refresh_runtime_auth_fingerprint_fn=lambda _state: {"applied": False, "counts": {}},
            prepare_prompt_input_request_fn=lambda _request, _progress: bridge_handlers.PreparedPromptInput(
                prompt_text="latest news"
            ),
            execute_prompt_with_retry_fn=lambda **kwargs: engine_prompts.append(kwargs["prompt_text"])
            or bridge_handlers.subprocess.CompletedProcess(
                args=["/bin/echo"],
                returncode=0,
                stdout="plain pi reply",
                stderr="",
            ),
            finalize_prompt_success_fn=lambda **kwargs: (None, kwargs["result"].stdout),
            finalize_request_progress_fn=lambda **_kwargs: None,
            emit_event_fn=lambda event, **kwargs: events.append((event, kwargs)),
        )

        with mock.patch.object(
            bridge_prompt_execution.web_context,
            "maybe_build_web_context",
            side_effect=RuntimeError("search exploded"),
        ):
            bridge_prompt_execution.process_prompt_request(request, runtime=runtime)

        self.assertEqual(engine_prompts, ["latest news"])
        self.assertTrue(
            any(
                event == "bridge.web_context_failed_open"
                and payload.get("fields", {}).get("error") == "search exploded"
                for event, payload in events
            )
        )

    @mock.patch.object(bridge_handlers, "finalize_chat_work")
    @mock.patch.object(bridge_request_processing, "run_dishframed_cli", return_value=("/tmp/menu_preview.png", "Rendered PNG preview"))
    @mock.patch.object(bridge_request_processing, "prepare_prompt_input")
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

    @mock.patch.object(bridge_request_processing.request_prompt_processing.response_delivery, "send_executor_output", return_value="unavailable")
    @mock.patch.object(bridge_request_processing, "run_youtube_analyzer")
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
        runtime = kwargs["runtime"]
        self.assertIsInstance(
            runtime,
            bridge_special_request_processing.YoutubeProcessingRuntime,
        )
        self.assertIs(runtime.build_progress_reporter_fn, bridge_handlers.build_progress_reporter)
        self.assertIs(runtime.execute_prompt_with_retry_fn, bridge_prompt_runtime.execute_prompt_with_retry)
        self.assertIs(runtime.finalize_prompt_success_fn, bridge_prompt_runtime.finalize_prompt_success)
        self.assertIs(runtime.finalize_request_progress_fn, bridge_handlers.finalize_request_progress)

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
        runtime = kwargs["runtime"]
        self.assertIsInstance(
            runtime,
            bridge_special_request_processing.DishframedProcessingRuntime,
        )
        self.assertIs(runtime.build_progress_reporter_fn, bridge_handlers.build_progress_reporter)
        self.assertIs(runtime.prepare_prompt_input_fn, bridge_request_processing.prepare_prompt_input)
        self.assertIs(runtime.run_dishframed_cli_fn, bridge_request_processing.run_dishframed_cli)
        self.assertIs(runtime.finalize_request_progress_fn, bridge_handlers.finalize_request_progress)

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

    def test_execute_prompt_with_retry_does_not_rerun_new_session_nonzero_exit(self):
        class NonzeroEngine:
            engine_name = "nonzero"

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
                del config, prompt, image_path, progress_callback, cancel_event
                self.calls += 1
                self.last_thread_id = thread_id
                return subprocess.CompletedProcess(
                    args=["codex", "exec"],
                    returncode=1,
                    stdout="",
                    stderr="executor failed",
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
        engine = NonzeroEngine()

        result = bridge_handlers.execute_prompt_with_retry(
            state_repo=state_repo,
            config=config,
            client=client,
            engine=engine,
            chat_id=1,
            message_id=53,
            prompt_text="hello",
            previous_thread_id=None,
            image_path=None,
            progress=progress,
            cancel_event=threading.Event(),
            session_continuity_enabled=True,
        )

        self.assertIsNone(result)
        self.assertEqual(engine.calls, 1)
        self.assertIsNone(engine.last_thread_id)
        self.assertEqual(progress.last_failure, "Execution failed.")
        self.assertTrue(client.messages)
        self.assertEqual(client.messages[-1][1], config.generic_error_message)

    def test_execute_prompt_with_retry_passes_raw_prompt_to_extended_engine_signature(self):
        class ExtendedEngine:
            engine_name = "codex"

            def __init__(self):
                self.original_prompts = []

            def run(
                self,
                config,
                prompt,
                thread_id,
                session_key=None,
                channel_name=None,
                actor_chat_id=None,
                actor_user_id=None,
                image_path=None,
                image_paths=None,
                original_prompt=None,
                progress_callback=None,
                cancel_event=None,
            ):
                del config, prompt, thread_id, session_key, channel_name, actor_chat_id
                del actor_user_id, image_path, image_paths, progress_callback, cancel_event
                self.original_prompts.append(original_prompt)
                return subprocess.CompletedProcess(
                    args=["codex", "exec"],
                    returncode=0,
                    stdout="OUTPUT_BEGIN\nok",
                    stderr="",
                )

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
        progress = FakeProgress()
        engine = ExtendedEngine()

        result = bridge_handlers.execute_prompt_with_retry(
            state_repo=state_repo,
            config=config,
            client=client,
            engine=engine,
            chat_id=1,
            message_id=55,
            prompt_text="wrapped prompt",
            raw_prompt_text="raw follow up",
            previous_thread_id=None,
            image_path=None,
            progress=progress,
            cancel_event=threading.Event(),
            session_continuity_enabled=True,
        )

        self.assertIsNotNone(result)
        self.assertEqual(engine.original_prompts, ["raw follow up"])

    def test_execute_prompt_with_retry_does_not_rerun_resume_nonzero_exit_without_invalid_thread_marker(self):
        class NonzeroResumeEngine:
            engine_name = "nonzero-resume"

            def __init__(self):
                self.calls = 0
                self.thread_ids = []

            def run(
                self,
                config,
                prompt,
                thread_id,
                image_path=None,
                progress_callback=None,
                cancel_event=None,
            ):
                del config, prompt, image_path, progress_callback, cancel_event
                self.calls += 1
                self.thread_ids.append(thread_id)
                return subprocess.CompletedProcess(
                    args=["codex", "exec"],
                    returncode=1,
                    stdout="",
                    stderr="executor failed for unrelated reason",
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
        engine = NonzeroResumeEngine()

        result = bridge_handlers.execute_prompt_with_retry(
            state_repo=state_repo,
            config=config,
            client=client,
            engine=engine,
            chat_id=1,
            message_id=54,
            prompt_text="hello",
            previous_thread_id="thread-123",
            image_path=None,
            progress=progress,
            cancel_event=threading.Event(),
            session_continuity_enabled=True,
        )

        self.assertIsNone(result)
        self.assertEqual(engine.calls, 1)
        self.assertEqual(engine.thread_ids, ["thread-123"])
        self.assertEqual(progress.last_failure, "Execution failed.")
        self.assertTrue(client.messages)
        self.assertEqual(client.messages[-1][1], config.generic_error_message)

    def test_execute_prompt_with_retry_retries_resume_when_thread_is_invalid(self):
        class InvalidResumeEngine:
            engine_name = "invalid-resume"

            def __init__(self):
                self.calls = 0
                self.thread_ids = []

            def run(
                self,
                config,
                prompt,
                thread_id,
                image_path=None,
                progress_callback=None,
                cancel_event=None,
            ):
                del config, prompt, image_path, progress_callback, cancel_event
                self.calls += 1
                self.thread_ids.append(thread_id)
                if self.calls == 1:
                    return subprocess.CompletedProcess(
                        args=["codex", "exec", "resume"],
                        returncode=1,
                        stdout="",
                        stderr="Thread not found for resume",
                    )
                return subprocess.CompletedProcess(
                    args=["codex", "exec"],
                    returncode=0,
                    stdout='{"type":"item.completed","item":{"type":"agent_message","text":"ok"}}\n',
                    stderr="",
                )

        class FakeProgress:
            def __init__(self):
                self.phases = []

            def handle_executor_event(self, _event):
                return None

            def set_phase(self, phase):
                self.phases.append(phase)

            def mark_failure(self, _detail):
                return None

        state = bridge.State(chat_threads={"tg:1": "thread-123"})
        state_repo = bridge.StateRepository(state)
        client = FakeTelegramClient()
        config = make_config(persistent_workers_enabled=True)
        progress = FakeProgress()
        engine = InvalidResumeEngine()

        result = bridge_handlers.execute_prompt_with_retry(
            state_repo=state_repo,
            config=config,
            client=client,
            engine=engine,
            chat_id=1,
            message_id=55,
            prompt_text="hello",
            previous_thread_id="thread-123",
            image_path=None,
            progress=progress,
            cancel_event=threading.Event(),
            session_continuity_enabled=True,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(engine.calls, 2)
        self.assertEqual(engine.thread_ids, ["thread-123", None])
        self.assertEqual(state.chat_threads, {})
        self.assertEqual(progress.phases, [bridge_handlers.resume_retry_phase(config)])

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

    def test_execute_prompt_with_retry_caches_legacy_engine_signature_detection(self):
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
        signature_target = bridge_prompt_runtime._engine_run_signature_target(engine.run)
        bridge_prompt_runtime._ENGINE_RUN_EXTENDED_KWARGS_SUPPORT_CACHE.clear()

        with mock.patch.object(
            bridge_prompt_runtime.inspect,
            "signature",
            wraps=bridge_prompt_runtime.inspect.signature,
        ) as signature_mock:
            first = bridge_handlers.execute_prompt_with_retry(
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
            second = bridge_handlers.execute_prompt_with_retry(
                state_repo=state_repo,
                config=config,
                client=client,
                engine=engine,
                scope_key="tg:1",
                chat_id=1,
                message_thread_id=None,
                message_id=53,
                prompt_text="hello again",
                previous_thread_id=None,
                image_path=None,
                actor_user_id=123,
                progress=FakeProgress(),
                cancel_event=threading.Event(),
                session_continuity_enabled=True,
            )

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(first.returncode, 0)
        self.assertEqual(second.returncode, 0)
        self.assertEqual(engine.calls, 2)
        self.assertEqual(signature_mock.call_count, 0)
        self.assertIn(signature_target, bridge_prompt_runtime._ENGINE_RUN_EXTENDED_KWARGS_SUPPORT_CACHE)
