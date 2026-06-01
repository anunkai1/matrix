import json
import tempfile
import unittest
from pathlib import Path

from telegram_bridge import dream_loop_state


class DreamLoopStateTests(unittest.TestCase):
    def test_load_stale_context_statuses_coerces_string_false_to_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "dream_loop_stale_context.json"
            path.write_text(
                json.dumps(
                    {
                        "tg:1": {
                            "warning_fingerprint": "fp-1",
                            "warning_outstanding": "false",
                        }
                    }
                ),
                encoding="utf-8",
            )

            loaded = dream_loop_state.load_stale_context_statuses(str(path))

        self.assertEqual(loaded["tg:1"]["warning_fingerprint"], "fp-1")
        self.assertFalse(loaded["tg:1"]["warning_outstanding"])

    def test_load_stale_context_statuses_coerces_string_true_to_true(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "dream_loop_stale_context.json"
            path.write_text(
                json.dumps(
                    {
                        "tg:1": {
                            "warning_fingerprint": "fp-1",
                            "warning_outstanding": "true",
                        }
                    }
                ),
                encoding="utf-8",
            )

            loaded = dream_loop_state.load_stale_context_statuses(str(path))

        self.assertTrue(loaded["tg:1"]["warning_outstanding"])

    def test_load_stale_context_statuses_skips_invalid_scope_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "dream_loop_stale_context.json"
            path.write_text(
                json.dumps(
                    {
                        "": {"warning_outstanding": True},
                        "tg:1": {"warning_outstanding": True},
                    }
                ),
                encoding="utf-8",
            )

            loaded = dream_loop_state.load_stale_context_statuses(str(path))

        self.assertEqual(set(loaded.keys()), {"tg:1"})


if __name__ == "__main__":
    unittest.main()
