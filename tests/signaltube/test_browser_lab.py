from __future__ import annotations

import unittest
from unittest import mock

from src.signaltube.browser_lab import (
    BrowserBrainClient,
    SignalTubeBrowserLabError,
    build_search_url,
    extract_video_candidates,
    extract_video_id,
)


class SignalTubeBrowserLabTests(unittest.TestCase):
    def test_build_search_url_encodes_topic(self) -> None:
        self.assertEqual(
            build_search_url("latest space videos"),
            "https://www.youtube.com/results?search_query=latest+space+videos",
        )

    def test_extract_video_id_accepts_watch_urls_and_rejects_shorts(self) -> None:
        self.assertEqual(extract_video_id("https://www.youtube.com/watch?v=abcDEF_1234&t=30"), "abcDEF_1234")
        self.assertEqual(extract_video_id("https://youtu.be/abcDEF_1234"), "abcDEF_1234")
        self.assertEqual(extract_video_id("https://www.youtube.com/shorts/abcDEF_1234"), "")

    def test_extract_video_candidates_requires_logged_out_marker(self) -> None:
        snapshot = {"elements": [{"name": "A good video", "href": "https://www.youtube.com/watch?v=abcDEF_1234"}]}

        with self.assertRaises(SignalTubeBrowserLabError) as ctx:
            extract_video_candidates(snapshot, topic="space")

        self.assertIn("logged-out", str(ctx.exception))

    def test_extract_video_candidates_rejects_logged_in_marker(self) -> None:
        snapshot = {
            "elements": [
                {"name": "Account menu", "href": ""},
                {"name": "A good video", "href": "https://www.youtube.com/watch?v=abcDEF_1234"},
            ]
        }

        with self.assertRaises(SignalTubeBrowserLabError) as ctx:
            extract_video_candidates(snapshot, topic="space", require_logged_out_marker=False)

        self.assertIn("logged-in", str(ctx.exception))

    def test_extract_video_candidates_dedupes_and_skips_empty_titles(self) -> None:
        snapshot = {
            "elements": [
                {"name": "Sign in", "href": "https://accounts.google.com/"},
                {"name": "A good space explainer", "href": "https://www.youtube.com/watch?v=abcDEF_1234"},
                {"name": "A good space explainer", "href": "https://www.youtube.com/watch?v=abcDEF_1234&pp=abc"},
                {"name": "", "href": "https://www.youtube.com/watch?v=zzzDEF_1234"},
            ]
        }

        candidates = extract_video_candidates(snapshot, topic="space")

        self.assertEqual([candidate.video_id for candidate in candidates], ["abcDEF_1234"])
        self.assertEqual(candidates[0].title, "A good space explainer")

    def test_client_refuses_existing_session_mode(self) -> None:
        client = BrowserBrainClient()
        with mock.patch.object(BrowserBrainClient, "request", return_value={"connection_mode": "existing_session"}):
            with self.assertRaises(SignalTubeBrowserLabError) as ctx:
                client.open_search_snapshot("space")

        self.assertIn("managed mode", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
