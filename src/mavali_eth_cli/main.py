#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from mavali_eth.config import MavaliEthConfig
from mavali_eth.service import MavaliEthService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CLI for the mavali_eth wallet runtime")
    parser.add_argument("prompt", nargs="*", help="Natural-language wallet prompt")
    parser.add_argument(
        "--session-key",
        default="cli:default",
        help="Confirmation session key shared across CLI calls",
    )
    parser.add_argument(
        "--state-dir",
        default="",
        help="Override MAVALI_ETH/bridge state dir",
    )
    return parser.parse_args()


def resolve_prompt(args: argparse.Namespace) -> str:
    if args.prompt:
        return " ".join(args.prompt).strip()
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    return ""


def main() -> int:
    args = parse_args()
    prompt = resolve_prompt(args)
    if not prompt:
        print("Usage: mavali-eth-cli \"show my wallet address\"")
        print("Usage: mavali-eth-cli \"send 0.03 ETH to 0x...\"")
        print("Usage: mavali-eth-cli confirm")
        return 1
    config = MavaliEthConfig.from_env(args.state_dir.strip() or None)
    service = MavaliEthService(config)
    print(service.handle_prompt(args.session_key, prompt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
