#!/usr/bin/env python3
"""Compatibility wrapper for the original seven-task review loop."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[2]
STANDALONE_ROOT = Path("/home/architect/mavali-loop")
CAMPAIGN_PATH = STANDALONE_ROOT / "campaigns" / "examples" / "server3_code_review_may_2026.json"
MAVALI_LOOP_PATH = STANDALONE_ROOT / "src" / "mavali_loop" / "runner.py"


def load_mavali_loop_module():
    spec = importlib.util.spec_from_file_location("mavali_loop", MAVALI_LOOP_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compatibility wrapper for the original review fix loop.")
    parser.add_argument("command", choices=("run", "status", "reset-state"))
    parser.add_argument(
        "--max-attempts-per-issue",
        type=int,
        default=0,
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    mavali_loop = load_mavali_loop_module()
    forwarded = [args.command, str(CAMPAIGN_PATH)]
    if args.command == "run" and args.max_attempts_per_issue:
        forwarded.extend(["--max-attempts-per-task", str(max(1, args.max_attempts_per_issue))])
    return mavali_loop.main(forwarded)


if __name__ == "__main__":
    raise SystemExit(main())
