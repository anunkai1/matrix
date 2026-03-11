from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Protocol

from .config import MavaliEthConfig
from .models import CreatedWallet, SignedTransaction


class SignerBackend(Protocol):
    def create_wallet(self, passphrase: str) -> CreatedWallet:
        ...

    def read_address(self, keystore_path: str) -> str:
        ...

    def sign_transaction(self, keystore_path: str, passphrase: str, tx_dict: dict) -> SignedTransaction:
        ...


class SubprocessSignerBackend:
    def __init__(self, config: MavaliEthConfig) -> None:
        self.python_bin = config.signer_python_bin
        self.helper_script = config.signer_helper_script

    def _run(self, command: str, payload: dict) -> dict:
        helper_path = Path(self.helper_script)
        if not helper_path.exists():
            raise RuntimeError(f"Signer helper script is missing: {self.helper_script}")
        process = subprocess.run(
            [self.python_bin, str(helper_path), command],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=False,
        )
        if process.returncode != 0:
            detail = process.stderr.strip() or process.stdout.strip() or "unknown signer error"
            raise RuntimeError(f"Signer helper failed: {detail}")
        try:
            data = json.loads(process.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Signer helper returned invalid JSON.") from exc
        if not isinstance(data, dict):
            raise RuntimeError("Signer helper returned invalid payload.")
        return data

    def create_wallet(self, passphrase: str) -> CreatedWallet:
        payload = self._run("create-wallet", {"passphrase": passphrase})
        return CreatedWallet(
            address=str(payload["address"]).lower(),
            keystore_json=str(payload["keystore_json"]),
        )

    def read_address(self, keystore_path: str) -> str:
        payload = self._run("read-address", {"keystore_path": keystore_path})
        return str(payload["address"]).lower()

    def sign_transaction(self, keystore_path: str, passphrase: str, tx_dict: dict) -> SignedTransaction:
        payload = self._run(
            "sign-transaction",
            {
                "keystore_path": keystore_path,
                "passphrase": passphrase,
                "tx_dict": tx_dict,
            },
        )
        return SignedTransaction(
            raw_tx_hex=str(payload["raw_tx_hex"]),
            tx_hash=str(payload["tx_hash"]).lower(),
            from_address=str(payload["from_address"]).lower(),
        )

