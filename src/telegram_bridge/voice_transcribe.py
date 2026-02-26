#!/usr/bin/env python3
"""Transcribe a voice file and print transcript text to stdout."""

from __future__ import annotations

import os
import sys
from typing import Iterable

from faster_whisper import WhisperModel


def _collect_transcript(segments: Iterable[object]) -> str:
    parts: list[str] = []
    for segment in segments:
        text = (getattr(segment, "text", "") or "").strip()
        if text:
            parts.append(text)
    return " ".join(parts).strip()


def _run_transcription(
    model_name: str,
    audio_path: str,
    language: str | None,
    *,
    device: str,
    compute_type: str,
    model_dir: str | None,
) -> str:
    model_kwargs = {
        "device": device,
        "compute_type": compute_type,
    }
    if model_dir:
        model_kwargs["download_root"] = model_dir

    model = WhisperModel(model_name, **model_kwargs)
    segments, _info = model.transcribe(audio_path, language=language, vad_filter=True)
    return _collect_transcript(segments)


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: voice_transcribe.py <voice_file_path>", file=sys.stderr)
        return 2

    audio_path = sys.argv[1]
    if not os.path.isfile(audio_path):
        print(f"voice file not found: {audio_path}", file=sys.stderr)
        return 2

    model_name = os.getenv("TELEGRAM_VOICE_WHISPER_MODEL", "base")
    device = os.getenv("TELEGRAM_VOICE_WHISPER_DEVICE", "cpu")
    compute_type = os.getenv("TELEGRAM_VOICE_WHISPER_COMPUTE_TYPE", "int8")
    language = os.getenv("TELEGRAM_VOICE_WHISPER_LANGUAGE", "") or None
    model_dir = os.getenv("TELEGRAM_VOICE_WHISPER_MODEL_DIR", "") or None

    try:
        transcript = _run_transcription(
            model_name,
            audio_path,
            language,
            device=device,
            compute_type=compute_type,
            model_dir=model_dir,
        )
    except Exception as exc:  # pragma: no cover - runtime integration path
        # If CUDA is unavailable at runtime, retry on CPU so voice flow keeps working.
        if device.lower() != "cuda":
            print(f"transcription backend error: {exc}", file=sys.stderr)
            return 1
        fallback_device = os.getenv("TELEGRAM_VOICE_WHISPER_FALLBACK_DEVICE", "cpu")
        fallback_compute_type = os.getenv(
            "TELEGRAM_VOICE_WHISPER_FALLBACK_COMPUTE_TYPE",
            "int8",
        )
        print(
            f"CUDA transcription failed ({exc}); retrying on {fallback_device}/{fallback_compute_type}.",
            file=sys.stderr,
        )
        try:
            transcript = _run_transcription(
                model_name,
                audio_path,
                language,
                device=fallback_device,
                compute_type=fallback_compute_type,
                model_dir=model_dir,
            )
        except Exception as fallback_exc:  # pragma: no cover - runtime integration path
            print(f"transcription backend error: {fallback_exc}", file=sys.stderr)
            return 1

    if transcript:
        print(transcript)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
