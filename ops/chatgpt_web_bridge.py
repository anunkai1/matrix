#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BROWSER_BRAIN_URL = "http://127.0.0.1:47831"
DEFAULT_BROWSER_BRAIN_SERVICE = "server3-browser-brain.service"
DEFAULT_CHATGPT_URL = "https://chatgpt.com/"

LOGIN_MARKERS = (
    "log in",
    "login",
    "sign up",
    "email address",
    "password",
    "continue with google",
    "continue with microsoft",
)
BLOCKED_MARKERS = (
    "captcha",
    "verify you are human",
    "unusual activity",
    "too many requests",
    "something went wrong",
)
PROMPT_HINTS = (
    "message chatgpt",
    "ask anything",
    "send a message",
    "message",
    "prompt",
)
SEND_HINTS = (
    "send prompt",
    "send message",
    "send",
)
COPY_HINTS = (
    "copy",
    "copy response",
    "copy code",
)
NOISE_LINE_PATTERNS = (
    r"^\s*-?\s*(button|link|textbox|combobox|menuitem|navigation|banner|complementary)\b",
    r"^\s*-?\s*(group|img|alert|status|tooltip)\b",
    r"^\s*-?\s*heading\s+\"?chatgpt said",
    r"^\s*ask anything\s*$",
    r"\b(copy|regenerate|thumbs up|thumbs down|read aloud|share|new chat|temporary chat)\b",
    r"\b(use voice|control, alt)\b",
    r"\b(chatgpt can make mistakes|check important info)\b",
)


class ChatGPTWebBridgeError(RuntimeError):
    pass


@dataclass(frozen=True)
class BrowserBrainClient:
    base_url: str = DEFAULT_BROWSER_BRAIN_URL
    timeout_seconds: int = 30

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="ignore") if exc.fp is not None else ""
            raise ChatGPTWebBridgeError(f"Browser Brain HTTP {exc.code}: {raw}") from exc
        except TimeoutError as exc:
            raise ChatGPTWebBridgeError(
                f"Browser Brain request timed out after {self.timeout_seconds}s: {method} {path}"
            ) from exc
        except URLError as exc:
            raise ChatGPTWebBridgeError(f"Browser Brain unavailable at {self.base_url}: {exc.reason}") from exc
        parsed = json.loads(raw or "{}")
        if not isinstance(parsed, dict):
            raise ChatGPTWebBridgeError("Browser Brain returned a non-object payload")
        return parsed


def ensure_browser_brain_service(service_name: str) -> None:
    status = subprocess.run(
        ["systemctl", "is-active", "--quiet", service_name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if status.returncode == 0:
        return
    start = subprocess.run(
        ["systemctl", "start", service_name],
        capture_output=True,
        text=True,
        check=False,
    )
    if start.returncode == 0:
        return
    detail = (start.stderr or start.stdout or "").strip() or f"exit {start.returncode}"
    raise ChatGPTWebBridgeError(
        f"failed to start {service_name} via systemctl: {detail}. Start it manually or disable --start-service."
    )


def snapshot_text(snapshot: dict[str, Any]) -> str:
    parts = [str(snapshot.get("aria_snapshot") or "")]
    elements = snapshot.get("elements")
    if isinstance(elements, list):
        for element in elements:
            if isinstance(element, dict):
                parts.extend(
                    str(element.get(key) or "")
                    for key in ("name", "text", "aria_label", "placeholder", "title")
                )
    return "\n".join(part for part in parts if part).strip()


def lower_page_text(snapshot: dict[str, Any]) -> str:
    return snapshot_text(snapshot).lower()


def find_prompt_box(snapshot: dict[str, Any]) -> dict[str, str]:
    elements = snapshot.get("elements")
    if not isinstance(elements, list):
        raise ChatGPTWebBridgeError("snapshot has no elements")
    candidates: list[tuple[int, dict[str, Any]]] = []
    for element in elements:
        if not isinstance(element, dict):
            continue
        if str(element.get("role") or "").lower() != "textbox":
            continue
        if not bool(element.get("visible", True)) or not bool(element.get("enabled", True)):
            continue
        blob = " ".join(
            str(element.get(key) or "")
            for key in ("name", "text", "aria_label", "placeholder", "title")
        ).lower()
        score = 5 if any(hint in blob for hint in PROMPT_HINTS) else 0
        if bool(element.get("content_editable")):
            score += 2
        if str(element.get("tag") or "").lower() == "textarea":
            score += 2
        if score:
            candidates.append((score, element))
    if not candidates:
        raise ChatGPTWebBridgeError("could not find ChatGPT prompt textbox; login, captcha, or UI drift likely")
    _, best = max(candidates, key=lambda item: item[0])
    return {"snapshot_id": str(snapshot["snapshot_id"]), "ref": str(best["ref"])}


def find_send_button(snapshot: dict[str, Any]) -> dict[str, str] | None:
    elements = snapshot.get("elements")
    if not isinstance(elements, list):
        return None
    candidates: list[tuple[int, dict[str, Any]]] = []
    for element in elements:
        if not isinstance(element, dict):
            continue
        if str(element.get("role") or "").lower() != "button":
            continue
        if not bool(element.get("visible", True)) or not bool(element.get("enabled", True)):
            continue
        blob = " ".join(
            str(element.get(key) or "")
            for key in ("name", "text", "aria_label", "placeholder", "title")
        ).lower()
        if any(hint in blob for hint in SEND_HINTS):
            candidates.append((len(blob), element))
    if not candidates:
        return None
    _, best = min(candidates, key=lambda item: item[0])
    return {"snapshot_id": str(snapshot["snapshot_id"]), "ref": str(best["ref"])}


def find_latest_copy_button(snapshot: dict[str, Any]) -> dict[str, str] | None:
    elements = snapshot.get("elements")
    if not isinstance(elements, list):
        return None
    matches: list[dict[str, Any]] = []
    for element in elements:
        if not isinstance(element, dict):
            continue
        if str(element.get("role") or "").lower() != "button":
            continue
        if not bool(element.get("visible", True)) or not bool(element.get("enabled", True)):
            continue
        blob = " ".join(
            str(element.get(key) or "")
            for key in ("name", "text", "aria_label", "placeholder", "title")
        ).lower()
        if any(hint == blob or hint in blob for hint in COPY_HINTS):
            matches.append(element)
    if not matches:
        return None
    latest = matches[-1]
    return {"snapshot_id": str(snapshot["snapshot_id"]), "ref": str(latest["ref"])}


def detect_blocked_state(snapshot: dict[str, Any]) -> str:
    text = lower_page_text(snapshot)
    for marker in BLOCKED_MARKERS:
        if marker in text:
            return marker
    if any(marker in text for marker in LOGIN_MARKERS):
        if any(hint in text for hint in PROMPT_HINTS) or "stop streaming" in text or "chatgpt said" in text:
            return "login_required"
        return "login_required"
    return ""


def detect_network_blocked_state(client: BrowserBrainClient, tab_id: str) -> str:
    try:
        payload = client.request("POST", "/v1/network", {"tab_id": tab_id, "limit": 20})
    except ChatGPTWebBridgeError:
        return ""
    events = payload.get("events")
    if not isinstance(events, list):
        return ""
    for event in reversed(events):
        if not isinstance(event, dict):
            continue
        url = str(event.get("url") or "")
        status = event.get("status")
        if status not in {401, 403}:
            continue
        if "chatgpt.com/backend-api/" in url or "chatgpt.com/ces/" in url or "chatgpt.com/backend-anon/" in url:
            return f"network_{status}"
    return ""


def open_or_reuse_chatgpt_tab(client: BrowserBrainClient, *, url: str) -> str:
    status = client.request("GET", "/v1/status")
    if not bool(status.get("running")):
        client.request("POST", "/v1/start", {})
    tabs = client.request("GET", "/v1/tabs").get("tabs")
    if isinstance(tabs, list):
        chatgpt_tabs = [tab for tab in tabs if isinstance(tab, dict) and "chatgpt.com" in str(tab.get("url") or "")]
        chatgpt_tabs.sort(key=lambda tab: 0 if "/c/" not in str(tab.get("url") or "") else 1)
        for tab in chatgpt_tabs:
            tab_url = str(tab.get("url") or "")
            if tab.get("tab_id"):
                tab_id = str(tab["tab_id"])
                if "/c/" in tab_url:
                    continue
                client.request("POST", "/v1/tabs/focus", {"tab_id": tab_id})
                return tab_id
    opened = client.request("POST", "/v1/tabs/open", {"url": url})
    tab = opened.get("tab")
    if not isinstance(tab, dict) or not tab.get("tab_id"):
        raise ChatGPTWebBridgeError("Browser Brain did not return a usable ChatGPT tab")
    return str(tab["tab_id"])


def wait_for_prompt_ready(
    client: BrowserBrainClient,
    tab_id: str,
    *,
    timeout_seconds: int,
    poll_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    while time.monotonic() < deadline:
        snapshot = client.request("POST", "/v1/snapshot", {"tab_id": tab_id})
        blocked = detect_network_blocked_state(client, tab_id)
        if blocked:
            raise ChatGPTWebBridgeError(f"ChatGPT web is not ready: {blocked}")
        blocked = detect_blocked_state(snapshot)
        if blocked:
            raise ChatGPTWebBridgeError(f"ChatGPT web is not ready: {blocked}")
        try:
            find_prompt_box(snapshot)
            return snapshot
        except ChatGPTWebBridgeError as exc:
            last_error = str(exc)
        time.sleep(poll_seconds)
    raise ChatGPTWebBridgeError(last_error or "timed out waiting for ChatGPT prompt box")


def submit_prompt(client: BrowserBrainClient, tab_id: str, snapshot: dict[str, Any], prompt: str) -> None:
    target = find_prompt_box(snapshot)
    client.request(
        "POST",
        "/v1/act/type",
        {
            "tab_id": tab_id,
            "snapshot_id": target["snapshot_id"],
            "ref": target["ref"],
            "text": prompt,
        },
    )
    after_type = client.request("POST", "/v1/snapshot", {"tab_id": tab_id})
    send_button = find_send_button(after_type)
    if send_button is not None:
        client.request(
            "POST",
            "/v1/act/click",
            {
                "tab_id": tab_id,
                "snapshot_id": send_button["snapshot_id"],
                "ref": send_button["ref"],
            },
        )
        return
    press_target = find_prompt_box(after_type)
    client.request(
        "POST",
        "/v1/act/press",
        {
            "tab_id": tab_id,
            "snapshot_id": press_target["snapshot_id"],
            "ref": press_target["ref"],
            "key": "Enter",
        },
    )


def normalize_line(line: str) -> str:
    line = re.sub(r"^\s*[-•]?\s*", "", line).strip()
    line = re.sub(r"^(paragraph|heading|text|article|main|listitem):\s*", "", line, flags=re.IGNORECASE)
    return line.strip().strip('"').strip("'").strip()


def is_noise_line(line: str) -> bool:
    lowered = line.lower()
    if not line or len(line) < 2:
        return True
    return any(re.search(pattern, lowered) for pattern in NOISE_LINE_PATTERNS)


def extract_response(snapshot: dict[str, Any], prompt: str) -> str:
    aria_snapshot = str(snapshot.get("aria_snapshot") or "")
    raw_lines = [normalize_line(line) for line in aria_snapshot.splitlines()]
    prompt_norm = " ".join(prompt.split()).lower()
    chatgpt_heading_indexes = [
        index for index, line in enumerate(raw_lines) if "chatgpt said" in " ".join(line.split()).lower()
    ]
    if chatgpt_heading_indexes:
        start = chatgpt_heading_indexes[-1] + 1
    else:
        start = len(raw_lines)
        for index, line in enumerate(raw_lines):
            if prompt_norm[:120] and prompt_norm[:120] in " ".join(line.split()).lower():
                start = index + 1
                break
    tail = [line for line in raw_lines[start:] if not is_noise_line(line)]
    prompt_tail_markers = {"ask anything", "message chatgpt", "send a message", "message", "prompt"}
    while tail and tail[-1].lower().strip() in prompt_tail_markers:
        tail.pop()
    answer = "\n".join(tail).strip()
    return answer


def wait_for_response(
    client: BrowserBrainClient,
    tab_id: str,
    prompt: str,
    *,
    timeout_seconds: int,
    poll_seconds: float,
) -> str:
    deadline = time.monotonic() + timeout_seconds
    best = ""
    stable_count = 0
    last = ""
    while time.monotonic() < deadline:
        snapshot = client.request("POST", "/v1/snapshot", {"tab_id": tab_id})
        blocked = detect_network_blocked_state(client, tab_id)
        if blocked:
            raise ChatGPTWebBridgeError(f"ChatGPT web became blocked: {blocked}")
        blocked = detect_blocked_state(snapshot)
        if blocked:
            raise ChatGPTWebBridgeError(f"ChatGPT web became blocked: {blocked}")
        candidate = copy_latest_response(client, tab_id, snapshot) or extract_response(snapshot, prompt)
        if len(candidate) > len(best):
            best = candidate
        if candidate and candidate == last:
            stable_count += 1
        else:
            stable_count = 0
        last = candidate
        if candidate and stable_count >= 2:
            return candidate
        time.sleep(poll_seconds)
    if best:
        return best
    raise ChatGPTWebBridgeError("timed out waiting for a ChatGPT response")


def copy_latest_response(client: BrowserBrainClient, tab_id: str, snapshot: dict[str, Any]) -> str:
    copy_button = find_latest_copy_button(snapshot)
    if copy_button is None:
        return ""
    try:
        client.request(
            "POST",
            "/v1/act/click",
            {
                "tab_id": tab_id,
                "snapshot_id": copy_button["snapshot_id"],
                "ref": copy_button["ref"],
            },
        )
        time.sleep(0.2)
        payload = client.request("POST", "/v1/clipboard/read", {"tab_id": tab_id})
    except ChatGPTWebBridgeError:
        return ""
    return str(payload.get("text") or "").strip()


def run_ask(args: argparse.Namespace) -> int:
    prompt = args.prompt if args.prompt is not None else sys.stdin.read()
    prompt = prompt.strip()
    if not prompt:
        raise ChatGPTWebBridgeError("prompt is empty")
    if args.start_service:
        ensure_browser_brain_service(args.service_name)
    client = BrowserBrainClient(args.base_url, timeout_seconds=args.request_timeout)
    tab_id = open_or_reuse_chatgpt_tab(client, url=args.url)
    ready_snapshot = wait_for_prompt_ready(
        client,
        tab_id,
        timeout_seconds=args.ready_timeout,
        poll_seconds=args.poll_seconds,
    )
    submit_prompt(client, tab_id, ready_snapshot, prompt)
    answer = wait_for_response(
        client,
        tab_id,
        prompt,
        timeout_seconds=args.response_timeout,
        poll_seconds=args.poll_seconds,
    )
    if args.json:
        print(json.dumps({"tab_id": tab_id, "answer": answer}, indent=2, sort_keys=True))
    else:
        print(answer)
    return 0


def run_status(args: argparse.Namespace) -> int:
    client = BrowserBrainClient(args.base_url, timeout_seconds=args.request_timeout)
    status = client.request("GET", "/v1/status")
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Experimental brittle CLI bridge from Server3 to chatgpt.com through Browser Brain."
    )
    parser.add_argument("--base-url", default=DEFAULT_BROWSER_BRAIN_URL)
    parser.add_argument("--service-name", default=DEFAULT_BROWSER_BRAIN_SERVICE)
    parser.add_argument("--request-timeout", type=int, default=30)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status")

    ask = subparsers.add_parser("ask")
    ask.add_argument("prompt", nargs="?")
    ask.add_argument("--url", default=DEFAULT_CHATGPT_URL)
    ask.add_argument("--start-service", action="store_true")
    ask.add_argument("--ready-timeout", type=int, default=45)
    ask.add_argument("--response-timeout", type=int, default=180)
    ask.add_argument("--poll-seconds", type=float, default=3.0)
    ask.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            return run_status(args)
        if args.command == "ask":
            return run_ask(args)
        raise AssertionError(f"Unhandled command: {args.command}")
    except ChatGPTWebBridgeError as exc:
        print(f"chatgpt-web-bridge: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
