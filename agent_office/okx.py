from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol, Sequence

from agent_office.models import Candle, ExchangePosition, ExchangeState, ExchangeStopOrder, Side


@dataclass(frozen=True)
class OkxCredentials:
    api_key: str = field(repr=False)
    api_secret: str = field(repr=False)
    passphrase: str = field(repr=False)
    demo: bool = True

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "OkxCredentials | None":
        env = environ or os.environ
        api_key = env.get("OKX_API_KEY", "").strip()
        api_secret = env.get("OKX_API_SECRET", "").strip()
        passphrase = env.get("OKX_API_PASSPHRASE", "").strip()
        if not api_key or not api_secret or not passphrase:
            return None
        return cls(
            api_key=api_key,
            api_secret=api_secret,
            passphrase=passphrase,
            demo=env.get("OKX_DEMO", "1").strip() != "0",
        )

    @classmethod
    def from_env_required(cls, environ: Mapping[str, str] | None = None) -> "OkxCredentials":
        credentials = cls.from_env(environ)
        if credentials is None:
            raise RuntimeError("OKX_API_KEY, OKX_API_SECRET, OKX_API_PASSPHRASE required")
        return credentials


class ExchangeStateAdapter(Protocol):
    def fetch_exchange_state(self, symbols: Sequence[str]) -> ExchangeState:
        ...


class OkxDemoAdapter:
    def __init__(self, credentials: OkxCredentials, exchange: Any | None = None) -> None:
        if not credentials.demo:
            raise ValueError("OkxDemoAdapter requires OKX_DEMO=1")
        self.credentials = credentials
        self.exchange = exchange or _create_okx_exchange(credentials)

    @classmethod
    def from_env(cls) -> "OkxDemoAdapter":
        return cls(OkxCredentials.from_env_required())

    def fetch_closed_candles(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        rows = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit + 1)
        closed_rows = rows[:-1]
        if len(closed_rows) < limit:
            raise RuntimeError(f"OKX returned {len(closed_rows)} closed {timeframe} candles, need {limit}")
        return [_parse_candle(row) for row in closed_rows[-limit:]]

    def fetch_exchange_state(self, symbols: Sequence[str]) -> ExchangeState:
        balance = self.exchange.fetch_balance()
        positions = self.fetch_positions(symbols)
        stop_orders = self.fetch_open_stop_orders(symbols)
        return ExchangeState(
            equity_usdt=_extract_equity_usdt(balance),
            positions=positions,
            stop_orders=stop_orders,
            raw_balance=_scrub_balance(balance),
        )

    def fetch_positions(self, symbols: Sequence[str]) -> tuple[ExchangePosition, ...]:
        positions = self.exchange.fetch_positions(list(symbols))
        parsed: list[ExchangePosition] = []
        for position in positions:
            quantity = abs(_float_value(position.get("contracts"), position.get("info", {}).get("pos"), default=0.0))
            if quantity <= 0:
                continue
            symbol = _normalize_symbol(str(position.get("symbol") or position.get("info", {}).get("instId") or ""))
            if symbols and symbol not in symbols:
                continue
            side = _parse_side(position.get("side"), position.get("info", {}).get("posSide"))
            entry_price = _float_value(position.get("entryPrice"), position.get("info", {}).get("avgPx"), default=0.0)
            leverage = _float_value(position.get("leverage"), position.get("info", {}).get("lever"), default=0.0)
            notional = abs(
                _float_value(
                    position.get("notional"),
                    position.get("info", {}).get("notionalUsd"),
                    position.get("info", {}).get("notional"),
                    default=entry_price * quantity,
                )
            )
            parsed.append(
                ExchangePosition(
                    symbol=symbol,
                    side=side,
                    entry_price=entry_price,
                    notional_usdt=notional,
                    leverage=leverage,
                    quantity=quantity,
                    raw=_scrub_mapping(position),
                )
            )
        return tuple(parsed)

    def fetch_open_stop_orders(self, symbols: Sequence[str]) -> tuple[ExchangeStopOrder, ...]:
        orders: list[dict[str, Any]] = []
        orders.extend(self._fetch_open_orders(symbols))
        orders.extend(self._fetch_pending_algo_orders())
        return tuple(_parse_stop_order(order) for order in orders if _looks_like_stop_order(order))

    def _fetch_open_orders(self, symbols: Sequence[str]) -> list[dict[str, Any]]:
        orders: list[dict[str, Any]] = []
        for symbol in symbols:
            try:
                orders.extend(self.exchange.fetch_open_orders(symbol))
            except Exception:
                continue
        return orders

    def _fetch_pending_algo_orders(self) -> list[dict[str, Any]]:
        method = getattr(self.exchange, "private_get_trade_orders_algo_pending", None)
        if method is None:
            return []
        response = method({"instType": "SWAP", "ordType": "conditional"})
        data = response.get("data", []) if isinstance(response, dict) else []
        return list(data)


def okx_demo_test_enabled(environ: Mapping[str, str] | None = None) -> bool:
    env = environ or os.environ
    credentials = OkxCredentials.from_env(env)
    return env.get("RUN_OKX_DEMO_TESTS", "0").strip() == "1" and credentials is not None and credentials.demo


def _create_okx_exchange(credentials: OkxCredentials) -> Any:
    try:
        import ccxt  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("ccxt not installed. Install project deps before OKX demo tests.") from exc

    config: dict[str, Any] = {
        "apiKey": credentials.api_key,
        "secret": credentials.api_secret,
        "password": credentials.passphrase,
        "enableRateLimit": True,
        "options": {
            "defaultType": "swap",
            "adjustForTimeDifference": True,
        },
        "headers": {"x-simulated-trading": "1"},
    }
    exchange = ccxt.okx(config)
    exchange.set_sandbox_mode(True)
    return exchange


def _parse_candle(row: Sequence[float]) -> Candle:
    return Candle(
        timestamp=datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc),
        open=float(row[1]),
        high=float(row[2]),
        low=float(row[3]),
        close=float(row[4]),
        volume=float(row[5]),
    )


def _parse_side(*values: object) -> Side:
    for value in values:
        normalized = str(value or "").lower()
        if normalized in {"short", "sell", "net_short"}:
            return Side.SHORT
        if normalized in {"long", "buy", "net_long"}:
            return Side.LONG
    return Side.LONG


def _parse_stop_order(order: dict[str, Any]) -> ExchangeStopOrder:
    info = order.get("info", {}) if isinstance(order.get("info"), dict) else {}
    symbol = _normalize_symbol(str(order.get("symbol") or info.get("instId") or ""))
    order_id = str(order.get("id") or info.get("algoId") or info.get("ordId") or "")
    stop_price = _optional_float(
        order.get("stopPrice"),
        order.get("triggerPrice"),
        info.get("slTriggerPx"),
        info.get("triggerPx"),
    )
    return ExchangeStopOrder(symbol=symbol, order_id=order_id, stop_price=stop_price, raw=_scrub_mapping(order))


def _looks_like_stop_order(order: dict[str, Any]) -> bool:
    info = order.get("info", {}) if isinstance(order.get("info"), dict) else {}
    order_type = str(order.get("type") or info.get("ordType") or "").lower()
    return any(
        value
        for value in (
            order.get("stopPrice"),
            order.get("triggerPrice"),
            info.get("slTriggerPx"),
            info.get("triggerPx"),
        )
    ) or order_type in {"stop", "trigger", "conditional", "oco", "move_order_stop"}


def _normalize_symbol(symbol: str) -> str:
    if "/" in symbol:
        return symbol
    if symbol.endswith("-USDT-SWAP"):
        base = symbol.removesuffix("-USDT-SWAP")
        return f"{base}/USDT:USDT"
    return symbol


def _extract_equity_usdt(balance: dict[str, Any]) -> float:
    usdt = balance.get("USDT")
    if isinstance(usdt, dict):
        value = _optional_float(usdt.get("total"), usdt.get("free"), usdt.get("used"))
        if value is not None:
            return value
    info = balance.get("info")
    if isinstance(info, dict):
        data = info.get("data")
        if isinstance(data, list) and data:
            value = _optional_float(data[0].get("totalEq"), data[0].get("adjEq"))
            if value is not None:
                return value
    raise RuntimeError("unable to extract USDT equity from OKX balance")


def _float_value(*values: object, default: float) -> float:
    parsed = _optional_float(*values)
    return default if parsed is None else parsed


def _optional_float(*values: object) -> float | None:
    for value in values:
        if value in (None, ""):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _scrub_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    blocked = {"apiKey", "secret", "password", "passphrase", "OK-ACCESS-KEY", "OK-ACCESS-SIGN"}
    return {str(key): ("<redacted>" if str(key) in blocked else _scrub_value(item)) for key, item in value.items()}


def _scrub_balance(balance: dict[str, Any]) -> dict[str, Any]:
    return _scrub_mapping(balance)


def _scrub_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _scrub_mapping(value)
    if isinstance(value, list):
        return [_scrub_value(item) for item in value]
    return value
