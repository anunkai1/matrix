#!/usr/bin/env python3
"""Merge per-chat live session keys into the configured shared archive key."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src" / "telegram_bridge"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from memory_engine import MemoryEngine  # noqa: E402
from memory_merge import merge_conversation_keys  # noqa: E402


TABLES = (
    "messages",
    "sessions",
    "memory_facts",
    "chat_summaries",
    "memory_state",
    "memory_config",
)

POST_MERGE_POLICY_KEEP = "keep_live_sessions"
POST_MERGE_POLICY_SUMMARIZE = "summarize_live_sessions"
POST_MERGE_POLICY_CHOICES = (
    POST_MERGE_POLICY_KEEP,
    POST_MERGE_POLICY_SUMMARIZE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge all shared-session conversation keys into one shared archive key",
    )
    parser.add_argument(
        "--db",
        default="/home/architect/.local/state/telegram-architect-bridge/memory.sqlite3",
        help="SQLite memory DB path",
    )
    parser.add_argument(
        "--shared-key",
        required=True,
        help="Shared archive conversation key, for example shared:architect:main",
    )
    parser.add_argument(
        "--post-merge-live-policy",
        default=POST_MERGE_POLICY_SUMMARIZE,
        choices=POST_MERGE_POLICY_CHOICES,
        help=(
            "What to do with the live shared-session keys after the archive merge. "
            "Default: summarize_live_sessions"
        ),
    )
    return parser.parse_args()


def load_source_keys(db_path: str, shared_key: str) -> list[str]:
    prefix = f"{shared_key}:session:%"
    out: list[str] = []
    seen: set[str] = set()
    with sqlite3.connect(db_path) as conn:
        for table in TABLES:
            for row in conn.execute(
                f"""
                SELECT DISTINCT conversation_key
                FROM {table}
                WHERE conversation_key LIKE ?
                ORDER BY conversation_key
                """,
                (prefix,),
            ):
                key = str(row[0] or "").strip()
                if not key or key in seen:
                    continue
                seen.add(key)
                out.append(key)
    return out


def emit_merge_report(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True))


def apply_post_merge_live_policy(
    db_path: str,
    source_keys: list[str],
    policy: str,
) -> tuple[int, int, int]:
    normalized_policy = (policy or "").strip().lower()
    if normalized_policy == POST_MERGE_POLICY_KEEP:
        return 0, 0, 0
    if normalized_policy != POST_MERGE_POLICY_SUMMARIZE:
        raise ValueError(f"Unsupported post-merge live policy: {policy}")

    engine = MemoryEngine(db_path)
    summarized_keys = 0
    summaries_generated = 0
    compacted_messages = 0
    for conversation_key in source_keys:
        key_generated = 0
        force_once = True
        while engine.run_summarization_if_needed(conversation_key, force=force_once):
            key_generated += 1
            force_once = False
        compacted_messages += engine.compact_summarized_messages(conversation_key)
        if key_generated > 0:
            summarized_keys += 1
            summaries_generated += key_generated
    return summarized_keys, summaries_generated, compacted_messages


def main() -> int:
    args = parse_args()
    shared_key = (args.shared_key or "").strip()
    if not shared_key:
        print("shared_key is required", file=sys.stderr)
        return 2

    source_keys = load_source_keys(args.db, shared_key)
    if not source_keys:
        emit_merge_report(
            {
                "archive_messages_compacted": 0,
                "db_path": args.db,
                "live_messages_compacted": 0,
                "live_session_summaries_generated": 0,
                "live_sessions_summarized": 0,
                "post_merge_live_policy": args.post_merge_live_policy,
                "shared_key": shared_key,
                "source_count": 0,
                "source_keys": [],
                "status": "no_sources",
            }
        )
        return 0

    result = merge_conversation_keys(
        db_path=args.db,
        source_keys=source_keys,
        target_key=shared_key,
        allow_existing_target=True,
        force_summarize_target=True,
        min_message_score=0.75,
    )
    engine = MemoryEngine(args.db)
    archive_messages_compacted = engine.compact_summarized_messages(shared_key)
    summarized_keys, live_session_summaries_generated, live_messages_compacted = apply_post_merge_live_policy(
        args.db,
        source_keys,
        args.post_merge_live_policy,
    )
    emit_merge_report(
        {
            "archive_messages_compacted": archive_messages_compacted,
            "clears_live_sessions": False,
            "db_path": args.db,
            "facts_merged": result.facts_merged,
            "live_messages_compacted": live_messages_compacted,
            "live_session_summaries_generated": live_session_summaries_generated,
            "live_sessions_summarized": summarized_keys,
            "messages_copied": result.messages_copied,
            "post_merge_live_policy": args.post_merge_live_policy,
            "shared_key": shared_key,
            "source_count": len(result.source_keys),
            "source_keys": list(result.source_keys),
            "status": "merged",
            "summaries_generated": result.summaries_generated,
            "target_key": result.target_key,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
