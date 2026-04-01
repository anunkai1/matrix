#!/usr/bin/env python3
"""Install thin per-runtime overlay shims for Server3 bridge runtimes."""

from __future__ import annotations

import argparse
import json
import os
import pwd
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "infra" / "server3-runtime-manifest.json"
OVERLAY_ENTRYPOINTS = ("main.py", "executor.sh")
OPTIONAL_ENTRYPOINTS = ("wait_for_signal_transport.py",)


@dataclass(frozen=True)
class OverlayRuntime:
    name: str
    owner_user: str
    runtime_root: Path
    shared_core_root: Path


def load_overlay_runtimes() -> List[OverlayRuntime]:
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    runtimes: List[OverlayRuntime] = []
    for entry in payload.get("runtimes", []):
        if entry.get("runtime_layout") != "shared-core-overlay":
            continue
        owner_user = (entry.get("owner_user") or "").strip()
        workspace_root = (entry.get("workspace_root") or "").strip()
        shared_core_root = (entry.get("shared_core_root") or "").strip()
        if not owner_user or not workspace_root or not shared_core_root:
            raise RuntimeError(f"Overlay runtime manifest entry is incomplete: {entry.get('name')!r}")
        runtimes.append(
            OverlayRuntime(
                name=str(entry.get("name") or owner_user),
                owner_user=owner_user,
                runtime_root=Path(workspace_root).expanduser().resolve(),
                shared_core_root=Path(shared_core_root).expanduser().resolve(),
            )
        )
    return runtimes


def render_python_shim(shared_core_root: Path, entrypoint: str) -> str:
    return f"""#!/usr/bin/env python3
\"\"\"Server3 shared-core overlay shim.\"\"\"

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


SHARED_CORE_ROOT = Path({str(shared_core_root)!r})
RUNTIME_ROOT = Path(__file__).resolve().parents[2]

os.environ.setdefault(\"TELEGRAM_SHARED_CORE_ROOT\", str(SHARED_CORE_ROOT))
os.environ.setdefault(\"TELEGRAM_RUNTIME_ROOT\", str(RUNTIME_ROOT))

shared_src = SHARED_CORE_ROOT / \"src\" / \"telegram_bridge\"
if str(shared_src) not in sys.path:
    sys.path.insert(0, str(shared_src))

runpy.run_path(str(shared_src / {entrypoint!r}), run_name=\"__main__\")
"""


def render_executor_shim(shared_core_root: Path) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail

script_dir=\"$(cd \"$(dirname \"${{BASH_SOURCE[0]}}\")\" && pwd)\"
runtime_root=\"$(cd \"${{script_dir}}/../..\" && pwd)\"

export TELEGRAM_SHARED_CORE_ROOT=\"${{TELEGRAM_SHARED_CORE_ROOT:-{str(shared_core_root)}}}\"
export TELEGRAM_RUNTIME_ROOT=\"${{TELEGRAM_RUNTIME_ROOT:-${{runtime_root}}}}\"

exec \"{str(shared_core_root / 'src' / 'telegram_bridge' / 'executor.sh')}\" \"$@\"
"""


def render_entrypoint(shared_core_root: Path, entrypoint: str) -> str:
    if entrypoint == "executor.sh":
        return render_executor_shim(shared_core_root)
    return render_python_shim(shared_core_root, entrypoint)


def write_text_file(path: Path, content: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(content, encoding="utf-8")
    os.chmod(tmp_path, mode)
    os.replace(tmp_path, path)


def backup_if_changed(path: Path, content: str) -> Path | None:
    if not path.exists():
        return None
    existing = path.read_text(encoding="utf-8")
    if existing == content:
        return None
    backup_path = path.with_name(f"{path.name}.pre-shared-core-overlay")
    if not backup_path.exists():
        backup_path.write_text(existing, encoding="utf-8")
    return backup_path


def install_runtime(runtime: OverlayRuntime) -> List[str]:
    src_root = runtime.runtime_root / "src" / "telegram_bridge"
    shared_src_root = (runtime.shared_core_root / "src" / "telegram_bridge").resolve()
    if src_root.exists() and src_root.resolve() == shared_src_root:
        return []
    installed: List[str] = []
    owner = pwd.getpwnam(runtime.owner_user)

    for entrypoint in OVERLAY_ENTRYPOINTS:
        target = src_root / entrypoint
        content = render_entrypoint(runtime.shared_core_root, entrypoint)
        backup_if_changed(target, content)
        write_text_file(target, content, 0o755 if entrypoint.endswith(".sh") else 0o644)
        os.chown(target, owner.pw_uid, owner.pw_gid)
        installed.append(str(target))

    for entrypoint in OPTIONAL_ENTRYPOINTS:
        target = src_root / entrypoint
        if not target.exists():
            continue
        content = render_entrypoint(runtime.shared_core_root, entrypoint)
        backup_if_changed(target, content)
        write_text_file(target, content, 0o644)
        os.chown(target, owner.pw_uid, owner.pw_gid)
        installed.append(str(target))

    return installed


def iter_selected_runtimes(all_runtimes: Iterable[OverlayRuntime], names: List[str]) -> List[OverlayRuntime]:
    if not names:
        return list(all_runtimes)
    wanted = {name.strip().casefold() for name in names if name.strip()}
    return [runtime for runtime in all_runtimes if runtime.name.casefold() in wanted]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime",
        action="append",
        default=[],
        help="Limit sync to one manifest runtime name (repeatable).",
    )
    args = parser.parse_args()

    runtimes = iter_selected_runtimes(load_overlay_runtimes(), args.runtime)
    if not runtimes:
        raise SystemExit("No matching shared-core overlay runtimes found.")

    for runtime in runtimes:
        installed = install_runtime(runtime)
        if not installed:
            print(f"[overlay-sync] {runtime.name}: no shim changes needed")
            continue
        print(f"[overlay-sync] {runtime.name}: {len(installed)} shim(s) updated")
        for target in installed:
            print(f"  - {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
