import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "ops" / "telegram-bridge" / "build_latency_corpus.py"

spec = importlib.util.spec_from_file_location("telegram_bridge_build_latency_corpus", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Failed to load build_latency_corpus module")
build_latency_corpus = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = build_latency_corpus
spec.loader.exec_module(build_latency_corpus)


class BuildLatencyCorpusTests(unittest.TestCase):
    def test_sanitize_prompt_redacts_common_sensitive_shapes(self) -> None:
        text = (
            "Open https://example.com and inspect /home/architect/matrix plus "
            "0x1234567890abcdef and @anunakii and 123456789"
        )
        sanitized = build_latency_corpus.sanitize_prompt(text)
        self.assertIn("<URL>", sanitized)
        self.assertIn("<PATH>", sanitized)
        self.assertIn("<HEX>", sanitized)
        self.assertIn("<HANDLE>", sanitized)
        self.assertIn("<NUM>", sanitized)

    def test_fetch_and_select_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "memory.sqlite3"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    """
                    CREATE TABLE messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        conversation_key TEXT NOT NULL,
                        channel TEXT NOT NULL,
                        sender_role TEXT NOT NULL,
                        sender_name TEXT NOT NULL,
                        text TEXT NOT NULL,
                        ts REAL NOT NULL,
                        token_estimate INTEGER NOT NULL,
                        is_bot INTEGER NOT NULL DEFAULT 0
                    )
                    """
                )
                rows = [
                    ("shared:architect:main", "telegram", "user", "anunakii", "short prompt", 9999999999.0, 2, 0),
                    (
                        "shared:architect:main",
                        "telegram",
                        "user",
                        "anunakii",
                        "medium prompt " * 10,
                        9999999998.0,
                        20,
                        0,
                    ),
                    (
                        "shared:architect:main",
                        "telegram",
                        "user",
                        "anunakii",
                        "long prompt " * 40,
                        9999999997.0,
                        80,
                        0,
                    ),
                    ("shared:architect:main", "telegram", "assistant", "Architect", "ignore me", 9999999996.0, 2, 1),
                ]
                conn.executemany(
                    """
                    INSERT INTO messages (
                        conversation_key, channel, sender_role, sender_name, text, ts, token_estimate, is_bot
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
                conn.commit()
            finally:
                conn.close()

            prompts = build_latency_corpus.fetch_recent_user_prompts(
                db_path,
                "shared:architect:main",
                since_days=36500,
                candidate_limit=20,
                min_chars=5,
                max_chars=600,
            )
            self.assertEqual(len(prompts), 3)
            selected = build_latency_corpus.select_representative_prompts(prompts, 3)
            self.assertEqual(len(selected), 3)
            payload = build_latency_corpus.build_corpus_payload(selected, engine_delay_ms=12.0)
            self.assertEqual(len(payload), 3)
            self.assertEqual(payload[0]["name"], "architect_case_01")
            self.assertEqual(payload[0]["engine_delay_ms"], 12.0)


if __name__ == "__main__":
    unittest.main()
