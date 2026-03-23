from __future__ import annotations

import json
import threading
import unittest
from urllib.request import Request, urlopen

from src.browser_brain.server import BrowserBrainHTTPServer
from src.browser_brain.service import BrowserBrainError


class FakeController:
    def status(self, payload):
        return {"ok": True, "payload": payload}

    def start(self, payload):
        return {"started": True, "payload": payload}

    def stop(self, payload):
        return {"stopped": True, "payload": payload}

    def tabs_list(self, payload):
        return {"tabs": [{"tab_id": "tab-1"}], "payload": payload}

    def tabs_open(self, payload):
        return {"tab": {"tab_id": "tab-2", "url": payload["url"]}}

    def tabs_focus(self, payload):
        return {"focused": payload["tab_id"]}

    def tabs_close(self, payload):
        return {"closed_tab_id": payload["tab_id"]}

    def navigate(self, payload):
        return {"tab": {"tab_id": payload.get("tab_id", "tab-1"), "url": payload["url"]}}

    def snapshot(self, payload):
        return {"snapshot_id": "snap-1", "elements": [{"ref": "el-0001"}], "payload": payload}

    def screenshot(self, payload):
        return {"path": "/tmp/capture.png", "payload": payload}

    def wait(self, payload):
        return {"ok": True, "payload": payload}

    def act_click(self, payload):
        return {"ok": True, "payload": payload}

    def act_type(self, payload):
        return {"ok": True, "payload": payload}

    def act_press(self, payload):
        raise BrowserBrainError("bad_key", "bad key", status=422)

    def act_upload(self, payload):
        return {"ok": True, "payload": payload}


def _request(server: BrowserBrainHTTPServer, method: str, path: str, payload: dict | None = None):
    base_url = f"http://127.0.0.1:{server.server_port}{path}"
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(base_url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        if not hasattr(exc, "code"):
            raise
        return exc.code, json.loads(exc.read().decode("utf-8"))


class BrowserBrainHTTPServerTests(unittest.TestCase):
    def test_http_routes_dispatch_to_controller_methods(self) -> None:
        server = BrowserBrainHTTPServer(("127.0.0.1", 0), FakeController())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status_code, body = _request(server, "GET", "/v1/status")
            self.assertEqual(status_code, 200)
            self.assertTrue(body["ok"])

            status_code, body = _request(server, "POST", "/v1/tabs/open", {"url": "https://example.com"})
            self.assertEqual(status_code, 200)
            self.assertEqual(body["tab"]["url"], "https://example.com")

            status_code, body = _request(server, "POST", "/v1/act/press", {"key": "BadKey"})
            self.assertEqual(status_code, 422)
            self.assertEqual(body["error"], "bad_key")

            status_code, body = _request(server, "POST", "/v1/act/upload", {"path": "/tmp/example.mp4"})
            self.assertEqual(status_code, 200)
            self.assertTrue(body["ok"])
        finally:
            server.shutdown()
            thread.join(timeout=3)
            server.server_close()


if __name__ == "__main__":
    unittest.main()
