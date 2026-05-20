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
import telegram_bridge.request_worker_requests as request_worker_requests
from telegram_bridge.state_store import State


class TestRequestWorkerRequests(unittest.TestCase):
    def test_build_youtube_worker_request_derives_scope_when_missing(self):
        request = request_worker_requests.build_youtube_worker_request(
            state=State(),
            config=make_config(),
            client=FakeTelegramClient(),
            engine=None,
            scope_key=None,
            chat_id=1,
            message_thread_id=77,
            message_id=88,
            request_text="watch this",
            youtube_url="https://youtube.example/watch?v=1",
            actor_user_id=9,
            cancel_event=None,
        )

        self.assertEqual(request.scope_key, "tg:1:topic:77")
        self.assertEqual(request.message_thread_id, 77)
        self.assertEqual(request.youtube_url, "https://youtube.example/watch?v=1")

    def test_start_message_worker_uses_background_worker_helper(self):
        request = object()

        with mock.patch.object(request_worker_requests, "start_background_worker") as start_background_worker:
            request_worker_requests.start_message_worker(request)

        start_background_worker.assert_called_once_with(
            request_worker_requests._process_message_worker_request,
            request,
        )

    def test_start_youtube_worker_uses_background_worker_helper(self):
        request = object()

        with mock.patch.object(request_worker_requests, "start_background_worker") as start_background_worker:
            request_worker_requests.start_youtube_worker(request)

        start_background_worker.assert_called_once_with(
            request_worker_requests._process_youtube_worker_request,
            request,
        )

    def test_build_prompt_worker_request_preserves_delivery_metadata(self):
        delivery_metadata = TelegramDeliveryMetadata(
            chat_id=1,
            scope_key="tg:1",
            message_thread_id=77,
            current_message_id=88,
            reply_to_message_id=66,
        )

        request = request_worker_requests.build_prompt_worker_request(
            state=State(),
            config=make_config(),
            client=FakeTelegramClient(),
            engine=None,
            scope_key="tg:1",
            chat_id=1,
            message_thread_id=77,
            message_id=88,
            prompt="hello",
            raw_prompt="hello",
            photo_file_id=None,
            voice_file_id=None,
            document=None,
            cancel_event=None,
            stateless=False,
            sender_name="User",
            photo_file_ids=None,
            actor_user_id=5,
            enforce_voice_prefix_from_transcript=False,
            prompt_diagnostics=None,
            delivery_metadata=delivery_metadata,
        )

        self.assertIs(request.delivery_metadata, delivery_metadata)


if __name__ == "__main__":
    unittest.main()
