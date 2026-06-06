from __future__ import annotations

import unittest
from dataclasses import replace

from agent_office.config import RiskLimits
from agent_office.models import AccountState, Side, TradeIntent
from agent_office.risk import RiskLayer


class RiskLayerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.account = AccountState(equity_usdt=10_000, peak_equity_usdt=10_000)
        self.layer = RiskLayer(RiskLimits())

    def test_accepts_compliant_trade(self) -> None:
        intent = TradeIntent(
            symbol="BTC/USDT:USDT",
            side=Side.LONG,
            entry_price=100,
            stop_loss=99,
            notional_usdt=5_000,
            leverage=2,
            thesis="test",
        )

        decision = self.layer.validate(intent, self.account)

        self.assertTrue(decision.accepted)
        self.assertEqual(decision.reason, "accepted")

    def test_rejects_over_max_leverage(self) -> None:
        intent = TradeIntent(
            symbol="BTC/USDT:USDT",
            side=Side.LONG,
            entry_price=100,
            stop_loss=99,
            notional_usdt=1_000,
            leverage=6,
            thesis="test",
        )

        decision = self.layer.validate(intent, self.account)

        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "max_leverage")

    def test_rejects_bad_stop_direction(self) -> None:
        intent = TradeIntent(
            symbol="BTC/USDT:USDT",
            side=Side.LONG,
            entry_price=100,
            stop_loss=101,
            notional_usdt=1_000,
            leverage=2,
            thesis="test",
        )

        decision = self.layer.validate(intent, self.account)

        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "long_stop_must_be_below_entry")

    def test_rejects_daily_loss_limit(self) -> None:
        account = replace(self.account, daily_pnl_usdt=-500)
        intent = TradeIntent(
            symbol="BTC/USDT:USDT",
            side=Side.LONG,
            entry_price=100,
            stop_loss=99,
            notional_usdt=1_000,
            leverage=2,
            thesis="test",
        )

        decision = self.layer.validate(intent, account)

        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "daily_loss_limit")


if __name__ == "__main__":
    unittest.main()
