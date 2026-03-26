#!/usr/bin/env python3
"""Deterministic preflight checks for the Architect split-planner path."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from telegram_bridge.agent_orchestrator import (  # noqa: E402
    ORCHESTRATOR_HARD_MAX_WORKERS,
    build_candidate_worker_plan,
    build_planner_preflight_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run deterministic preflight checks for the Architect planner schema and worker selection."
    )
    parser.add_argument(
        "--sample-prompt",
        help="Optional extra prompt to evaluate with the current candidate-worker selector.",
    )
    args = parser.parse_args()

    report = build_planner_preflight_report()
    if args.sample_prompt:
        report["candidate_plans"]["custom"] = [
            worker.role
            for worker in build_candidate_worker_plan(
                args.sample_prompt,
                max_workers=ORCHESTRATOR_HARD_MAX_WORKERS,
            )
        ]

    print(json.dumps(report, indent=2, sort_keys=True))
    schema_supported = bool(report["schema"]["schema_supported"])
    return 0 if schema_supported else 1


if __name__ == "__main__":
    raise SystemExit(main())
