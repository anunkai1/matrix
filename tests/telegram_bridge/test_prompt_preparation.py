import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from tests.telegram_bridge.helpers import FakeTelegramClient, make_config

import telegram_bridge.handlers as bridge_handlers
import telegram_bridge.main as bridge
import telegram_bridge.prompt_preparation as prompt_preparation


class TestPromptPreparation(unittest.TestCase):
    def test_prepare_prompt_input_request_uses_archived_photo_summary_when_redownload_rejected(self):
        state = bridge.State()
        state.attachment_store = mock.Mock()
        client = FakeTelegramClient()
        config = make_config()
        progress = mock.Mock()
        request = bridge_handlers.build_prompt_request(
            state=state,
            config=config,
            client=client,
            engine=None,
            scope_key="tg:1",
            chat_id=1,
            message_thread_id=None,
            message_id=101,
            prompt="Please summarize this",
            photo_file_id="photo-1",
            voice_file_id=None,
            document=None,
        )

        with mock.patch.object(
            prompt_preparation.attachment_processing,
            "resolve_attachment_binary_or_summary",
            return_value=(None, "Archived image summary"),
        ), mock.patch.object(
            prompt_preparation.attachment_processing,
            "download_photo_to_temp",
            side_effect=ValueError("too large"),
        ):
            prepared = prompt_preparation.prepare_prompt_input_request(
                request,
                progress,
                transcribe_voice_for_chat_fn=mock.Mock(),
                strip_required_prefix_fn=mock.Mock(),
                is_whatsapp_channel_fn=mock.Mock(return_value=False),
                send_input_too_long_fn=mock.Mock(),
                emit_event_fn=mock.Mock(),
                prefix_help_message="prefix help",
            )

        self.assertIsNotNone(prepared)
        self.assertIn("Please summarize this", prepared.prompt_text)
        self.assertIn("Archived image summary", prepared.prompt_text)
        self.assertEqual(prepared.attachment_file_ids, ["photo-1"])
        self.assertEqual(client.messages, [])

    def test_prepare_prompt_input_request_uses_archived_document_summary_when_redownload_fails(self):
        state = bridge.State()
        state.attachment_store = mock.Mock()
        state.attachment_store.get_summary.return_value = "stored summary"
        client = FakeTelegramClient()
        config = make_config()
        progress = mock.Mock()
        document = bridge.DocumentPayload(
            file_id="doc-1",
            file_name="report.pdf",
            mime_type="application/pdf",
        )
        request = bridge_handlers.build_prompt_request(
            state=state,
            config=config,
            client=client,
            engine=None,
            scope_key="tg:1",
            chat_id=1,
            message_thread_id=None,
            message_id=102,
            prompt="Review this file",
            photo_file_id=None,
            voice_file_id=None,
            document=document,
        )

        with (
            mock.patch.object(
                prompt_preparation.attachment_processing,
                "build_archived_attachment_summary_context",
                return_value="Archived file summary",
            ),
            mock.patch.object(
                prompt_preparation.attachment_processing,
                "resolve_attachment_binary_or_summary",
                return_value=(None, ""),
            ),
            mock.patch.object(
                prompt_preparation.attachment_processing,
                "download_document_to_temp",
                side_effect=RuntimeError("boom"),
            ),
        ):
            prepared = prompt_preparation.prepare_prompt_input_request(
                request,
                progress,
                transcribe_voice_for_chat_fn=mock.Mock(),
                strip_required_prefix_fn=mock.Mock(),
                is_whatsapp_channel_fn=mock.Mock(return_value=False),
                send_input_too_long_fn=mock.Mock(),
                emit_event_fn=mock.Mock(),
                prefix_help_message="prefix help",
            )

        self.assertIsNotNone(prepared)
        self.assertIn("Review this file", prepared.prompt_text)
        self.assertIn("Archived file summary", prepared.prompt_text)
        self.assertEqual(prepared.attachment_file_ids, ["doc-1"])
        self.assertEqual(client.messages, [])

    def test_prepare_prompt_input_request_rejects_voice_without_required_prefix(self):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config(required_prefixes=["architect"])
        progress = mock.Mock()
        emit_event = mock.Mock()
        request = bridge_handlers.build_prompt_request(
            state=state,
            config=config,
            client=client,
            engine=None,
            scope_key="tg:1",
            chat_id=1,
            message_thread_id=None,
            message_id=103,
            prompt="",
            photo_file_id=None,
            voice_file_id="voice-1",
            document=None,
            enforce_voice_prefix_from_transcript=True,
        )

        with mock.patch.object(
            prompt_preparation.attachment_processing,
            "maybe_suggest_voice_prefix_alias",
        ) as suggest_voice_prefix_alias:
            prepared = prompt_preparation.prepare_prompt_input_request(
                request,
                progress,
                transcribe_voice_for_chat_fn=mock.Mock(return_value="hello there"),
                strip_required_prefix_fn=mock.Mock(return_value=(False, "hello there")),
                is_whatsapp_channel_fn=mock.Mock(return_value=False),
                send_input_too_long_fn=mock.Mock(),
                emit_event_fn=emit_event,
                prefix_help_message="Prefix required",
            )

        self.assertIsNone(prepared)
        progress.mark_failure.assert_called_once_with("Voice transcript missing required prefix.")
        suggest_voice_prefix_alias.assert_called_once()
        emit_event.assert_called_once_with(
            "bridge.request_ignored",
            fields={"chat_id": 1, "message_id": 103, "reason": "prefix_required_transcript"},
        )
        self.assertEqual(client.messages[-1][:3], (1, "Prefix required", 103))

    def test_prepare_prompt_input_request_rejects_oversized_input(self):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config(max_input_chars=10)
        progress = mock.Mock()
        send_input_too_long = mock.Mock()
        request = bridge_handlers.build_prompt_request(
            state=state,
            config=config,
            client=client,
            engine=None,
            scope_key="tg:1",
            chat_id=1,
            message_thread_id=None,
            message_id=104,
            prompt="x" * 20,
            photo_file_id=None,
            voice_file_id=None,
            document=None,
        )

        prepared = prompt_preparation.prepare_prompt_input_request(
            request,
            progress,
            transcribe_voice_for_chat_fn=mock.Mock(),
            strip_required_prefix_fn=mock.Mock(),
            is_whatsapp_channel_fn=mock.Mock(return_value=False),
            send_input_too_long_fn=send_input_too_long,
            emit_event_fn=mock.Mock(),
            prefix_help_message="prefix help",
        )

        self.assertIsNone(prepared)
        progress.mark_failure.assert_called_once_with("Input rejected as too long.")
        send_input_too_long.assert_called_once_with(
            client=client,
            chat_id=1,
            message_id=104,
            actual_length=20,
            max_input_chars=10,
        )


if __name__ == "__main__":
    unittest.main()
