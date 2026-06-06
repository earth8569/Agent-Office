from __future__ import annotations

from typing import Protocol
from uuid import uuid4

from agent_office.models import AccountState, OrderResult, Position, TradeIntent, utc_now


class ExecutionAdapter(Protocol):
    def execute_open(self, intent: TradeIntent, account: AccountState) -> OrderResult:
        ...


class PaperExecutionAdapter:
    def execute_open(self, intent: TradeIntent, account: AccountState) -> OrderResult:
        quantity = intent.notional_usdt / intent.entry_price
        position = Position(
            symbol=intent.symbol,
            side=intent.side,
            entry_price=intent.entry_price,
            stop_loss=intent.stop_loss,
            notional_usdt=intent.notional_usdt,
            leverage=intent.leverage,
            quantity=quantity,
            opened_at=utc_now(),
            stop_order_id=f"paper-stop-{uuid4().hex[:12]}",
        )
        return OrderResult(
            success=True,
            order_id=f"paper-open-{uuid4().hex[:12]}",
            position=position,
            message="paper position opened with simulated exchange-native stop",
        )


class OkxExecutionAdapter:
    def execute_open(self, intent: TradeIntent, account: AccountState) -> OrderResult:
        raise NotImplementedError("OKX execution adapter pending ccxt/API-key integration")
