#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import http.server
import json
import os
import shutil
import socketserver
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.browser_brain.config import BrowserBrainConfig
from src.browser_brain.service import BrowserBrainService


def resolve_browser_executable() -> str:
    override = os.environ.get("BROWSER_BRAIN_SMOKE_BROWSER", "").strip()
    if override:
        return override
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            executable = playwright.chromium.executable_path
            if executable and Path(executable).exists():
                return executable
    except Exception:
        pass
    return shutil.which("brave-browser") or "/usr/bin/brave-browser"


class SmokeHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/ping":
            body = json.dumps({"ok": True}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        body = b"""<!doctype html>
<html>
  <head><title>Browser Brain Smoke</title></head>
  <body>
    <button id="go" onclick="document.getElementById('result').textContent='clicked'">Submit</button>
    <label>Name <input id="name" aria-label="Name"></label>
    <label>Choice
      <select id="choice" aria-label="Choice">
        <option value="">Pick</option>
        <option value="one">One</option>
      </select>
    </label>
    <button id="hover" onmouseover="document.getElementById('hovered').textContent='hovered'">Hover target</button>
    <div id="result"></div>
    <div id="hovered"></div>
    <script>
      console.log("browser-brain-smoke-console");
      fetch("/ping").then(() => console.log("browser-brain-smoke-network"));
    </script>
  </body>
</html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: Any) -> None:
        return


def find_ref(snapshot: dict[str, Any], *, role: str, name: str) -> str:
    for element in snapshot["elements"]:
        if element.get("role") == role and element.get("name") == name:
            return str(element["ref"])
    raise AssertionError(f"ref not found for role={role!r} name={name!r}: {snapshot['elements']}")


def note(message: str) -> None:
    print(f"[browser-brain-smoke] {message}", file=sys.stderr, flush=True)


def main() -> int:
    browser = resolve_browser_executable()
    if not Path(browser).exists():
        raise RuntimeError(f"browser executable not found at {browser}")

    with (
        tempfile.TemporaryDirectory(prefix="browser-brain-smoke-profile-") as profile_dir,
        tempfile.TemporaryDirectory(prefix="browser-brain-smoke-captures-") as capture_dir,
        socketserver.TCPServer(("127.0.0.1", 0), SmokeHandler) as httpd,
    ):
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        origin = f"http://127.0.0.1:{httpd.server_address[1]}"
        service = BrowserBrainService(
            BrowserBrainConfig(
                connection_mode="managed",
                browser_executable=browser,
                browser_user_data_dir=Path(profile_dir),
                state_dir=Path(profile_dir),
                capture_dir=Path(capture_dir),
                headless=True,
                navigation_allowed_origins=(origin,),
                action_timeout_ms=10000,
                log_actions=False,
            )
        )
        try:
            note("start")
            service.start({})
            note("open")
            tab = service.tabs_open({"url": origin})["tab"]
            tab_id = tab["tab_id"]
            note("wait")
            service.wait({"tab_id": tab_id, "condition": "text", "value": "Submit", "timeout_ms": 10000})
            note("snapshot")
            snapshot = service.snapshot({"tab_id": tab_id})
            assert snapshot["aria_snapshot"], "expected non-empty aria snapshot"

            submit_ref = find_ref(snapshot, role="button", name="Submit")
            name_ref = find_ref(snapshot, role="textbox", name="Name")
            choice_ref = find_ref(snapshot, role="combobox", name="Choice")
            hover_ref = find_ref(snapshot, role="button", name="Hover target")

            note("click")
            service.act_click({"tab_id": tab_id, "snapshot_id": snapshot["snapshot_id"], "ref": submit_ref})
            note("type")
            service.act_type({"tab_id": tab_id, "snapshot_id": snapshot["snapshot_id"], "ref": name_ref, "text": "Architect"})
            note("select")
            service.act_select({"tab_id": tab_id, "snapshot_id": snapshot["snapshot_id"], "ref": choice_ref, "value": "one"})
            note("hover")
            service.act_hover({"tab_id": tab_id, "snapshot_id": snapshot["snapshot_id"], "ref": hover_ref})

            note("dialog")
            page = service._page_for_payload({"tab_id": tab_id})
            assert service.dialog_handle({"tab_id": tab_id, "accept": True})["armed"]
            page.evaluate("alert('browser-brain-smoke-dialog')")
            dialog_state = {"dialog": None}
            for _ in range(50):
                dialog_state = service.dialogs_list({"tab_id": tab_id})
                if dialog_state["dialog"] is not None:
                    break
                time.sleep(0.1)
            assert dialog_state["dialog"]["message"] == "browser-brain-smoke-dialog"
            assert dialog_state["dialog"]["handled"]
            assert dialog_state["dialog"]["accepted"]

            note("assert page state")
            page.wait_for_function("document.getElementById('result').textContent === 'clicked'", timeout=10000)
            page.wait_for_function("document.getElementById('name').value === 'Architect'", timeout=10000)
            page.wait_for_function("document.getElementById('choice').value === 'one'", timeout=10000)
            page.wait_for_function("document.getElementById('hovered').textContent === 'hovered'", timeout=10000)
            page.wait_for_function("window.performance.getEntriesByName('/ping').length >= 0", timeout=10000)

            note("diagnostics")
            console_messages = service.console_messages({"tab_id": tab_id})["messages"]
            assert any("browser-brain-smoke-console" in item.get("text", "") for item in console_messages)
            network_events = service.network_events({"tab_id": tab_id})["events"]
            assert any(str(item.get("url", "")).endswith("/ping") and item.get("status") == 200 for item in network_events)
            capture = service.screenshot({"tab_id": tab_id, "label": "smoke", "full_page": False})
            assert Path(capture["path"]).exists()
        finally:
            with contextlib.suppress(Exception):
                service.stop({})
            httpd.shutdown()
            thread.join(timeout=5)

    print(json.dumps({"ok": True, "smoke": "browser_brain"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
