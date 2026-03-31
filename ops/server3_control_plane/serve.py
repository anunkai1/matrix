#!/usr/bin/env python3
"""Local Server3 control-plane server with snapshot and runtime-action endpoints."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional, Sequence


ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = ROOT / "docs"
EXPORTER = ROOT / "ops" / "server3_control_plane" / "export_snapshot.py"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8420
DEFAULT_SNAPSHOT_JSON = DOCS_DIR / "server3-control-plane-data.json"
LOCAL_CLIENTS = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}

RUNTIME_UNITS: Dict[str, List[str]] = {
    "architect": ["telegram-architect-bridge.service"],
    "tank": ["telegram-tank-bridge.service"],
    "diary": ["telegram-diary-bridge.service"],
    "govorun": ["whatsapp-govorun-bridge.service", "govorun-whatsapp-bridge.service"],
    "oracle": ["signal-oracle-bridge.service", "oracle-signal-bridge.service"],
    "mavali": ["telegram-mavali-eth-bridge.service"],
    "browser": ["server3-browser-brain.service"],
}


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    return parser.parse_args(argv)


def run_capture(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    attempts: List[List[str]] = [list(command)]
    if os.geteuid() != 0 and shutil.which("sudo"):
        sudo_attempt = ["sudo", "-n", *command]
        if command and command[0] == "journalctl":
            attempts = [sudo_attempt, list(command)]
        else:
            attempts.append(sudo_attempt)
    last: Optional[subprocess.CompletedProcess[str]] = None
    for attempt in attempts:
        result = subprocess.run(attempt, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            return result
        last = result
    if last is None:
        raise RuntimeError(f"failed to run command: {' '.join(command)}")
    return last


def refresh_snapshot() -> Dict[str, object]:
    result = run_capture(["python3", str(EXPORTER)])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "snapshot refresh failed")
    return load_snapshot()


def load_snapshot() -> Dict[str, object]:
    if not DEFAULT_SNAPSHOT_JSON.exists():
        return refresh_snapshot()
    return json.loads(DEFAULT_SNAPSHOT_JSON.read_text(encoding="utf-8"))


def is_local_client(handler: BaseHTTPRequestHandler) -> bool:
    client_ip = handler.client_address[0]
    if client_ip in LOCAL_CLIENTS:
        return True
    try:
        resolved_name, aliases, addresses = socket.gethostbyaddr(client_ip)
        candidates = {resolved_name, *aliases, *addresses}
    except OSError:
        return False
    return "127.0.0.1" in candidates or "::1" in candidates


def local_only_error(handler: BaseHTTPRequestHandler) -> None:
    json_response(
        handler,
        {
            "ok": False,
            "error": "local operator action only",
            "detail": "Use localhost on Server3 for refresh, logs, or restart actions.",
        },
        status=403,
    )


def runtime_units(runtime_key: str) -> List[str]:
    units = RUNTIME_UNITS.get(runtime_key, [])
    if not units:
        raise KeyError(f"unknown runtime key: {runtime_key}")
    return units


def restart_runtime(runtime_key: str) -> Dict[str, object]:
    units = runtime_units(runtime_key)
    result = run_capture(["systemctl", "restart", *units])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "systemctl restart failed")
    return {
        "ok": True,
        "runtime": runtime_key,
        "units": units,
        "message": f"restarted {', '.join(units)}",
    }


def runtime_logs(runtime_key: str, lines: int = 80) -> Dict[str, object]:
    units = runtime_units(runtime_key)
    command = ["journalctl"]
    for unit in units:
        command.extend(["-u", unit])
    command.extend(["-n", str(lines), "--no-pager", "--output=short-iso"])
    result = run_capture(command)
    return {
        "ok": result.returncode == 0,
        "runtime": runtime_key,
        "units": units,
        "logs": result.stdout,
        "stderr": result.stderr,
    }


def json_response(handler: BaseHTTPRequestHandler, payload: Dict[str, object], *, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def text_response(handler: BaseHTTPRequestHandler, body: bytes, *, content_type: str, status: int = 200) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class Handler(BaseHTTPRequestHandler):
    server_version = "Server3ControlPlane/0.1"

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/":
            body = b""
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/docs/server3-control-plane-sketch.html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return
        if path == "/api/snapshot":
            params = urllib.parse.parse_qs(parsed.query)
            try:
                wants_refresh = params.get("refresh") == ["1"]
                if wants_refresh and not is_local_client(self):
                    local_only_error(self)
                    return
                payload = refresh_snapshot() if wants_refresh else load_snapshot()
            except Exception as exc:
                json_response(self, {"ok": False, "error": str(exc)}, status=500)
                return
            json_response(self, {"ok": True, "snapshot": payload})
            return
        if path.startswith("/api/runtime/") and path.endswith("/logs"):
            if not is_local_client(self):
                local_only_error(self)
                return
            runtime_key = path.split("/")[3]
            try:
                json_response(self, runtime_logs(runtime_key))
            except Exception as exc:
                json_response(self, {"ok": False, "error": str(exc)}, status=500)
            return
        if path.startswith("/docs/"):
            target = (ROOT / path.lstrip("/")).resolve()
            if not str(target).startswith(str(DOCS_DIR.resolve())) or not target.is_file():
                json_response(self, {"ok": False, "error": "not found"}, status=404)
                return
            content_type = "text/plain; charset=utf-8"
            if target.suffix == ".html":
                content_type = "text/html; charset=utf-8"
            elif target.suffix == ".js":
                content_type = "application/javascript; charset=utf-8"
            elif target.suffix == ".json":
                content_type = "application/json; charset=utf-8"
            elif target.suffix == ".css":
                content_type = "text/css; charset=utf-8"
            text_response(self, target.read_bytes(), content_type=content_type)
            return
        json_response(self, {"ok": False, "error": "not found"}, status=404)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/api/refresh":
            if not is_local_client(self):
                local_only_error(self)
                return
            try:
                payload = refresh_snapshot()
            except Exception as exc:
                json_response(self, {"ok": False, "error": str(exc)}, status=500)
                return
            json_response(self, {"ok": True, "snapshot": payload})
            return
        if path.startswith("/api/runtime/") and path.endswith("/restart"):
            if not is_local_client(self):
                local_only_error(self)
                return
            runtime_key = path.split("/")[3]
            try:
                payload = restart_runtime(runtime_key)
            except Exception as exc:
                json_response(self, {"ok": False, "error": str(exc)}, status=500)
                return
            json_response(self, payload)
            return
        json_response(self, {"ok": False, "error": "not found"}, status=404)

    def log_message(self, format: str, *args) -> None:
        return


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    refresh_snapshot()
    with ThreadingHTTPServer((args.host, args.port), Handler) as httpd:
        print(json.dumps({"host": args.host, "port": args.port, "url": f"http://{args.host}:{args.port}/"}, ensure_ascii=True))
        httpd.serve_forever()


if __name__ == "__main__":
    sys.exit(main())
