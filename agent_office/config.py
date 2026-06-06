from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agent_office.models import TradingMode


@dataclass(frozen=True)
class RiskLimits:
    max_risk_per_trade_pct: float = 0.01
    max_leverage: float = 5.0
    max_concurrent_positions: int = 3
    max_total_notional_to_equity: float = 3.0
    daily_loss_limit_pct: float = 0.05
    max_drawdown_pct: float = 0.20


@dataclass(frozen=True)
class AppConfig:
    trading_mode: TradingMode = TradingMode.PAPER
    watchlist: tuple[str, ...] = ("BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT")
    db_path: Path = Path("data/agent_office.sqlite")
    starting_equity_usdt: float = 10_000.0
    default_leverage: float = 2.0
    risk_limits: RiskLimits = field(default_factory=RiskLimits)


def default_config() -> AppConfig:
    return AppConfig()
