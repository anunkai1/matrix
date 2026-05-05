#!/usr/bin/env python3

import argparse
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
TELEGRAM_BRIDGE_DIR = REPO_ROOT / "src" / "telegram_bridge"
if str(TELEGRAM_BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(TELEGRAM_BRIDGE_DIR))

from executor import parse_executor_output  # type: ignore


DEFAULT_LAUNCHER_NAME = os.getenv("CLI_LAUNCHER_NAME", "architect").strip() or "architect"
DEFAULT_ASSISTANT_NAME = os.getenv("CLI_ASSISTANT_NAME", "Architect").strip() or "Architect"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Codex CLI wrapper")
    parser.add_argument("prompt", nargs="*", help="Prompt text")
    parser.add_argument(
        "--launcher-name",
        default=DEFAULT_LAUNCHER_NAME,
        help="Launcher command name used in help text",
    )
    parser.add_argument(
        "--assistant-name",
        default=DEFAULT_ASSISTANT_NAME,
        help="Assistant name used in fallback output text",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=int(os.getenv("TELEGRAM_EXEC_TIMEOUT_SECONDS", "36000")),
        help="Executor timeout in seconds",
    )
    parser.add_argument(
        "--codex-bin",
        default=os.getenv("CODEX_BIN", "codex"),
        help="Codex binary path",
    )
    return parser.parse_args()


def resolve_input(args: argparse.Namespace) -> str:
    if args.prompt:
        return " ".join(args.prompt).strip()
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    return ""


def run_codex(codex_bin: str, prompt: str, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    cmd = [
        codex_bin,
        "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "--json",
        "-",
    ]
    return subprocess.run(
        cmd,
        input=prompt + ("\n" if not prompt.endswith("\n") else ""),
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )


def print_cli_help(launcher_name: str, assistant_name: str) -> None:
    print(f"{assistant_name} CLI")
    print(f"Usage: {launcher_name} <prompt>")
    print(f"Usage: {launcher_name} < input.txt")


def main() -> int:
    args = parse_args()
    raw_input = resolve_input(args)
    if not raw_input:
        print_cli_help(args.launcher_name, args.assistant_name)
        return 1

    if raw_input.strip().split(maxsplit=1)[0].split("@", maxsplit=1)[0] in {"/h", "/help"}:
        print_cli_help(args.launcher_name, args.assistant_name)
        return 0

    try:
        result = run_codex(args.codex_bin, raw_input, args.timeout_seconds)
    except subprocess.TimeoutExpired:
        print("Request timed out.", file=sys.stderr)
        return 124
    except FileNotFoundError:
        print(f"Codex binary not found: {args.codex_bin}", file=sys.stderr)
        return 127

    if result.returncode != 0:
        if result.stderr.strip():
            print(result.stderr.strip(), file=sys.stderr)
        elif result.stdout.strip():
            print(result.stdout.strip(), file=sys.stderr)
        else:
            print(f"Executor failed with exit code {result.returncode}", file=sys.stderr)
        return result.returncode

    _new_thread_id, output = parse_executor_output(result.stdout or "")
    if not output:
        output = f"(No output from {args.assistant_name})"
    print(output)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
