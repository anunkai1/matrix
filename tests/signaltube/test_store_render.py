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
                channel="Space Channel",
                published_at="2026-04-10T22:15:00+00:00",
                source_topic="latest space videos",
            )
            ranked = rank_candidates([candidate], topic="latest space videos")
            store = SignalTubeStore(db_path)
            store.save_ranked("latest space videos", ranked)

            loaded = store.load_ranked(topic="latest space videos")
            render_feed(html_path, loaded)

            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].candidate.video_id, "abcDEF_1234")
            self.assertEqual(loaded[0].candidate.published_at, "2026-04-10T22:15:00+00:00")
            body = html_path.read_text(encoding="utf-8")
            self.assertIn("SignalTube Lab", body)
            self.assertIn("Latest space telescope discovery", body)
            self.assertIn("Space Channel", body)
            self.assertIn("Published: 2026-04-11 08:15 AEST", body)
            self.assertIn("No downloads, no account automation", body)
            self.assertIn("Copied feedback command", body)
            self.assertIn("feedback --topic &#x27;latest space videos&#x27;", body)
            self.assertIn("--video-id &#x27;abcDEF_1234&#x27; --signal save", body)

    def test_store_round_trips_topics_and_feedback_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "signaltube.sqlite"
            candidate = VideoCandidate(
                video_id="abcDEF_1234",
                url="https://www.youtube.com/watch?v=abcDEF_1234",
                title="Latest space telescope discovery",
                channel="Space Channel",
                source_topic="latest space videos",
            )
            ranked = rank_candidates([candidate], topic="latest space videos")
            store = SignalTubeStore(db_path)
            store.upsert_topic("latest space videos", max_candidates=24, sort_order=5)
            store.save_ranked("latest space videos", ranked)
            store.add_feedback(
                topic="latest space videos",
                video_id="abcDEF_1234",
                signal="save",
                weight=1.5,
                note="good source",
            )

            topics = store.list_topics(enabled_only=True)
            feedback = store.load_feedback_profile(topic="latest space videos")

            self.assertEqual(len(topics), 1)
            self.assertEqual(topics[0].max_candidates, 24)
            self.assertTrue(topics[0].last_collected_at)
            self.assertAlmostEqual(feedback.video_scores["abcDEF_1234"], 2.025)
            self.assertAlmostEqual(feedback.channel_scores["Space Channel"], 2.025)


if __name__ == "__main__":
    unittest.main()
