from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from agent_office.backtest import RuleBaselineBacktester, load_or_fetch_okx_public_ohlcv, ohlcv_cache_path
from agent_office.config import AppConfig
from agent_office.models import Candle


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

        self.assertGreater(result.cycles, 0)
        self.assertGreaterEqual(result.ending_equity_usdt, 0)
        self.assertEqual(result.symbols, ("BTC/USDT:USDT",))

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
