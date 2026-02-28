#!/usr/bin/env python3
"""Persistent voice transcription service with warm-model idle timeout."""

from __future__ import annotations

import argparse
import gc
import json
import math
import os
import socket
import sys
import time
from typing import Iterable, Optional, Tuple


def collect_transcript(segments: Iterable[object]) -> str:
    parts: list[str] = []
    for segment in segments:
        text = (getattr(segment, "text", "") or "").strip()
        if text:
            parts.append(text)
    return " ".join(parts).strip()


def collect_transcript_and_confidence(
    segments: Iterable[object],
) -> Tuple[str, Optional[float]]:
    parts: list[str] = []
    confidence_parts: list[float] = []
    for segment in segments:
        text = (getattr(segment, "text", "") or "").strip()
        if text:
            parts.append(text)
        avg_logprob = getattr(segment, "avg_logprob", None)
        if avg_logprob is None:
            continue
        try:
            score = math.exp(float(avg_logprob))
        except (TypeError, ValueError, OverflowError):
            continue
        no_speech_prob = getattr(segment, "no_speech_prob", None)
        if no_speech_prob is not None:
            try:
                score *= max(0.0, min(1.0, 1.0 - float(no_speech_prob)))
            except (TypeError, ValueError):
                pass
        confidence_parts.append(max(0.0, min(1.0, score)))

    transcript = " ".join(parts).strip()
    if not confidence_parts:
        return transcript, None
    return transcript, sum(confidence_parts) / len(confidence_parts)


class WhisperRuntime:
    def __init__(
        self,
        *,
        model_name: str,
        language: Optional[str],
        model_dir: Optional[str],
        device: str,
        compute_type: str,
        fallback_device: str,
        fallback_compute_type: str,
        idle_timeout_seconds: int,
        beam_size: int,
        best_of: int,
        temperature: float,
    ) -> None:
        self.model_name = model_name
        self.language = language
        self.model_dir = model_dir
        self.device = device
        self.compute_type = compute_type
        self.fallback_device = fallback_device
        self.fallback_compute_type = fallback_compute_type
        self.idle_timeout_seconds = max(1, int(idle_timeout_seconds))
        self.beam_size = max(1, int(beam_size))
        self.best_of = max(1, int(best_of))
        self.temperature = float(temperature)

        self._model = None
        self._loaded_profile: Optional[Tuple[str, str]] = None
        self._last_used_monotonic = 0.0
        self._primary_failed = False
        self.last_confidence: Optional[float] = None

    @classmethod
    def from_env(cls, *, idle_timeout_seconds: Optional[int] = None) -> "WhisperRuntime":
        configured_idle = int(os.getenv("TELEGRAM_VOICE_WHISPER_IDLE_TIMEOUT_SECONDS", "3600") or "3600")
        beam_size = int(os.getenv("TELEGRAM_VOICE_WHISPER_BEAM_SIZE", "5") or "5")
        best_of = int(os.getenv("TELEGRAM_VOICE_WHISPER_BEST_OF", "5") or "5")
        temperature = float(os.getenv("TELEGRAM_VOICE_WHISPER_TEMPERATURE", "0.0") or "0.0")
        return cls(
            model_name=os.getenv("TELEGRAM_VOICE_WHISPER_MODEL", "small"),
            language=(os.getenv("TELEGRAM_VOICE_WHISPER_LANGUAGE", "en") or None),
            model_dir=(os.getenv("TELEGRAM_VOICE_WHISPER_MODEL_DIR", "") or None),
            device=os.getenv("TELEGRAM_VOICE_WHISPER_DEVICE", "cuda"),
            compute_type=os.getenv("TELEGRAM_VOICE_WHISPER_COMPUTE_TYPE", "float16"),
            fallback_device=os.getenv("TELEGRAM_VOICE_WHISPER_FALLBACK_DEVICE", "cpu"),
            fallback_compute_type=os.getenv("TELEGRAM_VOICE_WHISPER_FALLBACK_COMPUTE_TYPE", "int8"),
            idle_timeout_seconds=idle_timeout_seconds if idle_timeout_seconds is not None else configured_idle,
            beam_size=beam_size,
            best_of=best_of,
            temperature=temperature,
        )

    def _build_model(self, device: str, compute_type: str):
        # Import lazily so module can be imported in test environments without faster-whisper.
        from faster_whisper import WhisperModel  # type: ignore

        kwargs = {
            "device": device,
            "compute_type": compute_type,
        }
        if self.model_dir:
            kwargs["download_root"] = self.model_dir
        return WhisperModel(self.model_name, **kwargs)

    def _drop_model(self) -> None:
        self._model = None
        self._loaded_profile = None
        gc.collect()
        try:
            import torch  # type: ignore

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def unload_if_idle(self, *, now: Optional[float] = None) -> bool:
        if self._model is None:
            return False
        now_value = time.monotonic() if now is None else now
        if now_value - self._last_used_monotonic < self.idle_timeout_seconds:
            return False
        self._drop_model()
        return True

    def _get_model(self, *, device: str, compute_type: str):
        profile = (device, compute_type)
        if self._model is None or self._loaded_profile != profile:
            self._drop_model()
            self._model = self._build_model(device, compute_type)
            self._loaded_profile = profile
        return self._model

    def _transcribe_with_profile(
        self,
        audio_path: str,
        *,
        device: str,
        compute_type: str,
    ) -> Tuple[str, Optional[float]]:
        model = self._get_model(device=device, compute_type=compute_type)
        segments, _info = model.transcribe(
            audio_path,
            language=self.language,
            vad_filter=True,
            beam_size=self.beam_size,
            best_of=self.best_of,
            temperature=self.temperature,
        )
        return collect_transcript_and_confidence(segments)

    def transcribe(self, audio_path: str) -> str:
        if not os.path.isfile(audio_path):
            raise FileNotFoundError(f"voice file not found: {audio_path}")

        self.unload_if_idle()

        primary_device = self.fallback_device if self._primary_failed else self.device
        primary_compute = self.fallback_compute_type if self._primary_failed else self.compute_type

        try:
            transcript_result = self._transcribe_with_profile(
                audio_path,
                device=primary_device,
                compute_type=primary_compute,
            )
        except Exception as exc:
            if self._primary_failed or self.device.lower() != "cuda":
                raise RuntimeError(f"transcription backend error: {exc}") from exc
            self._primary_failed = True
            self._drop_model()
            transcript_result = self._transcribe_with_profile(
                audio_path,
                device=self.fallback_device,
                compute_type=self.fallback_compute_type,
            )

        if isinstance(transcript_result, tuple):
            transcript, confidence = transcript_result
        else:
            transcript = str(transcript_result)
            confidence = None

        transcript = transcript.strip()
        if not transcript:
            raise ValueError("Voice transcription output was empty")

        self._last_used_monotonic = time.monotonic()
        self.last_confidence = confidence
        return transcript


def _read_json_line(conn: socket.socket) -> dict:
    buffer = b""
    while b"\n" not in buffer:
        chunk = conn.recv(4096)
        if not chunk:
            break
        buffer += chunk
    if not buffer:
        raise ValueError("empty request")
    line = buffer.split(b"\n", 1)[0]
    payload = json.loads(line.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("invalid request payload")
    return payload


def _send_json_line(conn: socket.socket, payload: dict) -> None:
    conn.sendall((json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8"))


def _is_socket_stale(socket_path: str) -> bool:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.2)
            probe.connect(socket_path)
            return False
    except OSError:
        return True


def run_server(*, socket_path: str, idle_timeout_seconds: int) -> int:
    runtime = WhisperRuntime.from_env(idle_timeout_seconds=idle_timeout_seconds)

    os.makedirs(os.path.dirname(socket_path) or ".", exist_ok=True)
    if os.path.exists(socket_path) and _is_socket_stale(socket_path):
        os.remove(socket_path)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(socket_path)
    server.listen(8)
    server.settimeout(1.0)

    try:
        while True:
            runtime.unload_if_idle()
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue

            with conn:
                try:
                    request = _read_json_line(conn)
                    action = str(request.get("action", "")).strip().lower()
                    if action == "ping":
                        _send_json_line(conn, {"ok": True, "result": "pong"})
                        continue
                    if action != "transcribe":
                        _send_json_line(conn, {"ok": False, "error": "unknown_action"})
                        continue

                    audio_path = str(request.get("audio_path", "")).strip()
                    transcript = runtime.transcribe(audio_path)
                    _send_json_line(
                        conn,
                        {
                            "ok": True,
                            "text": transcript,
                            "confidence": runtime.last_confidence,
                        },
                    )
                except Exception as exc:
                    _send_json_line(conn, {"ok": False, "error": str(exc)})
    finally:
        server.close()
        if os.path.exists(socket_path):
            os.remove(socket_path)


def _request(socket_path: str, payload: dict, *, timeout_seconds: float) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(timeout_seconds)
        conn.connect(socket_path)
        _send_json_line(conn, payload)

        response = _read_json_line(conn)
        if not isinstance(response.get("ok"), bool):
            raise RuntimeError("invalid response from transcribe service")
        return response


def run_ping(*, socket_path: str, timeout_seconds: float) -> int:
    try:
        response = _request(
            socket_path,
            {"action": "ping"},
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        print(f"ping failed: {exc}", file=sys.stderr)
        return 1

    if response.get("ok"):
        return 0
    print(response.get("error", "ping failed"), file=sys.stderr)
    return 1


def run_client_transcribe(*, socket_path: str, audio_path: str, timeout_seconds: float) -> int:
    try:
        response = _request(
            socket_path,
            {"action": "transcribe", "audio_path": audio_path},
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        print(f"transcription request failed: {exc}", file=sys.stderr)
        return 1

    if not response.get("ok"):
        print(response.get("error", "transcription failed"), file=sys.stderr)
        return 1

    confidence = response.get("confidence")
    if isinstance(confidence, (int, float)):
        print(f"VOICE_CONFIDENCE={float(confidence):.3f}", file=sys.stderr)

    transcript = str(response.get("text", "")).strip()
    if transcript:
        print(transcript)
        return 0

    print("Voice transcription output was empty", file=sys.stderr)
    return 1


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Persistent voice transcription service")
    subparsers = parser.add_subparsers(dest="mode", required=True)

    server = subparsers.add_parser("server", help="run persistent transcribe server")
    server.add_argument(
        "--socket",
        default=os.getenv("TELEGRAM_VOICE_WHISPER_SOCKET_PATH", "/tmp/telegram-voice-whisper.sock"),
    )
    server.add_argument(
        "--idle-timeout",
        type=int,
        default=int(os.getenv("TELEGRAM_VOICE_WHISPER_IDLE_TIMEOUT_SECONDS", "3600") or "3600"),
    )

    ping = subparsers.add_parser("ping", help="check server health")
    ping.add_argument(
        "--socket",
        default=os.getenv("TELEGRAM_VOICE_WHISPER_SOCKET_PATH", "/tmp/telegram-voice-whisper.sock"),
    )
    ping.add_argument("--timeout", type=float, default=2.0)

    client = subparsers.add_parser("client", help="request a transcription")
    client.add_argument(
        "--socket",
        default=os.getenv("TELEGRAM_VOICE_WHISPER_SOCKET_PATH", "/tmp/telegram-voice-whisper.sock"),
    )
    client.add_argument("--audio-path", required=True)
    client.add_argument("--timeout", type=float, default=180.0)

    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.mode == "server":
        return run_server(socket_path=args.socket, idle_timeout_seconds=args.idle_timeout)
    if args.mode == "ping":
        return run_ping(socket_path=args.socket, timeout_seconds=args.timeout)
    if args.mode == "client":
        return run_client_transcribe(
            socket_path=args.socket,
            audio_path=args.audio_path,
            timeout_seconds=args.timeout,
        )
    raise RuntimeError(f"Unknown mode: {args.mode}")


if __name__ == "__main__":
    raise SystemExit(main())
