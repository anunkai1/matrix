import json
import logging
import os
import subprocess
import sys
import tempfile
from typing import Dict, List

from telegram_bridge.runtime_profile import build_repo_root
from telegram_bridge.transport import TELEGRAM_LIMIT

YOUTUBE_ANALYZER_TIMEOUT_SECONDS = 1800
YOUTUBE_INLINE_TRANSCRIPT_LIMIT = 12000

def build_youtube_analyzer_command(youtube_url: str, request_text: str) -> List[str]:
    analyzer_path = os.path.join(build_repo_root(), "ops", "youtube", "analyze_youtube.py")
    return [
        sys.executable,
        analyzer_path,
        "--url",
        youtube_url,
        "--request-text",
        request_text,
    ]

def run_youtube_analyzer(youtube_url: str, request_text: str) -> Dict[str, object]:
    cmd = build_youtube_analyzer_command(youtube_url, request_text)
    logging.info("Running YouTube analyzer command: %s", cmd)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=YOUTUBE_ANALYZER_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode != 0:
        logging.error(
            "YouTube analyzer failed returncode=%s stderr=%r",
            result.returncode,
            (result.stderr or "")[-2000:],
        )
        raise RuntimeError("YouTube analysis failed")
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("YouTube analysis returned invalid JSON") from exc
    if not isinstance(payload, dict) or not payload.get("ok", False):
        raise RuntimeError("YouTube analysis did not complete successfully")
    return payload

def build_youtube_summary_prompt(request_text: str, analysis: Dict[str, object]) -> str:
    title = str(analysis.get("title") or "").strip()
    channel = str(analysis.get("channel") or "").strip()
    duration_seconds = analysis.get("duration_seconds")
    duration_line = ""
    if isinstance(duration_seconds, int) and duration_seconds > 0:
        duration_line = f"Duration seconds: {duration_seconds}\n"
    transcript_source = str(analysis.get("transcript_source") or "unknown").strip()
    transcript_language = str(analysis.get("transcript_language") or "").strip()
    transcript_text = str(analysis.get("transcript_text") or "").strip()
    description = str(analysis.get("description") or "").strip()
    chapters = analysis.get("chapters") if isinstance(analysis.get("chapters"), list) else []
    chapter_lines: List[str] = []
    for item in chapters[:20]:
        if not isinstance(item, dict):
            continue
        start_time = item.get("start_time")
        chapter_title = str(item.get("title") or "").strip()
        if not chapter_title:
            continue
        if isinstance(start_time, (int, float)):
            chapter_lines.append(f"- {int(start_time)}s: {chapter_title}")
        else:
            chapter_lines.append(f"- {chapter_title}")
    chapter_block = "\n".join(chapter_lines)
    return (
        "You are answering a chat message about a YouTube video.\n"
        "Use the transcript below as the primary source of truth for what the video actually says.\n"
        "Do not mention backend tools, yt-dlp, Browser Brain, JSON, or implementation details.\n"
        "If the user only pasted the link, default to a concise content summary.\n"
        "If the transcript comes from automatic captions or transcription, mention that briefly only if it materially affects confidence.\n"
        "Do not invent details that are not supported by the transcript.\n\n"
        f"Original user message:\n{request_text.strip()}\n\n"
        f"Video title: {title}\n"
        f"Channel: {channel}\n"
        f"{duration_line}"
        f"Transcript source: {transcript_source}\n"
        f"Transcript language: {transcript_language or 'unknown'}\n\n"
        f"Description:\n{description or '(no description)'}\n\n"
        f"Chapters:\n{chapter_block or '(no chapters)'}\n\n"
        f"Transcript:\n{transcript_text}\n"
    )

def build_youtube_unavailable_message(analysis: Dict[str, object]) -> str:
    title = str(analysis.get("title") or "").strip()
    channel = str(analysis.get("channel") or "").strip()
    reason = str(analysis.get("transcript_error") or "").strip()
    parts = [
        "I could not obtain captions or a usable transcription for this video, so I cannot provide a reliable content summary."
    ]
    if title:
        parts.append(f"Title: {title}.")
    if channel:
        parts.append(f"Channel: {channel}.")
    if reason:
        parts.append(f"Reason: {reason}.")
    return " ".join(parts)

def build_youtube_transcript_output(
    config,
    analysis: Dict[str, object],
    cleanup_paths: List[str],
) -> str:
    title = str(analysis.get("title") or "YouTube video").strip()
    transcript_source = str(analysis.get("transcript_source") or "unknown").strip()
    transcript_language = str(analysis.get("transcript_language") or "unknown").strip()
    transcript_text = str(analysis.get("transcript_text") or "").strip()
    payload = (
        f"Full transcript for: {title}\n"
        f"Source: {transcript_source}\n"
        f"Language: {transcript_language}\n\n"
        f"{transcript_text}"
    )
    inline_limit = min(getattr(config, "max_output_chars", TELEGRAM_LIMIT), YOUTUBE_INLINE_TRANSCRIPT_LIMIT)
    if len(payload) <= inline_limit:
        return payload

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as handle:
        handle.write(payload)
        transcript_path = handle.name
    cleanup_paths.append(transcript_path)
    return json.dumps(
        {
            "telegram_outbound": {
                "text": f"Full transcript attached for: {title}",
                "media_ref": transcript_path,
                "as_voice": False,
            }
        }
    )
