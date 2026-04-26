"""Read-only tool harness for the Gemma bridge engine."""

from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

try:
    from .runtime_paths import build_runtime_root, build_shared_core_root, dedupe_paths
except ImportError:
    from runtime_paths import build_runtime_root, build_shared_core_root, dedupe_paths


MAX_TOOL_OUTPUT_CHARS = 24000
MAX_READ_BYTES = 128000
MAX_LOG_LINES = 200
MAX_LIST_ENTRIES = 300
MAX_DEPTH = 4
_SERVICE_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789@_.-")
_BLOCKED_NAME_PARTS = (
    "auth",
    "credential",
    "key",
    "password",
    "secret",
    "session",
    "token",
)


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    output: str
    error: str = ""

    def as_payload(self) -> Dict[str, Any]:
        return {"ok": self.ok, "output": self.output, "error": self.error}


def build_default_allowed_roots() -> List[str]:
    return dedupe_paths([build_runtime_root(), build_shared_core_root()])


def parse_roots(raw: str) -> List[str]:
    values = [item.strip() for item in str(raw or "").split(",") if item.strip()]
    if not values:
        return build_default_allowed_roots()
    return dedupe_paths([str(Path(value).expanduser().resolve()) for value in values])


class GemmaReadonlyToolHarness:
    """Executes a small, bounded set of read-only tools for Gemma."""

    def __init__(
        self,
        *,
        allowed_roots: Optional[Iterable[str]] = None,
        timeout_seconds: int = 20,
        max_output_chars: int = MAX_TOOL_OUTPUT_CHARS,
    ) -> None:
        roots = list(allowed_roots) if allowed_roots is not None else build_default_allowed_roots()
        self.allowed_roots = [Path(root).expanduser().resolve() for root in roots if str(root).strip()]
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.max_output_chars = max(1000, int(max_output_chars))

    def instructions(self) -> str:
        root_text = ", ".join(str(root) for root in self.allowed_roots) or "(none)"
        return (
            "You may request one read-only Server3 tool call when needed. "
            "To request a tool, reply with only compact JSON in this shape: "
            '{"tool":"tool_name","args":{...}}. '
            "Available tools: "
            "list_files(path, max_depth), read_file(path, max_bytes), "
            "service_status(unit), inspect_logs(unit, lines), "
            "run_readonly_command(command). "
            "Allowed file roots: "
            f"{root_text}. "
            "Do not request writes, deletes, restarts, installs, network changes, or shell pipelines. "
            "After receiving a tool result, answer the user normally."
        )

    def execute(self, tool: str, args: Mapping[str, Any]) -> ToolResult:
        normalized = str(tool or "").strip()
        try:
            if normalized == "list_files":
                return self._list_files(args)
            if normalized == "read_file":
                return self._read_file(args)
            if normalized == "service_status":
                return self._service_status(args)
            if normalized == "inspect_logs":
                return self._inspect_logs(args)
            if normalized == "run_readonly_command":
                return self._run_readonly_command(args)
            return ToolResult(False, "", f"Unknown read-only tool: {normalized}")
        except Exception as exc:
            return ToolResult(False, "", str(exc))

    def _truncate(self, text: str) -> str:
        if len(text) <= self.max_output_chars:
            return text
        return text[: self.max_output_chars] + "\n[truncated]"

    def _resolve_allowed_path(self, raw_path: Any) -> Path:
        path_text = str(raw_path or ".").strip() or "."
        path = Path(path_text).expanduser()
        if not path.is_absolute():
            base = self.allowed_roots[0] if self.allowed_roots else Path.cwd().resolve()
            path = base / path
        resolved = path.resolve()
        if not any(resolved == root or root in resolved.parents for root in self.allowed_roots):
            raise PermissionError(f"Path is outside allowed Gemma read roots: {resolved}")
        lowered_parts = [part.lower() for part in resolved.parts]
        if any(blocked in part for part in lowered_parts for blocked in _BLOCKED_NAME_PARTS):
            raise PermissionError(f"Path is blocked by sensitive-name guard: {resolved}")
        return resolved

    def _list_files(self, args: Mapping[str, Any]) -> ToolResult:
        root = self._resolve_allowed_path(args.get("path", "."))
        max_depth = _bounded_int(args.get("max_depth", 1), minimum=0, maximum=MAX_DEPTH)
        if not root.exists():
            return ToolResult(False, "", f"Path does not exist: {root}")
        if root.is_file():
            return ToolResult(True, f"{root} [file]")
        lines: List[str] = []
        base_depth = len(root.parts)
        for current, dirs, files in os.walk(root):
            current_path = Path(current)
            depth = len(current_path.parts) - base_depth
            dirs[:] = sorted(d for d in dirs if not _is_sensitive_name(d))
            files = sorted(f for f in files if not _is_sensitive_name(f))
            if depth > max_depth:
                dirs[:] = []
                continue
            indent = "  " * depth
            if depth == 0:
                lines.append(f"{current_path}/")
            else:
                lines.append(f"{indent}{current_path.name}/")
            for filename in files:
                lines.append(f"{indent}  {filename}")
                if len(lines) >= MAX_LIST_ENTRIES:
                    return ToolResult(True, self._truncate("\n".join(lines) + "\n[entry limit reached]"))
        return ToolResult(True, self._truncate("\n".join(lines)))

    def _read_file(self, args: Mapping[str, Any]) -> ToolResult:
        path = self._resolve_allowed_path(args.get("path", ""))
        max_bytes = _bounded_int(args.get("max_bytes", 24000), minimum=1, maximum=MAX_READ_BYTES)
        if not path.is_file():
            return ToolResult(False, "", f"Not a file: {path}")
        data = path.read_bytes()[:max_bytes]
        text = data.decode("utf-8", errors="replace")
        suffix = "\n[byte limit reached]" if path.stat().st_size > max_bytes else ""
        return ToolResult(True, self._truncate(text + suffix))

    def _service_status(self, args: Mapping[str, Any]) -> ToolResult:
        unit = _validate_unit(args.get("unit", ""))
        return self._run_command(["systemctl", "status", "--no-pager", "--lines=30", unit])

    def _inspect_logs(self, args: Mapping[str, Any]) -> ToolResult:
        unit = _validate_unit(args.get("unit", ""))
        lines = _bounded_int(args.get("lines", 80), minimum=1, maximum=MAX_LOG_LINES)
        return self._run_command(["journalctl", "-u", unit, "-n", str(lines), "--no-pager", "--output=short-iso"])

    def _run_readonly_command(self, args: Mapping[str, Any]) -> ToolResult:
        raw_command = str(args.get("command", "")).strip()
        argv = shlex.split(raw_command)
        if not argv:
            return ToolResult(False, "", "Empty read-only command.")
        allowed = _allowed_readonly_commands()
        if argv not in allowed:
            allowed_text = "; ".join(shlex.join(command) for command in allowed)
            return ToolResult(False, "", f"Command is not allowlisted. Allowed commands: {allowed_text}")
        return self._run_command(argv)

    def _run_command(self, argv: Sequence[str]) -> ToolResult:
        completed = subprocess.run(
            list(argv),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=self.timeout_seconds,
            check=False,
        )
        output = completed.stdout.strip()
        error = completed.stderr.strip()
        if completed.returncode != 0:
            return ToolResult(False, self._truncate(output), self._truncate(error or f"exit {completed.returncode}"))
        return ToolResult(True, self._truncate(output or error))


def _bounded_int(value: Any, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = minimum
    return max(minimum, min(maximum, parsed))


def _is_sensitive_name(name: str) -> bool:
    lowered = str(name or "").lower()
    return any(part in lowered for part in _BLOCKED_NAME_PARTS)


def _validate_unit(value: Any) -> str:
    unit = str(value or "").strip()
    if not unit or any(char not in _SERVICE_CHARS for char in unit):
        raise ValueError("Invalid systemd unit name.")
    if not unit.endswith((".service", ".timer", ".socket", ".target")):
        unit += ".service"
    return unit


def _allowed_readonly_commands() -> List[List[str]]:
    return [
        ["date"],
        ["uptime"],
        ["df", "-h"],
        ["free", "-h"],
        ["systemctl", "list-units", "--type=service", "--state=running", "--no-pager"],
        ["systemctl", "list-timers", "--all", "--no-pager"],
        ["git", "status", "--short"],
        ["git", "log", "-1", "--oneline"],
    ]
