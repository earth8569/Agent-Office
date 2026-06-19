from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from agent_office.backtest import RuleBaselineBacktester, _OpenPosition, _position_from_intent, load_or_fetch_okx_public_ohlcv, ohlcv_cache_path, result_summary
from agent_office.cli import _cache_summary, _load_backtest_candles
from agent_office.config import AppConfig
from agent_office.models import Candle, Side, TradeIntent


class BacktestTests(unittest.TestCase):
    def test_rule_backtest_runs_with_synthetic_history(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 2, 1, tzinfo=timezone.utc)
        candles_4h = _trend_candles(start - timedelta(days=90), end, timedelta(hours=4), 100, 0.35)
        candles_1d = _trend_candles(start - timedelta(days=90), end, timedelta(days=1), 90, 1.2)
        config = AppConfig(watchlist=("BTC/USDT:USDT",))

        result = RuleBaselineBacktester(config).run(
            candles_4h_by_symbol={"BTC/USDT:USDT": candles_4h},
            candles_1d_by_symbol={"BTC/USDT:USDT": candles_1d},
            start=start,
            end=end,
        )

        summary = result_summary(result)

        self.assertGreater(result.cycles, 0)
        self.assertGreaterEqual(result.ending_equity_usdt, 0)
        self.assertEqual(result.symbols, ("BTC/USDT:USDT",))
        self.assertIn("BTC/USDT:USDT", summary["per_symbol"])
        self.assertIn("classification", summary["per_symbol"]["BTC/USDT:USDT"])

    def test_position_from_intent_sets_take_profit_from_r_multiple(self) -> None:
        opened_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        long_intent = TradeIntent(
            symbol="BTC/USDT:USDT",
            side=Side.LONG,
            entry_price=100.0,
            stop_loss=96.0,
            notional_usdt=1000.0,
            leverage=2.0,
            thesis="test long",
        )
        short_intent = TradeIntent(
            symbol="ETH/USDT:USDT",
            side=Side.SHORT,
            entry_price=100.0,
            stop_loss=104.0,
            notional_usdt=1000.0,
            leverage=2.0,
            thesis="test short",
        )

        long_position = _position_from_intent(long_intent, opened_at, take_profit_r_multiple=1.5)
        short_position = _position_from_intent(short_intent, opened_at, take_profit_r_multiple=2.0)

        self.assertEqual(long_position.take_profit, 106.0)
        self.assertEqual(short_position.take_profit, 92.0)

    def test_take_profit_hit_for_long_and_short_positions(self) -> None:
        opened_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        candle = Candle(
            timestamp=opened_at,
            open=100.0,
            high=106.0,
            low=94.0,
            close=101.0,
            volume=1000.0,
        )
        long_position = _OpenPosition(
            symbol="BTC/USDT:USDT",
            side=Side.LONG,
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=106.0,
            notional_usdt=1000.0,
            leverage=2.0,
            quantity=10.0,
            opened_at=opened_at,
        )
        short_position = _OpenPosition(
            symbol="ETH/USDT:USDT",
            side=Side.SHORT,
            entry_price=100.0,
            stop_loss=105.0,
            take_profit=94.0,
            notional_usdt=1000.0,
            leverage=2.0,
            quantity=10.0,
            opened_at=opened_at,
        )

        self.assertTrue(RuleBaselineBacktester._take_profit_hit(long_position, candle))
        self.assertTrue(RuleBaselineBacktester._take_profit_hit(short_position, candle))

    def test_ohlcv_cache_reuses_saved_csv(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 1, 2, tzinfo=timezone.utc)
        candles = [
            Candle(
                timestamp=start,
                open=100.0,
                high=105.0,
                low=99.0,
                close=104.0,
                volume=123.0,
            )
        ]

        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            cache_path = ohlcv_cache_path(cache_dir, "BTC/USDT:USDT", "4h", start, end)
            with patch("agent_office.backtest.fetch_okx_public_ohlcv", return_value=candles) as fetch:
                first = load_or_fetch_okx_public_ohlcv("BTC/USDT:USDT", "4h", start, end, cache_dir)
                second = load_or_fetch_okx_public_ohlcv("BTC/USDT:USDT", "4h", start, end, cache_dir)

            self.assertTrue(cache_path.exists())
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(first, second)
            self.assertEqual(second[0].close, 104.0)

    def test_cli_backtest_cache_report_marks_csv_reuse(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 1, 2, tzinfo=timezone.utc)
        candles = [Candle(timestamp=start, open=100.0, high=105.0, low=99.0, close=104.0, volume=123.0)]

        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            cache_path = ohlcv_cache_path(cache_dir, "BTC/USDT:USDT", "4h", start, end)
            with patch("agent_office.cli.load_or_fetch_okx_public_ohlcv_with_source", return_value=(candles, "okx_swap_fetch_saved_csv")):
                candles_by_symbol, files = _load_backtest_candles(("BTC/USDT:USDT",), "4h", start, end, cache_dir)
            cache_path.touch()
            with patch("agent_office.cli.load_or_fetch_okx_public_ohlcv_with_source", return_value=(candles, "okx_swap_fetch_saved_csv")):
                _, cached_files = _load_backtest_candles(("BTC/USDT:USDT",), "4h", start, end, cache_dir)

        summary = _cache_summary(cache_dir, files + cached_files)

        self.assertEqual(candles_by_symbol["BTC/USDT:USDT"], candles)
        self.assertEqual(files[0]["source"], "okx_swap_fetch_saved_csv")
        self.assertEqual(cached_files[0]["source"], "csv_cache")
        self.assertEqual(summary["hits"], 1)
        self.assertEqual(summary["misses_saved_as_csv"], 1)


def _trend_candles(
    start: datetime,
    end: datetime,
    step: timedelta,
    start_price: float,
    drift: float,
) -> list[Candle]:
    candles: list[Candle] = []
    timestamp = start
    price = start_price
    while timestamp < end:
        close = price + drift
        candles.append(
            Candle(
                timestamp=timestamp,
                open=price,
                high=close + drift,
                low=price - drift,
                close=close,
                volume=1_000,
            )
        )
        price = close
        timestamp += step
    return candles


if __name__ == "__main__":
    unittest.main()
