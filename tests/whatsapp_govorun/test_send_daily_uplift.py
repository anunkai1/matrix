import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "ops" / "whatsapp_govorun" / "send_daily_uplift.py"

spec = importlib.util.spec_from_file_location("send_daily_uplift", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Failed to load send_daily_uplift module")
uplift = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = uplift
spec.loader.exec_module(uplift)


class SendDailyUpliftTests(unittest.TestCase):
    def test_build_daily_message_keeps_fixed_wrapper(self):
        message = uplift.build_daily_message("Путиловы", "Поставьте ложку в банку с мёдом, чтобы край не лип.")
        self.assertEqual(
            message,
            "Доброе утро, Путиловы! ☀️\n\nДаю справку: Поставьте ложку в банку с мёдом, чтобы край не лип.",
        )

    def test_parse_generated_life_hack_rejects_wrapper_text(self):
        with self.assertRaises(RuntimeError):
            uplift.parse_generated_life_hack(
                '{"hack_text":"Доброе утро, Путиловы!","idea_key":"ложка в меде","idea_summary":"ложка не дает липнуть меду"}'
            )

    def test_find_similarity_match_rejects_similar_underlying_life_hack(self):
        entry = uplift.build_history_entry(
            entry_id=1,
            sent_at="2026-03-18T09:00:00+10:00",
            message_text="Доброе утро, Путиловы! ☀️\n\nДаю справку: Кладите деревянную ложку поперек кастрюли, чтобы пена не убегала.",
            hack_text="Кладите деревянную ложку поперек кастрюли, чтобы пена не убегала.",
            idea_key="деревянная ложка против убегающей пены",
            idea_summary="Деревянная ложка на кастрюле помогает сдержать пену при закипании.",
        )
        candidate = uplift.GeneratedLifeHack(
            hack_text="Если молоко вот-вот убежит, положите деревянную ложку сверху кастрюли: она помогает сбить пену.",
            idea_key="ложка на кастрюле от пены",
            idea_summary="Положите деревянную ложку поперек кастрюли, чтобы молочная пена не так быстро убегала.",
        )
        match = uplift.find_similarity_match(candidate, [entry])
        self.assertIsNotNone(match)
        assert match is not None
        self.assertGreaterEqual(match.score, 0.66)

    def test_history_store_round_trip_with_source_metadata(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = uplift.HistoryStore(Path(tmp_dir) / "daily_uplift.sqlite3")
            sent_at = uplift.now_in_tz("Australia/Brisbane")
            store.insert_sent_message(
                sent_at,
                uplift.SentLifeHack(
                    message_text="Доброе утро, Путиловы! ☀️\n\nДаю справку: Храните зелень в банке с крышкой и салфеткой, чтобы она дольше оставалась сухой.",
                    hack_text="Храните зелень в банке с крышкой и салфеткой, чтобы она дольше оставалась сухой.",
                    idea_key="зелень в банке с салфеткой",
                    idea_summary="Салфетка в закрытой банке помогает зелени дольше оставаться свежей.",
                    source_post_id="abc123",
                    source_title="LPT: keep herbs fresh in a jar",
                    source_permalink="https://www.reddit.com/r/LifeProTips/comments/abc123/example/",
                    source_score=12345,
                    source_created_utc=1700000000,
                ),
            )
            entries = store.load_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].source_post_id, "abc123")
        self.assertEqual(entries[0].source_score, 12345)

    def test_reddit_cache_store_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = uplift.RedditCacheStore(Path(tmp_dir) / "daily_uplift.sqlite3")
            recent_ts = uplift.recent_cutoff_utc() + 100
            posts = [
                uplift.RedditPost(
                    post_id="a1",
                    title="LPT: Test one",
                    selftext="Body one",
                    permalink="/r/LifeProTips/comments/a1/test_one/",
                    score=100,
                    num_comments=10,
                    created_utc=recent_ts,
                    over_18=False,
                    title_probe=uplift.normalize_probe("LPT: Test one"),
                    body_probe=uplift.normalize_probe("Body one"),
                    cached_at="2026-03-18T00:00:00Z",
                ),
                uplift.RedditPost(
                    post_id="a2",
                    title="LPT: Test two",
                    selftext="Body two",
                    permalink="/r/LifeProTips/comments/a2/test_two/",
                    score=90,
                    num_comments=9,
                    created_utc=recent_ts + 10,
                    over_18=False,
                    title_probe=uplift.normalize_probe("LPT: Test two"),
                    body_probe=uplift.normalize_probe("Body two"),
                    cached_at="2026-03-18T00:00:00Z",
                ),
            ]
            store.upsert_posts(posts, "2026-03-18T00:00:00Z")
            loaded = store.load_recent_posts(uplift.recent_cutoff_utc())
            metadata = store.load_metadata()
        self.assertEqual([post.post_id for post in loaded], ["a1", "a2"])
        self.assertEqual(metadata["reddit_cache_post_count"], "2")

    def test_build_reddit_post_skips_lpt_request_titles(self):
        post = uplift.build_reddit_post(
            {
                "id": "req1",
                "title": "LPT request: how do I clean a pan?",
                "selftext": "help",
                "permalink": "/r/LifeProTips/comments/req1/example/",
                "score": 100,
                "num_comments": 10,
                "created_utc": uplift.recent_cutoff_utc() + 100,
                "over_18": False,
            },
            "2026-03-18T00:00:00Z",
        )
        self.assertIsNone(post)

    def test_build_source_adaptation_prompt_uses_updated_rules(self):
        source_post = uplift.RedditPost(
            post_id="abc123",
            title="LPT: Put your keys in your shoes at night",
            selftext="That way you will not lose them in the morning.",
            permalink="/r/LifeProTips/comments/abc123/example/",
            score=123,
            num_comments=45,
            created_utc=1700000000,
            over_18=False,
            title_probe="lpt put your keys in your shoes at night",
            body_probe="that way you will not lose them in the morning",
            cached_at="2026-03-18T00:00:00Z",
        )
        prompt = uplift.build_source_adaptation_prompt("Путиловы", source_post, [])
        self.assertIn("hack_text must be 1-7 short sentences", prompt)
        self.assertNotIn("Never output trivia", prompt)
        self.assertNotIn("Avoid politics", prompt)
        self.assertIn("Use the Reddit post below as the source of the life-hack idea.", prompt)
        self.assertIn("Do not shorten, compress, summarize, or omit meaningful details", prompt)
        self.assertIn("Prefer near-complete translation over concise paraphrase.", prompt)
        self.assertNotIn("Permalink:", prompt)

    def test_reddit_search_queries_defaults_and_override(self):
        original = uplift.os.environ.get("WA_DAILY_UPLIFT_REDDIT_SEARCH_QUERIES")
        try:
            uplift.os.environ.pop("WA_DAILY_UPLIFT_REDDIT_SEARCH_QUERIES", None)
            self.assertEqual(
                uplift.reddit_search_queries(),
                ["tip OR tips", "work OR job OR career", "money OR save OR budget"],
            )
            uplift.os.environ["WA_DAILY_UPLIFT_REDDIT_SEARCH_QUERIES"] = "alpha||beta || gamma"
            self.assertEqual(uplift.reddit_search_queries(), ["alpha", "beta", "gamma"])
        finally:
            if original is None:
                uplift.os.environ.pop("WA_DAILY_UPLIFT_REDDIT_SEARCH_QUERIES", None)
            else:
                uplift.os.environ["WA_DAILY_UPLIFT_REDDIT_SEARCH_QUERIES"] = original

    def test_legacy_history_entries_seed_old_life_hacks(self):
        entries = uplift.legacy_history_entries("Путиловы")
        self.assertGreaterEqual(len(entries), 2)
        self.assertTrue(any("широкая кружка" in entry.idea_key for entry in entries))

    def test_cache_status_payload_counts_unused_reddit_posts(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "daily_uplift.sqlite3"
            history_store = uplift.HistoryStore(db_path)
            cache_store = uplift.RedditCacheStore(db_path)
            recent_ts = uplift.recent_cutoff_utc() + 100
            cache_store.upsert_posts(
                [
                    uplift.RedditPost(
                        post_id="used1",
                        title="LPT: Used",
                        selftext="Body",
                        permalink="/r/LifeProTips/comments/used1/example/",
                        score=100,
                        num_comments=10,
                        created_utc=recent_ts,
                        over_18=False,
                        title_probe=uplift.normalize_probe("LPT: Used"),
                        body_probe=uplift.normalize_probe("Body"),
                        cached_at="2026-03-18T00:00:00Z",
                    ),
                    uplift.RedditPost(
                        post_id="unused1",
                        title="LPT: Unused",
                        selftext="Body",
                        permalink="/r/LifeProTips/comments/unused1/example/",
                        score=90,
                        num_comments=9,
                        created_utc=recent_ts + 5,
                        over_18=False,
                        title_probe=uplift.normalize_probe("LPT: Unused"),
                        body_probe=uplift.normalize_probe("Body"),
                        cached_at="2026-03-18T00:00:00Z",
                    ),
                ],
                "2026-03-18T00:00:00Z",
            )
            history_store.insert_sent_message(
                uplift.now_in_tz("Australia/Brisbane"),
                uplift.SentLifeHack(
                    message_text="Доброе утро, Путиловы! ☀️\n\nДаю справку: Used.",
                    hack_text="Used.",
                    idea_key="used",
                    idea_summary="used",
                    source_post_id="used1",
                ),
            )
            status = uplift.cache_status_payload(
                cache_store,
                uplift.legacy_history_entries("Путиловы") + history_store.load_entries(),
            )
        self.assertEqual(status["recent_count"], 2)
        self.assertEqual(status["unused_recent_count"], 1)


if __name__ == "__main__":
    unittest.main()
