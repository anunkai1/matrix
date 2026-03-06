#!/usr/bin/env python3
"""Merge multiple conversation keys into one shared memory key."""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / 'src' / 'telegram_bridge'
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from memory_merge import merge_conversation_keys  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Merge shared memory conversation keys')
    parser.add_argument(
        '--db',
        default='/home/architect/.local/state/telegram-architect-bridge/memory.sqlite3',
        help='SQLite memory DB path',
    )
    parser.add_argument('--target-key', required=True, help='Target shared conversation key')
    parser.add_argument(
        '--source-key',
        action='append',
        dest='source_keys',
        required=True,
        help='Source conversation key to merge (repeat for multiple keys)',
    )
    parser.add_argument(
        '--overwrite-target',
        action='store_true',
        help='Clear the target key before merging if it already has data',
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = merge_conversation_keys(
        db_path=args.db,
        source_keys=args.source_keys,
        target_key=args.target_key,
        overwrite_target=args.overwrite_target,
    )
    print('Merged shared memory key successfully:')
    print(f'- target: {result.target_key}')
    print(f'- sources: {", ".join(result.source_keys)}')
    print(f'- messages copied: {result.messages_copied}')
    print(f'- facts merged: {result.facts_merged}')
    print(f'- summaries generated: {result.summaries_generated}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
