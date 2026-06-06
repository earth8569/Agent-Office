from __future__ import annotations

from agent_office.config import RiskLimits
from agent_office.models import AccountState, Side, TradeIntent, RiskDecision


class RiskLayer:
    def __init__(self, limits: RiskLimits) -> None:
        self.limits = limits

    def validate(self, intent: TradeIntent, account: AccountState) -> RiskDecision:
        if account.equity_usdt <= 0:
            return self._reject(intent, "account_equity_not_positive")

        if account.daily_pnl_usdt <= -(account.equity_usdt * self.limits.daily_loss_limit_pct):
            return self._reject(intent, "daily_loss_limit")

        if account.peak_equity_usdt > 0:
            drawdown = 1 - (account.equity_usdt / account.peak_equity_usdt)
            if drawdown >= self.limits.max_drawdown_pct:
                return self._reject(intent, "max_drawdown_kill_switch", drawdown=drawdown)

        if intent.entry_price <= 0 or intent.notional_usdt <= 0:
            return self._reject(intent, "order_values_not_positive")

        if intent.leverage <= 0 or intent.leverage > self.limits.max_leverage:
            return self._reject(intent, "max_leverage", requested=intent.leverage, limit=self.limits.max_leverage)

        if intent.stop_loss <= 0:
            return self._reject(intent, "missing_stop_loss")

        if intent.side == Side.LONG and intent.stop_loss >= intent.entry_price:
            return self._reject(intent, "long_stop_must_be_below_entry")
        if intent.side == Side.SHORT and intent.stop_loss <= intent.entry_price:
            return self._reject(intent, "short_stop_must_be_above_entry")

        if len(account.positions) >= self.limits.max_concurrent_positions:
            return self._reject(intent, "max_concurrent_positions")

        if any(position.symbol == intent.symbol for position in account.positions):
            return self._reject(intent, "one_position_per_asset")

        total_notional = account.total_notional_usdt() + intent.notional_usdt
        max_notional = account.equity_usdt * self.limits.max_total_notional_to_equity
        if total_notional > max_notional:
            return self._reject(intent, "max_total_notional_exposure", total=total_notional, limit=max_notional)

        trade_risk = (abs(intent.entry_price - intent.stop_loss) / intent.entry_price) * intent.notional_usdt
        max_trade_risk = account.equity_usdt * self.limits.max_risk_per_trade_pct
        if trade_risk > max_trade_risk + 1e-9:
            return self._reject(intent, "max_risk_per_trade", risk=trade_risk, limit=max_trade_risk)

        return RiskDecision(
            accepted=True,
            reason="accepted",
            intent=intent,
            data={"trade_risk_usdt": trade_risk, "total_notional_usdt": total_notional},
        )

    @staticmethod
    def _reject(intent: TradeIntent, reason: str, **data: float | str) -> RiskDecision:
        return RiskDecision(accepted=False, reason=reason, intent=intent, data=data)
