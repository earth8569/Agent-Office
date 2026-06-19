from __future__ import annotations

from typing import Protocol
from uuid import uuid4

from agent_office.models import AccountState, OrderResult, Position, Side, TradeIntent, utc_now
from agent_office.okx import OkxDemoAdapter


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
            take_profit=_take_profit_from_intent(intent, 1.5),
        )
        return OrderResult(
            success=True,
            order_id=f"paper-open-{uuid4().hex[:12]}",
            position=position,
            message="paper position opened with simulated exchange-native stop",
        )


class OkxDemoExecutionAdapter:
    def __init__(self, adapter: OkxDemoAdapter, take_profit_r_multiple: float = 1.5) -> None:
        self.adapter = adapter
        self.take_profit_r_multiple = take_profit_r_multiple

    def execute_open(self, intent: TradeIntent, account: AccountState) -> OrderResult:
        amount = self.adapter.contract_amount_for_notional(intent.symbol, intent.notional_usdt, intent.entry_price)
        stop_pct = abs(intent.entry_price - intent.stop_loss) / intent.entry_price
        take_profit_pct = stop_pct * self.take_profit_r_multiple
        result = self.adapter.place_demo_market_with_stop(
            symbol=intent.symbol,
            side=intent.side,
            amount=amount,
            leverage=intent.leverage,
            stop_pct=stop_pct,
            take_profit_pct=take_profit_pct,
        )
        notional = self.adapter.contract_notional_usdt(intent.symbol, amount, result.last_price)
        position = Position(
            symbol=intent.symbol,
            side=intent.side,
            entry_price=result.last_price,
            stop_loss=result.stop_loss,
            notional_usdt=notional,
            leverage=intent.leverage,
            quantity=amount,
            opened_at=utc_now(),
            stop_order_id=f"okx-attached-stop:{result.order_id}",
            take_profit=result.take_profit,
        )
        return OrderResult(
            success=True,
            order_id=result.order_id,
            position=position,
            message="okx demo position opened with attached stop and take profit",
        )


class OkxExecutionAdapter:
    def execute_open(self, intent: TradeIntent, account: AccountState) -> OrderResult:
        raise NotImplementedError("OKX live execution adapter pending production approval")


def _take_profit_from_intent(intent: TradeIntent, take_profit_r_multiple: float) -> float:
    risk_distance = abs(intent.entry_price - intent.stop_loss)
    if intent.side == Side.LONG:
        return intent.entry_price + (risk_distance * take_profit_r_multiple)
    return intent.entry_price - (risk_distance * take_profit_r_multiple)