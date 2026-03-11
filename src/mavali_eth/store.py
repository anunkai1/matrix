from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

from .models import InboundTransfer, PendingAction


class MavaliEthStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS pending_actions (
                    session_key TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS outbound_transactions (
                    tx_hash TEXT PRIMARY KEY,
                    session_key TEXT NOT NULL,
                    destination_address TEXT NOT NULL,
                    amount_wei TEXT NOT NULL,
                    gas_limit INTEGER NOT NULL,
                    max_fee_per_gas_wei TEXT NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS inbound_receipts (
                    tx_hash TEXT PRIMARY KEY,
                    block_number INTEGER NOT NULL,
                    sender_address TEXT NOT NULL,
                    recipient_address TEXT NOT NULL,
                    amount_wei TEXT NOT NULL,
                    notified_at REAL NOT NULL
                );
                """
            )
            conn.commit()

    def get_metadata(self, key: str) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def set_metadata(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                (key, value),
            )
            conn.commit()

    def put_pending_action(self, action: PendingAction) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO pending_actions (
                    session_key,
                    payload_json,
                    created_at,
                    expires_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    action.session_key,
                    json.dumps(action.to_payload(), sort_keys=True),
                    action.created_at,
                    action.expires_at,
                ),
            )
            conn.commit()

    def get_pending_action(self, session_key: str, *, now: Optional[float] = None) -> Optional[PendingAction]:
        now_value = time.time() if now is None else float(now)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json, expires_at FROM pending_actions WHERE session_key = ?",
                (session_key,),
            ).fetchone()
            if row is None:
                return None
            if float(row["expires_at"]) < now_value:
                conn.execute("DELETE FROM pending_actions WHERE session_key = ?", (session_key,))
                conn.commit()
                return None
        payload = json.loads(str(row["payload_json"]))
        return PendingAction.from_payload(payload)

    def clear_pending_action(self, session_key: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM pending_actions WHERE session_key = ?", (session_key,))
            conn.commit()

    def record_outbound_transaction(
        self,
        *,
        tx_hash: str,
        session_key: str,
        destination_address: str,
        amount_wei: int,
        gas_limit: int,
        max_fee_per_gas_wei: int,
        created_at: Optional[float] = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO outbound_transactions (
                    tx_hash,
                    session_key,
                    destination_address,
                    amount_wei,
                    gas_limit,
                    max_fee_per_gas_wei,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tx_hash.lower(),
                    session_key,
                    destination_address.lower(),
                    str(int(amount_wei)),
                    int(gas_limit),
                    str(int(max_fee_per_gas_wei)),
                    time.time() if created_at is None else float(created_at),
                ),
            )
            conn.commit()

    def inbound_receipt_exists(self, tx_hash: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM inbound_receipts WHERE tx_hash = ?",
                (tx_hash.lower(),),
            ).fetchone()
        return row is not None

    def record_inbound_receipt(self, transfer: InboundTransfer) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO inbound_receipts (
                    tx_hash,
                    block_number,
                    sender_address,
                    recipient_address,
                    amount_wei,
                    notified_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    transfer.tx_hash.lower(),
                    int(transfer.block_number),
                    transfer.sender_address.lower(),
                    transfer.recipient_address.lower(),
                    str(int(transfer.amount_wei)),
                    time.time(),
                ),
            )
            conn.commit()

