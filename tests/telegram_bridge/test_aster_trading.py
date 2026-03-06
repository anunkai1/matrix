import importlib.util
import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "src" / "telegram_bridge" / "aster_trading.py"

spec = importlib.util.spec_from_file_location("aster_trading", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Failed to load aster_trading module spec")
aster_trading = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aster_trading)


class FakeClient:
    def __init__(self, _config):
        self._orders = []

    def get_ticker_price(self, symbol: str):
        if symbol == "BTCUSDT":
            return Decimal("50000")
        if symbol == "ETHUSDT":
            return Decimal("2080")
        return Decimal("100")

    def get_exchange_info(self):
        return {
            "symbols": [
                {
                    "symbol": "BTCUSDT",
                    "status": "TRADING",
                    "filters": [
                        {"filterType": "LOT_SIZE", "minQty": "0.001", "stepSize": "0.001"},
                        {"filterType": "MARKET_LOT_SIZE", "minQty": "0.001", "stepSize": "0.001"},
                        {"filterType": "MIN_NOTIONAL", "notional": "5"},
                    ],
                },
                {
                    "symbol": "ETHUSDT",
                    "status": "TRADING",
                    "filters": [
                        {"filterType": "LOT_SIZE", "minQty": "0.001", "stepSize": "0.001"},
                        {"filterType": "MARKET_LOT_SIZE", "minQty": "0.001", "stepSize": "0.001"},
                        {"filterType": "MIN_NOTIONAL", "notional": "5"},
                    ],
                },
            ]
        }

    def get_balance(self):
        return [{"asset": "USDT", "availableBalance": "10000", "balance": "10000"}]

    def get_income(self, start_time_ms: int, end_time_ms: int):
        del start_time_ms, end_time_ms
        return [{"income": "-120.5"}, {"income": "50"}]

    def set_leverage(self, symbol: str, leverage: int):
        return {"symbol": symbol, "leverage": leverage}

    def place_order(self, params):
        self._orders.append(dict(params))
        return {
            "orderId": 12345,
            "status": "FILLED",
            "avgPrice": "50000",
            "executedQty": params.get("quantity", "0"),
        }


class AsterTradingTests(unittest.TestCase):
    def test_parse_intent_confirm_cancel_status(self):
        self.assertEqual(aster_trading.parse_intent("Trade status").action, "status")
        confirm = aster_trading.parse_intent("Trade confirm A1B2C3")
        self.assertEqual(confirm.action, "confirm")
        self.assertEqual(confirm.ticket_id, "A1B2C3")
        cancel = aster_trading.parse_intent("Trade cancel ff0011")
        self.assertEqual(cancel.action, "cancel")
        self.assertEqual(cancel.ticket_id, "FF0011")

    def test_parse_intent_draft_market(self):
        intent = aster_trading.parse_intent("Trade long btc 2000 usdt 10x")
        self.assertEqual(intent.action, "draft")
        self.assertEqual(intent.side, "BUY")
        self.assertEqual(intent.symbol, "BTCUSDT")
        self.assertEqual(intent.notional_usdt, Decimal("2000"))
        self.assertEqual(intent.leverage, 10)
        self.assertEqual(intent.order_type, "MARKET")

    def test_parse_intent_draft_limit(self):
        intent = aster_trading.parse_intent("Trade short BTCUSDT qty 0.05 5x limit @ 62000")
        self.assertEqual(intent.side, "SELL")
        self.assertEqual(intent.quantity, Decimal("0.05"))
        self.assertEqual(intent.order_type, "LIMIT")
        self.assertEqual(intent.price, Decimal("62000"))

    def test_ticket_store_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = aster_trading.TicketStore(str(Path(tmpdir) / "state.sqlite3"))
            ticket_id, _ = store.create_ticket(
                chat_id="tg:1",
                request_data={"symbol": "BTCUSDT", "side": "BUY", "type": "MARKET", "quantity": "0.01", "notional_usdt": "500", "leverage": 2, "reduce_only": False, "price": None, "time_in_force": None, "inferred_from": "notional"},
                raw_request="long btc 500 usdt",
                ttl_seconds=60,
            )
            ticket = store.get_ticket("tg:1", ticket_id)
            self.assertIsNotNone(ticket)
            self.assertEqual(store.count_active("tg:1"), 1)
            self.assertTrue(store.delete_ticket(ticket_id))
            self.assertEqual(store.count_active("tg:1"), 0)

    def test_handle_trade_request_preview_and_confirm(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = aster_trading.TradingConfig(
                api_key="k",
                api_secret="s",
                api_base="https://fapi.asterdex.com",
                recv_window_ms=5000,
                http_timeout_seconds=5,
                max_order_notional_usdt=Decimal("10000"),
                notional_max_overshoot_pct=Decimal("0.15"),
                max_leverage=20,
                daily_max_realized_loss_usdt=Decimal("5000"),
                confirm_ttl_seconds=60,
                state_db_path=str(Path(tmpdir) / "state.sqlite3"),
            )
            with mock.patch.object(aster_trading, "AsterFuturesClient", FakeClient):
                preview = aster_trading.handle_trade_request(
                    "Trade long btc 2000 usdt 10x market",
                    chat_id="tg:77",
                    config=cfg,
                )
                self.assertIn("ASTER trade preview", preview)
                self.assertIn("ticket:", preview)
                self.assertIn("leverage: 10x", preview)
                self.assertIn("notional_usdt:", preview)
                self.assertIn("quantity:", preview)
                ticket = None
                for line in preview.splitlines():
                    if line.startswith("ticket:"):
                        ticket = line.split(":", 1)[1].strip()
                        break
                self.assertIsNotNone(ticket)

                executed = aster_trading.handle_trade_request(
                    f"Trade confirm {ticket}",
                    chat_id="tg:77",
                    config=cfg,
                )
                self.assertIn("ASTER order executed", executed)
                self.assertIn("order_id=12345", executed)

    def test_notional_rounds_to_nearest_step(self):
        cfg = aster_trading.TradingConfig(
            api_key="k",
            api_secret="s",
            api_base="https://fapi.asterdex.com",
            recv_window_ms=5000,
            http_timeout_seconds=5,
            max_order_notional_usdt=Decimal("10000"),
            notional_max_overshoot_pct=Decimal("0.15"),
            max_leverage=20,
            daily_max_realized_loss_usdt=Decimal("5000"),
            confirm_ttl_seconds=60,
            state_db_path="/tmp/unused.sqlite3",
        )
        intent = aster_trading.ParsedIntent(
            action="draft",
            symbol="ETHUSDT",
            side="BUY",
            order_type="MARKET",
            notional_usdt=Decimal("10"),
            leverage=2,
        )
        with mock.patch.object(aster_trading, "compute_daily_realized_loss", return_value=Decimal("0")):
            draft = aster_trading._build_draft(FakeClient(cfg), cfg, intent)
        self.assertEqual(draft.quantity, Decimal("0.005"))
        self.assertEqual(draft.notional_usdt, Decimal("10.400"))

    def test_notional_rejects_large_overshoot(self):
        cfg = aster_trading.TradingConfig(
            api_key="k",
            api_secret="s",
            api_base="https://fapi.asterdex.com",
            recv_window_ms=5000,
            http_timeout_seconds=5,
            max_order_notional_usdt=Decimal("10000"),
            notional_max_overshoot_pct=Decimal("0.15"),
            max_leverage=20,
            daily_max_realized_loss_usdt=Decimal("5000"),
            confirm_ttl_seconds=60,
            state_db_path="/tmp/unused.sqlite3",
        )
        intent = aster_trading.ParsedIntent(
            action="draft",
            symbol="BTCUSDT",
            side="BUY",
            order_type="MARKET",
            notional_usdt=Decimal("20"),
            leverage=2,
        )
        with mock.patch.object(aster_trading, "compute_daily_realized_loss", return_value=Decimal("0")):
            with self.assertRaisesRegex(aster_trading.TradeError, "Requested notional is too small"):
                aster_trading._build_draft(FakeClient(cfg), cfg, intent)


if __name__ == "__main__":
    unittest.main()
