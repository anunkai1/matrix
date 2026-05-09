import subprocess
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

from tests.telegram_bridge.helpers import FakeTelegramClient, make_config

import telegram_bridge.attachment_processing as attachment_processing
import telegram_bridge.main as bridge


class TestAttachmentProcessing(unittest.TestCase):
    def test_download_photo_to_temp_builds_expected_spec(self):
        client = FakeTelegramClient()
        config = make_config(max_image_bytes=1234)

        with mock.patch.object(
            attachment_processing,
            "download_telegram_file_to_temp",
            return_value=("/tmp/photo.jpg", 12),
        ) as download_telegram_file_to_temp:
            result = attachment_processing.download_photo_to_temp(client, config, "photo-1")

        self.assertEqual(result, "/tmp/photo.jpg")
        spec = download_telegram_file_to_temp.call_args.args[1]
        self.assertEqual(spec.file_id, "photo-1")
        self.assertEqual(spec.max_bytes, 1234)
        self.assertEqual(spec.default_suffix, ".jpg")

    def test_build_archived_attachment_summary_context_and_resolve_attachment_summary(self):
        attachment_store = mock.Mock()
        attachment_store.get_record.return_value = None
        attachment_store.get_summary.return_value = "Prior OCR summary"

        record_path, summary = attachment_processing.resolve_attachment_binary_or_summary(
            attachment_store,
            channel_name="telegram",
            file_id="doc-1",
            media_label="file",
        )

        self.assertIsNone(record_path)
        self.assertIn("Archived file context:", summary)
        self.assertIn("Prior OCR summary", summary)
        self.assertEqual(
            attachment_processing.build_archived_attachment_summary_context("file", "   "),
            "",
        )

    def test_resolve_attachment_for_prompt_uses_existing_record(self):
        attachment_store = mock.Mock()
        attachment_store.get_record.return_value = mock.Mock(local_path="/tmp/existing.pdf")

        with mock.patch.object(
            attachment_processing.os.path,
            "getsize",
            return_value=321,
        ) as getsize:
            result = attachment_processing.resolve_attachment_for_prompt(
                attachment_store,
                channel_name="telegram",
                file_id="doc-1",
                media_label="file",
                media_kind="document",
                downloader=mock.Mock(),
            )

        self.assertEqual(result.status, attachment_processing.AttachmentResolutionStatus.BINARY)
        self.assertEqual(result.local_path, "/tmp/existing.pdf")
        self.assertEqual(result.size_bytes, 321)
        getsize.assert_called_once_with("/tmp/existing.pdf")

    def test_resolve_attachment_for_prompt_returns_summary_on_redownload_failure(self):
        attachment_store = mock.Mock()
        attachment_store.get_record.return_value = None
        attachment_store.get_summary.return_value = "Prior OCR summary"

        result = attachment_processing.resolve_attachment_for_prompt(
            attachment_store,
            channel_name="telegram",
            file_id="doc-1",
            media_label="file",
            media_kind="document",
            downloader=mock.Mock(side_effect=RuntimeError("boom")),
        )

        self.assertEqual(result.status, attachment_processing.AttachmentResolutionStatus.SUMMARY)
        self.assertIn("Prior OCR summary", result.summary_context)

    def test_resolve_attachment_for_prompt_archives_and_cleans_up_temp_file(self):
        attachment_store = mock.Mock()
        attachment_store.get_record.return_value = None
        attachment_store.get_summary.return_value = ""

        with mock.patch.object(
            attachment_processing,
            "archive_media_path",
            return_value="/tmp/archive.jpg",
        ) as archive_media_path, mock.patch.object(
            attachment_processing.os,
            "remove",
        ) as remove_mock, mock.patch.object(
            attachment_processing.os.path,
            "getsize",
            return_value=456,
        ):
            result = attachment_processing.resolve_attachment_for_prompt(
                attachment_store,
                channel_name="telegram",
                file_id="photo-1",
                media_label="image",
                media_kind="photo",
                downloader=mock.Mock(return_value="/tmp/photo.jpg"),
            )

        self.assertEqual(result.status, attachment_processing.AttachmentResolutionStatus.BINARY)
        self.assertEqual(result.local_path, "/tmp/archive.jpg")
        self.assertIsNone(result.cleanup_path)
        archive_media_path.assert_called_once()
        remove_mock.assert_called_once_with("/tmp/photo.jpg")

    def test_resolve_attachment_for_prompt_preserves_temp_path_when_not_archived(self):
        attachment_store = mock.Mock()
        attachment_store.get_record.return_value = None
        attachment_store.get_summary.return_value = ""

        with mock.patch.object(
            attachment_processing,
            "archive_media_path",
            return_value=None,
        ):
            result = attachment_processing.resolve_attachment_for_prompt(
                attachment_store,
                channel_name="telegram",
                file_id="doc-1",
                media_label="file",
                media_kind="document",
                downloader=mock.Mock(return_value=("/tmp/upload.bin", 789)),
            )

        self.assertEqual(result.status, attachment_processing.AttachmentResolutionStatus.BINARY)
        self.assertEqual(result.local_path, "/tmp/upload.bin")
        self.assertEqual(result.cleanup_path, "/tmp/upload.bin")
        self.assertEqual(result.size_bytes, 789)

    def test_archive_media_path_returns_none_on_store_failure(self):
        attachment_store = mock.Mock()
        attachment_store.remember_file.side_effect = RuntimeError("boom")

        archived = attachment_processing.archive_media_path(
            attachment_store,
            channel_name="telegram",
            file_id="photo-1",
            media_kind="photo",
            source_path="/tmp/photo.jpg",
        )

        self.assertIsNone(archived)

    def test_build_voice_transcribe_command_handles_placeholder_and_append(self):
        self.assertEqual(
            attachment_processing.build_voice_transcribe_command(
                ["whisper", "--file", "{file}"],
                "/tmp/voice.ogg",
            ),
            ["whisper", "--file", "/tmp/voice.ogg"],
        )
        self.assertEqual(
            attachment_processing.build_voice_transcribe_command(
                ["whisper", "--model", "small"],
                "/tmp/voice.ogg",
            ),
            ["whisper", "--model", "small", "/tmp/voice.ogg"],
        )

    def test_parse_voice_confidence_clamps_and_ignores_invalid_values(self):
        self.assertEqual(
            attachment_processing.parse_voice_confidence("VOICE_CONFIDENCE=1.7"),
            1.0,
        )
        self.assertEqual(
            attachment_processing.parse_voice_confidence("VOICE_CONFIDENCE=-1"),
            None,
        )
        self.assertIsNone(attachment_processing.parse_voice_confidence("no confidence here"))

    def test_apply_voice_alias_replacements_prefers_longest_case_insensitive_match(self):
        transcript, changed = attachment_processing.apply_voice_alias_replacements(
            "Turn on master broom air con",
            [
                ("broom", "bedroom"),
                ("master broom", "master bedroom"),
            ],
        )

        self.assertTrue(changed)
        self.assertEqual(transcript, "Turn on master bedroom air con")

    def test_build_active_voice_alias_replacements_merges_learned_values(self):
        state = bridge.State()
        state.voice_alias_learning_store = mock.Mock()
        state.voice_alias_learning_store.get_approved_replacements.return_value = [
            ("foo", "baz"),
            ("new", "value"),
        ]
        config = make_config(voice_alias_replacements=[("foo", "bar"), ("keep", "same")])

        replacements = attachment_processing.build_active_voice_alias_replacements(config, state)

        self.assertIn(("foo", "baz"), replacements)
        self.assertIn(("keep", "same"), replacements)
        self.assertIn(("new", "value"), replacements)
        self.assertNotIn(("foo", "bar"), replacements)

    def test_suggest_required_prefix_alias_candidate_and_whatsapp_observation(self):
        candidate = attachment_processing.suggest_required_prefix_alias_candidate(
            "arkitect turn on the light",
            ["architect"],
            ignore_case=True,
            min_similarity=0.5,
        )

        self.assertEqual(candidate[0], "arkitect")
        self.assertEqual(candidate[1], "architect")

        state = bridge.State()
        learning_store = mock.Mock()
        learning_store.get_approved_replacements.return_value = []
        learning_store.observe_pair.return_value = [
            SimpleNamespace(suggestion_id=7, source="arkitect", target="architect", count=3)
        ]
        state.voice_alias_learning_store = learning_store
        client = FakeTelegramClient(channel_name="whatsapp")
        config = make_config(required_prefixes=["architect"])

        with mock.patch.object(
            attachment_processing,
            "emit_event",
        ) as emit_event:
            attachment_processing.maybe_suggest_voice_prefix_alias(
                state=state,
                config=config,
                client=client,
                chat_id=1,
                message_id=201,
                transcript="arkitect turn on the light",
            )

        learning_store.observe_pair.assert_called_once_with(source="arkitect", target="architect")
        emit_event.assert_called_once()
        self.assertIn("Voice correction learning suggestion", client.messages[-1][1])

    def test_transcribe_voice_success_and_failure_paths(self):
        config = make_config(
            voice_transcribe_cmd=["whisper", "{file}"],
            voice_transcribe_timeout_seconds=9,
        )

        success_result = subprocess.CompletedProcess(
            args=["whisper"],
            returncode=0,
            stdout="hello world\n",
            stderr="VOICE_CONFIDENCE=0.75\n",
        )
        with mock.patch.object(
            attachment_processing.subprocess,
            "run",
            return_value=success_result,
        ):
            transcript, confidence = attachment_processing.transcribe_voice(config, "/tmp/voice.ogg")
        self.assertEqual(transcript, "hello world")
        self.assertEqual(confidence, 0.75)

        failure_result = subprocess.CompletedProcess(
            args=["whisper"],
            returncode=1,
            stdout="",
            stderr="bad run",
        )
        with mock.patch.object(
            attachment_processing.subprocess,
            "run",
            return_value=failure_result,
        ):
            with self.assertRaises(RuntimeError):
                attachment_processing.transcribe_voice(config, "/tmp/voice.ogg")

        empty_result = subprocess.CompletedProcess(
            args=["whisper"],
            returncode=0,
            stdout="   ",
            stderr="",
        )
        with mock.patch.object(
            attachment_processing.subprocess,
            "run",
            return_value=empty_result,
        ):
            with self.assertRaises(ValueError):
                attachment_processing.transcribe_voice(config, "/tmp/voice.ogg")


if __name__ == "__main__":
    unittest.main()
