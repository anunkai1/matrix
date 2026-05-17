import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import telegram_bridge.message_inputs as message_inputs


class TestMessageInputs(unittest.TestCase):
    def test_extract_media_selection_prefers_photo_ids(self):
        photo_file_ids, voice_file_id, document = message_inputs._extract_media_selection(
            {
                "photo": [
                    {"file_id": "p-small", "file_size": 10},
                    {"file_id": "p-large", "file_size": 20},
                ]
            }
        )

        self.assertEqual(photo_file_ids, ["p-large"])
        self.assertIsNone(voice_file_id)
        self.assertIsNone(document)

    def test_extract_media_selection_returns_document_payload(self):
        photo_file_ids, voice_file_id, document = message_inputs._extract_media_selection(
            {
                "document": {
                    "file_id": "doc-1",
                    "file_name": "quoted.txt",
                    "mime_type": "text/plain",
                }
            }
        )

        self.assertEqual(photo_file_ids, [])
        self.assertIsNone(voice_file_id)
        self.assertIsNotNone(document)
        self.assertEqual(document.file_id, "doc-1")


if __name__ == "__main__":
    unittest.main()
