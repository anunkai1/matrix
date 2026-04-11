from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from .models import VideoCandidate


def enrich_candidates_with_youtube_metadata(
    candidates: list[VideoCandidate],
    *,
    yt_dlp_bin: str = "yt-dlp",
    timeout_seconds: int = 45,
) -> list[VideoCandidate]:
    if not candidates:
        return candidates
    if shutil.which(yt_dlp_bin) is None:
        return candidates
    return [_enrich_candidate(candidate, yt_dlp_bin=yt_dlp_bin, timeout_seconds=timeout_seconds) for candidate in candidates]


def _enrich_candidate(candidate: VideoCandidate, *, yt_dlp_bin: str, timeout_seconds: int) -> VideoCandidate:
    metadata = _fetch_youtube_metadata(candidate.url, yt_dlp_bin=yt_dlp_bin, timeout_seconds=timeout_seconds)
    if not metadata:
        return candidate
    title = _clean_text(str(metadata.get("title") or "")) or candidate.title
    channel = _clean_text(str(metadata.get("channel") or metadata.get("uploader") or "")) or candidate.channel
    published_at = _published_at_from_metadata(metadata) or candidate.published_at
    duration_text = _duration_text_from_metadata(metadata) or candidate.duration_text
    return replace(candidate, title=title, channel=channel, published_at=published_at, duration_text=duration_text)


def _fetch_youtube_metadata(url: str, *, yt_dlp_bin: str, timeout_seconds: int) -> dict[str, Any]:
    command = [
        yt_dlp_bin,
        "--dump-json",
        "--skip-download",
        "--no-playlist",
        "--no-warnings",
        "--simulate",
        url,
    ]
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout_seconds)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if result.returncode != 0 or not result.stdout.strip():
        return {}
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _published_at_from_metadata(metadata: dict[str, Any]) -> str:
    for key in ("release_timestamp", "timestamp"):
        value = metadata.get(key)
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    upload_date = str(metadata.get("upload_date") or "")
    if len(upload_date) == 8 and upload_date.isdigit():
        return f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"
    return ""


def _duration_text_from_metadata(metadata: dict[str, Any]) -> str:
    duration_string = _clean_text(str(metadata.get("duration_string") or ""))
    if duration_string:
        return duration_string
    duration = metadata.get("duration")
    if isinstance(duration, (int, float)):
        return _format_duration_seconds(int(duration))
    return ""


def _format_duration_seconds(total_seconds: int) -> str:
    if total_seconds <= 0:
        return ""
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _clean_text(value: str) -> str:
    return " ".join(value.split()).strip()
