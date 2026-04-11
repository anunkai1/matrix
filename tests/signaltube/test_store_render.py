from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.signaltube.models import VideoCandidate
from src.signaltube.ranking import rank_candidates
from src.signaltube.render import render_feed
from src.signaltube.store import SignalTubeStore


class SignalTubeStoreRenderTests(unittest.TestCase):
    def test_store_loads_ranked_candidates_and_render_writes_feed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "signaltube.sqlite"
            html_path = Path(tmp) / "feed.html"
            candidate = VideoCandidate(
                video_id="abcDEF_1234",
                url="https://www.youtube.com/watch?v=abcDEF_1234",
                title="Latest space telescope discovery",
                source_topic="latest space videos",
            )
            ranked = rank_candidates([candidate], topic="latest space videos")
            store = SignalTubeStore(db_path)
            store.save_ranked("latest space videos", ranked)

            loaded = store.load_ranked(topic="latest space videos")
            render_feed(html_path, loaded)

            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].candidate.video_id, "abcDEF_1234")
            body = html_path.read_text(encoding="utf-8")
            self.assertIn("SignalTube Lab", body)
            self.assertIn("Latest space telescope discovery", body)
            self.assertIn("No downloads, no account automation", body)


if __name__ == "__main__":
    unittest.main()
