from __future__ import annotations

import json
import subprocess
import unittest
from unittest import mock

from src.signaltube.metadata import enrich_candidates_with_youtube_metadata
from src.signaltube.models import VideoCandidate


class SignalTubeMetadataTests(unittest.TestCase):
    def test_enrich_candidates_with_youtube_metadata_uses_release_timestamp(self) -> None:
        candidate = VideoCandidate(
            video_id="abcDEF_1234",
            url="https://www.youtube.com/watch?v=abcDEF_1234",
            title="thumbnail label",
        )
        payload = {
            "title": "Actual video title",
            "channel": "Space Channel",
            "timestamp": 1775843156,
            "release_timestamp": 1775843292,
            "duration_string": "1:02:03",
        }
        result = subprocess.CompletedProcess(
            args=["yt-dlp"],
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        )

        with mock.patch("src.signaltube.metadata.shutil.which", return_value="/usr/bin/yt-dlp"):
            with mock.patch("src.signaltube.metadata.subprocess.run", return_value=result):
                enriched = enrich_candidates_with_youtube_metadata([candidate])

        self.assertEqual(enriched[0].title, "Actual video title")
        self.assertEqual(enriched[0].channel, "Space Channel")
        self.assertEqual(enriched[0].published_at, "2026-04-10T17:48:12+00:00")
        self.assertEqual(enriched[0].duration_text, "1:02:03")

    def test_enrich_candidates_falls_back_when_yt_dlp_is_missing(self) -> None:
        candidate = VideoCandidate(
            video_id="abcDEF_1234",
            url="https://www.youtube.com/watch?v=abcDEF_1234",
            title="Original title",
        )

        with mock.patch("src.signaltube.metadata.shutil.which", return_value=None):
            enriched = enrich_candidates_with_youtube_metadata([candidate])

        self.assertEqual(enriched, [candidate])


if __name__ == "__main__":
    unittest.main()
