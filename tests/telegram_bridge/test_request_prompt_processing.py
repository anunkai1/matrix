import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from tests.telegram_bridge.helpers import FakeTelegramClient, make_config

import telegram_bridge.handlers as bridge_handlers
import telegram_bridge.main as bridge
import telegram_bridge.prompt_execution as bridge_prompt_execution
import telegram_bridge.request_prompt_processing as request_prompt_processing


class TestRequestPromptProcessing(unittest.TestCase):
    def test_deliver_output_and_emit_success_emits_success_event(self):
        client = FakeTelegramClient()

        with (
            mock.patch.object(
                bridge_handlers,
                "send_executor_output",
                return_value="delivered output",
            ) as send_executor_output,
            mock.patch.object(request_prompt_processing, "_emit_event") as emit_event,
        ):
            delivered = request_prompt_processing.deliver_output_and_emit_success(
                client=client,
                chat_id=1,
                message_id=55,
                output="raw output",
                message_thread_id=77,
                new_thread_id=True,
            )

        self.assertEqual(delivered, "delivered output")
        send_executor_output.assert_called_once_with(
            client=client,
            chat_id=1,
            message_id=55,
            output="raw output",
            message_thread_id=77,
        )
        emit_event.assert_called_once_with(
            "bridge.request_succeeded",
            fields={
                "chat_id": 1,
                "message_id": 55,
                "new_thread_id": True,
                "output_chars": len("delivered output"),
            },
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

        with mock.patch.object(
            request_prompt_processing.prompt_execution,
            "process_prompt_request",
        ) as process_prompt_request:
            request_prompt_processing._process_prompt_request(request)

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

    def test_process_message_worker_request_emits_worker_exception_reply(self):
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
            message_thread_id=99,
            message_id=56,
            prompt="hello",
            photo_file_id=None,
            voice_file_id=None,
            document=None,
        )

        with (
            mock.patch.object(
                request_prompt_processing,
                "_process_prompt_request",
                side_effect=RuntimeError("boom"),
            ),
            mock.patch.object(
                request_prompt_processing,
                "emit_worker_exception_and_reply",
            ) as emit_worker_exception_and_reply,
        ):
            request_prompt_processing._process_message_worker_request(request)

        emit_worker_exception_and_reply.assert_called_once_with(
            log_message="Unexpected message worker error for chat_id=%s",
            failure_log_message="Failed to send worker error response for chat_id=%s",
            event_fields={"chat_id": 1, "message_id": 56},
            client=client,
            config=config,
            chat_id=1,
            message_id=56,
            message_thread_id=99,
        )


if __name__ == "__main__":
    unittest.main()
