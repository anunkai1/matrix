#!/usr/bin/env python3

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
TELEGRAM_BRIDGE_DIR = REPO_ROOT / "src" / "telegram_bridge"
if str(TELEGRAM_BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(TELEGRAM_BRIDGE_DIR))

from executor import parse_executor_output  # type: ignore
from memory_engine import MemoryEngine, build_memory_help_lines, handle_memory_command  # type: ignore


DEFAULT_STATE_DIR = "/home/architect/.local/state/telegram-architect-bridge"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Architect CLI with shared memory")
    parser.add_argument("prompt", nargs="*", help="Prompt text or memory command")
    parser.add_argument("--profile", default="default", help="CLI memory profile name")
    parser.add_argument(
        "--state-dir",
        default=os.getenv("TELEGRAM_BRIDGE_STATE_DIR", DEFAULT_STATE_DIR),
        help="Base state directory used for shared SQLite memory",
    )
    parser.add_argument(
        "--memory-db",
        default=os.getenv("TELEGRAM_MEMORY_SQLITE_PATH", ""),
        help="Shared memory SQLite path (default: <state-dir>/memory.sqlite3)",
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


def build_memory_db_path(args: argparse.Namespace) -> str:
    if args.memory_db.strip():
        return args.memory_db.strip()
    return str(Path(args.state_dir).expanduser() / "memory.sqlite3")


def run_codex(codex_bin: str, prompt: str, thread_id: Optional[str], timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    if thread_id:
        cmd = [
            codex_bin,
            "exec",
            "resume",
            "--dangerously-bypass-approvals-and-sandbox",
            "--json",
            thread_id,
            "-",
        ]
    else:
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


def print_cli_help() -> None:
    print("Architect CLI memory mode")
    print("Usage: architect <prompt>")
    print("Usage: architect --profile work <prompt>")
    print("Usage: architect /memory status")
    print("Usage: architect /ask <prompt>")
    print("")
    for line in build_memory_help_lines():
        print(line)


def main() -> int:
    args = parse_args()
    raw_input = resolve_input(args)
    if not raw_input:
        print_cli_help()
        return 1

    if raw_input.strip().split(maxsplit=1)[0].split("@", maxsplit=1)[0] in {"/h", "/help"}:
        print_cli_help()
        return 0

    memory_db = build_memory_db_path(args)
    engine = MemoryEngine(memory_db)
    conversation_key = MemoryEngine.cli_key(args.profile)

    cmd_result = handle_memory_command(engine, conversation_key, raw_input)
    if cmd_result.handled:
        if cmd_result.response:
            print(cmd_result.response)
        if cmd_result.run_prompt is None:
            return 0
        prompt_text = cmd_result.run_prompt
        stateless = cmd_result.stateless
    else:
        prompt_text = raw_input
        stateless = False

    try:
        turn = engine.begin_turn(
            conversation_key=conversation_key,
            channel="cli",
            sender_name="CLI User",
            user_input=prompt_text,
            stateless=stateless,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        result = run_codex(args.codex_bin, turn.prompt_text, turn.thread_id, args.timeout_seconds)
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

    new_thread_id, output = parse_executor_output(result.stdout or "")
    if not output:
        output = "(No output from Architect)"
    print(output)

    try:
        engine.finish_turn(
            turn,
            channel="cli",
            assistant_text=output,
            new_thread_id=new_thread_id,
        )
    except Exception:
        # Keep response success even if memory write fails.
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
