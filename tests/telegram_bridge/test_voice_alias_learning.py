import tempfile
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[2]
BRIDGE_DIR = ROOT / "src" / "telegram_bridge"
if str(BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(BRIDGE_DIR))

import voice_alias_learning as learning


class VoiceAliasLearningTests(unittest.TestCase):
    def test_suggestion_created_after_repeated_confirmation_and_can_be_approved(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = learning.VoiceAliasLearningStore(
                path=str(Path(tmp) / "voice_alias_learning.json"),
                min_examples=2,
                confirmation_window_seconds=3600,
            )

            store.register_low_confidence_transcript(
                chat_id=1,
                transcript="turn off master broom aircon",
                confidence=0.20,
            )
            first = store.consume_confirmation(
                chat_id=1,
                confirmed_text="turn off master bedroom aircon",
                active_replacements=[],
            )
            self.assertTrue(first.consumed)
            self.assertEqual(first.suggestion_created, [])

            store.register_low_confidence_transcript(
                chat_id=1,
                transcript="turn off master broom aircon",
                confidence=0.22,
            )
            second = store.consume_confirmation(
                chat_id=1,
                confirmed_text="turn off master bedroom aircon",
                active_replacements=[],
            )
            self.assertEqual(len(second.suggestion_created), 1)
            suggestion = second.suggestion_created[0]
            self.assertEqual(suggestion.source, "master broom")
            self.assertEqual(suggestion.target, "master bedroom")

            approved = store.approve(suggestion.suggestion_id)
            self.assertIsNotNone(approved)
            self.assertIn(
                ("master broom", "master bedroom"),
                store.get_approved_replacements(),
            )

    def test_active_replacement_prevents_duplicate_suggestion(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = learning.VoiceAliasLearningStore(
                path=str(Path(tmp) / "voice_alias_learning.json"),
                min_examples=1,
                confirmation_window_seconds=3600,
            )
            store.register_low_confidence_transcript(
                chat_id=1,
                transcript="turn off master broom",
                confidence=0.2,
            )
            result = store.consume_confirmation(
                chat_id=1,
                confirmed_text="turn off master bedroom",
                active_replacements=[("master broom", "master bedroom")],
            )
            self.assertTrue(result.consumed)
            self.assertEqual(result.suggestion_created, [])
            self.assertEqual(store.list_pending(), [])


if __name__ == "__main__":
    unittest.main()
