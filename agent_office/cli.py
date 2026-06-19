from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, is_dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from agent_office.backtest import (
    RuleBaselineBacktester,
    load_or_fetch_okx_public_ohlcv_with_source,
    ohlcv_cache_path,
    parse_utc_date,
    result_summary,
    warmup_start,
)
from agent_office.config import AppConfig, load_config
from agent_office.cycle import DecisionCycle
from agent_office.dashboard_export import export_dashboard_csv
from agent_office.env import load_dotenv
from agent_office.execution import PaperExecutionAdapter
from agent_office.models import Candle, Side
from agent_office.okx import OkxDemoAdapter
from agent_office.optimizer import CandidateParams, optimize_strategy_params, tuned_config_toml
from agent_office.risk import RiskLayer
from agent_office.storage import SQLiteStore
from agent_office.strategy import RuleBasedBaseline
from agent_office.web import run_dashboard


def main(argv: list[str] | None = None) -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(prog="agent-office")
    subparsers = parser.add_subparsers(dest="command", required=True)
    config_parent = argparse.ArgumentParser(add_help=False)
    config_parent.add_argument("--config", type=Path, default=None, help="TOML config path")

    init_parser = subparsers.add_parser("init", parents=[config_parent], help="initialize local SQLite paper store")
    init_parser.add_argument("--db", type=Path, default=None)

    smoke_parser = subparsers.add_parser("smoke-cycle", parents=[config_parent], help="run one deterministic paper cycle")
    smoke_parser.add_argument("--db", type=Path, default=None)
    smoke_parser.add_argument("--symbol", default=None)

    web_parser = subparsers.add_parser("web", parents=[config_parent], help="serve operator console for agent actions")
    web_parser.add_argument("--db", type=Path, default=None)
    web_parser.add_argument("--host", default="127.0.0.1")
    web_parser.add_argument("--port", type=int, default=8787)

    backtest_parser = subparsers.add_parser("backtest", parents=[config_parent], help="run rule-baseline historical backtest")
    backtest_parser.add_argument("--start", required=True, help="UTC start date, inclusive, e.g. 2026-01-01")
    backtest_parser.add_argument("--end", required=True, help="UTC end date, exclusive, e.g. 2026-04-01")
    backtest_parser.add_argument("--symbols", nargs="+", default=None)
    backtest_parser.add_argument("--fee-rate", type=float, default=0.0005)
    backtest_parser.add_argument("--db", type=Path, default=None)
    backtest_parser.add_argument("--cache-dir", type=Path, default=Path("data/ohlcv_cache"))

    dashboard_parser = subparsers.add_parser(
        "dashboard-export", parents=[config_parent], help="write latest backtest result to the pixel dashboard CSV"
    )
    dashboard_parser.add_argument("--db", type=Path, default=None)
    dashboard_parser.add_argument(
        "--out", type=Path, default=Path("results/grid-raw-walk-forward.csv")
    )

    optimize_parser = subparsers.add_parser("optimize", parents=[config_parent], help="offline random-search strategy parameter optimizer")
    optimize_parser.add_argument("--train-start", required=True)
    optimize_parser.add_argument("--train-end", required=True)
    optimize_parser.add_argument("--validate-start", required=True)
    optimize_parser.add_argument("--validate-end", required=True)
    optimize_parser.add_argument("--test-start", default=None)
    optimize_parser.add_argument("--test-end", default=None)
    optimize_parser.add_argument("--samples", type=int, default=20)
    optimize_parser.add_argument("--seed", type=int, default=7)
    optimize_parser.add_argument("--min-trades", type=int, default=20)
    optimize_parser.add_argument("--symbols", nargs="+", default=None)
    optimize_parser.add_argument("--cache-dir", type=Path, default=Path("data/ohlcv_cache"))
    optimize_parser.add_argument("--out-config", type=Path, default=Path("config/agent-office-optimized.toml"))

    demo_trade_parser = subparsers.add_parser("demo-trade", parents=[config_parent], help="place one tiny guarded OKX demo market order")
    demo_trade_parser.add_argument("--db", type=Path, default=None)
    demo_trade_parser.add_argument("--symbol", default=None)
    demo_trade_parser.add_argument("--side", choices=["long", "short"], default="long")
    demo_trade_parser.add_argument("--amount", type=float, default=1.0, help="OKX contract amount")
    demo_trade_parser.add_argument("--leverage", type=float, default=1.0)
    demo_trade_parser.add_argument("--stop-pct", type=float, default=0.05)

    args = parser.parse_args(argv)
    config = load_config(getattr(args, "config", None))
    if getattr(args, "db", None) is not None:
        config = replace(config, db_path=args.db)
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
        symbol = args.symbol or config.watchlist[0]
        result = cycle.run_symbol(
            symbol=symbol,
            candles_4h=_sample_candles(90, hours=4, start_price=100.0, drift=0.55),
            candles_1d=_sample_candles(90, hours=24, start_price=80.0, drift=0.85),
        )
        print(json.dumps(result, default=_json_default, indent=2))
        return 0

    if args.command == "web":
        run_dashboard(config.db_path, host=args.host, port=args.port, config=config)
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
        symbols = tuple(args.symbols or config.watchlist)
        backtest_config = AppConfig(
            watchlist=symbols,
            starting_equity_usdt=config.starting_equity_usdt,
            default_leverage=config.default_leverage,
            risk_limits=config.risk_limits,
            strategy=config.strategy,
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
        candles_4h, cache_4h = _load_backtest_candles(symbols, "4h", fetch_start, end, args.cache_dir)
        candles_1d, cache_1d = _load_backtest_candles(symbols, "1d", fetch_start, end, args.cache_dir)
        result = RuleBaselineBacktester(backtest_config, fee_rate=args.fee_rate).run(
            candles_4h_by_symbol=candles_4h,
            candles_1d_by_symbol=candles_1d,
            start=start,
            end=end,
        )
        summary = result_summary(result)
        summary["ohlcv_cache"] = _cache_summary(args.cache_dir, cache_4h + cache_1d)
        store.record_audit("backtest_result", None, summary)
        print(json.dumps(summary, default=_json_default, indent=2))
        return 0

    if args.command == "optimize":
        train_start = parse_utc_date(args.train_start)
        train_end = parse_utc_date(args.train_end)
        validate_start = parse_utc_date(args.validate_start)
        validate_end = parse_utc_date(args.validate_end)
        test_start = parse_utc_date(args.test_start) if args.test_start else None
        test_end = parse_utc_date(args.test_end) if args.test_end else None
        symbols = tuple(args.symbols or config.watchlist)
        optimize_config = replace(config, watchlist=symbols)
        fetch_start = warmup_start(min(train_start, validate_start, test_start or train_start))
        fetch_end = max(train_end, validate_end, test_end or validate_end)
        candles_4h, cache_4h = _load_backtest_candles(symbols, "4h", fetch_start, fetch_end, args.cache_dir)
        candles_1d, cache_1d = _load_backtest_candles(symbols, "1d", fetch_start, fetch_end, args.cache_dir)
        report = optimize_strategy_params(
            optimize_config,
            candles_4h,
            candles_1d,
            train_start=train_start,
            train_end=train_end,
            validate_start=validate_start,
            validate_end=validate_end,
            test_start=test_start,
            test_end=test_end,
            samples=args.samples,
            seed=args.seed,
            min_trades=args.min_trades,
        )
        best = report["best"]["params"]
        best_params = CandidateParams(
            stop_atr_multiple=best["stop_atr_multiple"],
            min_stop_distance_pct=best["min_stop_distance_pct"],
            max_concurrent_positions=best["max_concurrent_positions"],
        )
        args.out_config.parent.mkdir(parents=True, exist_ok=True)
        args.out_config.write_text(tuned_config_toml(optimize_config, best_params), encoding="utf-8")
        report["out_config"] = str(args.out_config)
        report["ohlcv_cache"] = _cache_summary(args.cache_dir, cache_4h + cache_1d)
        print(json.dumps(report, default=_json_default, indent=2))
        return 0

    if args.command == "demo-trade":
        store.initialize(config.starting_equity_usdt)
        symbol = args.symbol or config.watchlist[0]
        side = Side(args.side)
        store.record_audit(
            "demo_trade_requested",
            symbol,
            {
                "symbol": symbol,
                "side": args.side,
                "amount": args.amount,
                "leverage": args.leverage,
                "stop_pct": args.stop_pct,
            },
        )
        adapter = OkxDemoAdapter.from_env()
        result = adapter.place_demo_market_with_stop(
            symbol=symbol,
            side=side,
            amount=args.amount,
            leverage=args.leverage,
            stop_pct=args.stop_pct,
        )
        store.record_audit("demo_trade_placed", symbol, result)
        print(json.dumps(result, default=_json_default, indent=2))
        return 0

    raise AssertionError(f"unknown command {args.command}")


def _load_backtest_candles(
    symbols: tuple[str, ...],
    timeframe: str,
    start: datetime,
    end: datetime,
    cache_dir: Path,
) -> tuple[dict[str, list[Candle]], list[dict[str, Any]]]:
    candles_by_symbol: dict[str, list[Candle]] = {}
    cache_files: list[dict[str, Any]] = []

    for symbol in symbols:
        cache_path = ohlcv_cache_path(cache_dir, symbol, timeframe, start, end)
        cache_hit = cache_path.exists()
        candles, source = load_or_fetch_okx_public_ohlcv_with_source(symbol, timeframe, start, end, cache_dir)
        candles_by_symbol[symbol] = candles
        cache_files.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "path": str(cache_path),
                "rows": len(candles),
                "source": "csv_cache" if cache_hit else source,
            }
        )

    return candles_by_symbol, cache_files


def _cache_summary(cache_dir: Path, files: list[dict[str, Any]]) -> dict[str, Any]:
    hits = sum(1 for item in files if item["source"] == "csv_cache")
    misses = len(files) - hits
    return {
        "dir": str(cache_dir),
        "hits": hits,
        "misses_saved_as_csv": misses,
        "files": files,
    }


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
