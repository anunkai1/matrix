#!/usr/bin/env python3
"""Summarize orchestrator health, planner metrics, and restart-marker state."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from telegram_bridge.agent_orchestrator import build_planner_preflight_report  # noqa: E402


def status_path_for_unit(unit_name: str) -> Path:
    sanitized = "".join(char if char.isalnum() or char in "._-" else "_" for char in unit_name)
    return Path("/run/restart-and-verify") / f"restart_and_verify.{sanitized}.status.json"


def load_restart_status(unit_name: str) -> Dict[str, Any]:
    path = status_path_for_unit(unit_name)
    if not path.exists():
        return {"path": str(path), "present": False}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"path": str(path), "present": True, "parse_error": str(exc)}
    payload["path"] = str(path)
    payload["present"] = True
    return payload


def iter_structured_events(unit_name: str, since: str) -> Iterable[Dict[str, Any]]:
    cmd = [
        "journalctl",
        "-u",
        unit_name,
        "--since",
        since,
        "--no-pager",
        "-o",
        "cat",
    ]
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "journalctl failed")
    for line in result.stdout.splitlines():
        text = line.strip()
        if not text.startswith("{"):
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            yield payload


def build_metrics(unit_name: str, since: str) -> Dict[str, Any]:
    planner_decisions = []
    split_planner_runs = []
    worker_finishes = []
    reason_codes: Counter[str] = Counter()

    for event in iter_structured_events(unit_name, since):
        name = str(event.get("event") or "")
        if name == "bridge.orchestrator_planner_decision":
            planner_decisions.append(event)
            reason = str(event.get("reason_code") or "")
            if reason:
                reason_codes[reason] += 1
        elif name == "bridge.orchestrator_worker_finished":
            role = str(event.get("role") or "")
            if role == "split-planner":
                split_planner_runs.append(event)
            else:
                worker_finishes.append(event)

    total_decisions = len(planner_decisions)
    split_selected = sum(1 for event in planner_decisions if bool(event.get("enabled")))
    worker_count_total = 0
    for event in planner_decisions:
        raw_worker_count = event.get("worker_count")
        if raw_worker_count is None:
            raw_worker_count = len(event.get("worker_roles") or [])
        worker_count_total += int(raw_worker_count or 0)
    split_planner_total = len(split_planner_runs)
    split_planner_success = sum(1 for event in split_planner_runs if bool(event.get("success")))
    planner_fallbacks = sum(
        1
        for event in planner_decisions
        if str(event.get("reason_code") or "")
        in {"planner_failed_fallback", "planner_unparseable_fallback"}
    )

    return {
        "since": since,
        "planner_decision_total": total_decisions,
        "split_selected_total": split_selected,
        "single_agent_total": total_decisions - split_selected,
        "split_selection_rate": (split_selected / total_decisions) if total_decisions else 0.0,
        "average_worker_count": (worker_count_total / total_decisions) if total_decisions else 0.0,
        "split_planner_total": split_planner_total,
        "split_planner_success_total": split_planner_success,
        "split_planner_success_rate": (
            split_planner_success / split_planner_total if split_planner_total else 0.0
        ),
        "planner_fallback_total": planner_fallbacks,
        "worker_finish_total": len(worker_finishes),
        "reason_code_counts": dict(sorted(reason_codes.items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Summarize Architect orchestrator health from planner preflight, journal metrics, and restart markers."
    )
    parser.add_argument(
        "--unit",
        default="telegram-architect-bridge.service",
        help="Systemd unit to inspect.",
    )
    parser.add_argument(
        "--since",
        default="6 hours ago",
        help="journalctl --since window for recent orchestrator metrics.",
    )
    parser.add_argument(
        "--fail-on-bad-state",
        action="store_true",
        help="Exit non-zero if planner preflight is unsupported or the latest restart marker is failed/timeout.",
    )
    args = parser.parse_args()

    report = {
        "unit": args.unit,
        "planner_preflight": build_planner_preflight_report(),
        "recent_metrics": build_metrics(args.unit, args.since),
        "latest_restart_status": load_restart_status(args.unit),
    }
    print(json.dumps(report, indent=2, sort_keys=True))

    if not args.fail_on_bad_state:
        return 0

    preflight_ok = bool(report["planner_preflight"]["schema"]["schema_supported"])
    restart_status = report["latest_restart_status"]
    restart_ok = str(restart_status.get("verification") or "").lower() not in {"failed", "timeout"}
    return 0 if preflight_ok and restart_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
