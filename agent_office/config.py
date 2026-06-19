from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any

from agent_office.models import TradingMode

CONFIG_ENV_VAR = "AGENT_OFFICE_CONFIG"
DEFAULT_CONFIG_PATH = Path("config/agent-office.toml")


@dataclass(frozen=True)
class RiskLimits:
    max_risk_per_trade_pct: float = 0.01
    max_leverage: float = 5.0
    max_concurrent_positions: int = 3
    max_total_notional_to_equity: float = 3.0
    daily_loss_limit_pct: float = 0.05
    max_drawdown_pct: float = 0.20


@dataclass(frozen=True)
class StrategyParams:
    stop_atr_multiple: float = 2.0
    min_stop_distance_pct: float = 0.005
    take_profit_r_multiple: float = 1.5


@dataclass(frozen=True)
class AppConfig:
    trading_mode: TradingMode = TradingMode.PAPER
    watchlist: tuple[str, ...] = ("BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT")
    db_path: Path = Path("data/agent_office.sqlite")
    starting_equity_usdt: float = 10_000.0
    default_leverage: float = 2.0
    risk_limits: RiskLimits = field(default_factory=RiskLimits)
    strategy: StrategyParams = field(default_factory=StrategyParams)


def default_config() -> AppConfig:
    return AppConfig()


def load_config(path: Path | str | None = None) -> AppConfig:
    """Load real-world runtime config from TOML, with dataclass defaults.

    Resolution order:
    1. explicit `path`
    2. `AGENT_OFFICE_CONFIG`
    3. `config/agent-office.toml` when it exists
    4. built-in defaults
    """
    config_path = _resolve_config_path(path)
    if config_path is None:
        return default_config()
    if not config_path.exists():
        raise FileNotFoundError(f"config file not found: {config_path}")
    if not config_path.is_file():
        raise ValueError(f"config path is not a file: {config_path}")

    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("config file must contain a TOML table")
    return _config_from_mapping(data)


def _resolve_config_path(path: Path | str | None) -> Path | None:
    if path is not None:
        return Path(path)
    env_path = os.environ.get(CONFIG_ENV_VAR)
    if env_path:
        return Path(env_path)
    return DEFAULT_CONFIG_PATH if DEFAULT_CONFIG_PATH.exists() else None


def _config_from_mapping(data: dict[str, Any]) -> AppConfig:
    allowed = {
        "trading_mode",
        "watchlist",
        "db_path",
        "starting_equity_usdt",
        "default_leverage",
        "risk_limits",
        "strategy",
    }
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValueError(f"unknown config key(s): {', '.join(unknown)}")

    config = default_config()
    updates: dict[str, Any] = {}
    if "trading_mode" in data:
        updates["trading_mode"] = _trading_mode(data["trading_mode"])
    if "watchlist" in data:
        updates["watchlist"] = _watchlist(data["watchlist"])
    if "db_path" in data:
        updates["db_path"] = Path(_string(data["db_path"], "db_path"))
    if "starting_equity_usdt" in data:
        updates["starting_equity_usdt"] = _positive_float(data["starting_equity_usdt"], "starting_equity_usdt")
    if "default_leverage" in data:
        updates["default_leverage"] = _positive_float(data["default_leverage"], "default_leverage")
    if "risk_limits" in data:
        risk_limits = _risk_limits(data["risk_limits"], config.risk_limits)
        updates["risk_limits"] = risk_limits
    if "strategy" in data:
        updates["strategy"] = _strategy_params(data["strategy"], config.strategy)
    return replace(config, **updates)


def _strategy_params(data: Any, defaults: StrategyParams) -> StrategyParams:
    if not isinstance(data, dict):
        raise ValueError("strategy must be a TOML table")
    allowed = {field.name for field in fields(StrategyParams)}
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValueError(f"unknown strategy key(s): {', '.join(unknown)}")

    updates: dict[str, Any] = {}
    for key, value in data.items():
        updates[key] = _positive_float(value, key)
    return replace(defaults, **updates)


def _risk_limits(data: Any, defaults: RiskLimits) -> RiskLimits:
    if not isinstance(data, dict):
        raise ValueError("risk_limits must be a TOML table")
    allowed = {field.name for field in fields(RiskLimits)}
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValueError(f"unknown risk_limits key(s): {', '.join(unknown)}")

    updates: dict[str, Any] = {}
    for key, value in data.items():
        if key == "max_concurrent_positions":
            updates[key] = _positive_int(value, key)
        else:
            updates[key] = _positive_float(value, key)
    return replace(defaults, **updates)


def _trading_mode(value: Any) -> TradingMode:
    text = _string(value, "trading_mode")
    try:
        return TradingMode(text)
    except ValueError as exc:
        allowed = ", ".join(mode.value for mode in TradingMode)
        raise ValueError(f"trading_mode must be one of: {allowed}") from exc


def _watchlist(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError("watchlist must be a TOML array of symbols")
    symbols = tuple(_string(item, "watchlist item") for item in value)
    if not symbols:
        raise ValueError("watchlist must contain at least one symbol")
    return symbols


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _positive_float(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive number") from exc
    if number <= 0:
        raise ValueError(f"{name} must be a positive number")
    return number


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be a positive integer")
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value
