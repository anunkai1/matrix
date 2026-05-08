import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SERVICE_PATH = ROOT / "src" / "telegram_bridge" / "voice_transcribe_service.py"

spec = importlib.util.spec_from_file_location("voice_transcribe_service_more", SERVICE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Failed to load voice transcribe service module spec")
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)


class VoiceTranscribeServiceMoreTests(unittest.TestCase):
    def test_collect_transcript_and_confidence_handles_scores(self):
        seg_a = type("Seg", (), {"text": " hello ", "avg_logprob": -0.1, "no_speech_prob": 0.1})()
        seg_b = type("Seg", (), {"text": "", "avg_logprob": None, "no_speech_prob": None})()
        seg_c = type("Seg", (), {"text": " world ", "avg_logprob": -0.2, "no_speech_prob": 0.0})()

        transcript, confidence = service.collect_transcript_and_confidence([seg_a, seg_b, seg_c])

        self.assertEqual(transcript, "hello world")
        self.assertIsNotNone(confidence)
        self.assertGreater(confidence, 0.0)
        self.assertLessEqual(confidence, 1.0)

    def test_request_validates_response_shape(self):
        fake_conn = mock.Mock()
        fake_conn.__enter__ = mock.Mock(return_value=fake_conn)
        fake_conn.__exit__ = mock.Mock(return_value=False)
        with mock.patch.object(service.socket, "socket", return_value=fake_conn), mock.patch.object(
            service,
            "_read_json_line",
            return_value={"ok": "yes"},
        ):
            with self.assertRaises(RuntimeError):
                service._request("/tmp/socket", {"action": "ping"}, timeout_seconds=1.0)

    def test_run_ping_success_and_failure(self):
        with mock.patch.object(service, "_request", return_value={"ok": True, "result": "pong"}):
            self.assertEqual(service.run_ping(socket_path="/tmp/socket", timeout_seconds=1.0), 0)

        stderr = io.StringIO()
        with mock.patch.object(service, "_request", side_effect=RuntimeError("down")), mock.patch(
            "sys.stderr",
            stderr,
        ):
            self.assertEqual(service.run_ping(socket_path="/tmp/socket", timeout_seconds=1.0), 1)
        self.assertIn("ping failed: down", stderr.getvalue())

    def test_run_client_transcribe_success_and_failure(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(
            service,
            "_request",
            return_value={"ok": True, "text": "hello", "confidence": 0.875},
        ), mock.patch("sys.stdout", stdout), mock.patch("sys.stderr", stderr):
            self.assertEqual(
                service.run_client_transcribe(
                    socket_path="/tmp/socket",
                    audio_path="/tmp/audio.ogg",
                    timeout_seconds=1.0,
                ),
                0,
            )
        self.assertIn("hello", stdout.getvalue())
        self.assertIn("VOICE_CONFIDENCE=0.875", stderr.getvalue())

        stderr = io.StringIO()
        with mock.patch.object(
            service,
            "_request",
            return_value={"ok": False, "error": "bad audio"},
        ), mock.patch("sys.stderr", stderr):
            self.assertEqual(
                service.run_client_transcribe(
                    socket_path="/tmp/socket",
                    audio_path="/tmp/audio.ogg",
                    timeout_seconds=1.0,
                ),
                1,
            )
        self.assertIn("bad audio", stderr.getvalue())

    def test_is_socket_stale_true_when_connect_fails(self):
        class FakeSocket:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def settimeout(self, _timeout):
                return None

            def connect(self, _path):
                raise OSError("stale")

        with mock.patch.object(service.socket, "socket", return_value=FakeSocket()):
            self.assertTrue(service._is_socket_stale("/tmp/socket"))

    def test_transcribe_raises_file_not_found_for_missing_audio(self):
        runtime = service.WhisperRuntime(
            model_name="base",
            language=None,
            model_dir=None,
            device="cuda",
            compute_type="float16",
            fallback_device="cpu",
            fallback_compute_type="int8",
            idle_timeout_seconds=3600,
            beam_size=5,
            best_of=5,
            temperature=0.0,
        )

        with self.assertRaises(FileNotFoundError):
            runtime.transcribe("/tmp/does-not-exist.ogg")


if __name__ == "__main__":
    unittest.main()
