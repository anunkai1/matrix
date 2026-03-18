#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import html
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple


ROOT = Path(__file__).resolve().parents[2]
YTDLP_BIN = os.getenv("YOUTUBE_ANALYZER_YTDLP_BIN", "yt-dlp").strip() or "yt-dlp"
TRANSCRIBE_CMD_TEMPLATE = os.getenv(
    "TELEGRAM_VOICE_TRANSCRIBE_CMD",
    f"{ROOT}/ops/telegram-voice/transcribe_voice.sh {{file}}",
).strip()
TRANSCRIBE_TIMEOUT_SECONDS = int(os.getenv("TELEGRAM_VOICE_TRANSCRIBE_TIMEOUT_SECONDS", "180"))
TIMESTAMP_RE = re.compile(
    r"^\s*(?:\d+:)?\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?\s*-->\s*(?:\d+:)?\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?"
)
TAG_RE = re.compile(r"<[^>]+>")
TRANSCRIPT_MODE_RE = re.compile(
    r"\b(transcript|full transcript|subtitles|captions|transcribe|транскрипт|субтитр|субтитры|стенограмма|полный текст|расшифровк[аи])\b",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze a YouTube link for transcript-first chat handling")
    parser.add_argument("--url", required=True)
    parser.add_argument("--request-text", required=True)
    return parser.parse_args()


def normalize_youtube_url(url: str) -> str:
    return url.strip()


def infer_request_mode(text: str) -> str:
    return "transcript" if TRANSCRIPT_MODE_RE.search(text or "") else "summary"


def run_command(cmd: List[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def load_metadata(url: str) -> Dict[str, object]:
    result = run_command(
        [YTDLP_BIN, "--dump-single-json", "--no-warnings", "--skip-download", url],
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "").strip() or "yt-dlp metadata lookup failed")
    payload = json.loads(result.stdout or "{}")
    if not isinstance(payload, dict):
        raise RuntimeError("yt-dlp metadata payload was not a JSON object")
    return payload


def append_unique(items: List[str], value: str) -> None:
    cleaned = value.strip()
    if cleaned and cleaned not in items:
        items.append(cleaned)


def choose_subtitle_candidates(metadata: Dict[str, object]) -> List[Tuple[str, str]]:
    subtitles = metadata.get("subtitles") if isinstance(metadata.get("subtitles"), dict) else {}
    automatic = metadata.get("automatic_captions") if isinstance(metadata.get("automatic_captions"), dict) else {}
    ordered: List[Tuple[str, str]] = []
    seen: set[Tuple[str, str]] = set()

    preferred_languages: List[str] = []
    for candidate in (
        str(metadata.get("language") or "").strip(),
        "en",
        "en-US",
        "en-GB",
        "ru",
        "ru-RU",
    ):
        append_unique(preferred_languages, candidate)

    for language in preferred_languages:
        if language in subtitles and ("manual", language) not in seen:
            ordered.append(("manual", language))
            seen.add(("manual", language))
        if language in automatic and ("auto", language) not in seen:
            ordered.append(("auto", language))
            seen.add(("auto", language))

    for language in subtitles.keys():
        if ("manual", language) not in seen:
            ordered.append(("manual", language))
            seen.add(("manual", language))
    for language in automatic.keys():
        if ("auto", language) not in seen:
            ordered.append(("auto", language))
            seen.add(("auto", language))

    return ordered


def find_subtitle_file(tmpdir: str) -> Optional[str]:
    candidates = sorted(
        glob.glob(os.path.join(tmpdir, "*.vtt"))
        + glob.glob(os.path.join(tmpdir, "*.srv3"))
        + glob.glob(os.path.join(tmpdir, "*.srt"))
        + glob.glob(os.path.join(tmpdir, "*.ttml"))
    )
    return candidates[0] if candidates else None


def clean_subtitle_text(raw_text: str) -> str:
    lines: List[str] = []
    previous = ""
    for raw_line in (raw_text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        upper = line.upper()
        if upper == "WEBVTT" or upper.startswith("NOTE") or upper.startswith("STYLE"):
            continue
        if TIMESTAMP_RE.match(line):
            continue
        if line.isdigit():
            continue
        line = html.unescape(TAG_RE.sub("", line)).strip()
        if not line or line == previous:
            continue
        lines.append(line)
        previous = line
    return "\n".join(lines)


def try_download_subtitles(url: str, metadata: Dict[str, object]) -> Tuple[str, str, str]:
    candidates = choose_subtitle_candidates(metadata)
    for source_kind, language in candidates:
        with tempfile.TemporaryDirectory(prefix="youtube-subs-") as tmpdir:
            base_cmd = [
                YTDLP_BIN,
                "--no-warnings",
                "--skip-download",
                "--sub-langs",
                language,
                "--sub-format",
                "vtt",
                "-o",
                os.path.join(tmpdir, "%(id)s.%(ext)s"),
            ]
            if source_kind == "manual":
                cmd = base_cmd[:]
                cmd.insert(3, "--write-subs")
            else:
                cmd = base_cmd[:]
                cmd.insert(3, "--write-auto-subs")
            cmd.append(url)
            result = run_command(cmd, timeout=180)
            if result.returncode != 0:
                continue
            subtitle_path = find_subtitle_file(tmpdir)
            if subtitle_path is None:
                continue
            text = clean_subtitle_text(Path(subtitle_path).read_text(encoding="utf-8", errors="ignore"))
            if text:
                source_label = "subtitles" if source_kind == "manual" else "automatic_captions"
                return text, source_label, language
    return "", "", ""


def find_downloaded_audio(tmpdir: str) -> Optional[str]:
    candidates = [
        path
        for path in glob.glob(os.path.join(tmpdir, "*"))
        if os.path.isfile(path) and not path.endswith((".part", ".ytdl", ".json"))
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda path: os.path.getsize(path), reverse=True)
    return candidates[0]


def download_audio(url: str) -> str:
    with tempfile.TemporaryDirectory(prefix="youtube-audio-") as tmpdir:
        errors: List[str] = []
        commands = [
            [
                YTDLP_BIN,
                "--no-warnings",
                "--no-playlist",
                "-f",
                "bestaudio/best",
                "-o",
                os.path.join(tmpdir, "%(id)s.%(ext)s"),
                url,
            ],
            [
                YTDLP_BIN,
                "--no-warnings",
                "--no-playlist",
                "-o",
                os.path.join(tmpdir, "%(id)s.%(ext)s"),
                url,
            ],
        ]
        for cmd in commands:
            result = run_command(cmd, timeout=600)
            if result.returncode != 0:
                errors.append((result.stderr or "").strip() or "media download failed")
                continue
            audio_path = find_downloaded_audio(tmpdir)
            if audio_path is None:
                errors.append("media download did not produce a file")
                continue
            persist_dir = tempfile.mkdtemp(prefix="youtube-audio-persist-")
            persisted_path = os.path.join(persist_dir, os.path.basename(audio_path))
            os.replace(audio_path, persisted_path)
            return persisted_path
        raise RuntimeError(errors[-1] if errors else "audio download failed")


def build_transcribe_command(audio_path: str) -> List[str]:
    rendered = TRANSCRIBE_CMD_TEMPLATE.replace("{file}", audio_path)
    cmd = shlex.split(rendered)
    if not cmd:
        raise RuntimeError("voice transcription command is not configured")
    return cmd


def transcribe_audio(audio_path: str) -> str:
    cmd = build_transcribe_command(audio_path)
    result = run_command(cmd, timeout=TRANSCRIBE_TIMEOUT_SECONDS)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "").strip() or "local transcription failed")
    transcript = (result.stdout or "").strip()
    if not transcript:
        raise RuntimeError("local transcription returned empty text")
    return transcript


def build_metadata_fallback_note(metadata: Dict[str, object]) -> str:
    title = str(metadata.get("title") or "").strip()
    channel = str(metadata.get("channel") or metadata.get("uploader") or "").strip()
    description = str(metadata.get("description") or "").strip()
    parts: List[str] = []
    if title:
        parts.append(f"Title: {title}.")
    if channel:
        parts.append(f"Channel: {channel}.")
    if description:
        parts.append(f"Description: {description[:400].strip()}")
    return " ".join(parts)


def main() -> int:
    args = parse_args()
    url = normalize_youtube_url(args.url)
    request_text = args.request_text.strip()
    metadata = load_metadata(url)
    transcript_text = ""
    transcript_source = ""
    transcript_language = ""
    transcript_error = ""
    audio_path: Optional[str] = None
    try:
        transcript_text, transcript_source, transcript_language = try_download_subtitles(url, metadata)
        if not transcript_text:
            audio_path = download_audio(url)
            transcript_text = transcribe_audio(audio_path)
            transcript_source = "transcription"
            transcript_language = str(metadata.get("language") or "").strip() or "unknown"
    except Exception as exc:
        transcript_error = str(exc).strip()
    finally:
        if audio_path:
            try:
                os.remove(audio_path)
                audio_dir = os.path.dirname(audio_path)
                if audio_dir:
                    os.rmdir(audio_dir)
            except OSError:
                pass

    payload = {
        "ok": True,
        "request_mode": infer_request_mode(request_text),
        "url": url,
        "title": str(metadata.get("title") or "").strip(),
        "channel": str(metadata.get("channel") or metadata.get("uploader") or "").strip(),
        "duration_seconds": metadata.get("duration"),
        "upload_date": str(metadata.get("upload_date") or "").strip(),
        "description": str(metadata.get("description") or "").strip(),
        "chapters": metadata.get("chapters") if isinstance(metadata.get("chapters"), list) else [],
        "transcript_source": transcript_source or "none",
        "transcript_language": transcript_language or "",
        "transcript_text": transcript_text.strip(),
        "transcript_error": transcript_error,
        "metadata_fallback_note": build_metadata_fallback_note(metadata),
    }
    json.dump(payload, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
