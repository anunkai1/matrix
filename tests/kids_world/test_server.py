from __future__ import annotations

import json
import threading
import unittest
from urllib.request import Request, urlopen

from src.kids_world.server import KidsWorldDemoService, KidsWorldHTTPServer


def _request(server: KidsWorldHTTPServer, method: str, path: str, payload: dict | None = None):
    base_url = f"http://127.0.0.1:{server.server_port}{path}"
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(base_url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=3) as response:
            return response.status, response.headers.get_content_type(), response.read()
    except Exception as exc:
        if not hasattr(exc, "code"):
            raise
        return exc.code, exc.headers.get_content_type(), exc.read()


class KidsWorldDemoServiceTests(unittest.TestCase):
    def test_create_demo_returns_structured_follow_ups(self) -> None:
        service = KidsWorldDemoService()
        payload = service.create_demo("Add a funny robot friend for the dragon.").as_payload()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["sceneTitle"], "Robot Helper Workshop")
        self.assertEqual(len(payload["followUps"]), 4)
        self.assertIn("prompt", payload["followUps"][0])


class KidsWorldHTTPServerTests(unittest.TestCase):
    def test_routes_serve_html_health_and_create_demo(self) -> None:
        server = KidsWorldHTTPServer(("127.0.0.1", 0), KidsWorldDemoService())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status_code, content_type, body = _request(server, "GET", "/")
            self.assertEqual(status_code, 200)
            self.assertEqual(content_type, "text/html")
            self.assertIn(b"Kids World", body)

            status_code, content_type, body = _request(server, "GET", "/health")
            self.assertEqual(status_code, 200)
            self.assertEqual(content_type, "application/json")
            self.assertTrue(json.loads(body.decode("utf-8"))["ok"])

            status_code, content_type, body = _request(
                server,
                "POST",
                "/api/create-demo",
                {"prompt": "Make it gentler and bedtime calm."},
            )
            self.assertEqual(status_code, 200)
            self.assertEqual(content_type, "application/json")
            payload = json.loads(body.decode("utf-8"))
            self.assertEqual(payload["sceneTitle"], "Moon Garden Nest")
            self.assertEqual(payload["prompt"], "Make it gentler and bedtime calm.")
        finally:
            server.shutdown()
            thread.join(timeout=3)
            server.server_close()


if __name__ == "__main__":
    unittest.main()
