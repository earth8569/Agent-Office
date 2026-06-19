from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class TradingMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"


class Side(str, Enum):
    LONG = "long"
    SHORT = "short"


class CycleStatus(str, Enum):
    HOLD = "hold"
    REJECTED = "rejected"
    EXECUTED = "executed"
    ABORTED = "aborted"


class ReconciliationStatus(str, Enum):
    OK = "ok"
    MISMATCH = "mismatch"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        if self.high < max(self.open, self.close):
            raise ValueError("candle high below open/close")
        if self.low > min(self.open, self.close):
            raise ValueError("candle low above open/close")
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("candle prices must be positive")
        if self.volume < 0:
            raise ValueError("candle volume cannot be negative")


@dataclass(frozen=True)
class IndicatorSnapshot:
    symbol: str
    generated_at: datetime
    close: float
    trend: str
    daily_trend: str
    sma_fast: float
    sma_slow: float
    rsi: float
    macd: float
    macd_signal: float
    macd_hist: float
    atr: float
    support: float
    resistance: float
    volume_ratio: float
    volatility_pct: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TradeIntent:
    symbol: str
    side: Side
    entry_price: float
    stop_loss: float
    notional_usdt: float
    leverage: float
    thesis: str
    created_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Position:
    symbol: str
    side: Side
    entry_price: float
    stop_loss: float
    notional_usdt: float
    leverage: float
    quantity: float
    opened_at: datetime
    stop_order_id: str
    take_profit: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AccountState:
    equity_usdt: float
    peak_equity_usdt: float
    daily_pnl_usdt: float = 0.0
    positions: tuple[Position, ...] = field(default_factory=tuple)

    def total_notional_usdt(self) -> float:
        return sum(position.notional_usdt for position in self.positions)


@dataclass(frozen=True)
class ExchangePosition:
    symbol: str
    side: Side
    entry_price: float
    notional_usdt: float
    leverage: float
    quantity: float
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExchangeStopOrder:
    symbol: str
    order_id: str
    stop_price: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExchangeState:
    equity_usdt: float
    positions: tuple[ExchangePosition, ...] = field(default_factory=tuple)
    stop_orders: tuple[ExchangeStopOrder, ...] = field(default_factory=tuple)
    raw_balance: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReconciliationReport:
    status: ReconciliationStatus
    reason: str
    exchange_state: ExchangeState
    local_account: AccountState
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AuditEvent:
    id: int
    created_at: datetime
    event_type: str
    symbol: str | None
    payload: dict[str, Any]


@dataclass(frozen=True)
class RiskDecision:
    accepted: bool
    reason: str
    intent: TradeIntent | None = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrderResult:
    success: bool
    order_id: str
    position: Position | None
    message: str


@dataclass(frozen=True)
class CycleResult:
    status: CycleStatus
    symbol: str
    snapshot: IndicatorSnapshot | None
    intent: TradeIntent | None
    risk: RiskDecision | None
    order: OrderResult | None
    message: str
