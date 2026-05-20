import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import telegram_bridge.remember_commands as bridge_remember_commands


class TestRememberCommands(unittest.TestCase):
    def test_ensure_numbered_remember_file_renumbers_manual_lines(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            remember_path = Path(tmpdir) / "remember.md"
            remember_path.write_text(
                "1. First remembered item.\n\nManually added second line.\n",
                encoding="utf-8",
            )
            with mock.patch.object(
                bridge_remember_commands,
                "remember_file_path",
                return_value=remember_path,
            ):
                changed = bridge_remember_commands.ensure_numbered_remember_file()
                normalized = remember_path.read_text(encoding="utf-8")

        self.assertTrue(changed)
        self.assertEqual(
            normalized,
            "1. First remembered item.\n2. Manually added second line.\n",
        )

    def test_ensure_numbered_remember_file_is_noop_when_already_numbered(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            remember_path = Path(tmpdir) / "remember.md"
            remember_path.write_text("1. First.\n2. Second.\n", encoding="utf-8")
            with mock.patch.object(
                bridge_remember_commands,
                "remember_file_path",
                return_value=remember_path,
            ):
                changed = bridge_remember_commands.ensure_numbered_remember_file()

        self.assertFalse(changed)


if __name__ == "__main__":
    unittest.main()
