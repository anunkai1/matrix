"""Shared core and per-runtime overlay path helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, List

def _normalize_root(path: str) -> str:
    normalized = (path or "").strip()
    if not normalized:
        raise ValueError("root path cannot be empty")
    return str(Path(normalized).expanduser().resolve())

def build_shared_core_root() -> str:
    configured = (
        os.getenv("TELEGRAM_SHARED_CORE_ROOT", "").strip()
        or os.getenv("MATRIX_REPO_ROOT", "").strip()
    )
    if configured:
        return _normalize_root(configured)
    return str(Path(__file__).resolve().parents[2])

def build_runtime_root() -> str:
    configured = os.getenv("TELEGRAM_RUNTIME_ROOT", "").strip()
    if configured:
        return _normalize_root(configured)
    return build_shared_core_root()

def shared_core_path(*parts: str) -> str:
    return str(Path(build_shared_core_root(), *parts))

def runtime_path(*parts: str) -> str:
    return str(Path(build_runtime_root(), *parts))

def dedupe_paths(paths: Iterable[str]) -> List[str]:
    unique: List[str] = []
    seen = set()
    for candidate in paths:
        normalized = candidate.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique
