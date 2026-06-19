from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_office.config import CONFIG_ENV_VAR, load_config
from agent_office.models import TradingMode


class ConfigTests(unittest.TestCase):
    def test_loads_toml_runtime_config(self) -> None:
        path = self._write_config(
            """
            trading_mode = "paper"
            watchlist = ["DOGE/USDT:USDT", "SOL/USDT:USDT"]
            db_path = "data/custom.sqlite"
            starting_equity_usdt = 2500.0
            default_leverage = 1.5

            [risk_limits]
            max_leverage = 3.0
            max_concurrent_positions = 1

            [strategy]
            stop_atr_multiple = 1.5
            min_stop_distance_pct = 0.01
            take_profit_r_multiple = 1.8
            """
        )

        config = load_config(path)

        self.assertEqual(config.trading_mode, TradingMode.PAPER)
        self.assertEqual(config.watchlist, ("DOGE/USDT:USDT", "SOL/USDT:USDT"))
        self.assertEqual(config.db_path, Path("data/custom.sqlite"))
        self.assertEqual(config.starting_equity_usdt, 2500.0)
        self.assertEqual(config.default_leverage, 1.5)
        self.assertEqual(config.risk_limits.max_leverage, 3.0)
        self.assertEqual(config.risk_limits.max_concurrent_positions, 1)
        self.assertEqual(config.strategy.stop_atr_multiple, 1.5)
        self.assertEqual(config.strategy.min_stop_distance_pct, 0.01)
        self.assertEqual(config.strategy.take_profit_r_multiple, 1.8)

    def test_env_var_selects_config_file(self) -> None:
        path = self._write_config('watchlist = ["XRP/USDT:USDT"]')

        with patch.dict(os.environ, {CONFIG_ENV_VAR: str(path)}):
            config = load_config()

        self.assertEqual(config.watchlist, ("XRP/USDT:USDT",))

    def test_rejects_unknown_config_keys(self) -> None:
        path = self._write_config('watchlist = ["BTC/USDT:USDT"]\nunknown = true')

        with self.assertRaisesRegex(ValueError, "unknown config key"):
            load_config(path)

    def test_rejects_empty_watchlist(self) -> None:
        path = self._write_config("watchlist = []")

        with self.assertRaisesRegex(ValueError, "watchlist"):
            load_config(path)

    def _write_config(self, content: str) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "agent-office.toml"
        path.write_text(content.strip(), encoding="utf-8")
        return path


if __name__ == "__main__":
    unittest.main()