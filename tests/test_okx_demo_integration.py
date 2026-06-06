from __future__ import annotations

import unittest
from pathlib import Path
from uuid import uuid4

from agent_office.okx import OkxDemoAdapter, okx_demo_test_enabled
from agent_office.reconcile import ReconciliationService
from agent_office.storage import SQLiteStore


@unittest.skipUnless(okx_demo_test_enabled(), "set RUN_OKX_DEMO_TESTS=1 and OKX demo env vars")
class OkxDemoIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = OkxDemoAdapter.from_env()

    def test_fetches_closed_candles_and_exchange_state(self) -> None:
        candles_4h = self.adapter.fetch_closed_candles("BTC/USDT:USDT", "4h", 60)
        candles_1d = self.adapter.fetch_closed_candles("BTC/USDT:USDT", "1d", 60)
        state = self.adapter.fetch_exchange_state(("BTC/USDT:USDT",))

        self.assertEqual(len(candles_4h), 60)
        self.assertEqual(len(candles_1d), 60)
        self.assertGreater(state.equity_usdt, 0)

    def test_reconcile_records_ok_or_mismatch_without_trading(self) -> None:
        db_path = Path("data") / f"test-okx-demo-{uuid4().hex}.sqlite"
        self.addCleanup(lambda: db_path.unlink(missing_ok=True))
        store = SQLiteStore(db_path)
        store.initialize(10_000)
        service = ReconciliationService(self.adapter)

        report = service.reconcile(store, ("BTC/USDT:USDT",))

        self.assertIn(report.status.value, {"ok", "mismatch"})
        self.assertGreater(report.exchange_state.equity_usdt, 0)


if __name__ == "__main__":
    unittest.main()
