from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from agent_office.config import AppConfig
from agent_office.execution import ExecutionAdapter
from agent_office.indicators import build_indicator_snapshot
from agent_office.models import Candle, CycleResult, CycleStatus, ReconciliationStatus
from agent_office.reconcile import ReconciliationService
from agent_office.risk import RiskLayer
from agent_office.storage import SQLiteStore
from agent_office.strategy import RuleBasedBaseline


class DecisionCycle:
    def __init__(
        self,
        config: AppConfig,
        store: SQLiteStore,
        strategy: RuleBasedBaseline,
        risk_layer: RiskLayer,
        execution: ExecutionAdapter,
        reconciler: ReconciliationService | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.strategy = strategy
        self.risk_layer = risk_layer
        self.execution = execution
        self.reconciler = reconciler

    def run_symbol(
        self,
        symbol: str,
        candles_4h: Sequence[Candle],
        candles_1d: Sequence[Candle],
    ) -> CycleResult:
        self.store.initialize(self.config.starting_equity_usdt)
        self.store.record_audit("cycle_started", symbol, {"symbol": symbol})

        try:
            if self.reconciler is not None:
                report = self.reconciler.reconcile(self.store, self.config.watchlist)
                if report.status != ReconciliationStatus.OK:
                    return CycleResult(CycleStatus.ABORTED, symbol, None, None, None, None, report.reason)

            account = self.store.load_account()
            snapshot = build_indicator_snapshot(symbol, candles_4h, candles_1d)
            self.store.record_audit("indicator_snapshot", symbol, snapshot)

            intent = self.strategy.decide(snapshot, account)
            if intent is None:
                self.store.record_audit("strategy_hold", symbol, {"reason": "no_rule_signal"})
                return CycleResult(CycleStatus.HOLD, symbol, snapshot, None, None, None, "no rule signal")

            self.store.record_audit("strategy_intent", symbol, intent)
            risk = self.risk_layer.validate(intent, account)
            self.store.record_audit("risk_decision", symbol, risk)
            if not risk.accepted:
                return CycleResult(CycleStatus.REJECTED, symbol, snapshot, intent, risk, None, risk.reason)

            order = self.execution.execute_open(intent, account)
            self.store.record_audit("execution_result", symbol, order)
            if not order.success or order.position is None:
                return CycleResult(CycleStatus.ABORTED, symbol, snapshot, intent, risk, order, order.message)

            updated = replace(account, positions=account.positions + (order.position,))
            self.store.save_account(updated)
            self.store.record_audit("trade_opened", symbol, order.position)
            return CycleResult(CycleStatus.EXECUTED, symbol, snapshot, intent, risk, order, order.message)
        except Exception as exc:
            self.store.record_audit("cycle_aborted", symbol, {"error": str(exc)})
            return CycleResult(CycleStatus.ABORTED, symbol, None, None, None, None, str(exc))
