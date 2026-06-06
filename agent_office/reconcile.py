from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from agent_office.models import AccountState, ExchangeState, ReconciliationReport, ReconciliationStatus
from agent_office.okx import ExchangeStateAdapter
from agent_office.storage import SQLiteStore


class ReconciliationService:
    def __init__(self, adapter: ExchangeStateAdapter) -> None:
        self.adapter = adapter

    def reconcile(self, store: SQLiteStore, symbols: Sequence[str]) -> ReconciliationReport:
        local = store.load_account()
        exchange_state = self.adapter.fetch_exchange_state(symbols)
        report = self._compare(local, exchange_state)
        store.record_audit("reconciliation", None, report)
        if report.status == ReconciliationStatus.OK:
            store.save_account(
                replace(
                    local,
                    equity_usdt=exchange_state.equity_usdt,
                    peak_equity_usdt=max(local.peak_equity_usdt, exchange_state.equity_usdt),
                )
            )
        return report

    @staticmethod
    def _compare(local: AccountState, exchange_state: ExchangeState) -> ReconciliationReport:
        local_symbols = {position.symbol for position in local.positions}
        exchange_symbols = {position.symbol for position in exchange_state.positions}
        if local_symbols != exchange_symbols:
            return ReconciliationReport(
                status=ReconciliationStatus.MISMATCH,
                reason="position_symbol_mismatch",
                exchange_state=exchange_state,
                local_account=local,
                details={"local_symbols": sorted(local_symbols), "exchange_symbols": sorted(exchange_symbols)},
            )

        stop_symbols = {order.symbol for order in exchange_state.stop_orders if order.symbol}
        missing_stops = sorted(symbol for symbol in exchange_symbols if symbol not in stop_symbols)
        if missing_stops:
            return ReconciliationReport(
                status=ReconciliationStatus.MISMATCH,
                reason="exchange_position_without_native_stop",
                exchange_state=exchange_state,
                local_account=local,
                details={"missing_stop_symbols": missing_stops},
            )

        return ReconciliationReport(
            status=ReconciliationStatus.OK,
            reason="matched",
            exchange_state=exchange_state,
            local_account=local,
        )
