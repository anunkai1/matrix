import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from tests.telegram_bridge.helpers import FakeTelegramClient, make_config

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

    def test_start_dishframed_worker_uses_background_worker_helper(self):
        request = object()

        with mock.patch.object(request_worker_requests, "start_background_worker") as start_background_worker:
            request_worker_requests.start_dishframed_worker(request)

        start_background_worker.assert_called_once_with(
            request_worker_requests._process_dishframed_worker_request,
            request,
        )


if __name__ == "__main__":
    unittest.main()
