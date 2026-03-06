import argparse
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, InvalidOperation
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlencode

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

import requests


SYMBOL_RE = re.compile(r"\b([A-Za-z]{2,14}USDT)\b")
COIN_RE = re.compile(r"\b([A-Za-z]{2,14})\s*(?:perp|perpetual)?\b")
CONFIRM_RE = re.compile(r"\bconfirm\b[^A-Za-z0-9]*([A-Za-z0-9]{6,20})\b", re.IGNORECASE)
CANCEL_RE = re.compile(r"\bcancel\b[^A-Za-z0-9]*([A-Za-z0-9]{6,20})\b", re.IGNORECASE)
LEVERAGE_RE = re.compile(r"\b(?:leverage\s*)?(\d{1,3})(?:\.0+)?\s*x\b", re.IGNORECASE)
LEVERAGE_WORD_RE = re.compile(r"\bleverage\s*(?:to\s*)?(\d{1,3})\b", re.IGNORECASE)
NOTIONAL_PATTERNS = (
    re.compile(r"\b(?:notional|size|for|amount)\s*[:=]?\s*\$?\s*(\d+(?:\.\d+)?)\s*(?:usdt|usd)?\b", re.IGNORECASE),
    re.compile(r"\$\s*(\d+(?:\.\d+)?)\b"),
    re.compile(r"\b(\d+(?:\.\d+)?)\s*usdt\b", re.IGNORECASE),
)
QUANTITY_PATTERNS = (
    re.compile(r"\b(?:qty|quantity|amount)\s*[:=]?\s*(\d+(?:\.\d+)?)\b", re.IGNORECASE),
    re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:contracts?|coins?)\b", re.IGNORECASE),
)
PRICE_PATTERNS = (
    re.compile(r"@\s*(\d+(?:\.\d+)?)\b"),
    re.compile(r"\bprice\s*[:=]?\s*(\d+(?:\.\d+)?)\b", re.IGNORECASE),
    re.compile(r"\bat\s+(\d+(?:\.\d+)?)\b", re.IGNORECASE),
)


class TradeError(RuntimeError):
    pass


class AsterApiError(TradeError):
    def __init__(self, message: str, *, code: Optional[int] = None, payload: Optional[dict] = None) -> None:
        super().__init__(message)
        self.code = code
        self.payload = payload or {}


@dataclass
class TradingConfig:
    api_key: str
    api_secret: str
    api_base: str
    recv_window_ms: int
    http_timeout_seconds: float
    max_order_notional_usdt: Decimal
    notional_max_overshoot_pct: Decimal
    max_leverage: int
    daily_max_realized_loss_usdt: Decimal
    confirm_ttl_seconds: int
    state_db_path: str


@dataclass
class DraftOrder:
    symbol: str
    side: str
    order_type: str
    quantity: Decimal
    notional_usdt: Decimal
    leverage: int
    reduce_only: bool
    price: Optional[Decimal]
    time_in_force: Optional[str]
    inferred_from: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "type": self.order_type,
            "quantity": format_decimal(self.quantity),
            "notional_usdt": format_decimal(self.notional_usdt),
            "leverage": self.leverage,
            "reduce_only": self.reduce_only,
            "price": format_decimal(self.price) if self.price is not None else None,
            "time_in_force": self.time_in_force,
            "inferred_from": self.inferred_from,
        }


@dataclass
class ParsedIntent:
    action: str
    ticket_id: Optional[str] = None
    symbol: Optional[str] = None
    side: Optional[str] = None
    order_type: Optional[str] = None
    quantity: Optional[Decimal] = None
    notional_usdt: Optional[Decimal] = None
    leverage: Optional[int] = None
    reduce_only: bool = False
    price: Optional[Decimal] = None
    time_in_force: Optional[str] = None


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise TradeError(f"Missing required environment variable: {name}")
    return value


def _decimal_env(name: str, default: str) -> Decimal:
    raw = os.getenv(name, default).strip()
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise TradeError(f"Invalid decimal value for {name}: {raw}") from exc


def load_trading_config() -> TradingConfig:
    api_key = _require_env("ASTER_API_KEY")
    api_secret = _require_env("ASTER_API_SECRET")
    api_base = os.getenv("ASTER_API_BASE", "https://fapi.asterdex.com").strip().rstrip("/")
    recv_window_ms = int(os.getenv("ASTER_RECV_WINDOW_MS", "5000").strip() or "5000")
    http_timeout_seconds = float(os.getenv("ASTER_HTTP_TIMEOUT_SECONDS", "15").strip() or "15")
    max_order_notional_usdt = _decimal_env("ASTER_MAX_ORDER_NOTIONAL_USDT", "10000")
    notional_max_overshoot_pct = _decimal_env("ASTER_NOTIONAL_MAX_OVERSHOOT_PCT", "0.15")
    daily_max_realized_loss_usdt = _decimal_env("ASTER_DAILY_MAX_REALIZED_LOSS_USDT", "5000")
    max_leverage = int(os.getenv("ASTER_MAX_LEVERAGE", "20").strip() or "20")
    confirm_ttl_seconds = int(os.getenv("ASTER_CONFIRM_TTL_SECONDS", "120").strip() or "120")

    state_db_path = os.getenv("ASTER_STATE_DB_PATH", "").strip()
    if not state_db_path:
        state_dir = os.getenv("TELEGRAM_BRIDGE_STATE_DIR", "").strip()
        if state_dir:
            state_db_path = str(Path(state_dir) / "aster_trading.sqlite3")
        else:
            state_db_path = os.path.expanduser("~/.local/state/telegram-aster-trader-bridge/aster_trading.sqlite3")
    return TradingConfig(
        api_key=api_key,
        api_secret=api_secret,
        api_base=api_base,
        recv_window_ms=recv_window_ms,
        http_timeout_seconds=http_timeout_seconds,
        max_order_notional_usdt=max_order_notional_usdt,
        notional_max_overshoot_pct=notional_max_overshoot_pct,
        max_leverage=max_leverage,
        daily_max_realized_loss_usdt=daily_max_realized_loss_usdt,
        confirm_ttl_seconds=confirm_ttl_seconds,
        state_db_path=state_db_path,
    )


class AsterFuturesClient:
    def __init__(self, config: TradingConfig) -> None:
        self._config = config
        self._session = requests.Session()

    def _signed_request(self, method: str, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        payload = dict(params or {})
        payload["timestamp"] = str(int(time.time() * 1000))
        payload["recvWindow"] = str(self._config.recv_window_ms)
        ordered_items = sorted((str(k), str(v)) for k, v in payload.items() if v is not None)
        encoded = urlencode(ordered_items)
        signature = hmac.new(self._config.api_secret.encode("utf-8"), encoded.encode("utf-8"), sha256).hexdigest()
        signed_body = f"{encoded}&signature={signature}"

        headers = {
            "X-MBX-APIKEY": self._config.api_key,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }
        url = f"{self._config.api_base}{path}"
        method_upper = method.upper()
        if method_upper == "GET":
            response = self._session.get(
                f"{url}?{signed_body}",
                headers=headers,
                timeout=self._config.http_timeout_seconds,
            )
        elif method_upper == "POST":
            response = self._session.post(
                url,
                data=signed_body,
                headers=headers,
                timeout=self._config.http_timeout_seconds,
            )
        elif method_upper == "DELETE":
            response = self._session.delete(
                url,
                data=signed_body,
                headers=headers,
                timeout=self._config.http_timeout_seconds,
            )
        else:
            raise TradeError(f"Unsupported HTTP method: {method}")
        return self._parse_response(response)

    def _public_request(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self._config.api_base}{path}"
        response = self._session.get(url, params=params or {}, timeout=self._config.http_timeout_seconds)
        return self._parse_response(response)

    @staticmethod
    def _parse_response(response: requests.Response) -> Any:
        try:
            data = response.json()
        except ValueError:
            data = {"raw": response.text}
        if response.status_code >= 400:
            code = data.get("code") if isinstance(data, dict) else None
            msg = data.get("msg") if isinstance(data, dict) else response.text
            raise AsterApiError(f"ASTER API error ({response.status_code}): {msg}", code=code, payload=data if isinstance(data, dict) else None)
        if isinstance(data, dict) and "code" in data and "msg" in data and isinstance(data.get("code"), int) and data["code"] < 0:
            raise AsterApiError(f"ASTER API error ({data['code']}): {data.get('msg')}", code=data.get("code"), payload=data)
        return data

    def get_ticker_price(self, symbol: str) -> Decimal:
        data = self._public_request("/fapi/v1/ticker/price", params={"symbol": symbol})
        if not isinstance(data, dict) or "price" not in data:
            raise TradeError("Unexpected ticker price payload from ASTER")
        return Decimal(str(data["price"]))

    def get_exchange_info(self) -> Dict[str, Any]:
        data = self._public_request("/fapi/v1/exchangeInfo")
        if not isinstance(data, dict):
            raise TradeError("Unexpected exchangeInfo payload from ASTER")
        return data

    def get_balance(self) -> List[Dict[str, Any]]:
        data = self._signed_request("GET", "/fapi/v2/balance")
        if not isinstance(data, list):
            raise TradeError("Unexpected balance payload from ASTER")
        return data

    def get_income(self, start_time_ms: int, end_time_ms: int) -> List[Dict[str, Any]]:
        data = self._signed_request(
            "GET",
            "/fapi/v1/income",
            params={
                "incomeType": "REALIZED_PNL",
                "startTime": str(start_time_ms),
                "endTime": str(end_time_ms),
                "limit": "1000",
            },
        )
        if not isinstance(data, list):
            raise TradeError("Unexpected income payload from ASTER")
        return data

    def set_leverage(self, symbol: str, leverage: int) -> Dict[str, Any]:
        data = self._signed_request(
            "POST",
            "/fapi/v1/leverage",
            params={"symbol": symbol, "leverage": str(leverage)},
        )
        if not isinstance(data, dict):
            raise TradeError("Unexpected leverage payload from ASTER")
        return data

    def place_order(self, params: Dict[str, str]) -> Dict[str, Any]:
        data = self._signed_request("POST", "/fapi/v1/order", params=params)
        if not isinstance(data, dict):
            raise TradeError("Unexpected order payload from ASTER")
        return data


class TicketStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_tickets (
                    ticket_id TEXT PRIMARY KEY,
                    chat_id TEXT NOT NULL,
                    created_at_ms INTEGER NOT NULL,
                    expires_at_ms INTEGER NOT NULL,
                    request_json TEXT NOT NULL,
                    raw_request TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    created_at_ms INTEGER NOT NULL,
                    ticket_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    type TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    notional_usdt TEXT NOT NULL,
                    leverage INTEGER NOT NULL,
                    order_id TEXT,
                    response_json TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pending_chat ON pending_tickets(chat_id)")

    def purge_expired(self, now_ms: Optional[int] = None) -> int:
        current = now_ms if now_ms is not None else int(time.time() * 1000)
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM pending_tickets WHERE expires_at_ms <= ?", (current,))
            return cursor.rowcount

    def create_ticket(self, chat_id: str, request_data: Dict[str, Any], raw_request: str, ttl_seconds: int) -> Tuple[str, int]:
        now_ms = int(time.time() * 1000)
        expires_at_ms = now_ms + max(1, ttl_seconds) * 1000
        for _ in range(10):
            ticket_id = secrets.token_hex(4).upper()
            try:
                with self._connect() as conn:
                    conn.execute(
                        """
                        INSERT INTO pending_tickets (ticket_id, chat_id, created_at_ms, expires_at_ms, request_json, raw_request)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (ticket_id, chat_id, now_ms, expires_at_ms, json.dumps(request_data, sort_keys=True), raw_request),
                    )
                return ticket_id, expires_at_ms
            except sqlite3.IntegrityError:
                continue
        raise TradeError("Unable to create unique confirmation ticket")

    def get_ticket(self, chat_id: str, ticket_id: str) -> Optional[Dict[str, Any]]:
        self.purge_expired()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT ticket_id, chat_id, created_at_ms, expires_at_ms, request_json, raw_request FROM pending_tickets WHERE ticket_id = ?",
                (ticket_id,),
            ).fetchone()
        if row is None:
            return None
        if row["chat_id"] != chat_id:
            return None
        return {
            "ticket_id": row["ticket_id"],
            "chat_id": row["chat_id"],
            "created_at_ms": int(row["created_at_ms"]),
            "expires_at_ms": int(row["expires_at_ms"]),
            "request": json.loads(row["request_json"]),
            "raw_request": row["raw_request"],
        }

    def delete_ticket(self, ticket_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM pending_tickets WHERE ticket_id = ?", (ticket_id,))
            return cursor.rowcount > 0

    def count_active(self, chat_id: str) -> int:
        self.purge_expired()
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM pending_tickets WHERE chat_id = ?", (chat_id,)).fetchone()
        return int(row["c"]) if row else 0

    def log_execution(self, chat_id: str, ticket_id: str, draft: DraftOrder, response: Dict[str, Any]) -> None:
        now_ms = int(time.time() * 1000)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO executions (
                    chat_id, created_at_ms, ticket_id, symbol, side, type, quantity, notional_usdt, leverage, order_id, response_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chat_id,
                    now_ms,
                    ticket_id,
                    draft.symbol,
                    draft.side,
                    draft.order_type,
                    format_decimal(draft.quantity),
                    format_decimal(draft.notional_usdt),
                    draft.leverage,
                    str(response.get("orderId", "")),
                    json.dumps(response, sort_keys=True),
                ),
            )


def format_decimal(value: Optional[Decimal]) -> str:
    if value is None:
        return ""
    normalized = value.normalize()
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def parse_decimal(value: str, *, field: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise TradeError(f"Invalid numeric value for {field}: {value}") from exc


def _extract_decimal(patterns: Iterable[re.Pattern[str]], text: str) -> Optional[Decimal]:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return parse_decimal(match.group(1), field="value")
    return None


def _infer_symbol(text: str) -> Optional[str]:
    direct = SYMBOL_RE.search(text)
    if direct:
        return direct.group(1).upper()

    lowered = text.lower()
    context_match = re.search(r"\b(?:long|short|buy|sell)\s+([a-z]{2,14})(?:\s+perp(?:etual)?)?\b", lowered)
    if context_match:
        token = context_match.group(1).upper()
        if token.endswith("USDT"):
            return token
        return f"{token}USDT"

    perp_match = re.search(r"\b([a-z]{2,14})\s+perp(?:etual)?\b", lowered)
    if perp_match:
        token = perp_match.group(1).upper()
        if token.endswith("USDT"):
            return token
        return f"{token}USDT"

    for match in COIN_RE.finditer(text):
        token = match.group(1).upper()
        if token in {"LIMIT", "MARKET", "STATUS", "CONFIRM", "CANCEL", "BUY", "SELL", "LONG", "SHORT", "TRADE", "ASTER"}:
            continue
        if token.endswith("USDT"):
            return token
        if len(token) <= 12:
            return f"{token}USDT"
    return None


def parse_intent(raw_request: str) -> ParsedIntent:
    text = raw_request.strip()
    if not text:
        raise TradeError("Empty trade request")
    lowered = text.lower()

    confirm_match = CONFIRM_RE.search(text)
    if confirm_match:
        return ParsedIntent(action="confirm", ticket_id=confirm_match.group(1).upper())

    cancel_match = CANCEL_RE.search(text)
    if cancel_match:
        return ParsedIntent(action="cancel", ticket_id=cancel_match.group(1).upper())

    if re.search(r"\bstatus\b", lowered):
        return ParsedIntent(action="status")

    side: Optional[str]
    if re.search(r"\b(long|buy)\b", lowered):
        side = "BUY"
    elif re.search(r"\b(short|sell)\b", lowered):
        side = "SELL"
    else:
        side = None
    if side is None:
        raise TradeError("Could not infer side. Include long/buy or short/sell.")

    symbol = _infer_symbol(text)
    if not symbol:
        raise TradeError("Could not infer symbol. Include a symbol like BTCUSDT or 'BTC perp'.")

    order_type = "LIMIT" if ("limit" in lowered or "@" in text or re.search(r"\bat\s+\d", lowered)) else "MARKET"
    price = _extract_decimal(PRICE_PATTERNS, text)
    if order_type == "LIMIT" and price is None:
        raise TradeError("Limit order detected but no price was found.")

    quantity = _extract_decimal(QUANTITY_PATTERNS, text)
    notional = _extract_decimal(NOTIONAL_PATTERNS, text)
    if quantity is None and notional is None:
        raise TradeError("Could not infer size. Include quantity or a USDT notional amount.")

    leverage = None
    lev_match = LEVERAGE_RE.search(text) or LEVERAGE_WORD_RE.search(text)
    if lev_match:
        leverage = int(lev_match.group(1))

    reduce_only = bool(re.search(r"\breduce\s*-?\s*only\b|\bclose\s+position\b", lowered))

    return ParsedIntent(
        action="draft",
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=quantity,
        notional_usdt=notional,
        leverage=leverage,
        reduce_only=reduce_only,
        price=price,
        time_in_force="GTC" if order_type == "LIMIT" else None,
    )


def _symbol_entry(exchange_info: Dict[str, Any], symbol: str) -> Dict[str, Any]:
    for entry in exchange_info.get("symbols", []):
        if str(entry.get("symbol", "")).upper() == symbol.upper():
            return entry
    raise TradeError(f"Symbol {symbol} is not listed by ASTER futures.")


def _filter_map(symbol_entry: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    filters: Dict[str, Dict[str, Any]] = {}
    for f in symbol_entry.get("filters", []):
        filter_type = str(f.get("filterType", ""))
        if filter_type:
            filters[filter_type] = f
    return filters


def _round_down_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    units = (value / step).quantize(Decimal("1"), rounding=ROUND_DOWN)
    return units * step


def _round_up_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    down = _round_down_step(value, step)
    if down == value:
        return value
    return down + step


def _pick_quantity_for_notional(
    target_notional: Decimal,
    reference_price: Decimal,
    step_size: Decimal,
    min_qty: Decimal,
    min_notional: Decimal,
    max_overshoot_pct: Decimal,
) -> Decimal:
    raw_qty = target_notional / reference_price
    down_qty = _round_down_step(raw_qty, step_size)
    up_qty = _round_up_step(raw_qty, step_size)

    candidates: List[Decimal] = []
    for qty in (down_qty, up_qty, min_qty):
        if qty <= 0:
            continue
        if qty not in candidates:
            candidates.append(qty)

    valid: List[Tuple[Decimal, Decimal]] = []
    for qty in candidates:
        if min_qty > 0 and qty < min_qty:
            continue
        notional = qty * reference_price
        if min_notional > 0 and notional < min_notional:
            continue
        valid.append((qty, notional))

    if not valid:
        raise TradeError("Could not compute a valid quantity for requested notional.")

    best_qty, best_notional = min(
        valid,
        key=lambda item: (abs(item[1] - target_notional), item[1]),
    )
    if target_notional > 0 and best_notional > target_notional:
        overshoot = (best_notional - target_notional) / target_notional
        if overshoot > max_overshoot_pct:
            raise TradeError(
                "Requested notional is too small for symbol lot-size filters. "
                f"Requested={format_decimal(target_notional)} USDT, "
                f"minimum practical={format_decimal(best_notional)} USDT."
            )
    return best_qty


def _build_draft(client: AsterFuturesClient, config: TradingConfig, intent: ParsedIntent) -> DraftOrder:
    assert intent.action == "draft"
    assert intent.symbol is not None
    assert intent.side is not None
    assert intent.order_type is not None

    leverage = intent.leverage if intent.leverage is not None else 1
    if leverage < 1:
        raise TradeError("Leverage must be >= 1")
    if leverage > config.max_leverage:
        raise TradeError(
            f"Requested leverage {leverage}x exceeds configured max {config.max_leverage}x."
        )

    exchange_info = client.get_exchange_info()
    symbol_entry = _symbol_entry(exchange_info, intent.symbol)
    if str(symbol_entry.get("status", "")).upper() != "TRADING":
        raise TradeError(f"Symbol {intent.symbol} is not in TRADING status.")

    filters = _filter_map(symbol_entry)
    lot_filter = filters.get("LOT_SIZE") or {}
    market_lot_filter = filters.get("MARKET_LOT_SIZE") or lot_filter
    min_notional_filter = filters.get("MIN_NOTIONAL") or {}

    step_size = Decimal(str((market_lot_filter if intent.order_type == "MARKET" else lot_filter).get("stepSize", "0.000001")))
    min_qty = Decimal(str((market_lot_filter if intent.order_type == "MARKET" else lot_filter).get("minQty", "0")))
    min_notional = Decimal(str(min_notional_filter.get("notional", "0"))) if min_notional_filter else Decimal("0")

    reference_price = intent.price if intent.price is not None else client.get_ticker_price(intent.symbol)

    if intent.quantity is not None:
        quantity = intent.quantity
        inferred_from = "quantity"
    else:
        assert intent.notional_usdt is not None
        quantity = _pick_quantity_for_notional(
            target_notional=intent.notional_usdt,
            reference_price=reference_price,
            step_size=step_size,
            min_qty=min_qty,
            min_notional=min_notional,
            max_overshoot_pct=config.notional_max_overshoot_pct,
        )
        inferred_from = "notional"

    quantity = _round_down_step(quantity, step_size)
    if quantity <= 0:
        raise TradeError("Computed quantity is zero after lot-size rounding.")
    if min_qty > 0 and quantity < min_qty:
        raise TradeError(f"Quantity {format_decimal(quantity)} is below minimum {format_decimal(min_qty)} for {intent.symbol}.")

    notional = quantity * reference_price
    if min_notional > 0 and notional < min_notional:
        raise TradeError(
            f"Order notional {format_decimal(notional)} USDT is below symbol minimum {format_decimal(min_notional)} USDT."
        )

    if notional > config.max_order_notional_usdt:
        raise TradeError(
            f"Order notional {format_decimal(notional)} USDT exceeds max {format_decimal(config.max_order_notional_usdt)} USDT."
        )

    daily_realized_loss = compute_daily_realized_loss(client)
    if daily_realized_loss >= config.daily_max_realized_loss_usdt:
        raise TradeError(
            f"Daily realized loss guard active ({format_decimal(daily_realized_loss)} >= {format_decimal(config.daily_max_realized_loss_usdt)} USDT)."
        )

    return DraftOrder(
        symbol=intent.symbol,
        side=intent.side,
        order_type=intent.order_type,
        quantity=quantity,
        notional_usdt=notional,
        leverage=leverage,
        reduce_only=intent.reduce_only,
        price=intent.price,
        time_in_force=intent.time_in_force,
        inferred_from=inferred_from,
    )


def _brisbane_day_window_ms(now: Optional[datetime] = None) -> Tuple[int, int]:
    moment = now or datetime.now(timezone.utc)
    if ZoneInfo is None:
        start = datetime(moment.year, moment.month, moment.day, tzinfo=timezone.utc)
        return int(start.timestamp() * 1000), int(moment.timestamp() * 1000)
    brisbane = moment.astimezone(ZoneInfo("Australia/Brisbane"))
    day_start_local = datetime(
        brisbane.year,
        brisbane.month,
        brisbane.day,
        tzinfo=ZoneInfo("Australia/Brisbane"),
    )
    return int(day_start_local.timestamp() * 1000), int(moment.timestamp() * 1000)


def compute_daily_realized_loss(client: AsterFuturesClient) -> Decimal:
    start_ms, end_ms = _brisbane_day_window_ms()
    income_rows = client.get_income(start_ms, end_ms)
    total = Decimal("0")
    for row in income_rows:
        value = row.get("income")
        if value is None:
            continue
        amount = Decimal(str(value))
        if amount < 0:
            total += (-amount)
    return total


def _find_usdt_balance(balances: List[Dict[str, Any]]) -> Tuple[Optional[Decimal], Optional[Decimal]]:
    for row in balances:
        if str(row.get("asset", "")).upper() != "USDT":
            continue
        available = row.get("availableBalance") or row.get("balance")
        wallet = row.get("balance")
        available_dec = Decimal(str(available)) if available is not None else None
        wallet_dec = Decimal(str(wallet)) if wallet is not None else None
        return available_dec, wallet_dec
    return None, None


def _render_preview(ticket_id: str, expires_at_ms: int, draft: DraftOrder) -> str:
    expires = datetime.fromtimestamp(expires_at_ms / 1000, timezone.utc).astimezone()
    price_value = format_decimal(draft.price) if draft.price is not None else "market"
    return (
        "ASTER trade preview (not executed yet):\n"
        f"𝐓𝐈𝐂𝐊𝐄𝐓: {ticket_id}\n"
        f"𝐄𝐗𝐏𝐈𝐑𝐄𝐒_𝐀𝐓: {expires.isoformat()}\n"
        f"𝐒𝐘𝐌𝐁𝐎𝐋: {draft.symbol}\n"
        f"𝐒𝐈𝐃𝐄: {draft.side}\n"
        f"𝐓𝐘𝐏𝐄: {draft.order_type}\n"
        f"𝐋𝐄𝐕𝐄𝐑𝐀𝐆𝐄: {draft.leverage}x\n"
        f"𝐍𝐎𝐓𝐈𝐎𝐍𝐀𝐋 𝐔𝐒𝐃𝐓: {format_decimal(draft.notional_usdt)}\n"
        f"𝐐𝐔𝐀𝐍𝐓𝐈𝐓𝐘: {format_decimal(draft.quantity)}\n"
        f"𝐏𝐑𝐈𝐂𝐄: {price_value}\n"
        f"𝐑𝐄𝐃𝐔𝐂𝐄_𝐎𝐍𝐋𝐘: {str(draft.reduce_only).lower()}\n"
        f"𝐈𝐍𝐅𝐄𝐑𝐑𝐄𝐃_𝐅𝐑𝐎𝐌: {draft.inferred_from}\n\n"
        f"Confirm: Trade confirm {ticket_id}\n"
        f"Cancel: Trade cancel {ticket_id}"
    )


def _execute_draft(client: AsterFuturesClient, draft: DraftOrder) -> Dict[str, Any]:
    client.set_leverage(draft.symbol, draft.leverage)
    params: Dict[str, str] = {
        "symbol": draft.symbol,
        "side": draft.side,
        "type": draft.order_type,
        "quantity": format_decimal(draft.quantity),
        "newOrderRespType": "RESULT",
        "newClientOrderId": f"ASTR-{int(time.time())}-{secrets.token_hex(2)}",
    }
    if draft.order_type == "LIMIT":
        if draft.price is None:
            raise TradeError("LIMIT order requires price")
        params["price"] = format_decimal(draft.price)
        params["timeInForce"] = draft.time_in_force or "GTC"
    if draft.reduce_only:
        params["reduceOnly"] = "true"
    return client.place_order(params)


def handle_trade_request(raw_request: str, chat_id: str, config: Optional[TradingConfig] = None) -> str:
    cfg = config or load_trading_config()
    store = TicketStore(cfg.state_db_path)
    store.purge_expired()
    client = AsterFuturesClient(cfg)
    intent = parse_intent(raw_request)

    if intent.action == "status":
        daily_loss = compute_daily_realized_loss(client)
        balances = client.get_balance()
        available, wallet = _find_usdt_balance(balances)
        active_tickets = store.count_active(chat_id)
        available_str = format_decimal(available) if available is not None else "unknown"
        wallet_str = format_decimal(wallet) if wallet is not None else "unknown"
        return (
            "ASTER trading status:\n"
            f"chat={chat_id}\n"
            f"active_tickets={active_tickets}\n"
            f"daily_realized_loss_usdt={format_decimal(daily_loss)} / {format_decimal(cfg.daily_max_realized_loss_usdt)}\n"
            f"usdt_available={available_str}\n"
            f"usdt_wallet={wallet_str}\n"
            f"max_order_notional_usdt={format_decimal(cfg.max_order_notional_usdt)}\n"
            f"max_leverage={cfg.max_leverage}"
        )

    if intent.action == "cancel":
        assert intent.ticket_id is not None
        deleted = store.delete_ticket(intent.ticket_id)
        if not deleted:
            return f"No active ticket found: {intent.ticket_id}"
        return f"Canceled ticket: {intent.ticket_id}"

    if intent.action == "confirm":
        assert intent.ticket_id is not None
        ticket = store.get_ticket(chat_id, intent.ticket_id)
        if ticket is None:
            return f"Ticket not found or expired for this chat: {intent.ticket_id}"
        draft = draft_from_dict(ticket["request"])
        response = _execute_draft(client, draft)
        store.log_execution(chat_id, intent.ticket_id, draft, response)
        store.delete_ticket(intent.ticket_id)
        order_id = response.get("orderId", "unknown")
        status = response.get("status", "unknown")
        avg_price = response.get("avgPrice") or response.get("price") or ""
        executed_qty = response.get("executedQty") or response.get("origQty") or format_decimal(draft.quantity)
        return (
            "ASTER order executed:\n"
            f"ticket={intent.ticket_id}\n"
            f"order_id={order_id}\n"
            f"status={status}\n"
            f"symbol={draft.symbol}\n"
            f"side={draft.side}\n"
            f"type={draft.order_type}\n"
            f"quantity={executed_qty}\n"
            f"avg_price={avg_price}"
        )

    draft = _build_draft(client, cfg, intent)
    ticket_id, expires_at_ms = store.create_ticket(chat_id, draft.as_dict(), raw_request, cfg.confirm_ttl_seconds)
    return _render_preview(ticket_id, expires_at_ms, draft)


def draft_from_dict(payload: Dict[str, Any]) -> DraftOrder:
    return DraftOrder(
        symbol=str(payload["symbol"]),
        side=str(payload["side"]),
        order_type=str(payload["type"]),
        quantity=Decimal(str(payload["quantity"])),
        notional_usdt=Decimal(str(payload["notional_usdt"])),
        leverage=int(payload["leverage"]),
        reduce_only=bool(payload.get("reduce_only", False)),
        price=Decimal(str(payload["price"])) if payload.get("price") is not None else None,
        time_in_force=str(payload["time_in_force"]) if payload.get("time_in_force") else None,
        inferred_from=str(payload.get("inferred_from", "unknown")),
    )


def run_cli(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="ASTER trading assistant entrypoint")
    parser.add_argument("--chat-id", required=True, help="Conversation/chat key for ticket isolation")
    parser.add_argument("--request", required=True, help="Free-form trading request")
    args = parser.parse_args(argv)

    try:
        output = handle_trade_request(args.request, chat_id=args.chat_id)
    except (TradeError, AsterApiError) as exc:
        print(f"ASTER trade error: {exc}")
        return 2
    except Exception as exc:  # pragma: no cover
        print(f"ASTER trade unexpected error: {exc}")
        return 3

    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
