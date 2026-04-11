from __future__ import annotations

from datetime import UTC, datetime
import unittest

from src.signaltube.models import FeedbackProfile, VideoCandidate
from src.signaltube.ranking import diversify_ranked, feedback_weight_for_signal, rank_candidates, story_cluster_key


class SignalTubeRankingTests(unittest.TestCase):
    def test_rank_candidates_prefers_recent_feedback_supported_video(self) -> None:
        candidates = [
            VideoCandidate(
                video_id="abcDEF_1234",
                url="https://www.youtube.com/watch?v=abcDEF_1234",
                title="Latest space telescope discovery",
                channel="Space Channel",
                published_at="2026-04-10T20:00:00+00:00",
                source_topic="latest space videos",
            ),
            VideoCandidate(
                video_id="zzzDEF_1234",
                url="https://www.youtube.com/watch?v=zzzDEF_1234",
                title="Old shocking space rumor",
                channel="Rumor Channel",
                published_at="2025-01-10T20:00:00+00:00",
                source_topic="latest space videos",
            ),
        ]
        feedback = FeedbackProfile(
            video_scores={"abcDEF_1234": 2.0, "zzzDEF_1234": -1.5},
            channel_scores={"Space Channel": 1.0, "Rumor Channel": -1.0},
        )

        ranked = rank_candidates(
            candidates,
            topic="latest space videos",
            feedback_profile=feedback,
            now=datetime(2026, 4, 11, 8, 0, tzinfo=UTC),
        )

        self.assertEqual(ranked[0].candidate.video_id, "abcDEF_1234")
        self.assertIn("fresh", ranked[0].reasons)
        self.assertIn("feedback", ranked[0].reasons)
        self.assertIn("channel trend", ranked[0].reasons)
        self.assertLess(ranked[1].score, ranked[0].score)

    def test_feedback_weight_for_signal_maps_expected_values(self) -> None:
        self.assertEqual(feedback_weight_for_signal("save"), 1.5)
        self.assertEqual(feedback_weight_for_signal("more_like_this"), 1.0)
        self.assertEqual(feedback_weight_for_signal("less_like_this"), -1.0)
        self.assertEqual(feedback_weight_for_signal("too_clickbait"), -1.5)

    def test_diversify_ranked_limits_same_story_and_channel(self) -> None:
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
                channel="Channel A",
                source_topic="latest space videos",
            ),
            VideoCandidate(
                video_id="star_a00123",
                url="https://www.youtube.com/watch?v=star_a00123",
                title="Starship static fire test explained",
                channel="Channel A",
                source_topic="latest space videos",
            ),
        ]

        ranked = rank_candidates(candidates, topic="latest space videos")
        diversified = diversify_ranked(ranked, limit=5, max_per_story_cluster=2, max_per_channel=2)

        self.assertEqual([item.candidate.video_id for item in diversified], ["artemis_a01", "artemis_b01", "jwst_a00123"])
        self.assertNotIn("artemis_c01", [item.candidate.video_id for item in diversified])

    def test_story_cluster_key_keeps_different_angle_separate(self) -> None:
        splashdown = VideoCandidate(
            video_id="abcDEF_1234",
            url="https://www.youtube.com/watch?v=abcDEF_1234",
            title="Artemis II re-entry and splashdown live coverage",
        )
        conspiracy = VideoCandidate(
            video_id="zzzDEF_1234",
            url="https://www.youtube.com/watch?v=zzzDEF_1234",
            title="NASA Artemis II conspiracy theories take off about staged green screen",
        )

        self.assertNotEqual(story_cluster_key(splashdown), story_cluster_key(conspiracy))


if __name__ == "__main__":
    unittest.main()
