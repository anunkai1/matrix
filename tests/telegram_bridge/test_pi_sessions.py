import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from telegram_bridge.engines import pi_sessions


class TestPiSessions(unittest.TestCase):
    def test_build_session_args_handles_disabled_and_unsupported_modes(self):
        disabled = SimpleNamespace(pi_session_mode="none", pi_session_dir="")
        self.assertEqual(pi_sessions.build_session_args(disabled, "tg:1"), ["--no-session"])

        unsupported = SimpleNamespace(pi_session_mode="weird", pi_session_dir="")
        with self.assertRaises(RuntimeError):
            pi_sessions.build_session_args(unsupported, "tg:1")

    def test_build_session_args_rotates_oversized_session_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = SimpleNamespace(
                pi_session_mode="telegram_scope",
                pi_session_dir=tmpdir,
                pi_provider="deepseek",
                pi_model="deepseek-v4-pro",
                pi_session_max_bytes=1,
                pi_session_max_age_seconds=0,
                pi_session_archive_retention_seconds=3600,
                pi_session_archive_dir="",
            )
            session_key = "tg:-1003894351534:topic:1712"
            session_path = Path(tmpdir) / pi_sessions._safe_session_filename(
                pi_sessions._provider_scoped_session_key(config, session_key)
            )
            session_path.write_text("existing\n", encoding="utf-8")

            with mock.patch.object(pi_sessions.time, "strftime", return_value="20260508T214500Z"):
                args = pi_sessions.build_session_args(config, session_key)

            self.assertEqual(args[0], "--session-dir")
            self.assertEqual(args[2], "--session")
            self.assertEqual(args[3], str(session_path))
            archive_dir = Path(tmpdir) / ".archive"
            archived_files = list(archive_dir.glob("*.rotated.20260508T214500Z.jsonl"))
            self.assertEqual(len(archived_files), 1)
            self.assertFalse(session_path.exists())

    def test_clear_scope_session_files_moves_matching_sessions_to_archive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = SimpleNamespace(
                pi_session_mode="telegram_scope",
                pi_session_dir=tmpdir,
            )
            matching = Path(tmpdir) / "tg_1-abc.jsonl"
            matching.write_text("{}", encoding="utf-8")
            other = Path(tmpdir) / "other-xyz.jsonl"
            other.write_text("{}", encoding="utf-8")

            with mock.patch.object(pi_sessions.time, "strftime", return_value="20260508T214500Z"):
                archived = pi_sessions.clear_scope_session_files(config, "tg:1")

            self.assertEqual(archived, 1)
            self.assertFalse(matching.exists())
            self.assertTrue(other.exists())
            archive_dir = Path(tmpdir) / ".archive"
            self.assertEqual(len(list(archive_dir.glob("*.reset.20260508T214500Z.jsonl"))), 1)

    def test_sanitize_session_images_removes_image_blocks_and_empty_messages(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = SimpleNamespace(
                pi_session_mode="telegram_scope",
                pi_session_dir=tmpdir,
                pi_provider="ollama",
                pi_model="qwen3-coder:30b",
            )
            session_key = "tg:1"
            session_path = Path(tmpdir) / pi_sessions._safe_session_filename(
                pi_sessions._provider_scoped_session_key(config, session_key)
            )
            session_path.write_text(
                "\n".join(
                    [
                        '{"type":"message","message":{"role":"user","content":[{"type":"text","text":"hello"},{"type":"image","image_url":"x"}]}}',
                        '{"type":"message","message":{"role":"user","content":[{"type":"image","image_url":"x"}]}}',
                        '{"type":"message","message":{"role":"assistant","content":[{"type":"image","image_url":"x"}]}}',
                        '{"type":"note","value":"keep"}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            pi_sessions.sanitize_session_images(config, session_key)

            lines = session_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 3)
            self.assertIn('"text"', lines[0])
            self.assertNotIn('"image"', lines[0])
            self.assertIn('"assistant"', lines[1])
            self.assertIn('"note"', lines[2])

    def test_cleanup_session_archive_dir_removes_expired_archives(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir)
            old_file = archive_dir / "scope.rotated.old.jsonl"
            old_file.write_text("{}", encoding="utf-8")
            new_file = archive_dir / "scope.rotated.new.jsonl"
            new_file.write_text("{}", encoding="utf-8")

            os.utime(old_file, (10.0, 10.0))
            os.utime(new_file, (200.0, 200.0))

            with mock.patch.object(pi_sessions.time, "time", return_value=300.0):
                pi_sessions._cleanup_session_archive_dir(archive_dir, retention_seconds=150)

            self.assertFalse(old_file.exists())
            self.assertTrue(new_file.exists())


if __name__ == "__main__":
    unittest.main()
