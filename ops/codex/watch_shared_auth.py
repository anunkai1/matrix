#!/usr/bin/env python3
"""Keep Server3 runtime Codex auth links aligned with Architect auth."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
NEEDS_SYNC = REPO_ROOT / "ops" / "codex" / "needs_shared_auth_sync.sh"
SYNC_AUTH = REPO_ROOT / "ops" / "codex" / "sync_shared_auth.sh"


def interval_seconds() -> float:
    raw = os.getenv("SERVER3_CODEX_AUTH_WATCH_INTERVAL_SECONDS", "2").strip()
    try:
        value = float(raw)
    except ValueError:
        return 2.0
    return max(value, 0.5)


def run_checked(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        check=False,
    )


def emit(message: str) -> None:
    print(message, flush=True)


def main() -> int:
    if not NEEDS_SYNC.exists() or not SYNC_AUTH.exists():
        emit("shared-auth watcher missing helper script")
        return 1

    wait_seconds = interval_seconds()
    last_failure_at = 0.0
    emit(f"shared-auth watcher started interval_seconds={wait_seconds:g}")

    while True:
        condition = run_checked([str(NEEDS_SYNC)])
        if condition.returncode == 0:
            now = time.monotonic()
            if now - last_failure_at < 10:
                time.sleep(wait_seconds)
                continue
            emit("shared-auth drift detected; syncing")
            sync = run_checked([str(SYNC_AUTH)])
            if sync.stdout.strip():
                emit(sync.stdout.rstrip())
            if sync.stderr.strip():
                print(sync.stderr.rstrip(), file=sys.stderr, flush=True)
            if sync.returncode != 0:
                last_failure_at = time.monotonic()
                emit(f"shared-auth sync failed rc={sync.returncode}")
        elif condition.returncode not in (1,):
            if condition.stderr.strip():
                print(condition.stderr.rstrip(), file=sys.stderr, flush=True)
            emit(f"shared-auth condition check failed rc={condition.returncode}")

        time.sleep(wait_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
