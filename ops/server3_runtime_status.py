#!/usr/bin/env python3
"""Shared Server3 runtime status command driven by the canonical manifest."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST_PATH = ROOT / "infra" / "server3-runtime-manifest.json"
DEFAULT_TZ = "Australia/Brisbane"


@dataclass(frozen=True)
class UnitSpec:
    name: str
    kind: str
    expected_state: str
    expected_substate: Optional[str] = None


@dataclass(frozen=True)
class RuntimeSpec:
    name: str
    category: str
    purpose: str
    expected_default_state: str
    dependencies: List[str]
    owner_user: Optional[str]
    notes: List[str]
    units: List[UnitSpec]


@dataclass(frozen=True)
class UnitStatus:
    name: str
    load_state: str
    active_state: str
    sub_state: str
    unit_file_state: str
    available: bool
    matches_expected: bool
    issues: List[str]


@dataclass(frozen=True)
class RuntimeStatus:
    name: str
    category: str
    expected_default_state: str
    purpose: str
    dependencies: List[str]
    owner_user: Optional[str]
    notes: List[str]
    units: List[UnitStatus]
    matches_expected: bool
    live_state: str


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect Server3 runtime status from the canonical runtime manifest."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
        help="Path to the runtime manifest JSON file.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-runtime notes, dependencies, and unit-level detail.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of the operator summary table.",
    )
    return parser.parse_args(argv)


def load_manifest(path: Path) -> List[RuntimeSpec]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    runtimes: List[RuntimeSpec] = []
    for runtime in payload.get("runtimes", []):
        units = [
            UnitSpec(
                name=unit["name"],
                kind=unit.get("kind", "service"),
                expected_state=unit["expected_state"],
                expected_substate=unit.get("expected_substate"),
            )
            for unit in runtime.get("units", [])
        ]
        runtimes.append(
            RuntimeSpec(
                name=runtime["name"],
                category=runtime["category"],
                purpose=runtime["purpose"],
                expected_default_state=runtime["expected_default_state"],
                dependencies=list(runtime.get("dependencies", [])),
                owner_user=runtime.get("owner_user"),
                notes=list(runtime.get("notes", [])),
                units=units,
            )
        )
    if not runtimes:
        raise ValueError(f"manifest has no runtimes: {path}")
    return runtimes


def parse_key_value_output(text: str) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def run_capture(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    attempts: List[List[str]] = [list(command)]
    if os.geteuid() != 0 and shutil.which("sudo"):
        attempts.append(["sudo", "-n", *command])

    last_result: Optional[subprocess.CompletedProcess[str]] = None
    for attempt in attempts:
        result = subprocess.run(attempt, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            return result
        if result.stdout.strip():
            return result
        last_result = result

    if last_result is None:
        raise RuntimeError(f"command failed before execution: {' '.join(command)}")
    return last_result


def query_unit_status(unit_name: str) -> UnitStatus:
    result = run_capture(
        [
            "systemctl",
            "show",
            unit_name,
            "-p",
            "LoadState",
            "-p",
            "ActiveState",
            "-p",
            "SubState",
            "-p",
            "UnitFileState",
            "--no-pager",
        ]
    )
    fields = parse_key_value_output(result.stdout)
    load_state = fields.get("LoadState", "unknown")
    active_state = fields.get("ActiveState", "unknown")
    sub_state = fields.get("SubState", "unknown")
    unit_file_state = fields.get("UnitFileState", "unknown")
    available = load_state not in {"not-found", "unknown", ""}
    issues: List[str] = []
    if result.returncode != 0 and not fields:
        stderr = result.stderr.strip() or "systemctl show failed"
        issues.append(stderr)
    if not available:
        issues.append("unit not found")
    return UnitStatus(
        name=unit_name,
        load_state=load_state,
        active_state=active_state,
        sub_state=sub_state,
        unit_file_state=unit_file_state,
        available=available,
        matches_expected=False,
        issues=issues,
    )


def compact_state(active_state: str, sub_state: str) -> str:
    active = active_state or "unknown"
    sub = sub_state or "unknown"
    if active in {"active", "inactive", "failed"} and sub not in {"", "dead", "running", "exited"}:
        return f"{active}({sub})"
    return active


def evaluate_unit(spec: UnitSpec, status: UnitStatus) -> UnitStatus:
    issues = list(status.issues)
    if status.available and status.active_state != spec.expected_state:
        issues.append(
            f"expected {spec.expected_state}, got {compact_state(status.active_state, status.sub_state)}"
        )
    if (
        status.available
        and spec.expected_substate
        and status.sub_state != spec.expected_substate
    ):
        issues.append(f"expected substate {spec.expected_substate}, got {status.sub_state}")
    return UnitStatus(
        name=status.name,
        load_state=status.load_state,
        active_state=status.active_state,
        sub_state=status.sub_state,
        unit_file_state=status.unit_file_state,
        available=status.available,
        matches_expected=not issues,
        issues=issues,
    )


def combine_live_state(units: Iterable[UnitStatus]) -> str:
    live_states = {compact_state(unit.active_state, unit.sub_state) for unit in units}
    if len(live_states) == 1:
        return next(iter(live_states))
    return "mixed"


def evaluate_runtime(runtime: RuntimeSpec, unit_statuses: Dict[str, UnitStatus]) -> RuntimeStatus:
    evaluated_units = [
        evaluate_unit(spec, unit_statuses[spec.name])
        for spec in runtime.units
    ]
    return RuntimeStatus(
        name=runtime.name,
        category=runtime.category,
        expected_default_state=runtime.expected_default_state,
        purpose=runtime.purpose,
        dependencies=runtime.dependencies,
        owner_user=runtime.owner_user,
        notes=runtime.notes,
        units=evaluated_units,
        matches_expected=all(unit.matches_expected for unit in evaluated_units),
        live_state=combine_live_state(evaluated_units),
    )


def format_table(statuses: List[RuntimeStatus], manifest_path: Path) -> str:
    lines = [
        f"Server3 runtime status | {datetime.now(ZoneInfo(DEFAULT_TZ)).strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"Manifest: {manifest_path}",
        "",
    ]
    rows = [
        (
            "OK" if runtime.matches_expected else "WARN",
            runtime.category,
            runtime.name,
            runtime.live_state,
            runtime.expected_default_state,
            ", ".join(unit.name for unit in runtime.units),
        )
        for runtime in statuses
    ]
    widths = [max(len(str(row[index])) for row in [("Health", "Category", "Runtime", "Live", "Expected", "Units"), *rows]) for index in range(6)]
    header = "  ".join(
        value.ljust(widths[index])
        for index, value in enumerate(("Health", "Category", "Runtime", "Live", "Expected", "Units"))
    )
    lines.append(header)
    lines.append("  ".join("-" * width for width in widths))
    for row in rows:
        lines.append("  ".join(str(value).ljust(widths[index]) for index, value in enumerate(row)))

    ok_count = sum(1 for runtime in statuses if runtime.matches_expected)
    warn_count = len(statuses) - ok_count
    lines.extend(
        [
            "",
            f"Summary: {ok_count}/{len(statuses)} runtimes at expected default state; {warn_count} warning(s).",
        ]
    )
    return "\n".join(lines)


def format_verbose(statuses: List[RuntimeStatus], manifest_path: Path) -> str:
    lines = [format_table(statuses, manifest_path), ""]
    for runtime in statuses:
        lines.append(f"[{runtime.category}] {runtime.name}")
        lines.append(f"purpose: {runtime.purpose}")
        if runtime.owner_user:
            lines.append(f"owner: {runtime.owner_user}")
        if runtime.dependencies:
            lines.append(f"dependencies: {', '.join(runtime.dependencies)}")
        for note in runtime.notes:
            lines.append(f"note: {note}")
        for unit in runtime.units:
            status = "ok" if unit.matches_expected else "warn"
            lines.append(
                f"unit[{status}]: {unit.name} | live={compact_state(unit.active_state, unit.sub_state)} | "
                f"load={unit.load_state} | file={unit.unit_file_state}"
            )
            for issue in unit.issues:
                lines.append(f"issue: {issue}")
        lines.append("")
    return "\n".join(lines).rstrip()


def format_json(statuses: List[RuntimeStatus], manifest_path: Path) -> str:
    payload = {
        "generated_at": datetime.now(ZoneInfo(DEFAULT_TZ)).isoformat(),
        "timezone": DEFAULT_TZ,
        "manifest": str(manifest_path),
        "runtimes": [
            {
                "name": runtime.name,
                "category": runtime.category,
                "expected_default_state": runtime.expected_default_state,
                "live_state": runtime.live_state,
                "matches_expected": runtime.matches_expected,
                "purpose": runtime.purpose,
                "dependencies": runtime.dependencies,
                "owner_user": runtime.owner_user,
                "notes": runtime.notes,
                "units": [
                    {
                        "name": unit.name,
                        "load_state": unit.load_state,
                        "active_state": unit.active_state,
                        "sub_state": unit.sub_state,
                        "unit_file_state": unit.unit_file_state,
                        "matches_expected": unit.matches_expected,
                        "issues": unit.issues,
                    }
                    for unit in runtime.units
                ],
            }
            for runtime in statuses
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def collect_runtime_statuses(runtimes: List[RuntimeSpec]) -> List[RuntimeStatus]:
    unit_names = [unit.name for runtime in runtimes for unit in runtime.units]
    queried = {name: query_unit_status(name) for name in unit_names}
    return [evaluate_runtime(runtime, queried) for runtime in runtimes]


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    runtimes = load_manifest(args.manifest)
    statuses = collect_runtime_statuses(runtimes)
    if args.json:
        output = format_json(statuses, args.manifest)
    elif args.verbose:
        output = format_verbose(statuses, args.manifest)
    else:
        output = format_table(statuses, args.manifest)
    print(output)
    return 0 if all(runtime.matches_expected for runtime in statuses) else 1


if __name__ == "__main__":
    sys.exit(main())
