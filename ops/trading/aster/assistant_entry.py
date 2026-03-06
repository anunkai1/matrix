#!/usr/bin/env python3
"""CLI entrypoint for ASTER trading assistant runtime."""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src" / "telegram_bridge"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from aster_trading import run_cli  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(run_cli())
