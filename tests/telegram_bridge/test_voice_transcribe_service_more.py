import importlib.util
import io
import os
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

    def test_run_server_handles_ping_and_unknown_action_then_cleans_socket(self):
        class FakeConn:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class FakeServer:
            def __init__(self):
                self.accept_calls = 0
                self.bound = None
                self.closed = False

            def bind(self, path):
                self.bound = path

            def listen(self, backlog):
                self.backlog = backlog

            def settimeout(self, timeout):
                self.timeout = timeout

            def accept(self):
                self.accept_calls += 1
                if self.accept_calls == 1:
                    raise service.socket.timeout()
                if self.accept_calls == 2:
                    return FakeConn(), None
                raise KeyboardInterrupt()

            def close(self):
                self.closed = True

        fake_runtime = mock.Mock()
        fake_server = FakeServer()
        sent_payloads = []

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "whisper.sock")
            with mock.patch.object(
                service.WhisperRuntime,
                "from_env",
                return_value=fake_runtime,
            ), mock.patch.object(
                service.socket,
                "socket",
                return_value=fake_server,
            ), mock.patch.object(
                service,
                "_read_json_line",
                return_value={"action": "ping"},
            ), mock.patch.object(
                service,
                "_send_json_line",
                side_effect=lambda _conn, payload: sent_payloads.append(payload),
            ):
                with self.assertRaises(KeyboardInterrupt):
                    service.run_server(socket_path=socket_path, idle_timeout_seconds=5)

            self.assertEqual(sent_payloads, [{"ok": True, "result": "pong"}])
            self.assertTrue(fake_server.closed)
            self.assertFalse(os.path.exists(socket_path))
            fake_runtime.unload_if_idle.assert_called()

        fake_server = FakeServer()
        sent_payloads = []
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "whisper.sock")
            with mock.patch.object(
                service.WhisperRuntime,
                "from_env",
                return_value=fake_runtime,
            ), mock.patch.object(
                service.socket,
                "socket",
                return_value=fake_server,
            ), mock.patch.object(
                service,
                "_read_json_line",
                return_value={"action": "noop"},
            ), mock.patch.object(
                service,
                "_send_json_line",
                side_effect=lambda _conn, payload: sent_payloads.append(payload),
            ):
                with self.assertRaises(KeyboardInterrupt):
                    service.run_server(socket_path=socket_path, idle_timeout_seconds=5)

            self.assertEqual(sent_payloads, [{"ok": False, "error": "unknown_action"}])

    def test_run_server_handles_transcribe_success_and_error(self):
        class FakeConn:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class FakeServer:
            def __init__(self):
                self.accept_calls = 0

            def bind(self, path):
                self.bound = path

            def listen(self, backlog):
                self.backlog = backlog

            def settimeout(self, timeout):
                self.timeout = timeout

            def accept(self):
                self.accept_calls += 1
                if self.accept_calls == 1:
                    return FakeConn(), None
                raise KeyboardInterrupt()

            def close(self):
                return None

        fake_runtime = mock.Mock()
        fake_runtime.last_confidence = 0.42
        sent_payloads = []

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "whisper.sock")
            fake_server = FakeServer()
            with mock.patch.object(
                service.WhisperRuntime,
                "from_env",
                return_value=fake_runtime,
            ), mock.patch.object(
                service.socket,
                "socket",
                return_value=fake_server,
            ), mock.patch.object(
                service,
                "_read_json_line",
                return_value={"action": "transcribe", "audio_path": "/tmp/audio.ogg"},
            ), mock.patch.object(
                service,
                "_send_json_line",
                side_effect=lambda _conn, payload: sent_payloads.append(payload),
            ):
                fake_runtime.transcribe.return_value = "hello"
                with self.assertRaises(KeyboardInterrupt):
                    service.run_server(socket_path=socket_path, idle_timeout_seconds=5)

        self.assertEqual(
            sent_payloads,
            [{"ok": True, "text": "hello", "confidence": 0.42}],
        )

        sent_payloads = []
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "whisper.sock")
            fake_server = FakeServer()
            with mock.patch.object(
                service.WhisperRuntime,
                "from_env",
                return_value=fake_runtime,
            ), mock.patch.object(
                service.socket,
                "socket",
                return_value=fake_server,
            ), mock.patch.object(
                service,
                "_read_json_line",
                return_value={"action": "transcribe", "audio_path": "/tmp/audio.ogg"},
            ), mock.patch.object(
                service,
                "_send_json_line",
                side_effect=lambda _conn, payload: sent_payloads.append(payload),
            ):
                fake_runtime.transcribe.side_effect = RuntimeError("boom")
                with self.assertRaises(KeyboardInterrupt):
                    service.run_server(socket_path=socket_path, idle_timeout_seconds=5)

        self.assertEqual(sent_payloads, [{"ok": False, "error": "boom"}])

    def test_main_dispatches_modes(self):
        with mock.patch.object(service, "run_server", return_value=11) as run_server:
            self.assertEqual(service.main(["server", "--socket", "/tmp/sock"]), 11)
        run_server.assert_called_once()

        with mock.patch.object(service, "run_ping", return_value=12) as run_ping:
            self.assertEqual(service.main(["ping", "--socket", "/tmp/sock"]), 12)
        run_ping.assert_called_once()

        with mock.patch.object(service, "run_client_transcribe", return_value=13) as run_client:
            self.assertEqual(
                service.main(["client", "--socket", "/tmp/sock", "--audio-path", "/tmp/audio.ogg"]),
                13,
            )
        run_client.assert_called_once()


if __name__ == "__main__":
    unittest.main()
