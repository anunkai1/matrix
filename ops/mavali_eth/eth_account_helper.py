#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


def load_payload() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Helper payload must be a JSON object.")
    return payload


def read_keystore_json(path: str) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Keystore JSON is invalid.")
    return payload


def cmd_create_wallet(payload: dict) -> dict:
    from eth_account import Account

    passphrase = str(payload.get("passphrase") or "")
    if not passphrase:
        raise ValueError("passphrase is required")
    account = Account.create()
    keystore = Account.encrypt(account.key, passphrase)
    return {
        "address": account.address.lower(),
        "keystore_json": json.dumps(keystore),
    }


def cmd_read_address(payload: dict) -> dict:
    keystore_path = str(payload.get("keystore_path") or "")
    if not keystore_path:
        raise ValueError("keystore_path is required")
    keystore = read_keystore_json(keystore_path)
    address = str(keystore.get("address") or "").strip()
    if not address:
        raise ValueError("keystore does not contain an address field")
    if not address.startswith("0x"):
        address = f"0x{address}"
    return {"address": address.lower()}


def cmd_sign_transaction(payload: dict) -> dict:
    from eth_account import Account

    keystore_path = str(payload.get("keystore_path") or "")
    passphrase = str(payload.get("passphrase") or "")
    tx_dict = payload.get("tx_dict")
    if not keystore_path or not passphrase or not isinstance(tx_dict, dict):
        raise ValueError("keystore_path, passphrase, and tx_dict are required")
    keystore = read_keystore_json(keystore_path)
    private_key = Account.decrypt(keystore, passphrase)
    signed = Account.sign_transaction(tx_dict, private_key)
    return {
        "raw_tx_hex": signed.raw_transaction.hex(),
        "tx_hash": signed.hash.hex().lower(),
        "from_address": Account.from_key(private_key).address.lower(),
    }


COMMANDS = {
    "create-wallet": cmd_create_wallet,
    "read-address": cmd_read_address,
    "sign-transaction": cmd_sign_transaction,
}


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        raise SystemExit("Usage: eth_account_helper.py <create-wallet|read-address|sign-transaction>")
    payload = load_payload()
    result = COMMANDS[sys.argv[1]](payload)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

