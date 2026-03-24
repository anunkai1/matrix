import importlib.util
import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "src" / "telegram_bridge" / "diary_store.py"
MODULE_DIR = MODULE_PATH.parent

spec = importlib.util.spec_from_file_location("telegram_bridge_diary_store", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Failed to load telegram diary store module spec")
diary_store = importlib.util.module_from_spec(spec)
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))
sys.modules[spec.name] = diary_store
spec.loader.exec_module(diary_store)


def make_config(tmpdir: str, **overrides):
    base = {
        "state_dir": tmpdir,
        "diary_mode_enabled": True,
        "diary_capture_quiet_window_seconds": 75,
        "diary_timezone": "Australia/Brisbane",
        "diary_local_root": str(Path(tmpdir) / "diary"),
        "diary_nextcloud_enabled": False,
        "diary_nextcloud_base_url": "",
        "diary_nextcloud_username": "",
        "diary_nextcloud_app_password": "",
        "diary_nextcloud_remote_root": "/Diary",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class DiaryStoreTests(unittest.TestCase):
    def test_append_day_entry_renders_docx_with_embedded_image(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = make_config(tmpdir)
            image_path = Path(tmpdir) / "photo.jpg"
            Image.new("RGB", (64, 32), color="red").save(image_path, format="JPEG")

            relative_path = diary_store.copy_photo_to_day_assets(
                config=config,
                day=diary_store.dt.date(2026, 3, 24),
                source_path=str(image_path),
                entry_id="20260324T123000",
                index=1,
            )
            entry = diary_store.DiaryEntry(
                entry_id="20260324T123000",
                created_at="2026-03-24T12:30:00+10:00",
                time_label="12:30 PM",
                title="Beach walk",
                text_blocks=["We walked along the beach."],
                voice_transcripts=["It was hot and bright outside."],
                notes=["Voice note was clear."],
                photos=[diary_store.DiaryPhoto(relative_path=relative_path, caption="Dad near the water")],
            )

            docx_path = diary_store.append_day_entry(config, diary_store.dt.date(2026, 3, 24), entry)

            self.assertTrue(docx_path.exists())
            entries = diary_store.read_day_entries(config, diary_store.dt.date(2026, 3, 24))
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].title, "Beach walk")
            with zipfile.ZipFile(docx_path, "r") as archive:
                document_xml = archive.read("word/document.xml").decode("utf-8")
                media_names = archive.namelist()
            self.assertIn("Beach walk", document_xml)
            self.assertIn("Dad near the water", document_xml)
            self.assertIn("word/media/20260324T123000-01.jpg", media_names)

    def test_upload_to_nextcloud_creates_dirs_puts_file_and_verifies(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = make_config(
                tmpdir,
                diary_nextcloud_enabled=True,
                diary_nextcloud_base_url="https://nextcloud.local",
                diary_nextcloud_username="DiaryUser",
                diary_nextcloud_app_password="secret",
            )
            docx_path = Path(tmpdir) / "sample.docx"
            docx_path.write_bytes(b"docx")
            calls = []

            class FakeResponse:
                def __init__(self, status: int) -> None:
                    self.status = status

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

            def fake_urlopen(request, context=None, timeout=0):
                del context, timeout
                calls.append((request.get_method(), request.full_url))
                method = request.get_method()
                if method == "MKCOL":
                    return FakeResponse(201)
                if method == "PUT":
                    return FakeResponse(201)
                if method == "HEAD":
                    return FakeResponse(200)
                raise AssertionError(f"Unexpected method: {method}")

            with mock.patch.object(diary_store, "urlopen", side_effect=fake_urlopen):
                diary_store.upload_to_nextcloud(config, docx_path, "/Diary/2026/03/2026-03-24 - Diary.docx")

            self.assertEqual(
                calls,
                [
                    ("MKCOL", "https://nextcloud.local/remote.php/dav/files/DiaryUser/Diary"),
                    ("MKCOL", "https://nextcloud.local/remote.php/dav/files/DiaryUser/Diary/2026"),
                    ("MKCOL", "https://nextcloud.local/remote.php/dav/files/DiaryUser/Diary/2026/03"),
                    (
                        "PUT",
                        "https://nextcloud.local/remote.php/dav/files/DiaryUser/Diary/2026/03/2026-03-24%20-%20Diary.docx",
                    ),
                    (
                        "HEAD",
                        "https://nextcloud.local/remote.php/dav/files/DiaryUser/Diary/2026/03/2026-03-24%20-%20Diary.docx",
                    ),
                ],
            )


if __name__ == "__main__":
    unittest.main()
