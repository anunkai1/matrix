from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import List, Optional

from .models import SendIntent


RAW_ADDRESS_RE = re.compile(r"\b0x[a-fA-F0-9]{40}\b")
ETH_AMOUNT_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*eth\b", re.IGNORECASE)


class AddressParseError(ValueError):
    pass


def normalize_address(address: str) -> str:
    value = (address or "").strip()
    if not RAW_ADDRESS_RE.fullmatch(value):
        raise AddressParseError("Address must be one valid raw 0x... Ethereum address.")
    return value.lower()


def extract_raw_addresses(text: str) -> List[str]:
    return [match.group(0).lower() for match in RAW_ADDRESS_RE.finditer(text or "")]


def extract_single_raw_address(text: str) -> str:
    addresses = extract_raw_addresses(text)
    if not addresses:
        raise AddressParseError("I need exactly one raw 0x... address.")
    if len(addresses) > 1:
        raise AddressParseError("I found more than one raw 0x... address. Please send exactly one.")
    return normalize_address(addresses[0])


def parse_eth_amount_wei(text: str) -> Optional[tuple[int, str]]:
    match = ETH_AMOUNT_RE.search(text or "")
    if match is None:
        return None
    raw_value = match.group(1)
    try:
        decimal_value = Decimal(raw_value)
    except InvalidOperation as exc:
        raise ValueError("ETH amount is invalid.") from exc
    if decimal_value <= 0:
        raise ValueError("ETH amount must be greater than zero.")
    wei_value = int((decimal_value * Decimal("1000000000000000000")).to_integral_value(rounding=ROUND_DOWN))
    if wei_value <= 0:
        raise ValueError("ETH amount is too small.")
    normalized = format(decimal_value.normalize(), "f")
    return wei_value, normalized


def parse_send_intent(text: str) -> Optional[SendIntent]:
    normalized = " ".join((text or "").strip().split())
    if not normalized:
        return None
    lowered = normalized.lower()
    if not (
        lowered.startswith("send ")
        or lowered.startswith("transfer ")
        or " send " in f" {lowered}"
        or " transfer " in f" {lowered}"
    ):
        return None
    amount = parse_eth_amount_wei(normalized)
    if amount is None:
        raise ValueError("I need an explicit ETH amount, for example `0.03 ETH`.")
    address = extract_single_raw_address(normalized)
    amount_wei, amount_display = amount
    return SendIntent(
        amount_wei=amount_wei,
        amount_display=amount_display,
        destination_address=address,
    )

