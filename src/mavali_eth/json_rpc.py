from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List


def wei_to_gwei(value_wei: int) -> float:
    return float(value_wei) / 1_000_000_000


def wei_to_eth(value_wei: int) -> float:
    return float(value_wei) / 1_000_000_000_000_000_000


def int_to_hex(value: int) -> str:
    return hex(int(value))


def hex_to_int(value: str) -> int:
    if not isinstance(value, str):
        raise ValueError(f"Expected hex string, got {type(value).__name__}")
    return int(value, 16)


@dataclass(frozen=True)
class RpcBlockTransaction:
    tx_hash: str
    from_address: str
    to_address: str
    value_wei: int
    block_number: int


class EthereumJsonRpcClient:
    def __init__(self, rpc_url: str, *, timeout_seconds: int = 20) -> None:
        self.rpc_url = rpc_url
        self.timeout_seconds = timeout_seconds

    def _call(self, method: str, params: List[Any]) -> Any:
        if not self.rpc_url:
            raise RuntimeError("MAVALI_ETH_RPC_URL is not configured.")
        payload = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        ).encode("utf-8")
        request = urllib.request.Request(
            self.rpc_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            body = json.loads(response.read().decode("utf-8"))
        if body.get("error"):
            raise RuntimeError(f"RPC {method} failed: {body['error']}")
        return body.get("result")

    def get_chain_id(self) -> int:
        return hex_to_int(self._call("eth_chainId", []))

    def get_balance_wei(self, address: str) -> int:
        return hex_to_int(self._call("eth_getBalance", [address, "latest"]))

    def get_transaction_count(self, address: str) -> int:
        return hex_to_int(self._call("eth_getTransactionCount", [address, "pending"]))

    def get_suggested_max_fee_per_gas_wei(self) -> int:
        return hex_to_int(self._call("eth_gasPrice", []))

    def estimate_transfer_gas(self, from_address: str, to_address: str, value_wei: int) -> int:
        result = self._call(
            "eth_estimateGas",
            [
                {
                    "from": from_address,
                    "to": to_address,
                    "value": int_to_hex(value_wei),
                }
            ],
        )
        return hex_to_int(result)

    def send_raw_transaction(self, raw_tx_hex: str) -> str:
        result = self._call("eth_sendRawTransaction", [raw_tx_hex])
        return str(result).lower()

    def get_latest_block_number(self) -> int:
        return hex_to_int(self._call("eth_blockNumber", []))

    def get_block_transactions(self, block_number: int) -> List[RpcBlockTransaction]:
        result = self._call("eth_getBlockByNumber", [int_to_hex(block_number), True])
        if not isinstance(result, dict):
            return []
        transactions = result.get("transactions")
        if not isinstance(transactions, list):
            return []
        out: List[RpcBlockTransaction] = []
        for item in transactions:
            if not isinstance(item, dict):
                continue
            to_address = item.get("to")
            if not isinstance(to_address, str) or not to_address:
                continue
            tx_hash = item.get("hash")
            from_address = item.get("from")
            value = item.get("value")
            block_value = item.get("blockNumber")
            if not all(isinstance(v, str) for v in (tx_hash, from_address, value, block_value)):
                continue
            out.append(
                RpcBlockTransaction(
                    tx_hash=tx_hash.lower(),
                    from_address=from_address.lower(),
                    to_address=to_address.lower(),
                    value_wei=hex_to_int(value),
                    block_number=hex_to_int(block_value),
                )
            )
        return out

    def transaction_succeeded(self, tx_hash: str) -> bool:
        receipt = self._call("eth_getTransactionReceipt", [tx_hash])
        if not isinstance(receipt, dict):
            return False
        status = receipt.get("status")
        return isinstance(status, str) and hex_to_int(status) == 1

