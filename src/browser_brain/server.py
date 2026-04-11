from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

from .service import BrowserBrainError, BrowserBrainService


ROUTES = {
    ("GET", "/health"): "status",
    ("GET", "/v1/status"): "status",
    ("POST", "/v1/start"): "start",
    ("POST", "/v1/stop"): "stop",
    ("GET", "/v1/tabs"): "tabs_list",
    ("POST", "/v1/tabs/open"): "tabs_open",
    ("POST", "/v1/tabs/focus"): "tabs_focus",
    ("POST", "/v1/tabs/close"): "tabs_close",
    ("POST", "/v1/navigate"): "navigate",
    ("POST", "/v1/snapshot"): "snapshot",
    ("POST", "/v1/screenshot"): "screenshot",
    ("POST", "/v1/wait"): "wait",
    ("POST", "/v1/console"): "console_messages",
    ("POST", "/v1/network"): "network_events",
    ("POST", "/v1/dialogs"): "dialogs_list",
    ("POST", "/v1/dialogs/handle"): "dialog_handle",
    ("POST", "/v1/act/click"): "act_click",
    ("POST", "/v1/act/hover"): "act_hover",
    ("POST", "/v1/act/select"): "act_select",
    ("POST", "/v1/act/type"): "act_type",
    ("POST", "/v1/act/press"): "act_press",
    ("POST", "/v1/act/upload"): "act_upload",
}


class BrowserBrainHTTPServer(HTTPServer):
    def __init__(self, server_address, controller: BrowserBrainService):
        super().__init__(server_address, BrowserBrainRequestHandler)
        self.controller = controller


class BrowserBrainRequestHandler(BaseHTTPRequestHandler):
    server_version = "Server3BrowserBrain/0.1"

    def do_GET(self) -> None:  # noqa: N802
        self._handle()

    def do_POST(self) -> None:  # noqa: N802
        self._handle()

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _handle(self) -> None:
        route = (self.command, urlparse(self.path).path)
        method_name = ROUTES.get(route)
        if method_name is None:
            self._respond_json(HTTPStatus.NOT_FOUND, {"error": "not_found", "message": f"Unknown route: {route[1]}"})
            return
        try:
            payload = self._read_json_body() if self.command == "POST" else {}
            controller_method = getattr(self.server.controller, method_name)
            result = controller_method(payload)
        except BrowserBrainError as exc:
            self._respond_json(exc.status, exc.to_dict())
            return
        except json.JSONDecodeError:
            self._respond_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json", "message": "Request body must be valid JSON"})
            return
        except Exception as exc:  # pragma: no cover - defensive fallback
            self._respond_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "internal_error", "message": "Unexpected browser-brain failure", "details": {"exception": str(exc)}},
            )
            return
        self._respond_json(HTTPStatus.OK, result)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or "0")
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise BrowserBrainError("invalid_payload", "Request body must be a JSON object")
        return data

    def _respond_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
