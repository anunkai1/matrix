from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from fnmatch import fnmatch
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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
    locator_kind: str = ""
    locator_value: str = ""
    locator_selector: str = ""

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
            "locator_kind": self.locator_kind,
            "locator_value": self.locator_value,
            "locator_selector": self.locator_selector,
        }


@dataclass
class SnapshotRecord:
    snapshot_id: str
    tab_id: str
    created_at: str
    aria_snapshot: str = ""
    elements: dict[str, SnapshotElement] = field(default_factory=dict)


class BrowserBrainService:
    def __init__(self, config: BrowserBrainConfig) -> None:
        self.config = config
        self._lock = threading.RLock()
        self._playwright = None
        self._browser = None
        self._browser_connection = None
        self._started_at: datetime | None = None
        self._tab_ids: dict[int, str] = {}
        self._snapshots_by_tab: dict[str, SnapshotRecord] = {}
        self._observed_pages: set[int] = set()
        self._console_messages_by_tab: dict[str, list[dict[str, Any]]] = {}
        self._network_events_by_tab: dict[str, list[dict[str, Any]]] = {}
        self._dialogs_by_tab: dict[str, Any] = {}
        self._next_dialog_policy_by_tab: dict[str, dict[str, Any]] = {}

    def status(self, _payload: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            tabs = self._tab_payloads() if self._browser is not None else []
            return {
                "service": "server3-browser-brain",
                "running": self._managed_browser_alive(),
                "connection_mode": self.config.connection_mode,
                "headless": self.config.headless,
                "browser_executable": self.config.browser_executable,
                "user_data_dir": str(self.config.browser_user_data_dir),
                "capture_dir": str(self.config.capture_dir),
                "cdp_endpoint_url": self.config.cdp_endpoint_url if self.config.connection_mode == "existing_session" else None,
                "navigation_policy": {
                    "allowed_origins": list(self.config.navigation_allowed_origins),
                    "blocked_origins": list(self.config.navigation_blocked_origins),
                    "allow_file_urls": self.config.allow_file_urls,
                },
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
            self._log_action("start", {"headless": self.config.headless, "connection_mode": self.config.connection_mode})
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
        self._validate_navigation_url(url)
        with self._lock:
            self._ensure_started()
            page = self._create_page(url)
            tab = self._tab_payload(page)
            self._validate_navigation_url(tab["url"], after_redirect=True)
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
        self._validate_navigation_url(url)
        with self._lock:
            page = self._page_for_payload(payload)
            page.goto(url, wait_until="domcontentloaded", timeout=self.config.action_timeout_ms)
            tab = self._tab_payload(page)
            self._validate_navigation_url(tab["url"], after_redirect=True)
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
                "aria_snapshot": snapshot.aria_snapshot,
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
                page.wait_for_function("(expected) => window.location.href.includes(expected)", arg=value, timeout=timeout_ms)
            elif condition == "text":
                if not value:
                    raise BrowserBrainError("missing_value", "wait text requires value")
                page.wait_for_function(
                    "(expected) => document.body && document.body.innerText && document.body.innerText.includes(expected)",
                    arg=value,
                    timeout=timeout_ms,
                )
            else:
                raise BrowserBrainError(
                    "unsupported_wait_condition",
                    "wait condition must be one of: load_state, url_contains, text",
                )
            self._log_action("wait", {"tab_id": self._tab_id(page), "condition": condition, "value": value})
            return {"tab": self._tab_payload(page), "condition": condition, "value": value, "ok": True}

    def console_messages(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            page = self._page_for_payload(payload)
            tab_id = self._tab_id(page)
            messages = list(self._console_messages_by_tab.get(tab_id, []))
            limit = int(payload.get("limit") or 50)
            return {"tab": self._tab_payload(page), "messages": messages[-limit:]}

    def network_events(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            page = self._page_for_payload(payload)
            tab_id = self._tab_id(page)
            events = list(self._network_events_by_tab.get(tab_id, []))
            limit = int(payload.get("limit") or 50)
            return {"tab": self._tab_payload(page), "events": events[-limit:]}

    def dialogs_list(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            page = self._page_for_payload(payload)
            tab_id = self._tab_id(page)
            dialog = self._dialogs_by_tab.get(tab_id)
            tab = {"tab_id": tab_id, "url": page.url, "title": ""} if dialog else self._tab_payload(page)
            return {"tab": tab, "dialog": self._dialog_payload(dialog) if dialog else None}

    def dialog_handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        accept = bool(payload.get("accept", True))
        prompt_text = payload.get("prompt_text")
        with self._lock:
            page = self._page_for_payload(payload)
            tab_id = self._tab_id(page)
            self._next_dialog_policy_by_tab[tab_id] = {"accept": accept, "prompt_text": prompt_text}
            self._log_action("dialog.handle.arm", {"tab_id": tab_id, "accept": accept})
            return {
                "tab": self._tab_payload(page),
                "armed": True,
                "accept": accept,
                "last_dialog": self._dialogs_by_tab.get(tab_id),
            }

    def act_click(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            page = self._page_for_payload(payload)
            element = self._resolve_element(page, payload)
            element.click(timeout=self.config.action_timeout_ms)
            self._log_action("act.click", {"tab_id": self._tab_id(page), "ref": payload.get("ref")})
            return {"tab": self._tab_payload(page), "ref": payload.get("ref"), "ok": True}

    def act_hover(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            page = self._page_for_payload(payload)
            element = self._resolve_element(page, payload)
            element.hover(timeout=self.config.action_timeout_ms)
            self._log_action("act.hover", {"tab_id": self._tab_id(page), "ref": payload.get("ref")})
            return {"tab": self._tab_payload(page), "ref": payload.get("ref"), "ok": True}

    def act_select(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw_values = payload.get("values")
        if raw_values is None:
            raw_value = str(payload.get("value") or "").strip()
            if not raw_value:
                raise BrowserBrainError("missing_value", "act.select requires value or values")
            values: str | list[str] = raw_value
        elif isinstance(raw_values, list):
            values = [str(value) for value in raw_values if str(value) != ""]
            if not values:
                raise BrowserBrainError("missing_value", "act.select values must include at least one value")
        else:
            raise BrowserBrainError("invalid_values", "act.select values must be a JSON array")
        with self._lock:
            page = self._page_for_payload(payload)
            element = self._resolve_element(page, payload)
            selected = element.select_option(values, timeout=self.config.action_timeout_ms)
            self._log_action("act.select", {"tab_id": self._tab_id(page), "ref": payload.get("ref"), "selected_count": len(selected)})
            return {"tab": self._tab_payload(page), "ref": payload.get("ref"), "selected": selected, "ok": True}

    def act_type(self, payload: dict[str, Any]) -> dict[str, Any]:
        text = str(payload.get("text") or "")
        if text == "":
            raise BrowserBrainError("missing_text", "act.type requires text")
        with self._lock:
            page = self._page_for_payload(payload)
            element = self._resolve_element(page, payload)
            try:
                # Prefer keyboard-driven entry first because many modern React-style
                # forms discard DOM-level fill() values on rerender or submit.
                element.click(timeout=self.config.action_timeout_ms)
                page.keyboard.press("Control+A")
                page.keyboard.press("Backspace")
                page.keyboard.type(text, delay=20)
            except Exception:
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
            page.keyboard.press(key)
            self._log_action("act.press", {"tab_id": self._tab_id(page), "key": key, "ref": payload.get("ref")})
            return {"tab": self._tab_payload(page), "key": key, "ok": True}

    def act_upload(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw_paths = payload.get("paths")
        if raw_paths is None:
            single_path = str(payload.get("path") or "").strip()
            if not single_path:
                raise BrowserBrainError("missing_path", "act.upload requires path or paths")
            candidate_paths = [single_path]
        elif isinstance(raw_paths, list):
            candidate_paths = [str(item or "").strip() for item in raw_paths]
            if not candidate_paths:
                raise BrowserBrainError("missing_path", "act.upload requires at least one file path")
        else:
            raise BrowserBrainError("invalid_paths", "act.upload paths must be a JSON array of file paths")

        resolved_paths: list[str] = []
        for raw_path in candidate_paths:
            if not raw_path:
                raise BrowserBrainError("invalid_path", "act.upload file paths must be non-empty strings")
            candidate = Path(raw_path).expanduser()
            if not candidate.exists():
                raise BrowserBrainError(
                    "file_not_found",
                    f"Upload file not found: {candidate}",
                    details={"path": str(candidate)},
                )
            if not candidate.is_file():
                raise BrowserBrainError(
                    "invalid_path",
                    f"Upload path is not a file: {candidate}",
                    details={"path": str(candidate)},
                )
            resolved_paths.append(str(candidate.resolve()))

        with self._lock:
            page = self._page_for_payload(payload)
            element = self._resolve_element(page, payload)
            files_arg: str | list[str] = resolved_paths[0] if len(resolved_paths) == 1 else resolved_paths
            try:
                element.set_input_files(files_arg, timeout=self.config.action_timeout_ms)
            except Exception as exc:
                raise BrowserBrainError(
                    "upload_failed",
                    "Failed to set files on the target input element",
                    details={"exception": str(exc), "paths_count": len(resolved_paths)},
                ) from exc
            self._log_action(
                "act.upload",
                {"tab_id": self._tab_id(page), "ref": payload.get("ref"), "paths_count": len(resolved_paths)},
            )
            return {"tab": self._tab_payload(page), "ref": payload.get("ref"), "files": resolved_paths, "ok": True}

    def _ensure_started(self) -> None:
        if self._browser is None or not self._managed_browser_alive():
            self.start()

    def _managed_browser_alive(self) -> bool:
        if self._browser is None:
            return False
        connection = self._browser_connection
        if connection is not None:
            try:
                is_connected = getattr(connection, "is_connected", None)
                if callable(is_connected) and not is_connected():
                    return False
            except Exception:
                return False
        try:
            self._browser.pages
        except Exception:
            return False
        return True

    def _ensure_paths(self) -> None:
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        self.config.capture_dir.mkdir(parents=True, exist_ok=True)
        if self.config.connection_mode == "managed":
            self.config.browser_user_data_dir.mkdir(parents=True, exist_ok=True)
            (self.config.state_dir / "config").mkdir(parents=True, exist_ok=True)
            (self.config.state_dir / "cache").mkdir(parents=True, exist_ok=True)

    def _launch_browser(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BrowserBrainError(
                "playwright_missing",
                "playwright is not installed for server3-browser-brain",
                status=500,
                details={"hint": "Run ops/browser_brain/install_runtime_venv.sh to provision the runtime venv."},
            ) from exc

        self._playwright = sync_playwright().start()
        if self.config.connection_mode == "existing_session":
            self._attach_existing_session_browser()
        else:
            self._launch_managed_browser()
        self._started_at = datetime.now(timezone.utc)
        if not self._browser.pages:
            self._create_page("about:blank")

    def _launch_managed_browser(self) -> None:
        if not Path(self.config.browser_executable).exists():
            raise BrowserBrainError(
                "browser_executable_missing",
                f"Browser executable not found: {self.config.browser_executable}",
                status=500,
            )
        args = [
            "--no-default-browser-check",
            "--no-first-run",
            "--disable-background-networking",
            "--disable-sync",
            "--disable-component-update",
            "--disable-crash-reporter",
            "--disable-crashpad",
        ]
        self._browser = self._playwright.chromium.launch_persistent_context(
            str(self.config.browser_user_data_dir),
            executable_path=self.config.browser_executable,
            headless=self.config.headless,
            args=args,
            env={
                **os.environ,
                "XDG_CONFIG_HOME": str(self.config.state_dir / "config"),
                "XDG_CACHE_HOME": str(self.config.state_dir / "cache"),
            },
        )

    def _attach_existing_session_browser(self) -> None:
        endpoint_url = self.config.cdp_endpoint_url
        try:
            self._browser_connection = self._playwright.chromium.connect_over_cdp(endpoint_url)
        except Exception as exc:
            raise BrowserBrainError(
                "existing_session_unavailable",
                "Could not attach to the existing browser session",
                status=503,
                details={
                    "cdp_endpoint_url": endpoint_url,
                    "hint": "Launch Chrome/Brave with a local --remote-debugging-port and retry.",
                    "exception": str(exc),
                },
            ) from exc
        contexts = list(getattr(self._browser_connection, "contexts", []))
        if contexts:
            self._browser = contexts[0]
            return
        try:
            self._browser = self._browser_connection.new_context()
        except Exception as exc:
            raise BrowserBrainError(
                "existing_session_no_context",
                "Attached browser exposed no usable context",
                status=503,
                details={"cdp_endpoint_url": endpoint_url, "exception": str(exc)},
            ) from exc

    def _shutdown_browser(self) -> None:
        browser = self._browser
        browser_connection = self._browser_connection
        playwright = self._playwright
        self._browser = None
        self._browser_connection = None
        self._playwright = None
        self._started_at = None
        self._observed_pages.clear()
        self._console_messages_by_tab.clear()
        self._network_events_by_tab.clear()
        self._dialogs_by_tab.clear()
        self._next_dialog_policy_by_tab.clear()
        if browser is not None and self.config.connection_mode == "managed":
            try:
                browser.close()
            except Exception:
                pass
        if browser_connection is not None and self.config.connection_mode == "managed":
            try:
                browser_connection.close()
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
        pages = [page for page in context.pages if not page.is_closed()]
        for page in pages:
            self._register_page_observers(page)
        return pages

    def _create_page(self, url: str):
        self._validate_navigation_url(url)
        context = self._default_context()
        page = context.new_page()
        self._register_page_observers(page)
        if url and url != "about:blank":
            page.goto(url, wait_until="domcontentloaded", timeout=self.config.action_timeout_ms)
            self._validate_navigation_url(page.url, after_redirect=True)
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
        live_tab_ids = set(self._tab_ids.values())
        self._console_messages_by_tab = {
            key: value for key, value in self._console_messages_by_tab.items() if key in live_tab_ids
        }
        self._network_events_by_tab = {
            key: value for key, value in self._network_events_by_tab.items() if key in live_tab_ids
        }
        self._dialogs_by_tab = {key: value for key, value in self._dialogs_by_tab.items() if key in live_tab_ids}
        self._next_dialog_policy_by_tab = {
            key: value for key, value in self._next_dialog_policy_by_tab.items() if key in live_tab_ids
        }
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
        aria_snapshot = ""
        try:
            aria_snapshot = str(page.locator("body").aria_snapshot(timeout=self.config.action_timeout_ms) or "")
        except Exception:
            aria_snapshot = ""
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
                element.locator_kind, element.locator_value = self._locator_hint(element)
                element.locator_selector = self._selector_hint(element)
                elements[ref] = element
        return SnapshotRecord(
            snapshot_id=snapshot_id,
            tab_id=self._tab_id(page),
            created_at=created_at,
            aria_snapshot=aria_snapshot,
            elements=elements,
        )

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
            locator = self._locator_for_element(frame, element)
            if locator is not None:
                try:
                    if locator.count() == 1:
                        handle = locator.element_handle(timeout=self.config.action_timeout_ms)
                        if handle is not None:
                            return handle
                except Exception:
                    pass
            try:
                handle = frame.evaluate_handle(FIND_ELEMENT_JS, element.public_dict())
            except Exception:
                continue
            resolved = handle.as_element() if handle is not None else None
            if resolved is not None:
                return resolved
        return None

    def _locator_hint(self, element: SnapshotElement) -> tuple[str, str]:
        if element.role and element.name:
            return "role", f"{element.role}:{element.name}"
        if element.aria_label:
            return "label", element.aria_label
        if element.placeholder:
            return "placeholder", element.placeholder
        if element.title:
            return "title", element.title
        if element.text:
            return "text", element.text
        return "", ""

    def _selector_hint(self, element: SnapshotElement) -> str:
        if element.role and element.name:
            escaped_name = element.name.replace("\\", "\\\\").replace('"', '\\"')
            return f'role={element.role}[name="{escaped_name}"]'
        if element.aria_label:
            escaped = element.aria_label.replace("\\", "\\\\").replace('"', '\\"')
            return f'[aria-label="{escaped}"]'
        return element.tag

    def _locator_for_element(self, frame, element: SnapshotElement):
        if element.role and element.name:
            try:
                return frame.get_by_role(element.role, name=element.name, exact=True)
            except Exception:
                pass
        if element.aria_label:
            try:
                return frame.get_by_label(element.aria_label, exact=True)
            except Exception:
                pass
        if element.placeholder:
            try:
                return frame.get_by_placeholder(element.placeholder, exact=True)
            except Exception:
                pass
        if element.title:
            try:
                return frame.get_by_title(element.title, exact=True)
            except Exception:
                pass
        if element.text and element.tag in {"button", "a", "summary"}:
            try:
                return frame.get_by_text(element.text, exact=True)
            except Exception:
                pass
        return None

    def _register_page_observers(self, page) -> None:
        page_key = id(page)
        if page_key in self._observed_pages:
            return
        self._observed_pages.add(page_key)

        def on_console(message) -> None:
            with self._lock:
                tab_id = self._tab_id(page)
                entry = {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "type": getattr(message, "type", ""),
                    "text": getattr(message, "text", ""),
                    "location": getattr(message, "location", None),
                }
                self._append_limited(self._console_messages_by_tab.setdefault(tab_id, []), entry)

        def on_response(response) -> None:
            with self._lock:
                request = getattr(response, "request", None)
                tab_id = self._tab_id(page)
                entry = {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "method": getattr(request, "method", "") if request is not None else "",
                    "url": getattr(response, "url", ""),
                    "status": getattr(response, "status", None),
                    "resource_type": getattr(request, "resource_type", "") if request is not None else "",
                }
                self._append_limited(self._network_events_by_tab.setdefault(tab_id, []), entry)

        def on_dialog(dialog) -> None:
            with self._lock:
                tab_id = self._tab_id(page)
                payload = self._dialog_payload(dialog)
                policy = self._next_dialog_policy_by_tab.pop(tab_id, {"accept": False, "prompt_text": None})
                accept = bool(policy.get("accept"))
                try:
                    if accept:
                        prompt_text = policy.get("prompt_text")
                        dialog.accept(str(prompt_text)) if prompt_text is not None else dialog.accept()
                    else:
                        dialog.dismiss()
                    payload.update({"handled": True, "accepted": accept})
                except Exception as exc:
                    payload.update({"handled": False, "accepted": accept, "error": str(exc)})
                self._dialogs_by_tab[tab_id] = payload

        try:
            page.on("console", on_console)
            page.on("response", on_response)
            page.on("dialog", on_dialog)
        except Exception:
            self._observed_pages.discard(page_key)

    def _append_limited(self, items: list[dict[str, Any]], entry: dict[str, Any], limit: int = 200) -> None:
        items.append(entry)
        if len(items) > limit:
            del items[: len(items) - limit]

    def _dialog_payload(self, dialog) -> dict[str, Any]:
        if dialog is None:
            return {}
        if isinstance(dialog, dict):
            return dict(dialog)
        return {
            "type": getattr(dialog, "type", ""),
            "message": getattr(dialog, "message", ""),
            "default_value": getattr(dialog, "default_value", ""),
        }

    def _validate_navigation_url(self, url: str, *, after_redirect: bool = False) -> None:
        if not url or url == "about:blank":
            return
        parsed = urlparse(url)
        if parsed.scheme == "about":
            return
        if parsed.scheme == "file" and not self.config.allow_file_urls:
            raise BrowserBrainError(
                "navigation_blocked",
                "Navigation to file URLs is disabled",
                status=403,
                details={"url": url},
            )
        if parsed.scheme and parsed.scheme not in {"http", "https", "file"}:
            raise BrowserBrainError(
                "navigation_blocked",
                f"Navigation scheme is not allowed: {parsed.scheme}",
                status=403,
                details={"url": url},
            )
        origin = self._origin_for_url(url)
        blocked = self._match_origin_policy(origin, self.config.navigation_blocked_origins)
        allowed = not self.config.navigation_allowed_origins or self._match_origin_policy(
            origin,
            self.config.navigation_allowed_origins,
        )
        if blocked or not allowed:
            raise BrowserBrainError(
                "navigation_blocked_after_redirect" if after_redirect else "navigation_blocked",
                "Navigation target is outside Browser Brain policy",
                status=403,
                details={
                    "url": url,
                    "origin": origin,
                    "allowed_origins": list(self.config.navigation_allowed_origins),
                    "blocked_origins": list(self.config.navigation_blocked_origins),
                },
            )

    def _origin_for_url(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme == "file":
            return "file://"
        if not parsed.scheme:
            return ""
        return f"{parsed.scheme}://{parsed.netloc}".lower()

    def _match_origin_policy(self, origin: str, patterns: tuple[str, ...]) -> bool:
        if not patterns:
            return False
        parsed = urlparse(origin)
        host = (parsed.hostname or "").lower()
        for raw_pattern in patterns:
            pattern = raw_pattern.strip().lower()
            if not pattern:
                continue
            if pattern == "*":
                return True
            if pattern == "file://" and origin == "file://":
                return True
            if "://" in pattern:
                if fnmatch(origin, pattern):
                    return True
                continue
            if pattern.startswith("*.") and host.endswith(pattern[1:]):
                return True
            if host == pattern or fnmatch(host, pattern):
                return True
        return False

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
