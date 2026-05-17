#!/usr/bin/env python3
"""Compatibility wrapper for the standalone mavali-loop implementation."""

from __future__ import annotations

from pathlib import Path

STANDALONE_RUNNER = Path("/home/architect/mavali-loop/src/mavali_loop/runner.py")
if not STANDALONE_RUNNER.exists():
    raise RuntimeError(f"standalone mavali-loop runner is missing: {STANDALONE_RUNNER}")

globals()["__file__"] = str(STANDALONE_RUNNER)
code = compile(STANDALONE_RUNNER.read_text(encoding="utf-8"), str(STANDALONE_RUNNER), "exec")
exec(code, globals())
