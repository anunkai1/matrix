import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from tests.telegram_bridge.helpers import FakeTelegramClient, make_config

from telegram_bridge.handler_models import TelegramDeliveryMetadata
import telegram_bridge.request_starts as request_starts
from telegram_bridge.state_store import State


class TestRequestStarts(unittest.TestCase):
    def test_process_prompt_builds_then_dispatches_prompt_request(self):
        built_request = object()

        with mock.patch.object(
            request_starts.request_worker_requests,
            "build_prompt_worker_request",
            return_value=built_request,
        ) as build_prompt_worker_request:
            with mock.patch.object(request_starts.request_worker_requests, "process_prompt") as process_prompt:
                request_starts.process_prompt(
                    state=State(),
                    config=make_config(),
                    client=FakeTelegramClient(),
                    engine=None,
                    scope_key="tg:1",
                    chat_id=1,
                    message_thread_id=77,
                    message_id=88,
                    prompt="hello",
                    photo_file_id=None,
                    voice_file_id=None,
                    document=None,
                )

        build_prompt_worker_request.assert_called_once()
        process_prompt.assert_called_once_with(built_request)

    def test_start_message_worker_builds_then_starts_prompt_request(self):
        built_request = object()

        with mock.patch.object(
            request_starts.request_worker_requests,
            "build_prompt_worker_request",
            return_value=built_request,
        ) as build_prompt_worker_request:
            with mock.patch.object(request_starts.request_worker_requests, "start_message_worker") as start_message_worker:
                request_starts.start_message_worker(
                    state=State(),
                    config=make_config(),
                    client=FakeTelegramClient(),
                    engine=None,
                    scope_key="tg:1",
                    chat_id=1,
                    message_thread_id=77,
                    message_id=88,
                    prompt="hello",
                    photo_file_id=None,
                    voice_file_id=None,
                    document=None,
                )

        build_prompt_worker_request.assert_called_once()
        start_message_worker.assert_called_once_with(built_request)

    def test_start_youtube_worker_builds_then_starts_request(self):
        built_request = object()

        with mock.patch.object(
            request_starts.request_worker_requests,
            "build_youtube_worker_request",
            return_value=built_request,
        ) as build_youtube_worker_request:
            with mock.patch.object(request_starts.request_worker_requests, "start_youtube_worker") as start_youtube_worker:
                request_starts.start_youtube_worker(
                    state=State(),
                    config=make_config(),
                    client=FakeTelegramClient(),
                    engine=None,
                    scope_key="tg:1",
                    chat_id=1,
                    message_thread_id=77,
                    message_id=88,
                    request_text="watch this",
                    youtube_url="https://youtube.example/watch?v=1",
                )

        build_youtube_worker_request.assert_called_once()
        start_youtube_worker.assert_called_once_with(built_request)

    def test_start_message_worker_passes_delivery_metadata_through(self):
        delivery_metadata = TelegramDeliveryMetadata(
            chat_id=1,
            scope_key="tg:1",
            message_thread_id=77,
            current_message_id=88,
            reply_to_message_id=66,
        )

        with mock.patch.object(
            request_starts.request_worker_requests,
            "build_prompt_worker_request",
            return_value=object(),
        ) as build_prompt_worker_request:
            with mock.patch.object(request_starts.request_worker_requests, "start_message_worker"):
                request_starts.start_message_worker(
                    state=State(),
                    config=make_config(),
                    client=FakeTelegramClient(),
                    engine=None,
                    scope_key="tg:1",
                    chat_id=1,
                    message_thread_id=77,
                    message_id=88,
                    prompt="hello",
                    photo_file_id=None,
                    voice_file_id=None,
                    document=None,
                    delivery_metadata=delivery_metadata,
                )

        self.assertIs(build_prompt_worker_request.call_args.args[-1], delivery_metadata)


if __name__ == "__main__":
    unittest.main()
