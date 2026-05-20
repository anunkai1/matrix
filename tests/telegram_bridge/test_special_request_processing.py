import subprocess
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from tests.telegram_bridge.helpers import FakeTelegramClient, make_config

import telegram_bridge.handlers as bridge_handlers
import telegram_bridge.main as bridge
import telegram_bridge.special_request_processing as special_request_processing


class TestSpecialRequestProcessing(unittest.TestCase):
    def test_process_youtube_request_sends_canceled_response_when_pre_canceled(self):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()
        cancel_event = threading.Event()
        cancel_event.set()
        request = bridge_handlers.build_youtube_request(
            state=state,
            config=config,
            client=client,
            engine=None,
            scope_key="tg:1",
            chat_id=1,
            message_thread_id=77,
            message_id=401,
            request_text="summarize this",
            youtube_url="https://www.youtube.com/watch?v=abc",
            cancel_event=cancel_event,
        )
        progress = mock.Mock()

        runtime = special_request_processing.build_youtube_processing_runtime(
            build_progress_reporter_fn=lambda *_args, **_kwargs: progress,
            build_engine_progress_context_label_fn=lambda *_args, **_kwargs: "Codex",
            send_canceled_response_fn=mock.Mock(),
            run_youtube_analyzer_fn=mock.Mock(),
            build_youtube_transcript_output_fn=mock.Mock(),
            deliver_output_and_emit_success_fn=mock.Mock(),
            build_youtube_unavailable_message_fn=mock.Mock(),
            execute_prompt_with_retry_fn=mock.Mock(),
            build_youtube_summary_prompt_fn=mock.Mock(),
            finalize_prompt_success_fn=mock.Mock(),
            finalize_request_progress_fn=mock.Mock(),
        )

        special_request_processing.process_youtube_request(request, runtime=runtime)

        progress.start.assert_called_once_with()
        progress.mark_failure.assert_called_once_with("Execution canceled.")
        runtime.send_canceled_response_fn.assert_called_once_with(client, 1, 401, 77)
        runtime.run_youtube_analyzer_fn.assert_not_called()
        runtime.finalize_request_progress_fn.assert_called_once()

    def test_process_youtube_worker_request_handles_timeout(self):
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
            message_thread_id=78,
            message_id=402,
            request_text="summarize this",
            youtube_url="https://www.youtube.com/watch?v=abc",
        )
        emit_event = mock.Mock()
        send_timeout_response = mock.Mock()

        def raise_timeout(_request):
            raise subprocess.TimeoutExpired(cmd=["yt"], timeout=30)

        special_request_processing.process_youtube_worker_request(
            request,
            process_youtube_request_fn=raise_timeout,
            emit_event_fn=emit_event,
            send_timeout_response_fn=send_timeout_response,
            emit_worker_exception_and_reply_fn=mock.Mock(),
        )

        emit_event.assert_called_once_with(
            "bridge.request_timeout",
            level=mock.ANY,
            fields={"chat_id": 1, "message_id": 402, "phase": "youtube_analysis"},
        )
        send_timeout_response.assert_called_once_with(client, config, 1, 402, 78)

    def test_process_youtube_worker_request_handles_generic_error(self):
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
            message_thread_id=79,
            message_id=403,
            request_text="summarize this",
            youtube_url="https://www.youtube.com/watch?v=abc",
        )
        emit_worker_exception_and_reply = mock.Mock()

        special_request_processing.process_youtube_worker_request(
            request,
            process_youtube_request_fn=mock.Mock(side_effect=RuntimeError("boom")),
            emit_event_fn=mock.Mock(),
            send_timeout_response_fn=mock.Mock(),
            emit_worker_exception_and_reply_fn=emit_worker_exception_and_reply,
        )

        emit_worker_exception_and_reply.assert_called_once_with(
            log_message="Unexpected YouTube worker error for chat_id=%s",
            failure_log_message="Failed to send YouTube worker error response for chat_id=%s",
            event_fields={"chat_id": 1, "message_id": 403, "phase": "youtube_analysis"},
            client=client,
            config=config,
            chat_id=1,
            message_id=403,
            message_thread_id=79,
        )


if __name__ == "__main__":
    unittest.main()
