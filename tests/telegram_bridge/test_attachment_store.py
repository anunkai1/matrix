import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from src.telegram_bridge.attachment_store import AttachmentStore


class AttachmentStoreTests(unittest.TestCase):
    def test_constructor_defers_sqlite_open_until_first_store_use(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "photo.jpg"
            source_path.write_bytes(b"image-bytes")
            real_connect = __import__("src.telegram_bridge.attachment_store", fromlist=["sqlite3"]).sqlite3.connect

            with mock.patch("src.telegram_bridge.attachment_store.sqlite3.connect", wraps=real_connect) as connect_mock:
                store = AttachmentStore(
                    str(Path(tmpdir) / "attachments.sqlite3"),
                    str(Path(tmpdir) / "attachments"),
                    retention_seconds=60,
                    max_total_bytes=1024 * 1024,
                )
                self.assertEqual(connect_mock.call_count, 0)

                store.remember_file(
                    channel="telegram",
                    file_id="tg-file-1",
                    media_kind="photo",
                    source_path=str(source_path),
                    file_name="photo.jpg",
                    mime_type="image/jpeg",
                )

            self.assertEqual(connect_mock.call_count, 1)

    def test_remember_file_runs_single_full_prune_pass(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "photo.jpg"
            source_path.write_bytes(b"image-bytes")
            store = AttachmentStore(
                str(Path(tmpdir) / "attachments.sqlite3"),
                str(Path(tmpdir) / "attachments"),
                retention_seconds=60,
                max_total_bytes=1024 * 1024,
            )

            real_prune = store.prune
            with mock.patch.object(store, "prune", wraps=real_prune) as prune_mock:
                store.remember_file(
                    channel="telegram",
                    file_id="tg-file-1",
                    media_kind="photo",
                    source_path=str(source_path),
                    file_name="photo.jpg",
                    mime_type="image/jpeg",
                )

            self.assertEqual(prune_mock.call_count, 1)

    def test_store_reuses_single_sqlite_connection_across_operations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "photo.jpg"
            source_path.write_bytes(b"image-bytes")
            real_connect = __import__("src.telegram_bridge.attachment_store", fromlist=["sqlite3"]).sqlite3.connect

            with mock.patch("src.telegram_bridge.attachment_store.sqlite3.connect", wraps=real_connect) as connect_mock:
                store = AttachmentStore(
                    str(Path(tmpdir) / "attachments.sqlite3"),
                    str(Path(tmpdir) / "attachments"),
                    retention_seconds=60,
                    max_total_bytes=1024 * 1024,
                )
                store.remember_file(
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

            self.assertEqual(connect_mock.call_count, 1)

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

    def test_get_record_does_not_run_full_prune_for_live_attachment(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "photo.jpg"
            source_path.write_bytes(b"image-bytes")
            store = AttachmentStore(
                str(Path(tmpdir) / "attachments.sqlite3"),
                str(Path(tmpdir) / "attachments"),
                retention_seconds=60,
                max_total_bytes=1024 * 1024,
            )
            store.remember_file(
                channel="telegram",
                file_id="tg-file-1",
                media_kind="photo",
                source_path=str(source_path),
                file_name="photo.jpg",
                mime_type="image/jpeg",
            )

            with mock.patch.object(
                store,
                "prune",
                side_effect=AssertionError("get_record should not run full prune for a targeted live read"),
            ):
                loaded = store.get_record("telegram", "tg-file-1")

            self.assertIsNotNone(loaded)

    def test_remember_file_replaces_old_binary_without_leaking_orphan(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            first_source_path = Path(tmpdir) / "photo-1.jpg"
            second_source_path = Path(tmpdir) / "photo-2.jpg"
            first_source_path.write_bytes(b"first-image")
            second_source_path.write_bytes(b"second-image")
            store = AttachmentStore(
                str(Path(tmpdir) / "attachments.sqlite3"),
                str(Path(tmpdir) / "attachments"),
                retention_seconds=60,
                max_total_bytes=1024 * 1024,
            )

            first_record = store.remember_file(
                channel="telegram",
                file_id="tg-file-1",
                media_kind="photo",
                source_path=str(first_source_path),
                file_name="photo.jpg",
                mime_type="image/jpeg",
            )
            second_record = store.remember_file(
                channel="telegram",
                file_id="tg-file-1",
                media_kind="photo",
                source_path=str(second_source_path),
                file_name="photo.jpg",
                mime_type="image/jpeg",
            )

            self.assertNotEqual(first_record.local_path, second_record.local_path)
            self.assertFalse(Path(first_record.local_path).exists())
            self.assertTrue(Path(second_record.local_path).exists())
            loaded = store.get_record("telegram", "tg-file-1")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.local_path, second_record.local_path)


if __name__ == "__main__":
    unittest.main()
