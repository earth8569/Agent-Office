from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from agent_office.config import AppConfig, default_config
from agent_office.cycle import DecisionCycle
from agent_office.execution import PaperExecutionAdapter
from agent_office.models import Candle
from agent_office.risk import RiskLayer
from agent_office.storage import SQLiteStore
from agent_office.strategy import RuleBasedBaseline
from agent_office.web import run_dashboard


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-office")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="initialize local SQLite paper store")
    init_parser.add_argument("--db", type=Path, default=default_config().db_path)

    smoke_parser = subparsers.add_parser("smoke-cycle", help="run one deterministic paper cycle")
    smoke_parser.add_argument("--db", type=Path, default=default_config().db_path)
    smoke_parser.add_argument("--symbol", default="BTC/USDT:USDT")

    web_parser = subparsers.add_parser("web", help="serve operator console for agent actions")
    web_parser.add_argument("--db", type=Path, default=default_config().db_path)
    web_parser.add_argument("--host", default="127.0.0.1")
    web_parser.add_argument("--port", type=int, default=8787)

    args = parser.parse_args(argv)
    config = AppConfig(db_path=args.db)
    store = SQLiteStore(config.db_path)

    if args.command == "init":
        store.initialize(config.starting_equity_usdt)
        account = store.load_account()
        print(json.dumps({"db": str(config.db_path), "account": account}, default=_json_default, indent=2))
        return 0

    if args.command == "smoke-cycle":
        cycle = DecisionCycle(
            config=config,
            store=store,
            strategy=RuleBasedBaseline(config),
            risk_layer=RiskLayer(config.risk_limits),
            execution=PaperExecutionAdapter(),
        )
        result = cycle.run_symbol(
            symbol=args.symbol,
            candles_4h=_sample_candles(90, hours=4, start_price=100.0, drift=0.55),
            candles_1d=_sample_candles(90, hours=24, start_price=80.0, drift=0.85),
        )
        print(json.dumps(result, default=_json_default, indent=2))
        return 0

    if args.command == "web":
        run_dashboard(config.db_path, host=args.host, port=args.port)
        return 0

    raise AssertionError(f"unknown command {args.command}")


def _sample_candles(count: int, hours: int, start_price: float, drift: float) -> list[Candle]:
    timestamp = datetime.now(timezone.utc) - timedelta(hours=hours * count)
    price = start_price
    candles: list[Candle] = []
    for index in range(count):
        wave = math.sin(index / 4) * drift * 0.7
        open_price = price
        close = max(1.0, open_price + drift + wave)
        high = max(open_price, close) + (drift * 1.8)
        low = min(open_price, close) - (drift * 1.8)
        volume = 1_000 + (index % 10) * 35
        candles.append(Candle(timestamp, open_price, high, low, close, volume))
        price = close
        timestamp += timedelta(hours=hours)
    return candles


def _json_default(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return asdict(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


if __name__ == "__main__":
    raise SystemExit(main())
