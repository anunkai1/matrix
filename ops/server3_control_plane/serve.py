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
import threading
import urllib.parse
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional, Sequence
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = ROOT / "docs"
EXPORTER = ROOT / "ops" / "server3_control_plane" / "export_snapshot.py"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8420
DEFAULT_SNAPSHOT_JSON = DOCS_DIR / "server3-control-plane-data.json"
DEFAULT_OPERATOR_TOKEN_FILE = Path("/home/architect/.config/server3-control-plane/operator_token")
DEFAULT_STATE_DIR = Path("/home/architect/.local/state/server3-control-plane")
DEFAULT_AUDIT_LOG = DEFAULT_STATE_DIR / "audit.jsonl"
DEFAULT_BUNDLES_DIR = DEFAULT_STATE_DIR / "bundles"
OPERATOR_TOKEN_HEADER = "X-Server3-Operator-Token"
LOCAL_CLIENTS = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}
DEFAULT_TZ = ZoneInfo("Australia/Brisbane")
AUDIT_LOCK = threading.Lock()

RUNTIME_UNITS: Dict[str, List[str]] = {
    "architect": ["telegram-architect-bridge.service"],
    "tank": ["telegram-tank-bridge.service"],
    "diary": ["telegram-diary-bridge.service"],
    "govorun": ["whatsapp-govorun-bridge.service", "govorun-whatsapp-bridge.service"],
    "oracle": ["signal-oracle-bridge.service", "oracle-signal-bridge.service"],
    "mavali": ["telegram-mavali-eth-bridge.service"],
    "browser": ["server3-browser-brain.service"],
}
SIGNALTUBE_RESCAN_UNIT = "signaltube-lab-rescan.service"


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


def operator_token_file() -> Path:
    override = os.environ.get("SERVER3_CONTROL_PLANE_OPERATOR_TOKEN_FILE", "").strip()
    return Path(override) if override else DEFAULT_OPERATOR_TOKEN_FILE


def configured_operator_token() -> str:
    path = operator_token_file()
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def state_dir() -> Path:
    override = os.environ.get("SERVER3_CONTROL_PLANE_STATE_DIR", "").strip()
    return Path(override) if override else DEFAULT_STATE_DIR


def audit_log_path() -> Path:
    override = os.environ.get("SERVER3_CONTROL_PLANE_AUDIT_LOG", "").strip()
    return Path(override) if override else DEFAULT_AUDIT_LOG


def bundles_dir() -> Path:
    override = os.environ.get("SERVER3_CONTROL_PLANE_BUNDLES_DIR", "").strip()
    return Path(override) if override else DEFAULT_BUNDLES_DIR


def ensure_state_paths() -> None:
    state_dir().mkdir(parents=True, exist_ok=True)
    bundles_dir().mkdir(parents=True, exist_ok=True)
    audit_log_path().parent.mkdir(parents=True, exist_ok=True)


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


def is_operator_authorized(handler: BaseHTTPRequestHandler) -> bool:
    if is_local_client(handler):
        return True
    expected = configured_operator_token()
    if not expected:
        return False
    presented = handler.headers.get(OPERATOR_TOKEN_HEADER, "").strip()
    return bool(presented) and presented == expected


def actor_context(handler: BaseHTTPRequestHandler) -> Dict[str, str]:
    return {
        "mode": "local" if is_local_client(handler) else "token",
        "client_ip": handler.client_address[0],
    }


def append_audit_entry(
    *,
    action: str,
    outcome: str,
    summary: str,
    detail: str = "",
    runtime_key: str = "",
    scope: str = "board",
    actor_mode: str = "system",
    client_ip: str = "127.0.0.1",
    extra: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    ensure_state_paths()
    entry: Dict[str, object] = {
        "ts": datetime.now(DEFAULT_TZ).isoformat(),
        "action": action,
        "runtime_key": runtime_key,
        "scope": scope,
        "actor_mode": actor_mode,
        "client_ip": client_ip,
        "outcome": outcome,
        "summary": summary,
        "detail": detail,
    }
    if extra:
        entry.update(extra)
    with AUDIT_LOCK:
        with audit_log_path().open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def tail_audit_entries(limit: int = 20) -> List[Dict[str, object]]:
    path = audit_log_path()
    if not path.exists():
        return []
    rows = [row for row in path.read_text(encoding="utf-8").splitlines() if row.strip()]
    items: List[Dict[str, object]] = []
    for row in rows[-limit:]:
        try:
            payload = json.loads(row)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            items.append(payload)
    return items


def local_only_error(handler: BaseHTTPRequestHandler) -> None:
    token_configured = bool(configured_operator_token())
    json_response(
        handler,
        {
            "ok": False,
            "error": "operator authentication required" if token_configured else "local operator action only",
            "detail": (
                "Provide the Server3 operator token or use localhost on Server3."
                if token_configured
                else "Use localhost on Server3 for refresh, logs, or restart actions."
            ),
            "tokenConfigured": token_configured,
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


def signaltube_rescan_status() -> Dict[str, str]:
    result = run_capture(
        [
            "systemctl",
            "show",
            SIGNALTUBE_RESCAN_UNIT,
            "--no-pager",
            "-p",
            "ActiveState",
            "-p",
            "SubState",
            "-p",
            "Result",
            "-p",
            "ExecMainStartTimestamp",
            "-p",
            "ExecMainExitTimestamp",
        ]
    )
    fields: Dict[str, str] = {}
    for line in result.stdout.splitlines():
        key, _, value = line.partition("=")
        if key:
            fields[key] = value
    return fields


def trigger_signaltube_rescan() -> Dict[str, object]:
    status = signaltube_rescan_status()
    active_state = status.get("ActiveState", "")
    if active_state in {"activating", "active"}:
        return {
            "ok": True,
            "started": False,
            "unit": SIGNALTUBE_RESCAN_UNIT,
            "message": "SignalTube rescan is already running",
            "status": status,
        }
    result = run_capture(["systemctl", "start", "--no-block", SIGNALTUBE_RESCAN_UNIT])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "systemctl start failed")
    return {
        "ok": True,
        "started": True,
        "unit": SIGNALTUBE_RESCAN_UNIT,
        "message": "SignalTube rescan started",
        "status": signaltube_rescan_status(),
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


def runtime_service_snapshot(runtime_key: str) -> Dict[str, object]:
    units = runtime_units(runtime_key)
    services: List[Dict[str, str]] = []
    for unit in units:
        show = run_capture(
            [
                "systemctl",
                "show",
                unit,
                "--no-pager",
                "-p",
                "ActiveState",
                "-p",
                "SubState",
                "-p",
                "UnitFileState",
                "-p",
                "ExecMainStartTimestamp",
            ]
        )
        services.append({"unit": unit, "show": show.stdout.strip(), "stderr": show.stderr.strip()})
    journal = runtime_logs(runtime_key, lines=20)
    return {
        "runtime": runtime_key,
        "units": units,
        "services": services,
        "logs": journal.get("logs", ""),
    }


def create_incident_bundle(handler: BaseHTTPRequestHandler) -> Dict[str, object]:
    ensure_state_paths()
    actor = actor_context(handler)
    snapshot = refresh_snapshot()
    runtime_payload = run_capture(["python3", str(ROOT / "ops" / "server3_runtime_status.py"), "--json"])
    runtime_status = {}
    if runtime_payload.stdout.strip():
        try:
            runtime_status = json.loads(runtime_payload.stdout)
        except json.JSONDecodeError:
            runtime_status = {"raw": runtime_payload.stdout}
    bundle = {
        "generated_at": datetime.now(DEFAULT_TZ).isoformat(),
        "host": socket.gethostname(),
        "actor": actor,
        "snapshot": snapshot,
        "runtime_status": runtime_status,
        "recent_audit": tail_audit_entries(limit=40),
        "services": {runtime_key: runtime_service_snapshot(runtime_key) for runtime_key in RUNTIME_UNITS},
    }
    stamp = datetime.now(DEFAULT_TZ).strftime("%Y%m%dT%H%M%S")
    bundle_path = bundles_dir() / f"incident-bundle-{stamp}.json"
    bundle_path.write_text(json.dumps(bundle, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    append_audit_entry(
        action="incident.bundle",
        outcome="ok",
        summary="captured incident bundle",
        detail=str(bundle_path),
        scope="incident",
        actor_mode=actor["mode"],
        client_ip=actor["client_ip"],
        extra={"bundle_path": str(bundle_path)},
    )
    return {
        "ok": True,
        "bundlePath": str(bundle_path),
        "generatedAt": bundle["generated_at"],
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
                if wants_refresh and not is_operator_authorized(self):
                    local_only_error(self)
                    return
                payload = refresh_snapshot() if wants_refresh else load_snapshot()
                if wants_refresh:
                    actor = actor_context(self)
                    append_audit_entry(
                        action="snapshot.refresh",
                        outcome="ok",
                        summary="refreshed control-plane snapshot",
                        detail=str(DEFAULT_SNAPSHOT_JSON),
                        scope="snapshot",
                        actor_mode=actor["mode"],
                        client_ip=actor["client_ip"],
                    )
            except Exception as exc:
                if wants_refresh:
                    actor = actor_context(self)
                    append_audit_entry(
                        action="snapshot.refresh",
                        outcome="error",
                        summary="snapshot refresh failed",
                        detail=str(exc),
                        scope="snapshot",
                        actor_mode=actor["mode"],
                        client_ip=actor["client_ip"],
                    )
                json_response(self, {"ok": False, "error": str(exc)}, status=500)
                return
            json_response(self, {"ok": True, "snapshot": payload})
            return
        if path == "/api/operator/status":
            json_response(
                self,
                {
                    "ok": True,
                    "authorized": is_operator_authorized(self),
                    "localClient": is_local_client(self),
                    "tokenConfigured": bool(configured_operator_token()),
                    "tokenPath": str(operator_token_file()),
                },
            )
            return
        if path.startswith("/api/runtime/") and path.endswith("/logs"):
            if not is_operator_authorized(self):
                local_only_error(self)
                return
            runtime_key = path.split("/")[3]
            try:
                payload = runtime_logs(runtime_key)
                actor = actor_context(self)
                append_audit_entry(
                    action="runtime.logs",
                    outcome="ok" if payload.get("ok") else "error",
                    summary=f"viewed {runtime_key} logs",
                    detail=", ".join(payload.get("units", [])),
                    scope="runtime",
                    runtime_key=runtime_key,
                    actor_mode=actor["mode"],
                    client_ip=actor["client_ip"],
                )
                json_response(self, payload)
            except Exception as exc:
                actor = actor_context(self)
                append_audit_entry(
                    action="runtime.logs",
                    outcome="error",
                    summary=f"failed to load {runtime_key} logs",
                    detail=str(exc),
                    scope="runtime",
                    runtime_key=runtime_key,
                    actor_mode=actor["mode"],
                    client_ip=actor["client_ip"],
                )
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
            if not is_operator_authorized(self):
                local_only_error(self)
                return
            try:
                payload = refresh_snapshot()
            except Exception as exc:
                actor = actor_context(self)
                append_audit_entry(
                    action="snapshot.refresh",
                    outcome="error",
                    summary="snapshot refresh failed",
                    detail=str(exc),
                    scope="snapshot",
                    actor_mode=actor["mode"],
                    client_ip=actor["client_ip"],
                )
                json_response(self, {"ok": False, "error": str(exc)}, status=500)
                return
            actor = actor_context(self)
            append_audit_entry(
                action="snapshot.refresh",
                outcome="ok",
                summary="refreshed control-plane snapshot",
                detail=str(DEFAULT_SNAPSHOT_JSON),
                scope="snapshot",
                actor_mode=actor["mode"],
                client_ip=actor["client_ip"],
            )
            json_response(self, {"ok": True, "snapshot": payload})
            return
        if path == "/api/audit/bundle":
            if not is_operator_authorized(self):
                local_only_error(self)
                return
            try:
                payload = create_incident_bundle(self)
            except Exception as exc:
                actor = actor_context(self)
                append_audit_entry(
                    action="incident.bundle",
                    outcome="error",
                    summary="incident bundle capture failed",
                    detail=str(exc),
                    scope="incident",
                    actor_mode=actor["mode"],
                    client_ip=actor["client_ip"],
                )
                json_response(self, {"ok": False, "error": str(exc)}, status=500)
                return
            json_response(self, payload)
            return
        if path.startswith("/api/runtime/") and path.endswith("/restart"):
            if not is_operator_authorized(self):
                local_only_error(self)
                return
            runtime_key = path.split("/")[3]
            try:
                payload = restart_runtime(runtime_key)
            except Exception as exc:
                actor = actor_context(self)
                append_audit_entry(
                    action="runtime.restart",
                    outcome="error",
                    summary=f"failed to restart {runtime_key}",
                    detail=str(exc),
                    scope="runtime",
                    runtime_key=runtime_key,
                    actor_mode=actor["mode"],
                    client_ip=actor["client_ip"],
                )
                json_response(self, {"ok": False, "error": str(exc)}, status=500)
                return
            actor = actor_context(self)
            append_audit_entry(
                action="runtime.restart",
                outcome="ok",
                summary=f"restarted {runtime_key}",
                detail=", ".join(payload.get("units", [])),
                scope="runtime",
                runtime_key=runtime_key,
                actor_mode=actor["mode"],
                client_ip=actor["client_ip"],
            )
            json_response(self, payload)
            return
        if path == "/api/signaltube/rescan":
            if not is_operator_authorized(self):
                local_only_error(self)
                return
            try:
                payload = trigger_signaltube_rescan()
            except Exception as exc:
                actor = actor_context(self)
                append_audit_entry(
                    action="signaltube.rescan",
                    outcome="error",
                    summary="failed to start SignalTube rescan",
                    detail=str(exc),
                    scope="signaltube",
                    actor_mode=actor["mode"],
                    client_ip=actor["client_ip"],
                )
                json_response(self, {"ok": False, "error": str(exc)}, status=500)
                return
            actor = actor_context(self)
            append_audit_entry(
                action="signaltube.rescan",
                outcome="ok",
                summary=str(payload.get("message") or "SignalTube rescan requested"),
                detail=SIGNALTUBE_RESCAN_UNIT,
                scope="signaltube",
                actor_mode=actor["mode"],
                client_ip=actor["client_ip"],
                extra={"started": bool(payload.get("started"))},
            )
            json_response(self, payload)
            return
        json_response(self, {"ok": False, "error": "not found"}, status=404)

    def log_message(self, format: str, *args) -> None:
        return


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    ensure_state_paths()
    refresh_snapshot()
    with ThreadingHTTPServer((args.host, args.port), Handler) as httpd:
        print(json.dumps({"host": args.host, "port": args.port, "url": f"http://{args.host}:{args.port}/"}, ensure_ascii=True))
        httpd.serve_forever()


if __name__ == "__main__":
    sys.exit(main())
