#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from mavali_eth.config import MavaliEthConfig
from mavali_eth.service import MavaliEthService


def send_telegram_message(api_base: str, token: str, chat_id: int, text: str) -> None:
    payload = urllib.parse.urlencode(
        {
            "chat_id": str(chat_id),
            "text": text,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{api_base}/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not body.get("ok", False):
        raise RuntimeError(f"Telegram send failed: {body}")


def main() -> int:
    config = MavaliEthConfig.from_env()
    if not config.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is required for receipt monitoring.")
    if config.telegram_owner_chat_id is None:
        raise SystemExit("MAVALI_ETH_TELEGRAM_OWNER_CHAT_ID is required for receipt monitoring.")
    service = MavaliEthService(config)
    notifications = service.poll_inbound_transfers()
    for item in notifications:
        send_telegram_message(
            config.telegram_api_base,
            config.telegram_bot_token,
            config.telegram_owner_chat_id,
            item.message,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
