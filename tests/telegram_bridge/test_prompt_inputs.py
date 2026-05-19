import sys
import unittest
from pathlib import Path
import subprocess
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from tests.telegram_bridge.helpers import FakeTelegramClient, make_config

import telegram_bridge.handlers as bridge_handlers
import telegram_bridge.main as bridge
import telegram_bridge.prompt_inputs as prompt_inputs
import telegram_bridge.prompt_preparation as prompt_preparation


class TestPromptInputs(unittest.TestCase):
    def test_transcribe_voice_for_chat_replies_when_not_configured(self):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config(
            voice_transcribe_cmd=[],
            voice_not_configured_message="Voice transcription is not configured.",
        )

        transcript = prompt_inputs.transcribe_voice_for_chat(
            state=state,
            config=config,
            client=client,
            chat_id=1,
            message_id=103,
            voice_file_id="voice-1",
        )

        self.assertIsNone(transcript)
        self.assertEqual(client.messages[-1], (1, "Voice transcription is not configured.", 103, None))

    def test_transcribe_voice_for_chat_replies_on_timeout(self):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config(
            voice_transcribe_cmd=["/bin/echo"],
            timeout_message="Timed out",
        )

        with mock.patch.object(prompt_inputs, "download_voice_to_temp", return_value="/tmp/fake.oga"), mock.patch.object(
            prompt_inputs,
            "transcribe_voice",
            side_effect=subprocess.TimeoutExpired(cmd=["/bin/echo"], timeout=10),
        ), mock.patch.object(prompt_inputs.os, "remove"):
            transcript = prompt_inputs.transcribe_voice_for_chat(
                state=state,
                config=config,
                client=client,
                chat_id=1,
                message_id=104,
                voice_file_id="voice-2",
            )

        self.assertIsNone(transcript)
        self.assertEqual(client.messages[-1], (1, "Timed out", 104, None))

    def test_prepare_prompt_input_delegates_through_request_wrapper(self):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()
        progress = mock.Mock()

        with mock.patch.object(
            prompt_inputs,
            "_prepare_prompt_input_request",
            return_value="prepared",
        ) as prepare_prompt_input_request:
            prepared = prompt_inputs.prepare_prompt_input(
                state=state,
                config=config,
                client=client,
                chat_id=1,
                message_id=101,
                prompt="hello",
                photo_file_id="photo-1",
                voice_file_id="voice-1",
                document=None,
                progress=progress,
                photo_file_ids=["photo-1", "photo-2"],
                enforce_voice_prefix_from_transcript=True,
            )

        self.assertEqual(prepared, "prepared")
        request = prepare_prompt_input_request.call_args.args[0]
        self.assertEqual(request.chat_id, 1)
        self.assertEqual(request.message_id, 101)
        self.assertEqual(request.prompt, "hello")
        self.assertEqual(request.photo_file_id, "photo-1")
        self.assertEqual(request.photo_file_ids, ["photo-1", "photo-2"])
        self.assertEqual(request.voice_file_id, "voice-1")
        self.assertTrue(request.enforce_voice_prefix_from_transcript)
        self.assertIs(prepare_prompt_input_request.call_args.args[1], progress)

    def test_prepare_prompt_input_request_delegates_to_prompt_preparation_module(self):
        state = bridge.State()
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
            message_id=102,
            prompt="hello",
            photo_file_id=None,
            voice_file_id=None,
            document=None,
        )

        with mock.patch.object(
            prompt_preparation,
            "prepare_prompt_input_request",
            return_value="prepared",
        ) as prepare_prompt_input_request:
            prepared = prompt_inputs._prepare_prompt_input_request(request, progress)

        self.assertEqual(prepared, "prepared")
        kwargs = prepare_prompt_input_request.call_args.kwargs
        self.assertIs(kwargs["transcribe_voice_for_chat_fn"], prompt_inputs.transcribe_voice_for_chat)
        self.assertIs(kwargs["strip_required_prefix_fn"], prompt_inputs.strip_required_prefix)
        self.assertIs(kwargs["send_input_too_long_fn"], prompt_inputs.send_input_too_long)

    def test_prewarm_attachment_archive_for_message_delegates_to_prompt_preparation(self):
        state = bridge.State()
        client = FakeTelegramClient()
        config = make_config()
        message = {"message_id": 5}

        with mock.patch.object(
            prompt_preparation,
            "prewarm_attachment_archive_for_message",
        ) as prewarm_attachment_archive_for_message:
            prompt_inputs.prewarm_attachment_archive_for_message(
                state,
                config,
                client,
                1,
                message,
            )

        args = prewarm_attachment_archive_for_message.call_args.args
        self.assertEqual(args[:5], (state, config, client, 1, message))
        kwargs = prewarm_attachment_archive_for_message.call_args.kwargs
        self.assertIs(kwargs["extract_message_photo_file_ids_fn"], prompt_inputs.extract_message_photo_file_ids)
        self.assertIs(kwargs["extract_message_media_payload_fn"], prompt_inputs.extract_message_media_payload)
        self.assertIs(kwargs["download_photo_to_temp_fn"], prompt_inputs.download_photo_to_temp)


if __name__ == "__main__":
    unittest.main()
