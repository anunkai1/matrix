from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parents[2]


def _parse_int(name: str, default: int, minimum: int = 0) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    value = int(raw)
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


@dataclass(frozen=True)
class MavaliEthConfig:
    state_dir: str
    db_path: str
    keystore_path: str
    keystore_passphrase: str
    rpc_url: str
    chain_id: int
    gas_cap_gwei: int
    pending_action_expiry_minutes: int
    confirmation_count: int
    polling_interval_minutes: int
    signer_python_bin: str
    signer_helper_script: str
    telegram_bot_token: str
    telegram_api_base: str
    telegram_owner_chat_id: Optional[int]

    @property
    def gas_cap_wei(self) -> int:
        return int(self.gas_cap_gwei) * 1_000_000_000

    @classmethod
    def from_env(cls, state_dir_override: Optional[str] = None) -> "MavaliEthConfig":
        state_dir = (state_dir_override or os.getenv("TELEGRAM_BRIDGE_STATE_DIR", "").strip() or "").strip()
        if not state_dir:
            state_dir = "/home/mavali_eth/.local/state/telegram-mavali-eth-bridge"
        db_path = os.getenv("MAVALI_ETH_DB_PATH", "").strip() or str(Path(state_dir) / "mavali_eth.sqlite3")
        keystore_path = os.getenv("MAVALI_ETH_KEYSTORE_PATH", "").strip() or str(Path(state_dir) / "wallet.json")
        signer_helper_script = os.getenv("MAVALI_ETH_SIGNER_HELPER_SCRIPT", "").strip() or str(
            REPO_ROOT / "ops" / "mavali_eth" / "eth_account_helper.py"
        )
        owner_chat_id_raw = os.getenv("MAVALI_ETH_TELEGRAM_OWNER_CHAT_ID", "").strip()
        owner_chat_id = int(owner_chat_id_raw) if owner_chat_id_raw else None
        return cls(
            state_dir=state_dir,
            db_path=db_path,
            keystore_path=keystore_path,
            keystore_passphrase=os.getenv("MAVALI_ETH_KEYSTORE_PASSPHRASE", "").strip(),
            rpc_url=os.getenv("MAVALI_ETH_RPC_URL", "").strip(),
            chain_id=_parse_int("MAVALI_ETH_CHAIN_ID", 1, minimum=1),
            gas_cap_gwei=_parse_int("MAVALI_ETH_MAX_FEE_PER_GAS_GWEI", 5, minimum=1),
            pending_action_expiry_minutes=_parse_int("MAVALI_ETH_PENDING_ACTION_EXPIRY_MINUTES", 10, minimum=1),
            confirmation_count=_parse_int("MAVALI_ETH_CONFIRMATION_COUNT", 2, minimum=1),
            polling_interval_minutes=_parse_int("MAVALI_ETH_POLLING_INTERVAL_MINUTES", 30, minimum=1),
            signer_python_bin=os.getenv("MAVALI_ETH_PYTHON_BIN", "").strip() or "python3",
            signer_helper_script=signer_helper_script,
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
            telegram_api_base=os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/"),
            telegram_owner_chat_id=owner_chat_id,
        )

