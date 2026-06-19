from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from agent_office.config import AppConfig
from agent_office.models import Candle
from agent_office.optimizer import CandidateParams, optimize_strategy_params, tuned_config_toml


class OptimizerTests(unittest.TestCase):
    def test_optimizer_returns_best_candidate_and_toml(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 4, 1, tzinfo=timezone.utc)
        candles_4h = _trend_candles(start - timedelta(days=90), end, timedelta(hours=4), 100, 0.4)
        candles_1d = _trend_candles(start - timedelta(days=90), end, timedelta(days=1), 90, 1.0)
        config = AppConfig(watchlist=("BTC/USDT:USDT",))

        result = optimize_strategy_params(
            config,
            {"BTC/USDT:USDT": candles_4h},
            {"BTC/USDT:USDT": candles_1d},
            train_start=start,
            train_end=datetime(2026, 2, 1, tzinfo=timezone.utc),
            validate_start=datetime(2026, 2, 1, tzinfo=timezone.utc),
            validate_end=datetime(2026, 3, 1, tzinfo=timezone.utc),
            test_start=datetime(2026, 3, 1, tzinfo=timezone.utc),
            test_end=end,
            samples=2,
            seed=1,
            min_trades=0,
        )
        toml = tuned_config_toml(config, CandidateParams(3.0, 0.005, 2))

        self.assertIn("best", result)
        self.assertIn("test", result["best"])
        self.assertIn("[strategy]", toml)
        self.assertIn("stop_atr_multiple = 3.0", toml)
        self.assertIn("max_concurrent_positions = 2", toml)


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
        candles.append(Candle(timestamp=timestamp, open=price, high=close + drift, low=price - drift, close=close, volume=1_000))
        price = close
        timestamp += step
    return candles


if __name__ == "__main__":
    unittest.main()