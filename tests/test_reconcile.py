from __future__ import annotations

import unittest
from pathlib import Path
from uuid import uuid4

from agent_office.models import (
    AccountState,
    ExchangePosition,
    ExchangeState,
    ExchangeStopOrder,
    Position,
    ReconciliationStatus,
    Side,
    utc_now,
)
from agent_office.reconcile import ReconciliationService
from agent_office.storage import SQLiteStore


class FakeExchangeStateAdapter:
    def __init__(self, state: ExchangeState) -> None:
        self.state = state

    def fetch_exchange_state(self, symbols: list[str] | tuple[str, ...]) -> ExchangeState:
        return self.state


class ReconciliationTests(unittest.TestCase):
    def test_updates_equity_when_empty_local_matches_empty_exchange(self) -> None:
        store = self._store()
        service = ReconciliationService(FakeExchangeStateAdapter(ExchangeState(equity_usdt=12_000)))

        report = service.reconcile(store, ("BTC/USDT:USDT",))

        self.assertEqual(report.status, ReconciliationStatus.OK)
        self.assertEqual(store.load_account().equity_usdt, 12_000)
        self.assertEqual(store.load_account().peak_equity_usdt, 12_000)

    def test_halts_on_position_symbol_mismatch(self) -> None:
        store = self._store()
        exchange_state = ExchangeState(
            equity_usdt=10_000,
            positions=(
                ExchangePosition(
                    symbol="BTC/USDT:USDT",
                    side=Side.LONG,
                    entry_price=100,
                    notional_usdt=1_000,
                    leverage=2,
                    quantity=10,
                ),
            ),
        )
        service = ReconciliationService(FakeExchangeStateAdapter(exchange_state))

        report = service.reconcile(store, ("BTC/USDT:USDT",))

        self.assertEqual(report.status, ReconciliationStatus.MISMATCH)
        self.assertEqual(report.reason, "position_symbol_mismatch")

    def test_halts_when_exchange_position_has_no_native_stop(self) -> None:
        store = self._store()
        account = AccountState(
            equity_usdt=10_000,
            peak_equity_usdt=10_000,
            positions=(
                Position(
                    symbol="BTC/USDT:USDT",
                    side=Side.LONG,
                    entry_price=100,
                    stop_loss=95,
                    notional_usdt=1_000,
                    leverage=2,
                    quantity=10,
                    opened_at=utc_now(),
                    stop_order_id="local-stop",
                ),
            ),
        )
        store.save_account(account)
        position = ExchangePosition(
            symbol="BTC/USDT:USDT",
            side=Side.LONG,
            entry_price=100,
            notional_usdt=1_000,
            leverage=2,
            quantity=10,
        )
        service = ReconciliationService(
            FakeExchangeStateAdapter(
                ExchangeState(
                    equity_usdt=10_000,
                    positions=(position,),
                    stop_orders=(ExchangeStopOrder(symbol="ETH/USDT:USDT", order_id="stop-1"),),
                )
            )
        )

        report = service.reconcile(store, ("BTC/USDT:USDT",))

        self.assertEqual(report.status, ReconciliationStatus.MISMATCH)
        self.assertEqual(report.reason, "exchange_position_without_native_stop")

    def _store(self) -> SQLiteStore:
        db_path = Path("data") / f"test-reconcile-{uuid4().hex}.sqlite"
        self.addCleanup(lambda: db_path.unlink(missing_ok=True))
        store = SQLiteStore(db_path)
        store.initialize(10_000)
        return store


if __name__ == "__main__":
    unittest.main()
