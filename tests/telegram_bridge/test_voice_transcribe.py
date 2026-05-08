import importlib.util
import io
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "src" / "telegram_bridge" / "voice_transcribe.py"


def load_module():
    fake_backend = types.ModuleType("faster_whisper")
    fake_backend.WhisperModel = object
    spec = importlib.util.spec_from_file_location("voice_transcribe_test", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load voice transcribe module spec")
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict("sys.modules", {"faster_whisper": fake_backend}):
        spec.loader.exec_module(module)
    return module


voice_transcribe = load_module()


class VoiceTranscribeTests(unittest.TestCase):
    def test_collect_transcript_skips_empty_segments(self):
        segment_a = type("Seg", (), {"text": " hello "})()
        segment_b = type("Seg", (), {"text": ""})()
        segment_c = type("Seg", (), {"text": None})()
        segment_d = type("Seg", (), {"text": " world"})()

        transcript = voice_transcribe._collect_transcript(
            [segment_a, segment_b, segment_c, segment_d]
        )

        self.assertEqual(transcript, "hello world")

    def test_run_transcription_passes_runtime_options(self):
        calls = {}

        class FakeModel:
            def __init__(self, model_name, **kwargs):
                calls["init"] = (model_name, kwargs)

            def transcribe(self, audio_path, **kwargs):
                calls["transcribe"] = (audio_path, kwargs)
                return (
                    [
                        type("Seg", (), {"text": " hello "})(),
                        type("Seg", (), {"text": " world"})(),
                    ],
                    object(),
                )

        with mock.patch.object(voice_transcribe, "WhisperModel", FakeModel):
            transcript = voice_transcribe._run_transcription(
                "base",
                "/tmp/audio.ogg",
                "en",
                device="cuda",
                compute_type="float16",
                model_dir="/tmp/models",
                beam_size=7,
                best_of=3,
                temperature=0.25,
            )

        self.assertEqual(transcript, "hello world")
        self.assertEqual(
            calls["init"],
            (
                "base",
                {
                    "device": "cuda",
                    "compute_type": "float16",
                    "download_root": "/tmp/models",
                },
            ),
        )
        self.assertEqual(
            calls["transcribe"],
            (
                "/tmp/audio.ogg",
                {
                    "language": "en",
                    "vad_filter": True,
                    "beam_size": 7,
                    "best_of": 3,
                    "temperature": 0.25,
                },
            ),
        )

    def test_main_returns_usage_when_missing_arg(self):
        stderr = io.StringIO()
        with mock.patch("sys.argv", ["voice_transcribe.py"]), mock.patch("sys.stderr", stderr):
            result = voice_transcribe.main()

        self.assertEqual(result, 2)
        self.assertIn("usage: voice_transcribe.py <voice_file_path>", stderr.getvalue())

    def test_main_returns_missing_file_when_audio_absent(self):
        stderr = io.StringIO()
        with mock.patch("sys.argv", ["voice_transcribe.py", "/tmp/missing.ogg"]), mock.patch(
            "sys.stderr",
            stderr,
        ):
            result = voice_transcribe.main()

        self.assertEqual(result, 2)
        self.assertIn("voice file not found: /tmp/missing.ogg", stderr.getvalue())

    def test_main_uses_env_runtime_settings_and_prints_transcript(self):
        stdout = io.StringIO()
        with tempfile.NamedTemporaryFile(suffix=".ogg") as handle, mock.patch.dict(
            os.environ,
            {
                "TELEGRAM_VOICE_WHISPER_MODEL": "large-v3",
                "TELEGRAM_VOICE_WHISPER_DEVICE": "cpu",
                "TELEGRAM_VOICE_WHISPER_COMPUTE_TYPE": "int16",
                "TELEGRAM_VOICE_WHISPER_LANGUAGE": "",
                "TELEGRAM_VOICE_WHISPER_MODEL_DIR": "/tmp/cache",
                "TELEGRAM_VOICE_WHISPER_BEAM_SIZE": "9",
                "TELEGRAM_VOICE_WHISPER_BEST_OF": "4",
                "TELEGRAM_VOICE_WHISPER_TEMPERATURE": "0.5",
            },
            clear=False,
        ), mock.patch("sys.argv", ["voice_transcribe.py", handle.name]), mock.patch(
            "sys.stdout",
            stdout,
        ), mock.patch.object(
            voice_transcribe,
            "_run_transcription",
            return_value="ready transcript",
        ) as run_transcription:
            result = voice_transcribe.main()

        self.assertEqual(result, 0)
        run_transcription.assert_called_once_with(
            "large-v3",
            handle.name,
            None,
            device="cpu",
            compute_type="int16",
            model_dir="/tmp/cache",
            beam_size=9,
            best_of=4,
            temperature=0.5,
        )
        self.assertEqual(stdout.getvalue().strip(), "ready transcript")

    def test_main_retries_on_cuda_failure_with_fallback_settings(self):
        stderr = io.StringIO()
        stdout = io.StringIO()
        calls = []

        def fake_run(*args, **kwargs):
            calls.append((args, kwargs))
            if len(calls) == 1:
                raise RuntimeError("cuda unavailable")
            return "fallback transcript"

        with tempfile.NamedTemporaryFile(suffix=".ogg") as handle, mock.patch.dict(
            os.environ,
            {
                "TELEGRAM_VOICE_WHISPER_DEVICE": "cuda",
                "TELEGRAM_VOICE_WHISPER_COMPUTE_TYPE": "float16",
                "TELEGRAM_VOICE_WHISPER_FALLBACK_DEVICE": "cpu",
                "TELEGRAM_VOICE_WHISPER_FALLBACK_COMPUTE_TYPE": "int8",
            },
            clear=False,
        ), mock.patch("sys.argv", ["voice_transcribe.py", handle.name]), mock.patch(
            "sys.stderr",
            stderr,
        ), mock.patch(
            "sys.stdout",
            stdout,
        ), mock.patch.object(
            voice_transcribe,
            "_run_transcription",
            side_effect=fake_run,
        ):
            result = voice_transcribe.main()

        self.assertEqual(result, 0)
        self.assertEqual(calls[0][1]["device"], "cuda")
        self.assertEqual(calls[0][1]["compute_type"], "float16")
        self.assertEqual(calls[1][1]["device"], "cpu")
        self.assertEqual(calls[1][1]["compute_type"], "int8")
        self.assertIn("retrying on cpu/int8", stderr.getvalue())
        self.assertEqual(stdout.getvalue().strip(), "fallback transcript")

    def test_main_returns_error_when_fallback_also_fails(self):
        stderr = io.StringIO()
        with tempfile.NamedTemporaryFile(suffix=".ogg") as handle, mock.patch.dict(
            os.environ,
            {"TELEGRAM_VOICE_WHISPER_DEVICE": "cuda"},
            clear=False,
        ), mock.patch("sys.argv", ["voice_transcribe.py", handle.name]), mock.patch(
            "sys.stderr",
            stderr,
        ), mock.patch.object(
            voice_transcribe,
            "_run_transcription",
            side_effect=[RuntimeError("cuda unavailable"), RuntimeError("cpu unavailable")],
        ):
            result = voice_transcribe.main()

        self.assertEqual(result, 1)
        self.assertIn("transcription backend error: cpu unavailable", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
