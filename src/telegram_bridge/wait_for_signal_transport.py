#!/usr/bin/env python3
"""Wait for the local Signal transport bridge to expose a healthy HTTP API."""

from __future__ import annotations

import os
import sys
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import urlopen

DEFAULT_BASE_URL = "http://127.0.0.1:18797"
DEFAULT_TIMEOUT_SECONDS = 45.0
DEFAULT_INTERVAL_SECONDS = 1.0

def build_health_url(base_url: str) -> str:
    parsed = urlparse((base_url or "").strip() or DEFAULT_BASE_URL)
    path = parsed.path.rstrip("/")
    if not path:
        path = "/health"
    elif path != "/health":
        path = f"{path}/health"
    return urlunparse(parsed._replace(path=path, params="", query="", fragment=""))

def wait_for_signal_transport(
    health_url: str,
    timeout_seconds: float,
    interval_seconds: float,
    *,
    opener: Callable[..., object] = urlopen,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> bool:
    deadline = monotonic() + max(0.0, timeout_seconds)
    while monotonic() < deadline:
        try:
            with opener(health_url, timeout=2) as response:
                status = getattr(response, "status", 200)
                if 200 <= int(status) < 300:
                    return True
        except (HTTPError, URLError, OSError, ValueError):
            pass
        sleep(max(0.0, interval_seconds))
    return False

def main() -> int:
    base_url = os.getenv("SIGNAL_BRIDGE_API_BASE", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
    health_url = build_health_url(base_url)
    timeout_seconds = float(
        os.getenv("SIGNAL_BRIDGE_READY_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)).strip()
        or DEFAULT_TIMEOUT_SECONDS
    )
    interval_seconds = float(
        os.getenv("SIGNAL_BRIDGE_READY_INTERVAL_SECONDS", str(DEFAULT_INTERVAL_SECONDS)).strip()
        or DEFAULT_INTERVAL_SECONDS
    )
    if wait_for_signal_transport(health_url, timeout_seconds, interval_seconds):
        return 0
    print(
        f"Signal transport did not become ready before timeout: url={health_url} timeout={timeout_seconds}s",
        file=sys.stderr,
    )
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
