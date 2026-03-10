import tempfile
import time
import unittest
from pathlib import Path

from src.telegram_bridge.attachment_store import AttachmentStore


class AttachmentStoreTests(unittest.TestCase):
    def test_remember_file_persists_record_and_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "photo.jpg"
            source_path.write_bytes(b"image-bytes")
            store = AttachmentStore(
                str(Path(tmpdir) / "attachments.sqlite3"),
                str(Path(tmpdir) / "attachments"),
                retention_seconds=60,
                max_total_bytes=1024 * 1024,
            )

            record = store.remember_file(
                channel="whatsapp",
                file_id="wa-file-1",
                media_kind="photo",
                source_path=str(source_path),
                file_name="photo.jpg",
                mime_type="image/jpeg",
            )
            store.update_summary("whatsapp", "wa-file-1", "A window and a tree.")

            loaded = store.get_record("whatsapp", "wa-file-1")
            self.assertIsNotNone(loaded)
            self.assertEqual(record.file_id, "wa-file-1")
            self.assertTrue(Path(record.local_path).exists())
            self.assertEqual(store.get_summary("whatsapp", "wa-file-1"), "A window and a tree.")

    def test_prune_expires_binary_but_keeps_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "photo.jpg"
            source_path.write_bytes(b"image-bytes")
            db_path = Path(tmpdir) / "attachments.sqlite3"
            store = AttachmentStore(
                str(db_path),
                str(Path(tmpdir) / "attachments"),
                retention_seconds=60,
                max_total_bytes=1024 * 1024,
            )

            record = store.remember_file(
                channel="telegram",
                file_id="tg-file-1",
                media_kind="photo",
                source_path=str(source_path),
                file_name="photo.jpg",
                mime_type="image/jpeg",
            )
            store.update_summary("telegram", "tg-file-1", "A cat on a couch.")

            with store._connect() as conn:
                conn.execute(
                    "UPDATE attachments SET expires_at = ? WHERE channel = ? AND file_id = ?",
                    (time.time() - 1, "telegram", "tg-file-1"),
                )
                conn.commit()

            store.prune()

            self.assertIsNone(store.get_record("telegram", "tg-file-1"))
            self.assertEqual(store.get_summary("telegram", "tg-file-1"), "A cat on a couch.")
            self.assertFalse(Path(record.local_path).exists())


if __name__ == "__main__":
    unittest.main()
