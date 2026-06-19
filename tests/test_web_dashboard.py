from __future__ import annotations

import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from agent_office.config import AppConfig, RiskLimits
from agent_office.models import AccountState, Position, Side, utc_now
from agent_office.storage import SQLiteStore
from agent_office.web import AgentWorkRunner, _agent_history, _agent_status, _demo_account_snapshot, _is_client_disconnect, _okx_demo_status, _resolve_static_path, _start_agent_background, _start_agent_work, _stop_agent_background


class WebDashboardTests(unittest.TestCase):
    def test_root_dashboard_static_file_exists(self) -> None:
        path = _resolve_static_path("/reports/grid_pixel_dashboard.html")

        self.assertIsNotNone(path)
        self.assertTrue(path.exists())
        self.assertIn("grid_pixel_dashboard.html", path.name)

    def test_serves_dashboard_assets_only_from_reports_root(self) -> None:
        asset = _resolve_static_path("/reports/pixel_agents_assets/NOTICE.md")
        blocked = _resolve_static_path("/reports/../agent_office/web.py")
        backtest_result = _resolve_static_path("/results/grid-raw-walk-forward.csv")

        self.assertIsNotNone(asset)
        self.assertIsNone(blocked)
        self.assertIsNone(backtest_result)
    def test_dashboard_has_non_overlapping_work_indicators(self) -> None:
        path = _resolve_static_path("/reports/grid_pixel_dashboard.html")
        self.assertIsNotNone(path)
        html = path.read_text(encoding="utf-8")

        self.assertIn("right: -8px;", html)
        self.assertIn("top: -13px;", html)
        self.assertIn("pointer-events: none;", html)
        self.assertIn(".pixel-button.is-running", html)
        self.assertIn("is-complete", html)
        self.assertIn("AGENTS RUNNING", html)

    def test_dashboard_symbol_pill_is_config_driven(self) -> None:
        path = _resolve_static_path("/reports/grid_pixel_dashboard.html")
        self.assertIsNotNone(path)
        html = path.read_text(encoding="utf-8")

        self.assertIn("id=\"symbolsPill\"", html)
        self.assertIn("state.symbols_label", html)
        self.assertIn("labels.length > 4", html)
        self.assertIn("text-overflow: ellipsis", html)
        self.assertNotIn("BTCUSDT ACTIVE", html)
    def test_dashboard_idle_agents_roam_after_delay(self) -> None:
        path = _resolve_static_path("/reports/grid_pixel_dashboard.html")
        self.assertIsNotNone(path)
        html = path.read_text(encoding="utf-8")

        self.assertIn("const IDLE_ROAM_AFTER_MS = 10000", html)
        self.assertIn("agentLastWorkedAt", html)
        self.assertIn(".flat-agent.is-roaming", html)
        self.assertIn("roamStep", html)
        self.assertIn("sprite-work 440ms", html)
        self.assertNotIn("is-walking", html)
        self.assertNotIn("walk-bob", html)
        self.assertNotIn("patrol 2.4s", html)
    def test_dashboard_bubbles_avoid_plant_overlap(self) -> None:
        path = _resolve_static_path("/reports/grid_pixel_dashboard.html")
        self.assertIsNotNone(path)
        html = path.read_text(encoding="utf-8")

        self.assertIn(".plant-b { left: 370px; bottom: 88px; }", html)
        self.assertIn("#dataBubble", html)
        self.assertIn("left: 294px;", html)
        self.assertIn("top: 88px;", html)
        self.assertIn("max-width: 148px;", html)
        self.assertIn("SIGNAL: ${decision.positions} demo position(s)", html)
        self.assertNotIn("SIGNAL_AGENT: ${decision.positions} open demo position(s)", html)

    def test_dashboard_agents_stay_idle_until_start_clicked(self) -> None:
        path = _resolve_static_path("/reports/grid_pixel_dashboard.html")
        self.assertIsNotNone(path)
        html = path.read_text(encoding="utf-8")

        self.assertIn("let agentWorkflowStarted = false", html)
        self.assertIn("function showIdleOffice()", html)
        self.assertIn('setBubble("agentBubble", "PRESS START AGENTS", false)', html)
        self.assertIn("if (!agentWorkflowStarted)", html)
        self.assertIn("else showIdleOffice();", html)
        self.assertIn("agentWorkflowStarted = true;", html)
        self.assertIn('id="pmBubble">PM: idle', html)
        self.assertIn('id="dataBubble">DATA: standby', html)
        self.assertIn('id="riskBubble">RISK<br>standby', html)
        self.assertNotIn('AUTO SCAN QUEUED', html)

    def test_demo_status_uses_agent_dashboard_route(self) -> None:
        status = _okx_demo_status(self._store())

        self.assertEqual(status["mode"], "demo")
        self.assertEqual(status["dashboard"], "/reports/grid_pixel_dashboard.html")
    def test_windows_client_abort_is_treated_as_disconnect(self) -> None:
        error = ConnectionAbortedError(10053, "An established connection was aborted by the software in your host machine")

        self.assertTrue(_is_client_disconnect(error))
        self.assertFalse(_is_client_disconnect(OSError(22, "invalid argument")))
    def test_background_agent_runner_keeps_work_on_server(self) -> None:
        ran = threading.Event()
        calls = []

        def run_once() -> dict[str, object]:
            calls.append("run")
            ran.set()
            return {
                "source": "okx_demo",
                "status": "ok",
                "reason": "matched",
                "equity_usdt": 1000.0,
                "position_count": 0,
                "stop_order_count": 0,
                "total_notional_usdt": 0.0,
                "positions": [],
                "stop_orders": [],
                "pm_decision": "PM_WAIT_FOR_DEMO_POSITION",
                "execution": "no_trade_signal_or_risk_rejected",
                "team_score": 90.0,
                "updated_at": "2026-06-18T00:00:00",
            }

        runner = AgentWorkRunner(run_once, interval_seconds=5)
        try:
            result = _start_agent_background(self._store(), runner)
            self.assertTrue(result["background_running"])
            self.assertTrue(ran.wait(1.0))
            for _ in range(20):
                status = _agent_status(self._store(), runner)
                if status["background_cycle_count"] >= 1:
                    break
                time.sleep(0.05)

            self.assertTrue(status["background_running"])
            self.assertGreaterEqual(status["background_cycle_count"], 1)
            self.assertEqual(status["pm_decision"], "PM_WAIT_FOR_DEMO_POSITION")
            self.assertGreaterEqual(len(calls), 1)
        finally:
            stopped = _stop_agent_background(runner)

        self.assertFalse(stopped["worker"]["running"])

    def test_agent_history_returns_graph_points_from_recorded_scans(self) -> None:
        store = self._store()
        store.record_audit(
            "agent_work_started",
            None,
            {
                "equity_usdt": 1000.5,
                "total_notional_usdt": 250.0,
                "position_count": 1,
                "stop_order_count": 1,
                "team_score": 88.5,
                "status": "ok",
                "reason": "matched",
                "pm_decision": "PM_MONITOR_POSITION",
                "execution": "monitor_existing_position_no_new_order",
                "symbols_label": "BTCUSDT",
            },
        )
        store.record_audit(
            "agent_work_started",
            None,
            {
                "equity_usdt": "1002.25",
                "total_notional_usdt": "0",
                "position_count": "0",
                "stop_order_count": "0",
                "team_score": "91.0",
                "status": "ok",
                "reason": "matched",
                "pm_decision": "PM_WAIT_FOR_DEMO_POSITION",
                "execution": "no_trade_signal_or_risk_rejected",
                "symbols_label": "BTCUSDT / SOLUSDT",
            },
        )

        history = _agent_history(store)

        self.assertEqual(history["source"], "agent_work_started")
        self.assertEqual(len(history["points"]), 2)
        self.assertEqual(history["points"][0]["position_count"], 1)
        self.assertEqual(history["points"][1]["position_count"], 0)
        self.assertEqual(history["points"][1]["equity_usdt"], 1002.25)
        self.assertEqual(history["points"][1]["team_score"], 91.0)
        self.assertEqual(history["points"][1]["symbols_label"], "BTCUSDT / SOLUSDT")

    def test_start_agent_work_uses_demo_snapshot_without_order(self) -> None:
        fake_report = SimpleNamespace(
            status=SimpleNamespace(value="ok"),
            reason="matched",
            exchange_state=SimpleNamespace(equity_usdt=12345.0, positions=(), stop_orders=()),
        )
        with patch("agent_office.web.OkxDemoAdapter.from_env", return_value=object()):
            with patch("agent_office.web.ReconciliationService") as service:
                service.return_value.reconcile.return_value = fake_report
                config = AppConfig(watchlist=("DOGE/USDT:USDT",))
                result = _start_agent_work(self._store(), config=config)

        self.assertEqual(service.return_value.reconcile.call_args.args[1], ("DOGE/USDT:USDT",))
        self.assertEqual(result["source"], "okx_demo")
        self.assertEqual(result["position_count"], 0)
        self.assertEqual(result["pm_decision"], "PM_WAIT_FOR_DEMO_POSITION")
        self.assertEqual(result["execution"], "no_trade_signal_or_risk_rejected")
        self.assertTrue(result["trade_attempted"])
        self.assertEqual(result["watchlist"], ["DOGE/USDT:USDT"])
        self.assertEqual(result["symbols_label"], "DOGEUSDT")

    def test_demo_snapshot_blocks_current_position_without_stop_coverage(self) -> None:
        fake_position = SimpleNamespace(
            symbol="SOL/USDT:USDT",
            side=SimpleNamespace(value="long"),
            entry_price=100.0,
            notional_usdt=250.0,
            leverage=1.0,
            quantity=2.5,
        )
        fake_report = SimpleNamespace(
            status=SimpleNamespace(value="ok"),
            reason="matched",
            exchange_state=SimpleNamespace(equity_usdt=1000.0, positions=(fake_position,), stop_orders=()),
        )
        with patch("agent_office.web.OkxDemoAdapter.from_env", return_value=object()):
            with patch("agent_office.web.ReconciliationService") as service:
                service.return_value.reconcile.return_value = fake_report
                result = _start_agent_work(self._store())

        self.assertEqual(result["position_count"], 1)
        self.assertEqual(result["positions"][0]["symbol"], "SOL/USDT:USDT")
        self.assertEqual(result["pm_decision"], "PM_HALT_STOP_COVERAGE")
        self.assertEqual(result["execution"], "blocked_missing_stop_coverage")
        self.assertEqual(result["trade_blocker"], "missing_stop_coverage")

    def test_demo_snapshot_adopts_guarded_exchange_position(self) -> None:
        fake_position = SimpleNamespace(
            symbol="BTC/USDT:USDT",
            side=SimpleNamespace(value="long"),
            entry_price=100.0,
            notional_usdt=250.0,
            leverage=1.0,
            quantity=2.5,
        )
        fake_stop = SimpleNamespace(symbol="BTC/USDT:USDT", order_id="stop-1", stop_price=95.0)
        fake_report = SimpleNamespace(
            status=SimpleNamespace(value="mismatch"),
            reason="position_symbol_mismatch",
            exchange_state=SimpleNamespace(equity_usdt=1000.0, positions=(fake_position,), stop_orders=(fake_stop,)),
        )
        with patch("agent_office.web.OkxDemoAdapter.from_env", return_value=object()):
            with patch("agent_office.web.ReconciliationService") as service:
                service.return_value.reconcile.return_value = fake_report
                result = _start_agent_work(self._store())

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["reason"], "matched")
        self.assertEqual(result["stop_order_count"], 1)
        self.assertEqual(result["pm_decision"], "PM_SCAN_NEXT_POSITION")
        self.assertEqual(result["execution"], "no_trade_signal_or_risk_rejected")
        self.assertTrue(result["trade_attempted"])
        self.assertEqual(result["trade_blocker"], "no_executable_signal")

    def test_demo_snapshot_blocks_when_position_capacity_is_full(self) -> None:
        positions = tuple(
            SimpleNamespace(
                symbol=f"SYM{index}/USDT:USDT",
                side=SimpleNamespace(value="long"),
                entry_price=100.0,
                notional_usdt=250.0,
                leverage=1.0,
                quantity=2.5,
            )
            for index in range(3)
        )
        stops = tuple(
            SimpleNamespace(symbol=position.symbol, order_id=f"stop-{index}", stop_price=95.0)
            for index, position in enumerate(positions)
        )
        fake_report = SimpleNamespace(
            status=SimpleNamespace(value="ok"),
            reason="matched",
            exchange_state=SimpleNamespace(equity_usdt=1000.0, positions=positions, stop_orders=stops),
        )
        config = AppConfig(
            watchlist=("BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"),
            risk_limits=RiskLimits(max_concurrent_positions=3),
        )

        with patch("agent_office.web.OkxDemoAdapter.from_env", return_value=object()):
            with patch("agent_office.web.ReconciliationService") as service:
                service.return_value.reconcile.return_value = fake_report
                result = _start_agent_work(self._store(), config=config)

        self.assertEqual(result["position_count"], 3)
        self.assertEqual(result["stop_order_count"], 3)
        self.assertEqual(result["pm_decision"], "PM_MAX_POSITIONS_MONITOR")
        self.assertEqual(result["execution"], "monitor_max_positions_no_new_order")
        self.assertEqual(result["trade_blocker"], "max_concurrent_positions")
        self.assertFalse(result["trade_attempted"])
    def test_demo_snapshot_clears_stale_local_position_when_exchange_is_flat(self) -> None:
        store = self._store()
        store.save_account(
            AccountState(
                equity_usdt=1000.0,
                peak_equity_usdt=1100.0,
                positions=(
                    Position(
                        symbol="BTC/USDT:USDT",
                        side=Side.LONG,
                        entry_price=100.0,
                        stop_loss=95.0,
                        notional_usdt=250.0,
                        leverage=1.0,
                        quantity=2.5,
                        opened_at=utc_now(),
                        stop_order_id="stale-stop",
                    ),
                ),
            )
        )
        fake_report = SimpleNamespace(
            status=SimpleNamespace(value="mismatch"),
            reason="position_symbol_mismatch",
            exchange_state=SimpleNamespace(equity_usdt=1200.0, positions=(), stop_orders=()),
        )
        with patch("agent_office.web.OkxDemoAdapter.from_env", return_value=object()):
            with patch("agent_office.web.ReconciliationService") as service:
                service.return_value.reconcile.return_value = fake_report
                result = _start_agent_work(store)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["reason"], "matched")
        self.assertEqual(result["position_count"], 0)
        self.assertEqual(result["execution"], "no_trade_signal_or_risk_rejected")
        self.assertEqual(store.load_account().positions, ())
        self.assertEqual(store.load_account().equity_usdt, 1200.0)
    def _store(self) -> SQLiteStore:
        db_path = Path("data") / f"test-web-{uuid4().hex}.sqlite"
        self.addCleanup(lambda: db_path.unlink(missing_ok=True))
        store = SQLiteStore(db_path)
        store.initialize(10_000)
        return store


if __name__ == "__main__":
    unittest.main()
