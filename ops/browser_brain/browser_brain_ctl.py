#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "http://127.0.0.1:47831"
DEFAULT_SERVICE = "server3-browser-brain.service"


def _request(base_url: str, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(f"{base_url}{path}", data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except HTTPError as exc:
        body = exc.read().decode("utf-8") if exc.fp is not None else ""
        if body:
            try:
                error_payload = json.loads(body)
            except json.JSONDecodeError:
                error_payload = {"error": "http_error", "message": body}
        else:
            error_payload = {"error": "http_error", "message": f"HTTP {exc.code}"}
        raise RuntimeError(json.dumps(error_payload, sort_keys=True)) from exc
    except URLError as exc:
        raise RuntimeError(f"browser brain API unavailable: {exc.reason}") from exc


def _ensure_service(service_name: str) -> None:
    status = subprocess.run(
        ["systemctl", "is-active", "--quiet", service_name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if status.returncode == 0:
        return
    subprocess.run(["sudo", "systemctl", "start", service_name], check=True)


def _print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Server3 Browser Brain CLI wrapper")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--service-name", default=DEFAULT_SERVICE)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status")
    subparsers.add_parser("start")
    subparsers.add_parser("stop")
    subparsers.add_parser("tabs")

    open_parser = subparsers.add_parser("open")
    open_parser.add_argument("--url", required=True)

    focus_parser = subparsers.add_parser("focus")
    focus_parser.add_argument("--tab-id", required=True)

    close_parser = subparsers.add_parser("close")
    close_parser.add_argument("--tab-id", required=True)

    nav_parser = subparsers.add_parser("navigate")
    nav_parser.add_argument("--tab-id", required=True)
    nav_parser.add_argument("--url", required=True)

    snap_parser = subparsers.add_parser("snapshot")
    snap_parser.add_argument("--tab-id")

    shot_parser = subparsers.add_parser("screenshot")
    shot_parser.add_argument("--tab-id")
    shot_parser.add_argument("--label", default="capture")
    shot_parser.add_argument("--viewport-only", action="store_true")

    wait_parser = subparsers.add_parser("wait")
    wait_parser.add_argument("--tab-id", required=True)
    wait_parser.add_argument("--condition", required=True, choices=["load_state", "url_contains", "text"])
    wait_parser.add_argument("--value", default="")
    wait_parser.add_argument("--timeout-ms", type=int)

    click_parser = subparsers.add_parser("click")
    click_parser.add_argument("--tab-id", required=True)
    click_parser.add_argument("--snapshot-id", required=True)
    click_parser.add_argument("--ref", required=True)

    type_parser = subparsers.add_parser("type")
    type_parser.add_argument("--tab-id", required=True)
    type_parser.add_argument("--snapshot-id", required=True)
    type_parser.add_argument("--ref", required=True)
    type_parser.add_argument("--text", required=True)

    press_parser = subparsers.add_parser("press")
    press_parser.add_argument("--tab-id", required=True)
    press_parser.add_argument("--key", required=True)
    press_parser.add_argument("--snapshot-id")
    press_parser.add_argument("--ref")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command

    if command != "status":
        _ensure_service(args.service_name)

    if command == "status":
        payload = _request(args.base_url, "GET", "/v1/status")
    elif command == "start":
        payload = _request(args.base_url, "POST", "/v1/start", {})
    elif command == "stop":
        payload = _request(args.base_url, "POST", "/v1/stop", {})
    elif command == "tabs":
        payload = _request(args.base_url, "GET", "/v1/tabs")
    elif command == "open":
        payload = _request(args.base_url, "POST", "/v1/tabs/open", {"url": args.url})
    elif command == "focus":
        payload = _request(args.base_url, "POST", "/v1/tabs/focus", {"tab_id": args.tab_id})
    elif command == "close":
        payload = _request(args.base_url, "POST", "/v1/tabs/close", {"tab_id": args.tab_id})
    elif command == "navigate":
        payload = _request(args.base_url, "POST", "/v1/navigate", {"tab_id": args.tab_id, "url": args.url})
    elif command == "snapshot":
        request_payload = {}
        if args.tab_id:
            request_payload["tab_id"] = args.tab_id
        payload = _request(args.base_url, "POST", "/v1/snapshot", request_payload)
    elif command == "screenshot":
        request_payload = {"label": args.label, "full_page": not args.viewport_only}
        if args.tab_id:
            request_payload["tab_id"] = args.tab_id
        payload = _request(args.base_url, "POST", "/v1/screenshot", request_payload)
    elif command == "wait":
        request_payload = {"tab_id": args.tab_id, "condition": args.condition, "value": args.value}
        if args.timeout_ms is not None:
            request_payload["timeout_ms"] = args.timeout_ms
        payload = _request(args.base_url, "POST", "/v1/wait", request_payload)
    elif command == "click":
        payload = _request(
            args.base_url,
            "POST",
            "/v1/act/click",
            {"tab_id": args.tab_id, "snapshot_id": args.snapshot_id, "ref": args.ref},
        )
    elif command == "type":
        payload = _request(
            args.base_url,
            "POST",
            "/v1/act/type",
            {"tab_id": args.tab_id, "snapshot_id": args.snapshot_id, "ref": args.ref, "text": args.text},
        )
    elif command == "press":
        request_payload = {"tab_id": args.tab_id, "key": args.key}
        if args.snapshot_id:
            request_payload["snapshot_id"] = args.snapshot_id
        if args.ref:
            request_payload["ref"] = args.ref
        payload = _request(args.base_url, "POST", "/v1/act/press", request_payload)
    else:  # pragma: no cover
        raise AssertionError(f"Unhandled command: {command}")

    _print(payload)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(json.dumps({"error": "command_failed", "message": str(exc)}), file=sys.stderr)
        raise SystemExit(exc.returncode)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
