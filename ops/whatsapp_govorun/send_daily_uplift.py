#!/usr/bin/env python3
"""Send a daily Russian morning message to a WhatsApp chat via local bridge API."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]


UPLIFTING_FACTS_RU = [
    "Солнечный свет утром помогает организму мягко проснуться и поддерживает более стабильное настроение в течение дня.",
    "Даже одна искренняя улыбка близкому человеку часто возвращается добром и делает день теплее.",
    "Короткая прогулка на свежем воздухе помогает снизить напряжение и почувствовать больше внутренней лёгкости.",
    "Небольшой акт доброты сегодня может стать для кого-то главным светлым моментом дня.",
    "Музыка, которая нравится, способна заметно поднять настроение всего за несколько минут.",
    "Регулярный качественный сон связан с более устойчивым эмоциональным состоянием и ощущением бодрости.",
    "Моменты благодарности помогают замечать хорошее вокруг и усиливают чувство радости от простых вещей.",
]


def now_in_tz(tz_name: str) -> datetime:
    if ZoneInfo is not None:
        try:
            return datetime.now(ZoneInfo(tz_name))
        except Exception:
            pass
    return datetime.now()


def build_daily_message(group_name: str, now_dt: datetime) -> str:
    fact = UPLIFTING_FACTS_RU[now_dt.toordinal() % len(UPLIFTING_FACTS_RU)]
    return (
        f"Доброе утро, {group_name}! ☀️\n\n"
        f"Даю справку: {fact}"
    )


def build_payload(chat_id: Optional[str], chat_jid: Optional[str], text: str) -> dict[str, str]:
    payload: dict[str, str] = {"text": text}
    if chat_jid:
        payload["chat_jid"] = chat_jid
    elif chat_id:
        payload["chat_id"] = chat_id
    else:
        raise ValueError("chat destination is required")
    return payload


def send_message(api_base: str, auth_token: str, payload: dict[str, str]) -> dict[str, object]:
    endpoint = f"{api_base.rstrip('/')}/messages"
    request = Request(endpoint, data=json.dumps(payload).encode("utf-8"), method="POST")
    request.add_header("Content-Type", "application/json")
    if auth_token:
        request.add_header("Authorization", f"Bearer {auth_token}")
    try:
        with urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")
        except Exception:
            detail = ""
        raise RuntimeError(f"HTTP {exc.code}: {detail or exc.reason}") from exc
    except URLError as exc:
        raise RuntimeError(f"URL error: {exc}") from exc

    if not body:
        return {"ok": True}
    decoded = json.loads(body)
    if not isinstance(decoded, dict):
        raise RuntimeError("unexpected JSON response type")
    if decoded.get("ok") is False:
        raise RuntimeError(str(decoded.get("description") or "unknown bridge error"))
    return decoded


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send daily uplifting WhatsApp message (RU).")
    parser.add_argument("--chat-id", default=os.getenv("WA_DAILY_UPLIFT_CHAT_ID", "").strip())
    parser.add_argument("--chat-jid", default=os.getenv("WA_DAILY_UPLIFT_CHAT_JID", "").strip())
    parser.add_argument("--test", action="store_true", help="Wrap payload as 1:1 preview text.")
    parser.add_argument("--dry-run", action="store_true", help="Print message without sending.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api_base = os.getenv("WA_DAILY_UPLIFT_API_BASE", "http://127.0.0.1:8787").strip()
    auth_token = os.getenv("WA_DAILY_UPLIFT_AUTH_TOKEN", "").strip()
    tz_name = os.getenv("WA_DAILY_UPLIFT_TZ", "Australia/Brisbane").strip()
    group_name = os.getenv("WA_DAILY_UPLIFT_GROUP_NAME", "Путиловы").strip() or "Путиловы"

    now_dt = now_in_tz(tz_name)
    daily_message = build_daily_message(group_name, now_dt)
    text = daily_message
    if args.test:
        text = (
            "Тест 1:1. Так будет выглядеть ежедневное сообщение в 09:00 для группы:\n\n"
            f"{daily_message}"
        )

    if args.dry_run:
        print(text)
        return 0

    payload = build_payload(args.chat_id or None, args.chat_jid or None, text)
    response = send_message(api_base, auth_token, payload)
    print(json.dumps({"sent": True, "payload": payload, "response": response}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"send_daily_uplift failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
