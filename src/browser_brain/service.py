from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import BrowserBrainConfig


COLLECT_ELEMENTS_JS = r"""
() => {
  const normalize = (value) => (value || "").replace(/\s+/g, " ").trim();
  const isVisible = (element) => {
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    if (style.display === "none" || style.visibility === "hidden") {
      return false;
    }
    return rect.width > 0 && rect.height > 0;
  };
  const inferRole = (element) => {
    const explicit = normalize(element.getAttribute("role"));
    if (explicit) {
      return explicit;
    }
    const tag = element.tagName.toLowerCase();
    if (tag === "a" && element.href) {
      return "link";
    }
    if (tag === "button") {
      return "button";
    }
    if (tag === "textarea") {
      return "textbox";
    }
    if (tag === "select") {
      return "combobox";
    }
    if (tag === "summary") {
      return "button";
    }
    if (tag === "input") {
      const inputType = normalize(element.getAttribute("type")).toLowerCase();
      if (["button", "submit", "reset"].includes(inputType)) {
        return "button";
      }
      if (["checkbox"].includes(inputType)) {
        return "checkbox";
      }
      if (["radio"].includes(inputType)) {
        return "radio";
      }
      return "textbox";
    }
    if (element.isContentEditable) {
      return "textbox";
    }
    return "";
  };
  const actionTags = new Set(["a", "button", "input", "select", "textarea", "summary"]);
  const actionRoles = new Set(["button", "link", "textbox", "combobox", "checkbox", "radio", "switch", "tab", "menuitem", "option"]);
  const describe = (element) => {
    const tag = element.tagName.toLowerCase();
    const text = normalize(element.innerText || element.textContent || "");
    const ariaLabel = normalize(element.getAttribute("aria-label"));
    const placeholder = normalize(element.getAttribute("placeholder"));
    const title = normalize(element.getAttribute("title"));
    const alt = normalize(element.getAttribute("alt"));
    const value = normalize(element.value);
    const name = ariaLabel || alt || title || placeholder || text || value;
    const role = inferRole(element);
    return {
      tag,
      role,
      name,
      text,
      visible: isVisible(element),
      enabled: !(element.disabled || normalize(element.getAttribute("aria-disabled")).toLowerCase() === "true"),
      input_type: tag === "input" ? normalize(element.getAttribute("type")).toLowerCase() : "",
      placeholder,
      title,
      href: tag === "a" ? normalize(element.href) : "",
      aria_label: ariaLabel,
      content_editable: element.isContentEditable,
    };
  };
  const candidates = Array.from(document.querySelectorAll("a,button,input,select,textarea,summary,[role],[contenteditable='true'],[contenteditable='']"));
  const results = [];
  for (const element of candidates) {
    const info = describe(element);
    if (!actionTags.has(info.tag) && !actionRoles.has(info.role)) {
      continue;
    }
    if (!info.name && !info.text && !info.role) {
      continue;
    }
    results.push(info);
  }
  return results;
}
"""


FIND_ELEMENT_JS = r"""
(fingerprint) => {
  const normalize = (value) => (value || "").replace(/\s+/g, " ").trim().toLowerCase();
  const isVisible = (element) => {
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    if (style.display === "none" || style.visibility === "hidden") {
      return false;
    }
    return rect.width > 0 && rect.height > 0;
  };
  const inferRole = (element) => {
    const explicit = normalize(element.getAttribute("role"));
    if (explicit) {
      return explicit;
    }
    const tag = element.tagName.toLowerCase();
    if (tag === "a" && element.href) return "link";
    if (tag === "button") return "button";
    if (tag === "textarea") return "textbox";
    if (tag === "select") return "combobox";
    if (tag === "summary") return "button";
    if (tag === "input") {
      const inputType = normalize(element.getAttribute("type"));
      if (["button", "submit", "reset"].includes(inputType)) return "button";
      if (["checkbox"].includes(inputType)) return "checkbox";
      if (["radio"].includes(inputType)) return "radio";
      return "textbox";
    }
    if (element.isContentEditable) return "textbox";
    return "";
  };
  const describe = (element) => {
    const tag = element.tagName.toLowerCase();
    const text = normalize(element.innerText || element.textContent || "");
    const ariaLabel = normalize(element.getAttribute("aria-label"));
    const placeholder = normalize(element.getAttribute("placeholder"));
    const title = normalize(element.getAttribute("title"));
    const alt = normalize(element.getAttribute("alt"));
    const value = normalize(element.value);
    const name = ariaLabel || alt || title || placeholder || text || value;
    const role = inferRole(element);
    return {
      tag,
      role,
      name,
      text,
      visible: isVisible(element),
      enabled: !(element.disabled || normalize(element.getAttribute("aria-disabled")) === "true"),
      input_type: tag === "input" ? normalize(element.getAttribute("type")) : "",
      placeholder,
      title,
      href: tag === "a" ? normalize(element.href) : "",
      aria_label: ariaLabel,
      content_editable: element.isContentEditable,
    };
  };
  const candidates = Array.from(document.querySelectorAll("a,button,input,select,textarea,summary,[role],[contenteditable='true'],[contenteditable='']"));
  let best = null;
  let bestScore = -1;
  let secondScore = -1;
  for (const candidate of candidates) {
    const info = describe(candidate);
    let score = 0;
    if (fingerprint.frame_id && normalize(fingerprint.frame_id) !== normalize(window.location.href)) {
      // Python binds per-frame. Keep JS generic.
    }
    if (normalize(fingerprint.tag) && normalize(fingerprint.tag) === info.tag) score += 2;
    if (normalize(fingerprint.role) && normalize(fingerprint.role) === info.role) score += 5;
    if (normalize(fingerprint.name) && normalize(fingerprint.name) === info.name) score += 7;
    if (normalize(fingerprint.text) && normalize(fingerprint.text) === info.text) score += 4;
    if (normalize(fingerprint.input_type) && normalize(fingerprint.input_type) === info.input_type) score += 3;
    if (normalize(fingerprint.placeholder) && normalize(fingerprint.placeholder) === normalize(info.placeholder)) score += 2;
    if (normalize(fingerprint.title) && normalize(fingerprint.title) === normalize(info.title)) score += 1;
    if (normalize(fingerprint.href) && normalize(fingerprint.href) === normalize(info.href)) score += 2;
    if (fingerprint.visible === info.visible) score += 1;
    if (fingerprint.enabled === info.enabled) score += 1;
    if (score > bestScore) {
      secondScore = bestScore;
      bestScore = score;
      best = candidate;
    } else if (score > secondScore) {
      secondScore = score;
    }
  }
  if (bestScore < 7) {
    return null;
  }
  if (bestScore === secondScore) {
    return null;
  }
  return best;
}
"""


class BrowserBrainError(RuntimeError):
    def __init__(self, code: str, message: str, *, status: int = 400, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        payload = {"error": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


@dataclass
class SnapshotElement:
    ref: str
    frame_id: str
    frame_name: str
    tag: str
    role: str
    name: str
    text: str
    visible: bool
    enabled: bool
    input_type: str
    placeholder: str
    title: str
    href: str
    aria_label: str
    content_editable: bool

    def public_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "frame_id": self.frame_id,
            "frame_name": self.frame_name,
            "tag": self.tag,
            "role": self.role,
            "name": self.name,
            "text": self.text,
            "visible": self.visible,
            "enabled": self.enabled,
            "input_type": self.input_type,
            "placeholder": self.placeholder,
            "title": self.title,
            "href": self.href,
            "aria_label": self.aria_label,
            "content_editable": self.content_editable,
        }


@dataclass
class SnapshotRecord:
    snapshot_id: str
    tab_id: str
    created_at: str
    elements: dict[str, SnapshotElement] = field(default_factory=dict)


class BrowserBrainService:
    def __init__(self, config: BrowserBrainConfig) -> None:
        self.config = config
        self._lock = threading.RLock()
        self._playwright = None
        self._browser = None
        self._started_at: datetime | None = None
        self._tab_ids: dict[int, str] = {}
        self._snapshots_by_tab: dict[str, SnapshotRecord] = {}

    def status(self, _payload: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            tabs = self._tab_payloads() if self._browser is not None else []
            return {
                "service": "server3-browser-brain",
                "running": self._managed_browser_alive(),
                "headless": self.config.headless,
                "browser_executable": self.config.browser_executable,
                "user_data_dir": str(self.config.browser_user_data_dir),
                "capture_dir": str(self.config.capture_dir),
                "started_at": self._started_at.isoformat() if self._started_at else None,
                "tabs": tabs,
            }

    def start(self, _payload: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            if self._browser is not None and self._managed_browser_alive():
                return self.status()
            if self._browser is not None:
                self._shutdown_browser()
            self._ensure_paths()
            self._cleanup_old_captures()
            self._launch_browser()
            self._log_action("start", {"headless": self.config.headless})
            return self.status()

    def stop(self, _payload: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            self._shutdown_browser()
            self._snapshots_by_tab.clear()
            self._tab_ids.clear()
            self._log_action("stop", {})
            return {"service": "server3-browser-brain", "running": False}

    def tabs_list(self, _payload: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            self._ensure_started()
            return {"tabs": self._tab_payloads()}

    def tabs_open(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = str(payload.get("url") or "about:blank")
        with self._lock:
            self._ensure_started()
            page = self._create_page(url)
            tab = self._tab_payload(page)
            self._log_action("tabs.open", {"tab_id": tab["tab_id"], "url": url})
            return {"tab": tab}

    def tabs_focus(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            page = self._page_for_payload(payload)
            page.bring_to_front()
            tab = self._tab_payload(page)
            self._log_action("tabs.focus", {"tab_id": tab["tab_id"]})
            return {"tab": tab}

    def tabs_close(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            page = self._page_for_payload(payload)
            tab_id = self._tab_id(page)
            page.close(run_before_unload=False)
            self._snapshots_by_tab.pop(tab_id, None)
            self._log_action("tabs.close", {"tab_id": tab_id})
            return {"closed_tab_id": tab_id}

    def navigate(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = str(payload.get("url") or "")
        if not url:
            raise BrowserBrainError("missing_url", "navigate requires a url")
        with self._lock:
            page = self._page_for_payload(payload)
            page.goto(url, wait_until="domcontentloaded", timeout=self.config.action_timeout_ms)
            tab = self._tab_payload(page)
            self._log_action("navigate", {"tab_id": tab["tab_id"], "url": url})
            return {"tab": tab}

    def snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            page = self._page_for_payload(payload)
            page.wait_for_load_state("domcontentloaded", timeout=self.config.action_timeout_ms)
            snapshot = self._build_snapshot(page)
            self._snapshots_by_tab[snapshot.tab_id] = snapshot
            tab = self._tab_payload(page)
            self._log_action("snapshot", {"tab_id": tab["tab_id"], "snapshot_id": snapshot.snapshot_id, "elements": len(snapshot.elements)})
            return {
                "tab": tab,
                "snapshot_id": snapshot.snapshot_id,
                "created_at": snapshot.created_at,
                "elements": [element.public_dict() for element in snapshot.elements.values()],
            }

    def screenshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        label = str(payload.get("label") or "capture")
        with self._lock:
            page = self._page_for_payload(payload)
            self._ensure_paths()
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            safe_label = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in label)[:40] or "capture"
            file_path = self.config.capture_dir / f"{timestamp}-{safe_label}.png"
            page.screenshot(path=str(file_path), full_page=bool(payload.get("full_page", True)))
            self._log_action("screenshot", {"tab_id": self._tab_id(page), "path": str(file_path)})
            return {"tab_id": self._tab_id(page), "path": str(file_path)}

    def wait(self, payload: dict[str, Any]) -> dict[str, Any]:
        condition = str(payload.get("condition") or "")
        value = str(payload.get("value") or "")
        timeout_ms = int(payload.get("timeout_ms") or self.config.action_timeout_ms)
        with self._lock:
            page = self._page_for_payload(payload)
            if condition == "load_state":
                state = value or "domcontentloaded"
                page.wait_for_load_state(state, timeout=timeout_ms)
            elif condition == "url_contains":
                if not value:
                    raise BrowserBrainError("missing_value", "wait url_contains requires value")
                page.wait_for_function("(expected) => window.location.href.includes(expected)", value, timeout=timeout_ms)
            elif condition == "text":
                if not value:
                    raise BrowserBrainError("missing_value", "wait text requires value")
                page.wait_for_function(
                    "(expected) => document.body && document.body.innerText && document.body.innerText.includes(expected)",
                    value,
                    timeout=timeout_ms,
                )
            else:
                raise BrowserBrainError(
                    "unsupported_wait_condition",
                    "wait condition must be one of: load_state, url_contains, text",
                )
            self._log_action("wait", {"tab_id": self._tab_id(page), "condition": condition, "value": value})
            return {"tab": self._tab_payload(page), "condition": condition, "value": value, "ok": True}

    def act_click(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            page = self._page_for_payload(payload)
            element = self._resolve_element(page, payload)
            element.click(timeout=self.config.action_timeout_ms)
            self._log_action("act.click", {"tab_id": self._tab_id(page), "ref": payload.get("ref")})
            return {"tab": self._tab_payload(page), "ref": payload.get("ref"), "ok": True}

    def act_type(self, payload: dict[str, Any]) -> dict[str, Any]:
        text = str(payload.get("text") or "")
        if text == "":
            raise BrowserBrainError("missing_text", "act.type requires text")
        with self._lock:
            page = self._page_for_payload(payload)
            element = self._resolve_element(page, payload)
            try:
                element.fill(text, timeout=self.config.action_timeout_ms)
            except Exception:
                element.click(timeout=self.config.action_timeout_ms)
                element.type(text, timeout=self.config.action_timeout_ms)
            self._log_action("act.type", {"tab_id": self._tab_id(page), "ref": payload.get("ref"), "text_length": len(text)})
            return {"tab": self._tab_payload(page), "ref": payload.get("ref"), "ok": True}

    def act_press(self, payload: dict[str, Any]) -> dict[str, Any]:
        key = str(payload.get("key") or "")
        if not key:
            raise BrowserBrainError("missing_key", "act.press requires key")
        with self._lock:
            page = self._page_for_payload(payload)
            if payload.get("ref"):
                element = self._resolve_element(page, payload)
                element.focus()
            page.keyboard.press(key, timeout=self.config.action_timeout_ms)
            self._log_action("act.press", {"tab_id": self._tab_id(page), "key": key, "ref": payload.get("ref")})
            return {"tab": self._tab_payload(page), "key": key, "ok": True}

    def _ensure_started(self) -> None:
        if self._browser is None or not self._managed_browser_alive():
            self.start()

    def _managed_browser_alive(self) -> bool:
        if self._browser is None:
            return False
        try:
            self._browser.pages
        except Exception:
            return False
        return True

    def _ensure_paths(self) -> None:
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        self.config.capture_dir.mkdir(parents=True, exist_ok=True)
        self.config.browser_user_data_dir.mkdir(parents=True, exist_ok=True)

    def _launch_browser(self) -> None:
        if not Path(self.config.browser_executable).exists():
            raise BrowserBrainError(
                "browser_executable_missing",
                f"Browser executable not found: {self.config.browser_executable}",
                status=500,
            )
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BrowserBrainError(
                "playwright_missing",
                "playwright is not installed for server3-browser-brain",
                status=500,
                details={"hint": "Run ops/browser_brain/install_runtime_venv.sh to provision the runtime venv."},
            ) from exc

        args = [
            "--no-default-browser-check",
            "--no-first-run",
            "--disable-background-networking",
            "--disable-sync",
            "--disable-component-update",
        ]
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch_persistent_context(
            str(self.config.browser_user_data_dir),
            executable_path=self.config.browser_executable,
            headless=self.config.headless,
            args=args,
        )
        self._started_at = datetime.now(timezone.utc)
        if not self._browser.pages:
            self._create_page("about:blank")

    def _shutdown_browser(self) -> None:
        browser = self._browser
        playwright = self._playwright
        self._browser = None
        self._playwright = None
        self._started_at = None
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                pass

    def _default_context(self):
        if self._browser is None:
            raise BrowserBrainError("browser_not_running", "Browser is not running", status=503)
        return self._browser

    def _live_pages(self):
        context = self._default_context()
        return [page for page in context.pages if not page.is_closed()]

    def _create_page(self, url: str):
        context = self._default_context()
        page = context.new_page()
        if url and url != "about:blank":
            page.goto(url, wait_until="domcontentloaded", timeout=self.config.action_timeout_ms)
        return page

    def _tab_id(self, page) -> str:
        key = id(page)
        if key not in self._tab_ids:
            self._tab_ids[key] = f"tab-{uuid.uuid4().hex[:8]}"
        return self._tab_ids[key]

    def _tab_payload(self, page) -> dict[str, Any]:
        title = ""
        try:
            title = page.title()
        except Exception:
            title = ""
        return {
            "tab_id": self._tab_id(page),
            "url": page.url,
            "title": title,
        }

    def _tab_payloads(self) -> list[dict[str, Any]]:
        payloads = [self._tab_payload(page) for page in self._live_pages()]
        live_ids = {id(page) for page in self._live_pages()}
        self._tab_ids = {key: value for key, value in self._tab_ids.items() if key in live_ids}
        return payloads

    def _page_for_payload(self, payload: dict[str, Any]):
        self._ensure_started()
        tab_id = str(payload.get("tab_id") or "")
        if not tab_id:
            pages = self._live_pages()
            if not pages:
                raise BrowserBrainError("tab_not_found", "No live tabs are available")
            return pages[0]
        for page in self._live_pages():
            if self._tab_id(page) == tab_id:
                return page
        raise BrowserBrainError("tab_not_found", f"Unknown tab_id: {tab_id}", details={"tab_id": tab_id})

    def _build_snapshot(self, page) -> SnapshotRecord:
        snapshot_id = f"snap-{uuid.uuid4().hex[:8]}"
        created_at = datetime.now(timezone.utc).isoformat()
        elements: dict[str, SnapshotElement] = {}
        index = 0
        for frame in page.frames:
            frame_id = frame.url or "about:blank"
            frame_name = frame.name or ""
            try:
                candidates = frame.evaluate(COLLECT_ELEMENTS_JS)
            except Exception:
                continue
            for candidate in candidates:
                index += 1
                ref = f"el-{index:04d}"
                element = SnapshotElement(
                    ref=ref,
                    frame_id=frame_id,
                    frame_name=frame_name,
                    tag=str(candidate.get("tag") or ""),
                    role=str(candidate.get("role") or ""),
                    name=str(candidate.get("name") or ""),
                    text=str(candidate.get("text") or ""),
                    visible=bool(candidate.get("visible")),
                    enabled=bool(candidate.get("enabled")),
                    input_type=str(candidate.get("input_type") or ""),
                    placeholder=str(candidate.get("placeholder") or ""),
                    title=str(candidate.get("title") or ""),
                    href=str(candidate.get("href") or ""),
                    aria_label=str(candidate.get("aria_label") or ""),
                    content_editable=bool(candidate.get("content_editable")),
                )
                elements[ref] = element
        return SnapshotRecord(snapshot_id=snapshot_id, tab_id=self._tab_id(page), created_at=created_at, elements=elements)

    def _resolve_element(self, page, payload: dict[str, Any]):
        snapshot = self._snapshot_for_payload(payload)
        ref = str(payload.get("ref") or "")
        if not ref:
            raise BrowserBrainError("missing_ref", "Action requires ref from snapshot")
        element = snapshot.elements.get(ref)
        if element is None:
            raise BrowserBrainError(
                "unknown_ref",
                f"Unknown ref: {ref}",
                details={"snapshot_id": snapshot.snapshot_id, "tab_id": snapshot.tab_id},
            )
        target = self._find_element(page, element)
        if target is None:
            refreshed = self._build_snapshot(page)
            self._snapshots_by_tab[refreshed.tab_id] = refreshed
            target = self._find_element(page, element)
            if target is None:
                raise BrowserBrainError(
                    "stale_target",
                    "Snapshot ref no longer resolves cleanly. Re-run snapshot before acting again.",
                    details={"tab_id": snapshot.tab_id, "snapshot_id": snapshot.snapshot_id, "ref": ref},
                )
        return target

    def _snapshot_for_payload(self, payload: dict[str, Any]) -> SnapshotRecord:
        tab_id = str(payload.get("tab_id") or "")
        snapshot_id = str(payload.get("snapshot_id") or "")
        if not tab_id or not snapshot_id:
            raise BrowserBrainError("missing_snapshot_context", "Action requires tab_id and snapshot_id")
        snapshot = self._snapshots_by_tab.get(tab_id)
        if snapshot is None or snapshot.snapshot_id != snapshot_id:
            raise BrowserBrainError(
                "snapshot_mismatch",
                "No matching snapshot is stored for this tab",
                details={"tab_id": tab_id, "snapshot_id": snapshot_id},
            )
        return snapshot

    def _find_element(self, page, element: SnapshotElement):
        for frame in page.frames:
            if (frame.url or "about:blank") != element.frame_id:
                continue
            try:
                handle = frame.evaluate_handle(FIND_ELEMENT_JS, element.public_dict())
            except Exception:
                continue
            resolved = handle.as_element() if handle is not None else None
            if resolved is not None:
                return resolved
        return None

    def _cleanup_old_captures(self) -> None:
        if not self.config.capture_dir.exists():
            return
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.config.screenshot_ttl_hours)
        for path in self.config.capture_dir.glob("*.png"):
            try:
                modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            except OSError:
                continue
            if modified < cutoff:
                try:
                    path.unlink()
                except OSError:
                    continue

    def _log_action(self, action: str, fields: dict[str, Any]) -> None:
        if not self.config.log_actions:
            return
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "service": "server3-browser-brain",
            "action": action,
        }
        payload.update(fields)
        print(json.dumps(payload, sort_keys=True), flush=True)
