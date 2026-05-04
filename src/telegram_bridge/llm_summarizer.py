import json
import logging
import time
import urllib.error
import urllib.request
from typing import List, Optional, Sequence, Tuple

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
OLLAMA_MODEL = "gemma3:4b"
OLLAMA_TIMEOUT_SECONDS = 30

_log = logging.getLogger(__name__)


def summarize_via_ollama(
    rows: Sequence,
    *,
    timeout_seconds: int = OLLAMA_TIMEOUT_SECONDS,
) -> Optional[str]:
    if not rows:
        return None

    conversation = _build_conversation_text(rows)
    prompt = (
        "You are a conversation summarizer. Summarize this chat into EXACTLY these sections. "
        "Keep each section brief. Use 'No X captured/detected' for empty sections.\n\n"
        "SECTIONS:\n"
        "Objective: what the user wants or asked for\n"
        "Decisions Made: decisions or agreements reached\n"
        "Current State: what was done or status updates\n"
        "Open Items: pending tasks or unanswered questions\n"
        "User Preferences: any preferences the user expressed\n"
        "Risks/Blockers: errors, failures, or problems\n\n"
        "CONVERSATION:\n"
        f"{conversation}\n\n"
        "SUMMARY:"
    )

    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_predict": 600,
            "temperature": 0.2,
        },
    }).encode("utf-8")

    req = urllib.request.Request(OLLAMA_URL, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        _log.warning("Ollama summarization failed: %s", exc)
        return None

    response = data.get("response", "").strip()
    if not response:
        return None
    return _clean_ollama_response(response)


def _build_conversation_text(rows: Sequence) -> str:
    lines: List[str] = []
    for row in rows:
        # sqlite3.Row uses key access, not attribute access
        try:
            role = str(row["sender_role"] or "user")
            text = str(row["text"] or "")
        except (KeyError, TypeError):
            role = str(getattr(row, "sender_role", "user") or "user")
            text = str(getattr(row, "text", "") or "")
        # Strip bridge-injected context header from user messages
        if role == "user":
            marker = "Current User Message:"
            if marker in text:
                text = text.split(marker, 1)[1].strip()
        # Truncate very long messages
        if len(text) > 400:
            text = text[:397] + "..."
        lines.append(f"[{role}]: {text}")
    return "\n".join(lines)


def _clean_ollama_response(text: str) -> str:
    return " ".join(text.split()).strip()
