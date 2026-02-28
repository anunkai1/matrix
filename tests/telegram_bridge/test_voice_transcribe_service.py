import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SERVICE_PATH = ROOT / "src" / "telegram_bridge" / "voice_transcribe_service.py"

spec = importlib.util.spec_from_file_location("voice_transcribe_service", SERVICE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Failed to load voice transcribe service module spec")
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)


class VoiceTranscribeServiceTests(unittest.TestCase):
    def test_collect_transcript_skips_empty_segments(self):
        segment_a = type("Seg", (), {"text": " hello "})()
        segment_b = type("Seg", (), {"text": ""})()
        segment_c = type("Seg", (), {"text": " world"})()

        transcript = service.collect_transcript([segment_a, segment_b, segment_c])
        self.assertEqual(transcript, "hello world")

    def test_unload_if_idle_drops_loaded_model(self):
        runtime = service.WhisperRuntime(
            model_name="base",
            language=None,
            model_dir=None,
            device="cuda",
            compute_type="float16",
            fallback_device="cpu",
            fallback_compute_type="int8",
            idle_timeout_seconds=3600,
        )
        runtime._model = object()
        runtime._loaded_profile = ("cuda", "float16")
        runtime._last_used_monotonic = 0.0

        unloaded = runtime.unload_if_idle(now=4000.0)

        self.assertTrue(unloaded)
        self.assertIsNone(runtime._model)
        self.assertIsNone(runtime._loaded_profile)

    def test_transcribe_falls_back_after_cuda_failure(self):
        runtime = service.WhisperRuntime(
            model_name="base",
            language=None,
            model_dir=None,
            device="cuda",
            compute_type="float16",
            fallback_device="cpu",
            fallback_compute_type="int8",
            idle_timeout_seconds=3600,
        )

        calls = []

        def fake_transcribe(_audio_path, *, device, compute_type):
            calls.append((device, compute_type))
            if device == "cuda":
                raise RuntimeError("cuda unavailable")
            return "fallback transcript"

        with tempfile.NamedTemporaryFile(suffix=".ogg") as handle:
            with mock.patch.object(runtime, "_transcribe_with_profile", side_effect=fake_transcribe):
                transcript = runtime.transcribe(handle.name)

        self.assertEqual(transcript, "fallback transcript")
        self.assertTrue(runtime._primary_failed)
        self.assertEqual(calls, [("cuda", "float16"), ("cpu", "int8")])

    def test_transcribe_uses_fallback_only_after_primary_failure(self):
        runtime = service.WhisperRuntime(
            model_name="base",
            language=None,
            model_dir=None,
            device="cuda",
            compute_type="float16",
            fallback_device="cpu",
            fallback_compute_type="int8",
            idle_timeout_seconds=3600,
        )
        runtime._primary_failed = True

        calls = []

        def fake_transcribe(_audio_path, *, device, compute_type):
            calls.append((device, compute_type))
            return "ok"

        with tempfile.NamedTemporaryFile(suffix=".ogg") as handle:
            with mock.patch.object(runtime, "_transcribe_with_profile", side_effect=fake_transcribe):
                transcript = runtime.transcribe(handle.name)

        self.assertEqual(transcript, "ok")
        self.assertEqual(calls, [("cpu", "int8")])


if __name__ == "__main__":
    unittest.main()
