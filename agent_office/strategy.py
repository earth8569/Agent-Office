from __future__ import annotations

from agent_office.config import AppConfig
from agent_office.models import AccountState, IndicatorSnapshot, Side, TradeIntent


class RuleBasedBaseline:
    """Free baseline consuming same indicator snapshot as LLM layer."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def decide(self, snapshot: IndicatorSnapshot, account: AccountState) -> TradeIntent | None:
        if snapshot.trend == "bullish" and snapshot.daily_trend != "bearish" and snapshot.macd_hist > 0:
            stop = max(snapshot.support, snapshot.close - (2 * snapshot.atr))
            stop = min(stop, snapshot.close * 0.995)
            return self._build_intent(snapshot, account, Side.LONG, stop, "Bullish 4h trend with non-bearish 1d bias.")

        if snapshot.trend == "bearish" and snapshot.daily_trend != "bullish" and snapshot.macd_hist < 0:
            stop = min(snapshot.resistance, snapshot.close + (2 * snapshot.atr))
            stop = max(stop, snapshot.close * 1.005)
            return self._build_intent(snapshot, account, Side.SHORT, stop, "Bearish 4h trend with non-bullish 1d bias.")

        return None

    def _build_intent(
        self,
        snapshot: IndicatorSnapshot,
        account: AccountState,
        side: Side,
        stop_loss: float,
        thesis: str,
    ) -> TradeIntent | None:
        stop_distance_pct = abs(snapshot.close - stop_loss) / snapshot.close
        if stop_distance_pct <= 0:
            return None

        risk_budget = account.equity_usdt * self.config.risk_limits.max_risk_per_trade_pct
        notional = risk_budget / stop_distance_pct
        max_new_notional = account.equity_usdt * self.config.risk_limits.max_total_notional_to_equity
        notional = min(notional, max_new_notional - account.total_notional_usdt())
        if notional <= 0:
            return None

        return TradeIntent(
            symbol=snapshot.symbol,
            side=side,
            entry_price=snapshot.close,
            stop_loss=stop_loss,
            notional_usdt=notional,
            leverage=self.config.default_leverage,
            thesis=thesis,
        )
