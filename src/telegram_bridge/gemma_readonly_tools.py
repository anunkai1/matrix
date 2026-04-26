"""Read-only tool harness for the Gemma bridge engine."""

from __future__ import annotations

import os
import re
import shlex
import socket
import subprocess
from html import unescape
from ipaddress import ip_address
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence
from urllib import parse as urllib_parse
from urllib import request as urllib_request

try:
    from .runtime_paths import build_runtime_root, build_shared_core_root, dedupe_paths
except ImportError:
    from runtime_paths import build_runtime_root, build_shared_core_root, dedupe_paths


MAX_TOOL_OUTPUT_CHARS = 24000
MAX_READ_BYTES = 128000
MAX_LOG_LINES = 200
MAX_LIST_ENTRIES = 300
MAX_DEPTH = 4
MAX_WEB_RESULTS = 8
MAX_WEB_FETCH_BYTES = 192000
WEB_USER_AGENT = "Server3-Gemma-WebResearch/1.0"
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
_BLOCKED_EXACT_NAMES = {
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "private",
}


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
        web_research_enabled: bool = False,
    ) -> None:
        roots = list(allowed_roots) if allowed_roots is not None else build_default_allowed_roots()
        self.allowed_roots = [Path(root).expanduser().resolve() for root in roots if str(root).strip()]
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.max_output_chars = max(1000, int(max_output_chars))
        self.web_research_enabled = bool(web_research_enabled)

    def instructions(self) -> str:
        root_text = ", ".join(str(root) for root in self.allowed_roots) or "(none)"
        tools = (
            "list_files(path, max_depth), read_file(path, max_bytes), "
            "service_status(unit), inspect_logs(unit, lines), "
            "run_readonly_command(command)"
        )
        web_text = ""
        if self.web_research_enabled:
            tools += ", web_search(query, max_results), fetch_url(url, max_bytes)"
            web_text = (
                " Web research may fetch arbitrary public http/https URLs; "
                "local, private, loopback, link-local, and multicast network targets are blocked."
            )
        return (
            "You may request one read-only Server3 tool call when needed. "
            "To request a tool, reply with only compact JSON in this shape: "
            '{"tool":"tool_name","args":{...}}. '
            f"Available tools: {tools}. "
            "Allowed file roots: "
            f"{root_text}. "
            "Do not request writes, deletes, restarts, installs, or shell pipelines."
            f"{web_text} "
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
            if normalized == "web_search":
                return self._web_search(args)
            if normalized == "fetch_url":
                return self._fetch_url(args)
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
        if not resolved.exists():
            resolved = self._resolve_case_insensitive_path(path)
        if not any(resolved == root or root in resolved.parents for root in self.allowed_roots):
            raise PermissionError(f"Path is outside allowed Gemma read roots: {resolved}")
        lowered_parts = [part.lower() for part in resolved.parts]
        if any(part in _BLOCKED_EXACT_NAMES for part in lowered_parts):
            raise PermissionError(f"Path is blocked by private/internal guard: {resolved}")
        if any(blocked in part for part in lowered_parts for blocked in _BLOCKED_NAME_PARTS):
            raise PermissionError(f"Path is blocked by sensitive-name guard: {resolved}")
        return resolved

    def _resolve_case_insensitive_path(self, path: Path) -> Path:
        parts = path.expanduser().parts
        if not parts:
            return path.resolve()
        current = Path(parts[0])
        for part in parts[1:]:
            candidate = current / part
            if candidate.exists():
                current = candidate
                continue
            if not current.is_dir():
                return path.resolve()
            lowered = part.lower()
            matches = [child for child in current.iterdir() if child.name.lower() == lowered]
            if len(matches) != 1:
                return path.resolve()
            current = matches[0]
        return current.resolve()

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

    def _ensure_web_research_enabled(self) -> None:
        if not self.web_research_enabled:
            raise PermissionError("Gemma web research tools are disabled.")

    def _web_search(self, args: Mapping[str, Any]) -> ToolResult:
        self._ensure_web_research_enabled()
        query = str(args.get("query", "")).strip()
        if not query:
            return ToolResult(False, "", "Empty web search query.")
        max_results = _bounded_int(args.get("max_results", 5), minimum=1, maximum=MAX_WEB_RESULTS)
        search_url = "https://duckduckgo.com/html/?" + urllib_parse.urlencode({"q": query})
        html = self._fetch_public_text(search_url, max_bytes=MAX_WEB_FETCH_BYTES)
        results = _parse_duckduckgo_results(html, max_results=max_results)
        if not results:
            return ToolResult(True, f"No web search results found for: {query}")
        lines: List[str] = [f"Web search results for: {query}"]
        for index, result in enumerate(results, start=1):
            lines.append(f"{index}. {result['title']}")
            lines.append(f"   URL: {result['url']}")
            if result.get("snippet"):
                lines.append(f"   Snippet: {result['snippet']}")
        return ToolResult(True, self._truncate("\n".join(lines)))

    def _fetch_url(self, args: Mapping[str, Any]) -> ToolResult:
        self._ensure_web_research_enabled()
        url = str(args.get("url", "")).strip()
        max_bytes = _bounded_int(args.get("max_bytes", 64000), minimum=1, maximum=MAX_WEB_FETCH_BYTES)
        text = self._fetch_public_text(url, max_bytes=max_bytes)
        cleaned = _html_to_text(text) if _looks_like_html(text) else text
        return ToolResult(True, self._truncate(cleaned.strip()))

    def _fetch_public_text(self, url: str, *, max_bytes: int) -> str:
        parsed = _validate_public_http_url(url)
        request = urllib_request.Request(
            parsed.geturl(),
            headers={
                "Accept": "text/html,text/plain,application/xhtml+xml,application/json;q=0.8,*/*;q=0.2",
                "User-Agent": WEB_USER_AGENT,
            },
        )
        with urllib_request.urlopen(request, timeout=self.timeout_seconds) as response:
            content_type = response.headers.get("Content-Type", "")
            charset = response.headers.get_content_charset() or "utf-8"
            data = response.read(max_bytes + 1)
        suffix = "\n[byte limit reached]" if len(data) > max_bytes else ""
        text = data[:max_bytes].decode(charset, errors="replace")
        if content_type and not _looks_like_text_content_type(content_type):
            return f"Fetched non-text content type {content_type}; first bytes decoded as text:\n{text}{suffix}"
        return text + suffix


def _bounded_int(value: Any, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = minimum
    return max(minimum, min(maximum, parsed))


def _is_sensitive_name(name: str) -> bool:
    lowered = str(name or "").lower()
    return lowered in _BLOCKED_EXACT_NAMES or any(part in lowered for part in _BLOCKED_NAME_PARTS)


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


def _validate_public_http_url(raw_url: str) -> urllib_parse.ParseResult:
    url = str(raw_url or "").strip()
    parsed = urllib_parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise PermissionError("Only public http/https URLs are allowed.")
    if not parsed.hostname:
        raise PermissionError("URL host is required.")
    host = parsed.hostname.strip()
    try:
        ip = ip_address(host)
        if _is_blocked_ip(ip):
            raise PermissionError(f"Blocked non-public URL host: {host}")
    except ValueError:
        for family, _, _, _, sockaddr in socket.getaddrinfo(host, None):
            if family not in {socket.AF_INET, socket.AF_INET6}:
                continue
            resolved_ip = ip_address(sockaddr[0])
            if _is_blocked_ip(resolved_ip):
                raise PermissionError(f"Blocked non-public URL host: {host}")
    return parsed


def _is_blocked_ip(ip) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _looks_like_text_content_type(content_type: str) -> bool:
    lowered = content_type.lower()
    return any(
        marker in lowered
        for marker in (
            "text/",
            "application/json",
            "application/xml",
            "application/xhtml+xml",
            "application/rss+xml",
            "application/atom+xml",
        )
    )


def _looks_like_html(text: str) -> bool:
    lowered = text[:1000].lower()
    return "<html" in lowered or "<body" in lowered or "<p" in lowered or "<div" in lowered


def _html_to_text(text: str) -> str:
    cleaned = re.sub(r"(?is)<(script|style|noscript|svg).*?</\1>", " ", text)
    cleaned = re.sub(r"(?is)<br\s*/?>", "\n", cleaned)
    cleaned = re.sub(r"(?is)</(p|div|li|h[1-6]|tr)>", "\n", cleaned)
    cleaned = re.sub(r"(?is)<[^>]+>", " ", cleaned)
    cleaned = unescape(cleaned)
    cleaned = re.sub(r"[ \t\r\f\v]+", " ", cleaned)
    cleaned = re.sub(r"\n\s+", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _parse_duckduckgo_results(html: str, *, max_results: int) -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []
    blocks = re.findall(r'(?is)<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html)
    snippets = re.findall(r'(?is)<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', html)
    for index, (raw_url, raw_title) in enumerate(blocks):
        url = _normalize_duckduckgo_url(unescape(raw_url))
        title = _html_to_text(raw_title)
        if not url or not title or _is_duckduckgo_ad_url(url):
            continue
        snippet = _html_to_text(snippets[index]) if index < len(snippets) else ""
        results.append({"title": title, "url": url, "snippet": snippet})
        if len(results) >= max_results:
            break
    return results


def _normalize_duckduckgo_url(raw_url: str) -> str:
    parsed = urllib_parse.urlparse(raw_url)
    if parsed.path.startswith("/l/"):
        query = urllib_parse.parse_qs(parsed.query)
        if query.get("uddg"):
            return query["uddg"][0]
    if raw_url.startswith("//"):
        return "https:" + raw_url
    return raw_url


def _is_duckduckgo_ad_url(url: str) -> bool:
    parsed = urllib_parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    return host.endswith("duckduckgo.com") and parsed.path.endswith("/y.js")
