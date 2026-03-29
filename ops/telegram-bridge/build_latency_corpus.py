#!/usr/bin/env python3
"""Build an anonymized latency benchmark corpus from bridge memory SQLite."""

from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence


DEFAULT_ARCHITECT_DB = "/home/architect/.local/state/telegram-architect-bridge/memory.sqlite3"
DEFAULT_ARCHITECT_CONVERSATION_KEY = "shared:architect:main"
URL_RE = re.compile(r"https?://\S+")
PATH_RE = re.compile(r"(?:(?:/[\w.\-]+)+)")
HEX_RE = re.compile(r"\b0x[a-fA-F0-9]{8,}\b")
LONG_NUMBER_RE = re.compile(r"\b\d{5,}\b")
WHITESPACE_RE = re.compile(r"\s+")
USER_HANDLE_RE = re.compile(r"(?<!\w)@[A-Za-z0-9_]{2,}\b")


@dataclass(frozen=True)
class PromptRecord:
    text: str
    ts: float


def sanitize_prompt(text: str) -> str:
    value = str(text or "")
    value = URL_RE.sub("<URL>", value)
    value = PATH_RE.sub("<PATH>", value)
    value = HEX_RE.sub("<HEX>", value)
    value = LONG_NUMBER_RE.sub("<NUM>", value)
    value = USER_HANDLE_RE.sub("<HANDLE>", value)
    value = WHITESPACE_RE.sub(" ", value).strip()
    return value


def fetch_recent_user_prompts(
    db_path: Path,
    conversation_key: str,
    *,
    since_days: int,
    candidate_limit: int,
    min_chars: int,
    max_chars: int,
) -> List[PromptRecord]:
    if since_days <= 0:
        raise ValueError("since_days must be >= 1")
    if candidate_limit <= 0:
        raise ValueError("candidate_limit must be >= 1")
    threshold_ts = time.time() - (since_days * 24 * 60 * 60)
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            """
            SELECT text, ts
            FROM messages
            WHERE conversation_key = ?
              AND sender_role = 'user'
              AND ts >= ?
            ORDER BY ts DESC
            LIMIT ?
            """,
            (conversation_key, threshold_ts, candidate_limit),
        ).fetchall()
    finally:
        conn.close()

    seen = set()
    prompts: List[PromptRecord] = []
    for raw_text, ts in rows:
        cleaned = sanitize_prompt(raw_text)
        if len(cleaned) < min_chars or len(cleaned) > max_chars:
            continue
        dedupe_key = cleaned.casefold()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        prompts.append(PromptRecord(text=cleaned, ts=float(ts)))
    return prompts


def _bucket_index(text: str) -> int:
    length = len(text)
    if length <= 80:
        return 0
    if length <= 220:
        return 1
    return 2


def select_representative_prompts(prompts: Sequence[PromptRecord], count: int) -> List[PromptRecord]:
    if count <= 0:
        raise ValueError("count must be >= 1")
    buckets = {0: [], 1: [], 2: []}
    for prompt in prompts:
        buckets[_bucket_index(prompt.text)].append(prompt)

    ordered: List[PromptRecord] = []
    target = min(count, len(prompts))
    while len(ordered) < target:
        progressed = False
        for bucket_index in (0, 1, 2):
            bucket = buckets[bucket_index]
            if not bucket:
                continue
            ordered.append(bucket.pop(0))
            progressed = True
            if len(ordered) >= target:
                break
        if not progressed:
            break
    return ordered


def build_corpus_payload(prompts: Iterable[PromptRecord], *, engine_delay_ms: float) -> List[dict]:
    payload = []
    for index, prompt in enumerate(prompts, start=1):
        reply = f"Benchmark reply {index:02d}."
        payload.append(
            {
                "name": f"architect_case_{index:02d}",
                "prompt": prompt.text,
                "expected_reply": reply,
                "engine_output": reply,
                "engine_delay_ms": engine_delay_ms,
            }
        )
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build an anonymized latency benchmark corpus from bridge memory."
    )
    parser.add_argument(
        "--db",
        default=DEFAULT_ARCHITECT_DB,
        help=f"SQLite memory DB path. Default: {DEFAULT_ARCHITECT_DB}",
    )
    parser.add_argument(
        "--conversation-key",
        default=DEFAULT_ARCHITECT_CONVERSATION_KEY,
        help=f"Conversation key to sample. Default: {DEFAULT_ARCHITECT_CONVERSATION_KEY}",
    )
    parser.add_argument("--output", required=True, help="Output JSON corpus path.")
    parser.add_argument("--count", type=int, default=24, help="Final corpus size. Default: 24.")
    parser.add_argument(
        "--candidate-limit",
        type=int,
        default=250,
        help="How many recent prompts to inspect before selection. Default: 250.",
    )
    parser.add_argument(
        "--since-days",
        type=int,
        default=30,
        help="Only use prompts from this many recent days. Default: 30.",
    )
    parser.add_argument("--min-chars", type=int, default=8, help="Minimum prompt length.")
    parser.add_argument("--max-chars", type=int, default=600, help="Maximum prompt length.")
    parser.add_argument(
        "--engine-delay-ms",
        type=float,
        default=12.0,
        help="Mock engine delay to assign to generated cases. Default: 12.0",
    )
    return parser


def main(argv: List[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db_path = Path(args.db).resolve()
    output_path = Path(args.output).resolve()
    prompts = fetch_recent_user_prompts(
        db_path,
        args.conversation_key,
        since_days=args.since_days,
        candidate_limit=args.candidate_limit,
        min_chars=args.min_chars,
        max_chars=args.max_chars,
    )
    selected = select_representative_prompts(prompts, args.count)
    if not selected:
        raise SystemExit("No prompts matched the requested filters.")
    payload = build_corpus_payload(selected, engine_delay_ms=args.engine_delay_ms)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    print(
        "\n".join(
            [
                f"db={db_path}",
                f"conversation_key={args.conversation_key}",
                f"candidate_prompts={len(prompts)}",
                f"selected_prompts={len(selected)}",
                f"output={output_path}",
            ]
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
