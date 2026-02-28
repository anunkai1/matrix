#!/usr/bin/env python3
import argparse
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
TELEGRAM_BRIDGE_SRC = REPO_ROOT / "src" / "telegram_bridge"
if str(TELEGRAM_BRIDGE_SRC) not in sys.path:
    sys.path.insert(0, str(TELEGRAM_BRIDGE_SRC))

from memory_engine import MemoryEngine  # type: ignore  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Regenerate chat_summaries rows using the current summary formatter."
    )
    parser.add_argument(
        "--db",
        default=os.getenv(
            "TELEGRAM_MEMORY_SQLITE_PATH",
            "/home/architect/.local/state/telegram-architect-bridge/memory.sqlite3",
        ),
        help="SQLite memory DB path (default: TELEGRAM_MEMORY_SQLITE_PATH or architect default path)",
    )
    parser.add_argument(
        "--conversation-key",
        default="",
        help="Optional conversation key filter (example: tg:211761499)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = str(Path(args.db).expanduser())
    engine = MemoryEngine(db_path)
    key = args.conversation_key.strip() or None
    updated = engine.regenerate_summaries(conversation_key=key)
    scope = key if key else "all keys"
    print(f"regenerated_summaries={updated} scope={scope} db={db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
