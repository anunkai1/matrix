#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a Telegram message using TELEGRAM_BOT_TOKEN.")
    parser.add_argument("--chat-id", required=True, type=int)
    parser.add_argument("--thread-id", type=int)
    parser.add_argument("--text", required=True)
    args = parser.parse_args()

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is required")
    api_base = os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/")
    payload = {
        "chat_id": str(args.chat_id),
        "text": args.text,
        "disable_web_page_preview": "true",
    }
    if args.thread_id is not None:
        payload["message_thread_id"] = str(args.thread_id)
    data = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{api_base}/bot{token}/sendMessage",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not body.get("ok", False):
        raise SystemExit(f"Telegram send failed: {body}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
