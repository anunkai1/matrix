from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError

from .models import VideoCandidate


DEFAULT_BROWSER_BRAIN_URL = "http://127.0.0.1:47832"
YOUTUBE_SEARCH_URL = "https://www.youtube.com/results"
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
SHORTS_PATH = "/shorts/"


class SignalTubeBrowserLabError(RuntimeError):
    pass


@dataclass(frozen=True)
class BrowserBrainClient:
    base_url: str = DEFAULT_BROWSER_BRAIN_URL
    timeout_seconds: int = 30

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = None
        headers = {}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="ignore") if exc.fp is not None else ""
            raise SignalTubeBrowserLabError(f"Browser Brain API error at {self.base_url}: HTTP {exc.code} {raw}") from exc
        except URLError as exc:
            raise SignalTubeBrowserLabError(f"Browser Brain API unavailable at {self.base_url}: {exc.reason}") from exc
        parsed = json.loads(raw or "{}")
        if not isinstance(parsed, dict):
            raise SignalTubeBrowserLabError("Browser Brain returned a non-object payload")
        return parsed

    def open_search_snapshot(self, topic: str) -> dict[str, Any]:
        status = self.request("GET", "/v1/status")
        if status.get("connection_mode") != "managed":
            raise SignalTubeBrowserLabError(
                "SignalTube lab discovery requires Browser Brain managed mode, not existing_session"
            )
        url = build_search_url(topic)
        self.request("POST", "/v1/start", {})
        tab_payload = self.request("POST", "/v1/tabs/open", {"url": url})
        tab = tab_payload.get("tab")
        if not isinstance(tab, dict) or not tab.get("tab_id"):
            raise SignalTubeBrowserLabError("Browser Brain did not return a usable tab")
        tab_id = str(tab["tab_id"])
        self.request("POST", "/v1/wait", {"tab_id": tab_id, "condition": "load_state", "value": "domcontentloaded"})
        try:
            self.request("POST", "/v1/wait", {"tab_id": tab_id, "condition": "text", "value": "Sign in", "timeout_ms": 10000})
        except SignalTubeBrowserLabError:
            pass
        return self.request("POST", "/v1/snapshot", {"tab_id": tab_id})


def build_search_url(topic: str) -> str:
    query = topic.strip()
    if not query:
        raise ValueError("topic must not be empty")
    return f"{YOUTUBE_SEARCH_URL}?{urllib.parse.urlencode({'search_query': query})}"


def extract_video_candidates(
    snapshot: dict[str, Any],
    *,
    topic: str,
    max_candidates: int = 40,
    require_logged_out_marker: bool = True,
) -> list[VideoCandidate]:
    elements = snapshot.get("elements")
    if not isinstance(elements, list):
        raise SignalTubeBrowserLabError("Browser Brain snapshot did not include elements")
    if _looks_logged_in(elements):
        raise SignalTubeBrowserLabError("Refusing logged-in YouTube browser state for SignalTube lab discovery")
    if require_logged_out_marker and not _has_logged_out_marker(elements):
        raise SignalTubeBrowserLabError("Could not verify logged-out YouTube state from the snapshot")

    candidates: list[VideoCandidate] = []
    seen: set[str] = set()
    for element in elements:
        if not isinstance(element, dict):
            continue
        href = str(element.get("href") or "")
        video_id = extract_video_id(href)
        if not video_id or video_id in seen:
            continue
        title = _clean_text(str(element.get("name") or element.get("text") or ""))
        if not _looks_like_video_title(title):
            continue
        seen.add(video_id)
        candidates.append(
            VideoCandidate(
                video_id=video_id,
                url=f"https://www.youtube.com/watch?v={video_id}",
                title=title,
                metadata_text=_clean_text(str(element.get("text") or "")),
                source_topic=topic.strip(),
            )
        )
        if len(candidates) >= max_candidates:
            break
    return candidates


def extract_video_id(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    if host not in {"youtube.com", "m.youtube.com", "youtu.be"}:
        return ""
    if SHORTS_PATH in parsed.path:
        return ""
    if host == "youtu.be":
        candidate = parsed.path.strip("/").split("/", 1)[0]
        return candidate if VIDEO_ID_RE.fullmatch(candidate) else ""
    if parsed.path != "/watch":
        return ""
    values = urllib.parse.parse_qs(parsed.query).get("v") or []
    candidate = values[0] if values else ""
    return candidate if VIDEO_ID_RE.fullmatch(candidate) else ""


def _looks_logged_in(elements: list[Any]) -> bool:
    markers = ("account menu", "your channel", "switch account", "sign out")
    for element in elements:
        text = _element_blob(element)
        if any(marker in text for marker in markers):
            return True
    return False


def _has_logged_out_marker(elements: list[Any]) -> bool:
    for element in elements:
        text = _element_blob(element)
        href = str(element.get("href") or "").lower() if isinstance(element, dict) else ""
        if "sign in" in text or "accounts.google.com" in href:
            return True
    return False


def _element_blob(element: Any) -> str:
    if not isinstance(element, dict):
        return ""
    parts = (
        str(element.get("name") or ""),
        str(element.get("text") or ""),
        str(element.get("aria_label") or ""),
        str(element.get("title") or ""),
    )
    return " ".join(parts).lower()


def _clean_text(value: str) -> str:
    return " ".join(value.split()).strip()


def _looks_like_video_title(title: str) -> bool:
    if len(title) < 4:
        return False
    lowered = title.lower()
    blocked = {"youtube", "home", "shorts", "subscriptions", "history", "sign in"}
    return lowered not in blocked
