#!/usr/bin/env python3
"""Merge per-chat live session keys into the configured shared archive key."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src" / "telegram_bridge"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from memory_merge import merge_conversation_keys  # noqa: E402


TABLES = (
    "messages",
    "sessions",
    "memory_facts",
    "chat_summaries",
    "memory_state",
    "memory_config",
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


def main() -> int:
    args = parse_args()
    shared_key = (args.shared_key or "").strip()
    if not shared_key:
        print("shared_key is required", file=sys.stderr)
        return 2

    source_keys = load_source_keys(args.db, shared_key)
    if not source_keys:
        print(f"No live session keys found for shared archive {shared_key}.")
        return 0

    result = merge_conversation_keys(
        db_path=args.db,
        source_keys=source_keys,
        target_key=shared_key,
        allow_existing_target=True,
        force_summarize_target=True,
    )
    print("Merged shared memory archive successfully:")
    print(f"- target: {result.target_key}")
    print(f"- sources: {', '.join(result.source_keys)}")
    print(f"- messages copied: {result.messages_copied}")
    print(f"- facts merged: {result.facts_merged}")
    print(f"- summaries generated: {result.summaries_generated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
