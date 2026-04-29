import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "ops" / "telegram-bridge" / "merge_shared_memory_archive.py"
MODULE_DIR = MODULE_PATH.parent

spec = importlib.util.spec_from_file_location("merge_shared_memory_archive_script", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Failed to load merge_shared_memory_archive.py spec")
module = importlib.util.module_from_spec(spec)
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))
spec.loader.exec_module(module)


class MergeSharedMemoryArchiveScriptTests(unittest.TestCase):
    def test_load_source_keys_deduplicates_keys_across_tables(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.sqlite3")
            conn = module.sqlite3.connect(db_path)
            for table in module.TABLES:
                conn.execute(f"CREATE TABLE {table} (conversation_key TEXT)")
            conn.execute(
                "INSERT INTO messages (conversation_key) VALUES (?)",
                ("shared:architect:main:session:tg:1",),
            )
            conn.execute(
                "INSERT INTO memory_facts (conversation_key) VALUES (?)",
                ("shared:architect:main:session:tg:1",),
            )
            conn.execute(
                "INSERT INTO chat_summaries (conversation_key) VALUES (?)",
                ("shared:architect:main:session:tg:2",),
            )
            conn.commit()
            conn.close()

            source_keys = module.load_source_keys(db_path, "shared:architect:main")

        self.assertEqual(
            source_keys,
            [
                "shared:architect:main:session:tg:1",
                "shared:architect:main:session:tg:2",
            ],
        )

    def test_main_reports_no_sources_as_json(self):
        args = mock.Mock(
            db="/tmp/memory.sqlite3",
            shared_key="shared:architect:main",
            post_merge_live_policy="summarize_live_sessions",
        )
        stdout = io.StringIO()

        with (
            mock.patch.object(module, "parse_args", return_value=args),
            mock.patch.object(module, "load_source_keys", return_value=[]),
            contextlib.redirect_stdout(stdout),
        ):
            exit_code = module.main()

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue().strip())
        self.assertEqual(payload["status"], "no_sources")
        self.assertEqual(payload["source_count"], 0)
        self.assertEqual(payload["shared_key"], "shared:architect:main")
        self.assertEqual(payload["post_merge_live_policy"], "summarize_live_sessions")
        self.assertEqual(payload["archive_messages_compacted"], 0)
        self.assertEqual(payload["live_messages_compacted"], 0)
        self.assertEqual(payload["live_sessions_summarized"], 0)
        self.assertEqual(payload["live_session_summaries_generated"], 0)

    def test_main_reports_merge_counts_as_json(self):
        args = mock.Mock(
            db="/tmp/memory.sqlite3",
            shared_key="shared:architect:main",
            post_merge_live_policy="summarize_live_sessions",
        )
        result = mock.Mock(
            target_key="shared:architect:main",
            source_keys=("shared:architect:main:session:tg:1", "shared:architect:main:session:tg:2"),
            messages_copied=14,
            facts_merged=3,
            summaries_generated=1,
        )
        stdout = io.StringIO()

        with (
            mock.patch.object(module, "parse_args", return_value=args),
            mock.patch.object(
                module,
                "load_source_keys",
                return_value=[
                    "shared:architect:main:session:tg:1",
                    "shared:architect:main:session:tg:2",
                ],
            ),
            mock.patch.object(module, "merge_conversation_keys", return_value=result),
            mock.patch.object(module, "MemoryEngine") as engine_cls,
            mock.patch.object(module, "apply_post_merge_live_policy", return_value=(2, 4, 9)),
            contextlib.redirect_stdout(stdout),
        ):
            engine_cls.return_value.compact_summarized_messages.return_value = 11
            exit_code = module.main()

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue().strip())
        self.assertEqual(payload["status"], "merged")
        self.assertEqual(payload["target_key"], "shared:architect:main")
        self.assertEqual(payload["source_count"], 2)
        self.assertEqual(payload["messages_copied"], 14)
        self.assertEqual(payload["facts_merged"], 3)
        self.assertEqual(payload["summaries_generated"], 1)
        self.assertEqual(payload["archive_messages_compacted"], 11)
        self.assertEqual(payload["live_messages_compacted"], 9)
        self.assertEqual(payload["post_merge_live_policy"], "summarize_live_sessions")
        self.assertEqual(payload["live_sessions_summarized"], 2)
        self.assertEqual(payload["live_session_summaries_generated"], 4)
        self.assertFalse(payload["clears_live_sessions"])

    def test_apply_post_merge_live_policy_summarizes_each_source_key(self):
        fake_engine = mock.Mock()
        fake_engine.run_summarization_if_needed.side_effect = [
            True,
            False,
            False,
        ]
        fake_engine.compact_summarized_messages.side_effect = [7, 0]

        with mock.patch.object(module, "MemoryEngine", return_value=fake_engine):
            summarized_keys, summaries_generated, compacted_messages = module.apply_post_merge_live_policy(
                "/tmp/memory.sqlite3",
                [
                    "shared:architect:main:session:tg:1",
                    "shared:architect:main:session:tg:2",
                ],
                "summarize_live_sessions",
            )

        self.assertEqual(summarized_keys, 1)
        self.assertEqual(summaries_generated, 1)
        self.assertEqual(compacted_messages, 7)
        self.assertEqual(fake_engine.run_summarization_if_needed.call_count, 3)
        self.assertEqual(fake_engine.compact_summarized_messages.call_count, 2)

    def test_apply_post_merge_live_policy_keep_leaves_sources_unchanged(self):
        with mock.patch.object(module, "MemoryEngine") as engine_cls:
            summarized_keys, summaries_generated, compacted_messages = module.apply_post_merge_live_policy(
                "/tmp/memory.sqlite3",
                ["shared:architect:main:session:tg:1"],
                "keep_live_sessions",
            )

        self.assertEqual(summarized_keys, 0)
        self.assertEqual(summaries_generated, 0)
        self.assertEqual(compacted_messages, 0)
        engine_cls.assert_not_called()
