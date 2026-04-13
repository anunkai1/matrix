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
                duration_text="12:34",
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
            self.assertEqual(loaded[0].candidate.duration_text, "12:34")
            body = html_path.read_text(encoding="utf-8")
            self.assertIn("SignalTube Lab", body)
            self.assertIn("Latest space telescope discovery", body)
            self.assertIn("Space Channel", body)
            self.assertIn("12:34", body)
            self.assertIn("Published: 2026-04-11 08:15 AEST", body)
            self.assertIn("No downloads, no account automation", body)
            self.assertIn('class="topic-nav"', body)
            self.assertIn('href="#topic-latest-space-videos"', body)
            self.assertIn('<section id="topic-latest-space-videos">', body)
            self.assertIn("Copied feedback command", body)
            self.assertIn("feedback --topic &#x27;latest space videos&#x27;", body)
            self.assertIn("--video-id &#x27;abcDEF_1234&#x27; --signal save", body)
            self.assertIn("Don&#x27;t recommend this channel", body)
            self.assertIn("channels block --channel &#x27;Space Channel&#x27;", body)
            self.assertIn(">Seen<", body)
            self.assertIn("videos seen --video-id &#x27;abcDEF_1234&#x27;", body)

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

    def test_load_ranked_diversifies_same_story_wave(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "signaltube.sqlite"
            store = SignalTubeStore(db_path)
            candidates = [
                VideoCandidate(
                    video_id="artemis_a01",
                    url="https://www.youtube.com/watch?v=artemis_a01",
                    title="Artemis II astronauts return to Earth after moon mission",
                    channel="Channel A",
                    source_topic="latest space videos",
                ),
                VideoCandidate(
                    video_id="artemis_b01",
                    url="https://www.youtube.com/watch?v=artemis_b01",
                    title="Artemis II re-entry and splashdown live coverage",
                    channel="Channel B",
                    source_topic="latest space videos",
                ),
                VideoCandidate(
                    video_id="artemis_c01",
                    url="https://www.youtube.com/watch?v=artemis_c01",
                    title="Watch live: Artemis II crew returns after moon flyby",
                    channel="Channel C",
                    source_topic="latest space videos",
                ),
                VideoCandidate(
                    video_id="jwst_a00123",
                    url="https://www.youtube.com/watch?v=jwst_a00123",
                    title="JWST finds a strange exoplanet atmosphere",
                    channel="Channel D",
                    source_topic="latest space videos",
                ),
            ]
            ranked = rank_candidates(candidates, topic="latest space videos")
            store.save_ranked("latest space videos", ranked)

            loaded = store.load_ranked(topic="latest space videos", limit=3)

            self.assertEqual([item.candidate.video_id for item in loaded], ["artemis_a01", "artemis_b01", "jwst_a00123"])

    def test_blocked_channel_is_filtered_from_loaded_feed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "signaltube.sqlite"
            store = SignalTubeStore(db_path)
            candidates = [
                VideoCandidate(
                    video_id="abcDEF_1234",
                    url="https://www.youtube.com/watch?v=abcDEF_1234",
                    title="Latest space telescope discovery",
                    channel="Space Channel",
                    source_topic="latest space videos",
                ),
                VideoCandidate(
                    video_id="zzzDEF_1234",
                    url="https://www.youtube.com/watch?v=zzzDEF_1234",
                    title="Another astronomy briefing",
                    channel="Other Channel",
                    source_topic="latest space videos",
                ),
            ]
            ranked = rank_candidates(candidates, topic="latest space videos")
            store.save_ranked("latest space videos", ranked)
            store.block_channel("Space Channel")

            loaded = store.load_ranked(topic="latest space videos", limit=5)

            self.assertEqual([item.candidate.channel for item in loaded], ["Other Channel"])

    def test_seen_video_is_filtered_from_loaded_feed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "signaltube.sqlite"
            store = SignalTubeStore(db_path)
            candidates = [
                VideoCandidate(
                    video_id="abcDEF_1234",
                    url="https://www.youtube.com/watch?v=abcDEF_1234",
                    title="Latest space telescope discovery",
                    channel="Space Channel",
                    source_topic="latest space videos",
                ),
                VideoCandidate(
                    video_id="zzzDEF_1234",
                    url="https://www.youtube.com/watch?v=zzzDEF_1234",
                    title="Another astronomy briefing",
                    channel="Other Channel",
                    source_topic="latest space videos",
                ),
            ]
            ranked = rank_candidates(candidates, topic="latest space videos")
            store.save_ranked("latest space videos", ranked)
            store.mark_video_seen("abcDEF_1234")

            loaded = store.load_ranked(topic="latest space videos", limit=5)

            self.assertEqual([item.candidate.video_id for item in loaded], ["zzzDEF_1234"])


if __name__ == "__main__":
    unittest.main()
