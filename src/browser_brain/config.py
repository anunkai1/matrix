from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_int(value: str | None, default: int) -> int:
    if value is None or value.strip() == "":
        return default
    return int(value)


@dataclass(frozen=True)
class BrowserBrainConfig:
    host: str = "127.0.0.1"
    port: int = 47831
    browser_executable: str = "/usr/bin/brave-browser"
    browser_user_data_dir: Path = Path("/var/lib/server3-browser-brain/profile")
    state_dir: Path = Path("/var/lib/server3-browser-brain")
    capture_dir: Path = Path("/var/lib/server3-browser-brain/captures")
    remote_debugging_port: int = 9223
    startup_timeout_seconds: int = 20
    action_timeout_ms: int = 7000
    screenshot_ttl_hours: int = 24
    headless: bool = True
    log_actions: bool = True

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "BrowserBrainConfig":
        values = dict(os.environ if env is None else env)
        state_dir = Path(values.get("BROWSER_BRAIN_STATE_DIR", "/var/lib/server3-browser-brain"))
        capture_dir = Path(values.get("BROWSER_BRAIN_CAPTURE_DIR", str(state_dir / "captures")))
        profile_dir = Path(values.get("BROWSER_BRAIN_PROFILE_DIR", str(state_dir / "profile")))
        return cls(
            host=values.get("BROWSER_BRAIN_HOST", "127.0.0.1"),
            port=_parse_int(values.get("BROWSER_BRAIN_PORT"), 47831),
            browser_executable=values.get("BROWSER_BRAIN_BROWSER_EXECUTABLE", "/usr/bin/brave-browser"),
            browser_user_data_dir=profile_dir,
            state_dir=state_dir,
            capture_dir=capture_dir,
            remote_debugging_port=_parse_int(values.get("BROWSER_BRAIN_REMOTE_DEBUGGING_PORT"), 9223),
            startup_timeout_seconds=_parse_int(values.get("BROWSER_BRAIN_STARTUP_TIMEOUT_SECONDS"), 20),
            action_timeout_ms=_parse_int(values.get("BROWSER_BRAIN_ACTION_TIMEOUT_MS"), 7000),
            screenshot_ttl_hours=_parse_int(values.get("BROWSER_BRAIN_SCREENSHOT_TTL_HOURS"), 24),
            headless=_parse_bool(values.get("BROWSER_BRAIN_HEADLESS"), True),
            log_actions=_parse_bool(values.get("BROWSER_BRAIN_LOG_ACTIONS"), True),
        )
