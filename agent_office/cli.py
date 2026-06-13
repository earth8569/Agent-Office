from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from agent_office.backtest import (
    RuleBaselineBacktester,
    load_or_fetch_okx_public_ohlcv,
    parse_utc_date,
    result_summary,
    warmup_start,
)
from agent_office.config import AppConfig, default_config
from agent_office.cycle import DecisionCycle
from agent_office.dashboard_export import export_dashboard_csv
from agent_office.env import load_dotenv
from agent_office.execution import PaperExecutionAdapter
from agent_office.models import Candle
from agent_office.okx import OkxDemoAdapter
from agent_office.models import Side
from agent_office.risk import RiskLayer
from agent_office.storage import SQLiteStore
from agent_office.strategy import RuleBasedBaseline
from agent_office.web import run_dashboard


def main(argv: list[str] | None = None) -> int:
    load_dotenv()

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

    backtest_parser = subparsers.add_parser("backtest", help="run rule-baseline historical backtest")
    backtest_parser.add_argument("--start", required=True, help="UTC start date, inclusive, e.g. 2026-01-01")
    backtest_parser.add_argument("--end", required=True, help="UTC end date, exclusive, e.g. 2026-04-01")
    backtest_parser.add_argument("--symbols", nargs="+", default=list(default_config().watchlist))
    backtest_parser.add_argument("--fee-rate", type=float, default=0.0005)
    backtest_parser.add_argument("--db", type=Path, default=default_config().db_path)
    backtest_parser.add_argument("--cache-dir", type=Path, default=Path("data/ohlcv_cache"))

    dashboard_parser = subparsers.add_parser(
        "dashboard-export", help="write latest backtest result to the pixel dashboard CSV"
    )
    dashboard_parser.add_argument("--db", type=Path, default=default_config().db_path)
    dashboard_parser.add_argument(
        "--out", type=Path, default=Path("results/grid-raw-walk-forward.csv")
    )

    demo_trade_parser = subparsers.add_parser("demo-trade", help="place one tiny guarded OKX demo market order")
    demo_trade_parser.add_argument("--db", type=Path, default=default_config().db_path)
    demo_trade_parser.add_argument("--symbol", default="SOL/USDT:USDT")
    demo_trade_parser.add_argument("--side", choices=["long", "short"], default="long")
    demo_trade_parser.add_argument("--amount", type=float, default=1.0, help="OKX contract amount")
    demo_trade_parser.add_argument("--leverage", type=float, default=1.0)
    demo_trade_parser.add_argument("--stop-pct", type=float, default=0.05)

    args = parser.parse_args(argv)
    config = AppConfig(db_path=getattr(args, "db", default_config().db_path))
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

    if args.command == "dashboard-export":
        store.initialize(config.starting_equity_usdt)
        count = export_dashboard_csv(store, args.out)
        print(json.dumps({"out": str(args.out), "rows": count}, indent=2))
        return 0

    if args.command == "backtest":
        start = parse_utc_date(args.start)
        end = parse_utc_date(args.end)
        if end <= start:
            raise ValueError("--end must be after --start")
        symbols = tuple(args.symbols)
        backtest_config = AppConfig(
            watchlist=symbols,
            starting_equity_usdt=config.starting_equity_usdt,
            default_leverage=config.default_leverage,
            risk_limits=config.risk_limits,
        )
        fetch_start = warmup_start(start)
        store.initialize(config.starting_equity_usdt)
        store.record_audit(
            "backtest_started",
            None,
            {
                "start": start.isoformat(),
                "end_exclusive": end.isoformat(),
                "symbols": list(symbols),
                "fee_rate": args.fee_rate,
                "cache_dir": str(args.cache_dir),
            },
        )
        candles_4h = {
            symbol: load_or_fetch_okx_public_ohlcv(symbol, "4h", fetch_start, end, args.cache_dir)
            for symbol in symbols
        }
        candles_1d = {
            symbol: load_or_fetch_okx_public_ohlcv(symbol, "1d", fetch_start, end, args.cache_dir)
            for symbol in symbols
        }
        result = RuleBaselineBacktester(backtest_config, fee_rate=args.fee_rate).run(
            candles_4h_by_symbol=candles_4h,
            candles_1d_by_symbol=candles_1d,
            start=start,
            end=end,
        )
        summary = result_summary(result)
        store.record_audit("backtest_result", None, summary)
        print(json.dumps(summary, default=_json_default, indent=2))
        return 0

    if args.command == "demo-trade":
        store.initialize(config.starting_equity_usdt)
        side = Side(args.side)
        store.record_audit(
            "demo_trade_requested",
            args.symbol,
            {
                "symbol": args.symbol,
                "side": args.side,
                "amount": args.amount,
                "leverage": args.leverage,
                "stop_pct": args.stop_pct,
            },
        )
        adapter = OkxDemoAdapter.from_env()
        result = adapter.place_demo_market_with_stop(
            symbol=args.symbol,
            side=side,
            amount=args.amount,
            leverage=args.leverage,
            stop_pct=args.stop_pct,
        )
        store.record_audit("demo_trade_placed", args.symbol, result)
        print(json.dumps(result, default=_json_default, indent=2))
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
