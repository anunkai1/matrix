#!/usr/bin/env python3
"""Send a daily Russian morning life hack to a WhatsApp chat via local bridge API."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]


PROMPT_HISTORY_LIMIT = 240
DEFAULT_GENERATION_ATTEMPTS = 8
DEFAULT_CODEX_TIMEOUT_SECONDS = 180
DEFAULT_CODEX_REASONING_EFFORT = "medium"
RUSSIAN_STOP_WORDS = {
    "а",
    "без",
    "бы",
    "в",
    "во",
    "вот",
    "вы",
    "где",
    "да",
    "для",
    "до",
    "его",
    "ее",
    "если",
    "же",
    "за",
    "и",
    "из",
    "или",
    "их",
    "к",
    "как",
    "когда",
    "кто",
    "ли",
    "на",
    "над",
    "не",
    "но",
    "ну",
    "о",
    "об",
    "от",
    "по",
    "под",
    "при",
    "про",
    "с",
    "со",
    "так",
    "там",
    "то",
    "тот",
    "у",
    "уже",
    "чем",
    "что",
    "чтобы",
    "это",
    "этот",
}
RUSSIAN_TOKEN_ENDINGS = (
    "иями",
    "ями",
    "ами",
    "иях",
    "иях",
    "его",
    "ого",
    "ему",
    "ому",
    "ыми",
    "ими",
    "ее",
    "ие",
    "ые",
    "ое",
    "ей",
    "ий",
    "ый",
    "ой",
    "ем",
    "им",
    "ом",
    "ам",
    "ям",
    "ах",
    "ях",
    "ию",
    "ью",
    "ия",
    "ья",
    "иям",
    "ием",
    "иях",
    "а",
    "я",
    "ы",
    "и",
    "е",
    "у",
    "ю",
    "о",
)


@dataclass(frozen=True)
class GeneratedLifeHack:
    hack_text: str
    idea_key: str
    idea_summary: str


@dataclass(frozen=True)
class SentLifeHack:
    message_text: str
    hack_text: str
    idea_key: str
    idea_summary: str


@dataclass(frozen=True)
class HistoryEntry:
    id: int
    sent_at: str
    message_text: str
    hack_text: str
    idea_key: str
    idea_summary: str
    message_probe: str
    hack_probe: str
    idea_key_probe: str
    idea_summary_probe: str


@dataclass(frozen=True)
class SimilarityMatch:
    entry: HistoryEntry
    reason: str
    score: float


def now_in_tz(tz_name: str) -> datetime:
    if ZoneInfo is not None:
        try:
            return datetime.now(ZoneInfo(tz_name))
        except Exception:
            pass
    return datetime.now()


def build_daily_message(group_name: str, hack_text: str) -> str:
    return f"Доброе утро, {group_name}! ☀️\n\nДаю справку: {hack_text}"


def build_payload(chat_id: Optional[str], chat_jid: Optional[str], text: str) -> dict[str, str]:
    payload: dict[str, str] = {"text": text}
    if chat_jid:
        payload["chat_jid"] = chat_jid
    elif chat_id:
        payload["chat_id"] = chat_id
    else:
        raise ValueError("chat destination is required")
    return payload


def send_message(api_base: str, auth_token: str, payload: dict[str, str]) -> dict[str, object]:
    endpoint = f"{api_base.rstrip('/')}/messages"
    request = Request(endpoint, data=json.dumps(payload).encode("utf-8"), method="POST")
    request.add_header("Content-Type", "application/json")
    if auth_token:
        request.add_header("Authorization", f"Bearer {auth_token}")
    try:
        with urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")
        except Exception:
            detail = ""
        raise RuntimeError(f"HTTP {exc.code}: {detail or exc.reason}") from exc
    except URLError as exc:
        raise RuntimeError(f"URL error: {exc}") from exc

    if not body:
        return {"ok": True}
    decoded = json.loads(body)
    if not isinstance(decoded, dict):
        raise RuntimeError("unexpected JSON response type")
    if decoded.get("ok") is False:
        raise RuntimeError(str(decoded.get("description") or "unknown bridge error"))
    return decoded


def collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_probe(text: str) -> str:
    lowered = (text or "").lower().replace("ё", "е")
    lowered = lowered.replace("☀️", " ")
    lowered = re.sub(r"[^0-9a-zа-я]+", " ", lowered)
    return collapse_whitespace(lowered)


def stem_token(token: str) -> str:
    token = normalize_probe(token)
    for ending in RUSSIAN_TOKEN_ENDINGS:
        if len(token) <= len(ending) + 2:
            continue
        if token.endswith(ending):
            return token[: -len(ending)]
    return token


def probe_tokens(text: str) -> set[str]:
    tokens = []
    for token in normalize_probe(text).split():
        if len(token) <= 2:
            continue
        if token in RUSSIAN_STOP_WORDS:
            continue
        stemmed = stem_token(token)
        if len(stemmed) <= 2:
            continue
        tokens.append(stemmed)
    return set(tokens)


def jaccard_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def overlap_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def sequence_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def best_similarity(left: str, right: str) -> float:
    left_probe = normalize_probe(left)
    right_probe = normalize_probe(right)
    return max(
        sequence_similarity(left_probe, right_probe),
        jaccard_similarity(probe_tokens(left_probe), probe_tokens(right_probe)),
        overlap_similarity(probe_tokens(left_probe), probe_tokens(right_probe)),
    )


def state_dir_path() -> Path:
    override = os.getenv("WA_DAILY_UPLIFT_STATE_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".local" / "state" / "govorun-whatsapp-daily-uplift"


def history_db_path() -> Path:
    override = os.getenv("WA_DAILY_UPLIFT_HISTORY_DB_PATH", "").strip()
    if override:
        return Path(override).expanduser()
    return state_dir_path() / "history.sqlite3"


class HistoryStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sent_life_hacks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sent_at TEXT NOT NULL,
                    message_text TEXT NOT NULL,
                    hack_text TEXT NOT NULL,
                    idea_key TEXT NOT NULL,
                    idea_summary TEXT NOT NULL,
                    message_probe TEXT NOT NULL,
                    hack_probe TEXT NOT NULL,
                    idea_key_probe TEXT NOT NULL,
                    idea_summary_probe TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_sent_life_hacks_message_probe
                ON sent_life_hacks(message_probe)
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_sent_life_hacks_idea_key_probe
                ON sent_life_hacks(idea_key_probe)
                """
            )
            conn.commit()

    def load_entries(self) -> list[HistoryEntry]:
        self.ensure_schema()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    id,
                    sent_at,
                    message_text,
                    hack_text,
                    idea_key,
                    idea_summary,
                    message_probe,
                    hack_probe,
                    idea_key_probe,
                    idea_summary_probe
                FROM sent_life_hacks
                ORDER BY id ASC
                """
            ).fetchall()
        return [
            HistoryEntry(
                id=int(row["id"]),
                sent_at=str(row["sent_at"]),
                message_text=str(row["message_text"]),
                hack_text=str(row["hack_text"]),
                idea_key=str(row["idea_key"]),
                idea_summary=str(row["idea_summary"]),
                message_probe=str(row["message_probe"]),
                hack_probe=str(row["hack_probe"]),
                idea_key_probe=str(row["idea_key_probe"]),
                idea_summary_probe=str(row["idea_summary_probe"]),
            )
            for row in rows
        ]

    def insert_sent_message(self, sent_at: datetime, message: SentLifeHack) -> None:
        self.ensure_schema()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sent_life_hacks (
                    sent_at,
                    message_text,
                    hack_text,
                    idea_key,
                    idea_summary,
                    message_probe,
                    hack_probe,
                    idea_key_probe,
                    idea_summary_probe
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sent_at.isoformat(),
                    message.message_text,
                    message.hack_text,
                    message.idea_key,
                    message.idea_summary,
                    normalize_probe(message.message_text),
                    normalize_probe(message.hack_text),
                    normalize_probe(message.idea_key),
                    normalize_probe(message.idea_summary),
                ),
            )
            conn.commit()


def build_generation_prompt(
    group_name: str,
    history_entries: list[HistoryEntry],
    rejected: list[SimilarityMatch],
) -> str:
    history_slice = history_entries[-PROMPT_HISTORY_LIMIT:]
    if history_slice:
        history_text = "\n".join(
            f"- {entry.idea_key} | {entry.idea_summary}" for entry in history_slice
        )
    else:
        history_text = "- none yet"

    rejection_text = ""
    if rejected:
        rejection_lines = [
            f"- rejected as too similar ({match.reason}, score={match.score:.3f}): "
            f"{match.entry.idea_key} | {match.entry.idea_summary}"
            for match in rejected[-5:]
        ]
        rejection_text = (
            "\nRejected earlier in this run because they overlapped with prior ideas:\n"
            + "\n".join(rejection_lines)
        )

    return f"""
Generate one original Russian WhatsApp daily morning message for the group "{group_name}".

Return exactly one JSON object and nothing else. No markdown, no code fences, no commentary.
Required JSON keys:
- hack_text
- idea_key
- idea_summary

Hard requirements:
- Topic: only one practical life hack. Prefer life hacks.
- Never output trivia, history, culture, animals, science, space, wholesome stories, quotes, motivation, or general fun facts.
- The underlying life-hack idea must be genuinely different from every prior idea listed below.
- Do not paraphrase, modernize, shorten, or slightly vary a previous idea. Pick a different idea entirely.
- Keep it warm, light, positive, and useful.
- Use simple Russian.
- hack_text must be 1-2 short sentences and must not include the greeting or the words "Доброе утро" or "Даю справку".
- idea_key must be a short canonical description of the exact trick, 4-10 words, plain and specific.
- idea_summary must be one short sentence that restates the same trick canonically for duplicate detection.
- Avoid politics, war, tragedy, death, illness, dangerous advice, chemical/medical advice, money anxiety, and work-pressure topics.
- If there is any overlap with a prior idea, choose a different life hack.

The caller will wrap your hack like this:
Доброе утро, {group_name}! ☀️

Даю справку: <hack_text>

Prior life-hack ideas that must never be repeated or closely reused:
{history_text}{rejection_text}
""".strip()


def extract_json_object(raw_text: str) -> dict[str, object]:
    text = (raw_text or "").strip()
    if not text:
        raise RuntimeError("generator returned empty output")

    decoder = json.JSONDecoder()
    for start_index, char in enumerate(text):
        if char != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(text[start_index:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise RuntimeError(f"generator did not return a JSON object: {text[:400]}")


def clean_generated_field(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise RuntimeError(f"generator field {field_name} must be a string")
    cleaned = collapse_whitespace(value)
    if not cleaned:
        raise RuntimeError(f"generator field {field_name} is empty")
    return cleaned


def parse_generated_life_hack(raw_text: str) -> GeneratedLifeHack:
    payload = extract_json_object(raw_text)
    hack_text = clean_generated_field(payload.get("hack_text"), "hack_text")
    idea_key = clean_generated_field(payload.get("idea_key"), "idea_key")
    idea_summary = clean_generated_field(payload.get("idea_summary"), "idea_summary")

    forbidden_fragments = ("доброе утро", "даю справку")
    lowered_hack = hack_text.lower()
    if any(fragment in lowered_hack for fragment in forbidden_fragments):
        raise RuntimeError("hack_text must not include greeting wrapper text")

    return GeneratedLifeHack(
        hack_text=hack_text,
        idea_key=idea_key,
        idea_summary=idea_summary,
    )


def similarity_against_history(candidate: GeneratedLifeHack, entry: HistoryEntry) -> Optional[SimilarityMatch]:
    key_score = best_similarity(candidate.idea_key, entry.idea_key)
    if key_score >= 0.66:
        return SimilarityMatch(entry=entry, reason="idea_key", score=key_score)

    summary_score = best_similarity(candidate.idea_summary, entry.idea_summary)
    if summary_score >= 0.70:
        return SimilarityMatch(entry=entry, reason="idea_summary", score=summary_score)

    hack_score = best_similarity(candidate.hack_text, entry.hack_text)
    if hack_score >= 0.82:
        return SimilarityMatch(entry=entry, reason="hack_text", score=hack_score)

    candidate_tokens = probe_tokens(candidate.idea_summary) | probe_tokens(candidate.idea_key)
    entry_tokens = probe_tokens(entry.idea_summary) | probe_tokens(entry.idea_key)
    overlap_score = overlap_similarity(candidate_tokens, entry_tokens)
    if overlap_score >= 0.75 and len(candidate_tokens & entry_tokens) >= 3:
        return SimilarityMatch(entry=entry, reason="token_overlap", score=overlap_score)

    return None


def find_similarity_match(
    candidate: GeneratedLifeHack,
    history_entries: list[HistoryEntry],
) -> Optional[SimilarityMatch]:
    best_match: Optional[SimilarityMatch] = None
    for entry in history_entries:
        match = similarity_against_history(candidate, entry)
        if match is None:
            continue
        if best_match is None or match.score > best_match.score:
            best_match = match
    return best_match


def codex_binary() -> str:
    return os.getenv("WA_DAILY_UPLIFT_CODEX_BIN", os.getenv("CODEX_BIN", "codex")).strip() or "codex"


def codex_workdir() -> str:
    override = os.getenv("WA_DAILY_UPLIFT_CODEX_WORKDIR", "").strip()
    if override:
        return override
    runtime_root = os.getenv("TELEGRAM_RUNTIME_ROOT", "").strip()
    if runtime_root:
        return runtime_root
    return os.getcwd()


def codex_model() -> str:
    return os.getenv("WA_DAILY_UPLIFT_CODEX_MODEL", "").strip()


def codex_reasoning_effort() -> str:
    return (
        os.getenv("WA_DAILY_UPLIFT_CODEX_REASONING_EFFORT", DEFAULT_CODEX_REASONING_EFFORT).strip()
        or DEFAULT_CODEX_REASONING_EFFORT
    )


def codex_timeout_seconds() -> int:
    raw_value = os.getenv("WA_DAILY_UPLIFT_CODEX_TIMEOUT_SECONDS", str(DEFAULT_CODEX_TIMEOUT_SECONDS)).strip()
    try:
        return max(30, int(raw_value))
    except ValueError:
        return DEFAULT_CODEX_TIMEOUT_SECONDS


def generation_attempt_limit() -> int:
    raw_value = os.getenv("WA_DAILY_UPLIFT_GENERATION_ATTEMPTS", str(DEFAULT_GENERATION_ATTEMPTS)).strip()
    try:
        return max(1, int(raw_value))
    except ValueError:
        return DEFAULT_GENERATION_ATTEMPTS


def run_codex_generation(prompt: str) -> str:
    code_bin = codex_binary()
    output_dir = state_dir_path() / "tmp"
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix="daily-uplift-",
        suffix=".txt",
        dir=str(output_dir),
        delete=False,
    ) as temp_file:
        output_file = Path(temp_file.name)

    cmd = [
        code_bin,
        "exec",
        "--skip-git-repo-check",
        "--dangerously-bypass-approvals-and-sandbox",
        "--color",
        "never",
        "--output-last-message",
        str(output_file),
    ]
    model = codex_model()
    if model:
        cmd.extend(["--model", model])
    reasoning_effort = codex_reasoning_effort()
    if reasoning_effort:
        cmd.extend(["-c", f'model_reasoning_effort="{reasoning_effort}"'])
    cmd.append("-")

    env = dict(os.environ)
    env["HOME"] = env.get("HOME", str(Path.home()))

    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            text=True,
            capture_output=True,
            timeout=codex_timeout_seconds(),
            cwd=codex_workdir(),
            env=env,
            check=False,
        )
    finally:
        pass

    reply = ""
    try:
        if output_file.exists():
            reply = output_file.read_text(encoding="utf-8").strip()
    finally:
        output_file.unlink(missing_ok=True)

    if result.returncode != 0:
        detail = collapse_whitespace(result.stderr or result.stdout or reply)
        raise RuntimeError(
            f"codex generation failed with exit code {result.returncode}: {detail[:500]}"
        )
    if not reply:
        reply = (result.stdout or "").strip()
    if not reply:
        raise RuntimeError("codex generation returned no reply")
    return reply


def generate_unique_life_hack(
    group_name: str,
    history_entries: list[HistoryEntry],
) -> GeneratedLifeHack:
    rejected: list[SimilarityMatch] = []
    last_error: Optional[str] = None

    for _ in range(generation_attempt_limit()):
        prompt = build_generation_prompt(group_name, history_entries, rejected)
        try:
            candidate = parse_generated_life_hack(run_codex_generation(prompt))
        except Exception as exc:
            last_error = str(exc)
            continue

        match = find_similarity_match(candidate, history_entries)
        if match is not None:
            rejected.append(match)
            last_error = (
                f"candidate overlapped with prior idea ({match.reason}, score={match.score:.3f}): "
                f"{match.entry.idea_key}"
            )
            continue

        return candidate

    raise RuntimeError(last_error or "failed to generate a unique life hack")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send daily uplifting WhatsApp life hack (RU).")
    parser.add_argument("--chat-id", default=os.getenv("WA_DAILY_UPLIFT_CHAT_ID", "").strip())
    parser.add_argument("--chat-jid", default=os.getenv("WA_DAILY_UPLIFT_CHAT_JID", "").strip())
    parser.add_argument("--test", action="store_true", help="Wrap payload as 1:1 preview text.")
    parser.add_argument("--dry-run", action="store_true", help="Print message without sending.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api_base = os.getenv("WA_DAILY_UPLIFT_API_BASE", "http://127.0.0.1:8787").strip()
    auth_token = os.getenv("WA_DAILY_UPLIFT_AUTH_TOKEN", "").strip()
    tz_name = os.getenv("WA_DAILY_UPLIFT_TZ", "Australia/Brisbane").strip()
    group_name = os.getenv("WA_DAILY_UPLIFT_GROUP_NAME", "Путиловы").strip() or "Путиловы"

    now_dt = now_in_tz(tz_name)
    history_store = HistoryStore(history_db_path())
    history_entries = history_store.load_entries()
    life_hack = generate_unique_life_hack(group_name, history_entries)
    daily_message = build_daily_message(group_name, life_hack.hack_text)

    text = daily_message
    if args.test:
        text = (
            "Тест 1:1. Так будет выглядеть ежедневное сообщение в 09:00 для группы:\n\n"
            f"{daily_message}"
        )

    if args.dry_run:
        print(text)
        return 0

    payload = build_payload(args.chat_id or None, args.chat_jid or None, text)
    response = send_message(api_base, auth_token, payload)
    if not args.test:
        history_store.insert_sent_message(
            now_dt,
            SentLifeHack(
                message_text=daily_message,
                hack_text=life_hack.hack_text,
                idea_key=life_hack.idea_key,
                idea_summary=life_hack.idea_summary,
            ),
        )
    print(json.dumps({"sent": True, "payload": payload, "response": response}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"send_daily_uplift failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
