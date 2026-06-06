from __future__ import annotations

import unittest
from pathlib import Path
from uuid import uuid4

from agent_office.cli import _sample_candles
from agent_office.config import AppConfig
from agent_office.cycle import DecisionCycle
from agent_office.execution import PaperExecutionAdapter
from agent_office.models import CycleStatus
from agent_office.risk import RiskLayer
from agent_office.storage import SQLiteStore
from agent_office.strategy import RuleBasedBaseline


class CycleSmokeTests(unittest.TestCase):
    def test_smoke_cycle_persists_paper_position_or_hold(self) -> None:
        db_path = Path("data") / f"test-cycle-{uuid4().hex}.sqlite"
        self.addCleanup(lambda: db_path.unlink(missing_ok=True))
        config = AppConfig(db_path=db_path)
        store = SQLiteStore(config.db_path)
        cycle = DecisionCycle(
            config=config,
            store=store,
            strategy=RuleBasedBaseline(config),
            risk_layer=RiskLayer(config.risk_limits),
            execution=PaperExecutionAdapter(),
        )

        result = cycle.run_symbol(
            symbol="BTC/USDT:USDT",
            candles_4h=_sample_candles(90, hours=4, start_price=100, drift=0.55),
            candles_1d=_sample_candles(90, hours=24, start_price=80, drift=0.85),
        )

        self.assertIn(result.status, {CycleStatus.EXECUTED, CycleStatus.HOLD})
        if result.status == CycleStatus.EXECUTED:
            account = store.load_account()
            self.assertEqual(len(account.positions), 1)
            self.assertEqual(account.positions[0].symbol, "BTC/USDT:USDT")
            self.assertTrue(account.positions[0].stop_order_id.startswith("paper-stop-"))


if __name__ == "__main__":
    unittest.main()
