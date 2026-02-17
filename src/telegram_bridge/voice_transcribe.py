#!/usr/bin/env python3
"""Transcribe a voice file and print transcript text to stdout."""

from __future__ import annotations

import os
import sys

from faster_whisper import WhisperModel


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

    model_kwargs = {
        "device": device,
        "compute_type": compute_type,
    }
    if model_dir:
        model_kwargs["download_root"] = model_dir

    try:
        model = WhisperModel(model_name, **model_kwargs)
        segments, _info = model.transcribe(audio_path, language=language, vad_filter=True)
    except Exception as exc:  # pragma: no cover - runtime integration path
        print(f"transcription backend error: {exc}", file=sys.stderr)
        return 1

    parts: list[str] = []
    for segment in segments:
        text = (segment.text or "").strip()
        if text:
            parts.append(text)

    transcript = " ".join(parts).strip()
    if transcript:
        print(transcript)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
