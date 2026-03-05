#!/usr/bin/env python3
"""Validate Govorun Telegram/WhatsApp routing env files against a canonical contract."""

from __future__ import annotations

import argparse
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = REPO_ROOT / "infra" / "contracts" / "server3-chat-routing.contract.env"
DEFAULT_TELEGRAM_ENV = Path("/etc/default/govorun-whatsapp-bridge")
DEFAULT_WHATSAPP_ENV = Path("/home/govorun/whatsapp-govorun/app/.env")
DEFAULT_OBSERVER_ENV = Path("/etc/default/server3-runtime-observer")
DEFAULT_ARCHITECT_ENV = Path("/etc/default/telegram-architect-bridge")
DEFAULT_TZ = "Australia/Brisbane"


class ValidationError(RuntimeError):
    """Raised when the routing contract check fails."""


@dataclass(frozen=True)
class Mismatch:
    field: str
    expected: str
    actual: str


def parse_env_file(path: Path) -> Dict[str, str]:
    if not path.is_file():
        raise ValidationError(f"missing env file: {path}")
    parsed: Dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        parsed[key] = strip_quotes(value.strip())
    return parsed


def strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def normalize_bool(raw: str, *, field: str) -> str:
    lowered = raw.strip().lower()
    if lowered in TRUE_VALUES:
        return "true"
    if lowered in FALSE_VALUES:
        return "false"
    raise ValidationError(f"invalid boolean value for {field}: {raw!r}")


def split_csv(raw: str) -> List[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def csv_sort_key(value: str) -> Tuple[int, int | str]:
    if re.fullmatch(r"-?\d+", value):
        return (0, int(value))
    return (1, value.lower())


def normalize_csv(raw: str) -> str:
    unique = {item for item in split_csv(raw)}
    return ",".join(sorted(unique, key=csv_sort_key))


def load_required(contract: Dict[str, str], key: str) -> str:
    if key not in contract:
        raise ValidationError(f"contract key missing: {key}")
    return contract[key]


def load_optional(contract: Dict[str, str], key: str) -> Optional[str]:
    if key not in contract:
        return None
    return contract[key]


def compare_equals(
    mismatches: List[Mismatch],
    *,
    field: str,
    expected: str,
    actual: str,
) -> None:
    if expected != actual:
        mismatches.append(Mismatch(field=field, expected=expected, actual=actual))


def validate_contract(contract: Dict[str, str], telegram_env: Dict[str, str], whatsapp_env: Dict[str, str]) -> None:
    mismatches: List[Mismatch] = []

    expected_chat_ids = normalize_csv(load_required(contract, "CONTRACT_ALLOWED_CHAT_IDS"))
    actual_tg_chat_ids = normalize_csv(telegram_env.get("TELEGRAM_ALLOWED_CHAT_IDS", ""))
    actual_wa_chat_ids = normalize_csv(whatsapp_env.get("WA_ALLOWED_CHAT_IDS", ""))
    compare_equals(
        mismatches,
        field="TELEGRAM_ALLOWED_CHAT_IDS",
        expected=expected_chat_ids,
        actual=actual_tg_chat_ids,
    )
    compare_equals(
        mismatches,
        field="WA_ALLOWED_CHAT_IDS",
        expected=expected_chat_ids,
        actual=actual_wa_chat_ids,
    )

    expected_tg_dm_unlisted = normalize_bool(
        load_required(contract, "CONTRACT_TELEGRAM_ALLOW_PRIVATE_CHATS_UNLISTED"),
        field="CONTRACT_TELEGRAM_ALLOW_PRIVATE_CHATS_UNLISTED",
    )
    actual_tg_dm_unlisted = normalize_bool(
        telegram_env.get("TELEGRAM_ALLOW_PRIVATE_CHATS_UNLISTED", ""),
        field="TELEGRAM_ALLOW_PRIVATE_CHATS_UNLISTED",
    )
    compare_equals(
        mismatches,
        field="TELEGRAM_ALLOW_PRIVATE_CHATS_UNLISTED",
        expected=expected_tg_dm_unlisted,
        actual=actual_tg_dm_unlisted,
    )

    expected_tg_prefix_in_private = normalize_bool(
        load_required(contract, "CONTRACT_TELEGRAM_REQUIRE_PREFIX_IN_PRIVATE"),
        field="CONTRACT_TELEGRAM_REQUIRE_PREFIX_IN_PRIVATE",
    )
    actual_tg_prefix_in_private = normalize_bool(
        telegram_env.get("TELEGRAM_REQUIRE_PREFIX_IN_PRIVATE", ""),
        field="TELEGRAM_REQUIRE_PREFIX_IN_PRIVATE",
    )
    compare_equals(
        mismatches,
        field="TELEGRAM_REQUIRE_PREFIX_IN_PRIVATE",
        expected=expected_tg_prefix_in_private,
        actual=actual_tg_prefix_in_private,
    )

    expected_wa_dm_always_respond = normalize_bool(
        load_required(contract, "CONTRACT_WA_DM_ALWAYS_RESPOND"),
        field="CONTRACT_WA_DM_ALWAYS_RESPOND",
    )
    actual_wa_dm_always_respond = normalize_bool(
        whatsapp_env.get("WA_DM_ALWAYS_RESPOND", ""),
        field="WA_DM_ALWAYS_RESPOND",
    )
    compare_equals(
        mismatches,
        field="WA_DM_ALWAYS_RESPOND",
        expected=expected_wa_dm_always_respond,
        actual=actual_wa_dm_always_respond,
    )

    expected_wa_group_trigger_required = normalize_bool(
        load_required(contract, "CONTRACT_WA_GROUP_TRIGGER_REQUIRED"),
        field="CONTRACT_WA_GROUP_TRIGGER_REQUIRED",
    )
    actual_wa_group_trigger_required = normalize_bool(
        whatsapp_env.get("WA_GROUP_TRIGGER_REQUIRED", ""),
        field="WA_GROUP_TRIGGER_REQUIRED",
    )
    compare_equals(
        mismatches,
        field="WA_GROUP_TRIGGER_REQUIRED",
        expected=expected_wa_group_trigger_required,
        actual=actual_wa_group_trigger_required,
    )

    expected_wa_allowed_dms_raw = load_optional(contract, "CONTRACT_WA_ALLOWED_DMS")
    if expected_wa_allowed_dms_raw is not None:
        expected_wa_allowed_dms = normalize_csv(expected_wa_allowed_dms_raw)
        actual_wa_allowed_dms = normalize_csv(whatsapp_env.get("WA_ALLOWED_DMS", ""))
        compare_equals(
            mismatches,
            field="WA_ALLOWED_DMS",
            expected=expected_wa_allowed_dms,
            actual=actual_wa_allowed_dms,
        )

    expected_wa_allowed_groups_raw = load_optional(contract, "CONTRACT_WA_ALLOWED_GROUPS")
    if expected_wa_allowed_groups_raw is not None:
        expected_wa_allowed_groups = normalize_csv(expected_wa_allowed_groups_raw)
        actual_wa_allowed_groups = normalize_csv(whatsapp_env.get("WA_ALLOWED_GROUPS", ""))
        compare_equals(
            mismatches,
            field="WA_ALLOWED_GROUPS",
            expected=expected_wa_allowed_groups,
            actual=actual_wa_allowed_groups,
        )

    if not mismatches:
        return

    detail = "; ".join(
        f"{row.field} expected={row.expected or '<empty>'} actual={row.actual or '<empty>'}" for row in mismatches
    )
    raise ValidationError(f"chat routing contract drift detected: {detail}")


def resolve_alert_targets(
    observer_env: Optional[Dict[str, str]],
    architect_env: Optional[Dict[str, str]],
) -> Tuple[str, List[str]]:
    observer_env = observer_env or {}
    architect_env = architect_env or {}

    token = (
        os.getenv("RUNTIME_OBSERVER_TELEGRAM_BOT_TOKEN", "").strip()
        or observer_env.get("RUNTIME_OBSERVER_TELEGRAM_BOT_TOKEN", "").strip()
        or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        or architect_env.get("TELEGRAM_BOT_TOKEN", "").strip()
    )
    chat_csv = (
        os.getenv("RUNTIME_OBSERVER_TELEGRAM_CHAT_IDS", "").strip()
        or observer_env.get("RUNTIME_OBSERVER_TELEGRAM_CHAT_IDS", "").strip()
        or os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").strip()
        or architect_env.get("TELEGRAM_ALLOWED_CHAT_IDS", "").strip()
    )
    chat_ids = split_csv(chat_csv)
    return token, chat_ids


def send_telegram_alert(token: str, chat_ids: Iterable[str], text: str, timeout_seconds: int = 10) -> None:
    if not token:
        raise ValidationError("telegram alert send skipped: missing bot token")
    chat_ids = list(chat_ids)
    if not chat_ids:
        raise ValidationError("telegram alert send skipped: missing chat ids")
    endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
    for chat_id in chat_ids:
        payload = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")
        request = urllib.request.Request(endpoint, data=payload, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                response.read()
        except urllib.error.URLError as exc:
            raise ValidationError(f"telegram alert send failed for chat_id={chat_id}: {exc}") from exc


def now_local_iso(timezone_name: str) -> str:
    return datetime.now(ZoneInfo(timezone_name)).isoformat(timespec="seconds")


def run(args: argparse.Namespace) -> int:
    contract = parse_env_file(args.contract)
    telegram_env = parse_env_file(args.telegram_env)
    whatsapp_env = parse_env_file(args.whatsapp_env)

    try:
        validate_contract(contract, telegram_env, whatsapp_env)
        print(
            "chat_routing_contract_check=pass "
            f"time={now_local_iso(args.timezone)} contract={args.contract}"
        )
        return 0
    except ValidationError as exc:
        print(
            "chat_routing_contract_check=fail "
            f"time={now_local_iso(args.timezone)} reason={exc}",
            file=sys.stderr,
        )
        if args.telegram_alert_on_fail:
            observer_env = parse_env_file(args.observer_env) if args.observer_env.is_file() else None
            architect_env = parse_env_file(args.architect_env) if args.architect_env.is_file() else None
            token, chat_ids = resolve_alert_targets(observer_env, architect_env)
            alert_text = (
                "Server3 chat-routing contract drift detected.\n"
                f"Time: {now_local_iso(args.timezone)}\n"
                f"Details: {exc}"
            )
            try:
                send_telegram_alert(token, chat_ids, alert_text)
                print("chat_routing_contract_alert=sent", file=sys.stderr)
            except ValidationError as alert_exc:
                print(f"chat_routing_contract_alert=failed reason={alert_exc}", file=sys.stderr)
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--telegram-env", type=Path, default=DEFAULT_TELEGRAM_ENV)
    parser.add_argument("--whatsapp-env", type=Path, default=DEFAULT_WHATSAPP_ENV)
    parser.add_argument("--observer-env", type=Path, default=DEFAULT_OBSERVER_ENV)
    parser.add_argument("--architect-env", type=Path, default=DEFAULT_ARCHITECT_ENV)
    parser.add_argument("--timezone", default=DEFAULT_TZ)
    parser.add_argument("--telegram-alert-on-fail", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
