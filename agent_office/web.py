from __future__ import annotations

import json
import mimetypes
import threading
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from errno import EPIPE, ECONNABORTED, ECONNRESET
from typing import Any, Callable
from agent_office.alerts import TelegramNotifier, agent_restart_keyboard, agent_stopped_message
from agent_office.cycle import DecisionCycle
from urllib.parse import urlparse

from agent_office.config import AppConfig, load_config
from agent_office.execution import OkxDemoExecutionAdapter
from agent_office.models import AccountState, CycleResult, Position, ReconciliationReport, ReconciliationStatus, utc_now
from agent_office.okx import OkxDemoAdapter
from agent_office.reconcile import ReconciliationService
from agent_office.risk import RiskLayer
from agent_office.strategy import RuleBasedBaseline
from agent_office.storage import SQLiteStore

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_PATH = ROOT / "reports" / "grid_pixel_dashboard.html"
STATIC_ROOTS = {
    "/reports/": ROOT / "reports",
}
AGENT_LOOP_INTERVAL_SECONDS = 60.0


class AgentWorkRunner:
    def __init__(
        self,
        run_once: Callable[[], dict[str, Any]],
        *,
        interval_seconds: float = AGENT_LOOP_INTERVAL_SECONDS,
    ) -> None:
        self._run_once = run_once
        self._interval_seconds = max(0.1, float(interval_seconds))
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_result: dict[str, Any] | None = None
        self._last_error: str | None = None
        self._last_started_at: datetime | None = None
        self._last_finished_at: datetime | None = None
        self._cycle_count = 0
        self._phase = "idle"

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return self.status()
            self._stop_event.clear()
            self._last_error = None
            self._phase = "starting"
            self._thread = threading.Thread(target=self._loop, name="agent-office-worker", daemon=True)
            self._thread.start()
            return self.status()

    def stop(self) -> dict[str, Any]:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._phase = "stopped"
            return self.status()

    def status(self) -> dict[str, Any]:
        with self._lock:
            running = self._thread is not None and self._thread.is_alive()
            return {
                "running": running,
                "phase": self._phase if running else ("stopped" if self._phase == "stopped" else "idle"),
                "interval_seconds": self._interval_seconds,
                "cycle_count": self._cycle_count,
                "last_started_at": _iso_or_none(self._last_started_at),
                "last_finished_at": _iso_or_none(self._last_finished_at),
                "last_error": self._last_error,
                "last_result": self._last_result,
            }

    def latest_result(self) -> dict[str, Any] | None:
        with self._lock:
            return None if self._last_result is None else dict(self._last_result)

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            with self._lock:
                self._phase = "scanning"
                self._last_started_at = datetime.now(timezone.utc)
            try:
                result = self._run_once()
            except Exception as exc:
                with self._lock:
                    self._last_error = str(exc)
                    self._phase = "error_waiting"
                    self._last_finished_at = datetime.now(timezone.utc)
            else:
                with self._lock:
                    self._last_result = result
                    self._last_error = None
                    self._cycle_count += 1
                    self._phase = "waiting"
                    self._last_finished_at = datetime.now(timezone.utc)
            if self._stop_event.wait(self._interval_seconds):
                break
        with self._lock:
            self._phase = "stopped"


def run_dashboard(db_path: Path, host: str = "127.0.0.1", port: int = 8787, config: AppConfig | None = None) -> None:
    store = SQLiteStore(db_path)
    store.initialize()
    app_config = config or load_config()
    notifier = TelegramNotifier.from_env()
    runner = AgentWorkRunner(lambda: _start_agent_work(store, config=app_config))
    server = ThreadingHTTPServer((host, port), _handler_for(store, app_config, notifier, runner))
    print(f"Agent Office dashboard: http://{host}:{port}/reports/grid_pixel_dashboard.html")
    server.serve_forever()


def _handler_for(
    store: SQLiteStore,
    config: AppConfig | None = None,
    notifier: TelegramNotifier | None = None,
    runner: AgentWorkRunner | None = None,
) -> type[BaseHTTPRequestHandler]:
    app_config = config or load_config()
    app_notifier = notifier or TelegramNotifier.from_env()
    app_runner = runner or AgentWorkRunner(lambda: _start_agent_work(store, config=app_config))
    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", "/reports/grid_pixel_dashboard.html")
                self.end_headers()
                return
            if parsed.path == "/api/okx-demo/status":
                self._send_json(_okx_demo_status(store))
                return
            if parsed.path == "/api/agents/status":
                self._send_json(_agent_status(store, app_runner, config=app_config))
                return
            if parsed.path == "/api/agents/history":
                self._send_json(_agent_history(store))
                return
            static_path = _resolve_static_path(parsed.path)
            if static_path is not None:
                self._send_file(static_path)
                return
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/api/okx-demo/reconcile":
                    self._send_json(_okx_demo_reconcile(store, config=app_config))
                    return
                if parsed.path == "/api/agents/start":
                    self._send_json(_start_agent_background(store, app_runner, config=app_config))
                    return
                if parsed.path == "/api/agents/stop":
                    self._send_json(_stop_agent_background(app_runner))
                    return
                if parsed.path == "/api/agents/stopped":
                    self._send_json(_notify_agents_stopped(store, self._read_json_body(), app_notifier))
                    return
                self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except Exception as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

        def log_message(self, format: str, *args: object) -> None:
            return

        def _send_file(self, path: Path) -> None:
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            body = path.read_bytes()
            try:
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except OSError as exc:
                if _is_client_disconnect(exc):
                    return
                raise

        def _send_json(self, body: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
            encoded = json.dumps(body, default=_json_default).encode("utf-8")
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
            except OSError as exc:
                if _is_client_disconnect(exc):
                    return
                raise

        def _read_json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length <= 0:
                return {}
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("JSON body must be an object")
            return payload

    return DashboardHandler


def _resolve_static_path(request_path: str) -> Path | None:
    if request_path == "/reports/grid_pixel_dashboard.html":
        return DASHBOARD_PATH if DASHBOARD_PATH.exists() else None
    for prefix, root in STATIC_ROOTS.items():
        if not request_path.startswith(prefix):
            continue
        relative = request_path.removeprefix(prefix).replace("/", "\\")
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            return None
        if candidate.is_file():
            return candidate
    return None


def _okx_demo_status(store: SQLiteStore) -> dict[str, Any]:
    store.initialize()
    rows = store.list_audit_events(limit=1, event_type="demo_trade_placed")
    return {
        "mode": "demo",
        "dashboard": "/reports/grid_pixel_dashboard.html",
        "last_demo_trade": rows[0].created_at.isoformat() if rows else None,
    }


def _agent_history(store: SQLiteStore, limit: int = 80) -> dict[str, Any]:
    store.initialize()
    events = store.list_audit_events(limit=limit, event_type="agent_work_started")
    points: list[dict[str, Any]] = []
    for event in reversed(events):
        payload = event.payload if isinstance(event.payload, dict) else {}
        points.append(
            {
                "time": event.created_at.isoformat(),
                "equity_usdt": _float_or_zero(payload.get("equity_usdt")),
                "total_notional_usdt": _float_or_zero(payload.get("total_notional_usdt")),
                "position_count": _int_or_zero(payload.get("position_count")),
                "stop_order_count": _int_or_zero(payload.get("stop_order_count")),
                "team_score": _float_or_zero(payload.get("team_score")),
                "status": payload.get("status") or "unknown",
                "reason": payload.get("reason") or "--",
                "pm_decision": payload.get("pm_decision") or "--",
                "execution": payload.get("execution") or "--",
                "symbols_label": payload.get("symbols_label") or "--",
            }
        )
    return {"source": "agent_work_started", "points": points}


def _agent_status(store: SQLiteStore, runner: AgentWorkRunner, config: AppConfig | None = None) -> dict[str, Any]:
    worker = runner.status()
    latest = runner.latest_result()
    if latest is None:
        latest = _demo_account_snapshot(store, record=False, config=config)
    latest = dict(latest)
    latest["worker"] = worker
    latest["background_running"] = bool(worker["running"])
    latest["background_phase"] = worker["phase"]
    latest["background_cycle_count"] = worker["cycle_count"]
    return latest


def _start_agent_background(
    store: SQLiteStore,
    runner: AgentWorkRunner,
    config: AppConfig | None = None,
) -> dict[str, Any]:
    worker = runner.start()
    deadline = time.monotonic() + 0.5
    latest = runner.latest_result()
    while latest is None and time.monotonic() < deadline and runner.status()["running"]:
        time.sleep(0.02)
        latest = runner.latest_result()
        worker = runner.status()
    if latest is None:
        latest = _demo_account_snapshot(store, record=False, config=config)
    latest = dict(latest)
    latest["worker"] = worker
    latest["background_running"] = bool(worker["running"])
    latest["background_phase"] = worker["phase"]
    latest["background_cycle_count"] = worker["cycle_count"]
    return latest


def _stop_agent_background(runner: AgentWorkRunner) -> dict[str, Any]:
    return {"worker": runner.stop()}

def _okx_demo_reconcile(store: SQLiteStore, config: AppConfig | None = None) -> dict[str, Any]:
    store.initialize()
    app_config = config or load_config()
    report = ReconciliationService(OkxDemoAdapter.from_env()).reconcile(store, app_config.watchlist)
    return {
        "status": report.status.value,
        "reason": report.reason,
        "equity_usdt": round(report.exchange_state.equity_usdt, 2),
        "positions": len(report.exchange_state.positions),
        "stop_orders": len(report.exchange_state.stop_orders),
    }



def _start_agent_work(store: SQLiteStore, config: AppConfig | None = None) -> dict[str, Any]:
    return _demo_account_snapshot(store, record=True, config=config)


def _demo_account_snapshot(store: SQLiteStore, record: bool, config: AppConfig | None = None) -> dict[str, Any]:
    store.initialize()
    app_config = config or load_config()
    adapter = OkxDemoAdapter.from_env()
    if record:
        report = ReconciliationService(adapter).reconcile(store, app_config.watchlist)
    else:
        local = store.load_account()
        exchange_state = adapter.fetch_exchange_state(app_config.watchlist)
        report = ReconciliationService._compare(local, exchange_state)
    report = _adopt_guarded_demo_positions(store, report)

    positions = [_position_payload(position) for position in report.exchange_state.positions]
    stop_orders = [_stop_order_payload(order) for order in report.exchange_state.stop_orders]
    total_notional = round(sum(float(position.get("notional_usdt") or 0) for position in positions), 2)
    decision = _pm_decision(report.status.value, len(positions), len(stop_orders), app_config.risk_limits.max_concurrent_positions)
    proficiency = _agent_proficiency(
        status=report.status.value,
        reason=report.reason,
        watchlist=app_config.watchlist,
        positions=positions,
        stop_orders=stop_orders,
        equity_usdt=round(report.exchange_state.equity_usdt, 2),
        total_notional_usdt=total_notional,
        pm_decision=decision,
        max_positions=app_config.risk_limits.max_concurrent_positions,
    )
    detail = {
        "source": "okx_demo",
        "watchlist": list(app_config.watchlist),
        "symbols_label": _symbols_label(app_config.watchlist),
        "status": report.status.value,
        "reason": report.reason,
        "equity_usdt": round(report.exchange_state.equity_usdt, 2),
        "position_count": len(positions),
        "stop_order_count": len(stop_orders),
        "total_notional_usdt": total_notional,
        "positions": positions,
        "stop_orders": stop_orders,
        "pm_decision": decision,
        "execution": "no_order_submitted_from_webpage",
        "team_score": proficiency["team_score"],
        "agent_proficiency": proficiency["agents"],
        "team_recommendations": proficiency["recommendations"],
        "updated_at": datetime.now().isoformat(),
    }
    if record:
        detail = _maybe_run_demo_trade_workflow(store, app_config, adapter, detail)
        store.record_audit("agent_work_started", None, detail)
    return detail


def _maybe_run_demo_trade_workflow(
    store: SQLiteStore,
    config: AppConfig,
    adapter: OkxDemoAdapter,
    detail: dict[str, Any],
) -> dict[str, Any]:
    detail["trade_attempted"] = False
    detail["trade_blocker"] = None
    detail["cycle_results"] = []

    if detail["status"] != "ok":
        detail["execution"] = "blocked_reconcile"
        detail["trade_blocker"] = detail.get("reason") or "reconcile_not_ok"
        return detail

    position_count = int(detail.get("position_count") or 0)
    stop_order_count = int(detail.get("stop_order_count") or 0)
    max_positions = config.risk_limits.max_concurrent_positions

    if stop_order_count < position_count:
        detail["execution"] = "blocked_missing_stop_coverage"
        detail["trade_blocker"] = "missing_stop_coverage"
        return detail

    if stop_order_count > position_count:
        detail["execution"] = "blocked_stale_stop_orders"
        detail["trade_blocker"] = "stale_stop_orders"
        return detail

    if position_count >= max_positions:
        detail["execution"] = "monitor_max_positions_no_new_order"
        detail["trade_blocker"] = "max_concurrent_positions"
        return detail

    cycle = DecisionCycle(
        config=config,
        store=store,
        strategy=RuleBasedBaseline(config),
        risk_layer=RiskLayer(config.risk_limits),
        execution=OkxDemoExecutionAdapter(adapter),
    )
    executed = None
    for symbol in config.watchlist:
        try:
            candles_4h = adapter.fetch_closed_candles(symbol, "4h", 60)
            candles_1d = adapter.fetch_closed_candles(symbol, "1d", 60)
            result = cycle.run_symbol(symbol, candles_4h, candles_1d)
        except Exception as exc:
            result = CycleResult("aborted", symbol, None, None, None, None, str(exc))  # type: ignore[arg-type]
        payload = _cycle_result_payload(result)
        detail["cycle_results"].append(payload)
        if payload["status"] == "executed":
            executed = payload
            break

    detail["trade_attempted"] = True
    if executed is None:
        detail["execution"] = "no_trade_signal_or_risk_rejected"
        detail["trade_blocker"] = "no_executable_signal"
        return detail

    detail["execution"] = "demo_order_submitted"
    detail["trade_blocker"] = None
    detail["last_trade"] = executed
    return detail


def _cycle_result_payload(result: CycleResult) -> dict[str, Any]:
    return {
        "symbol": result.symbol,
        "status": result.status.value if hasattr(result.status, "value") else str(result.status),
        "message": result.message,
        "intent_side": None if result.intent is None else result.intent.side.value,
        "intent_notional_usdt": None if result.intent is None else round(result.intent.notional_usdt, 2),
        "risk": None if result.risk is None else result.risk.reason,
        "order_id": None if result.order is None else result.order.order_id,
    }
def _adopt_guarded_demo_positions(store: SQLiteStore, report: Any) -> Any:
    if getattr(report, "reason", "") != "position_symbol_mismatch":
        return report
    exchange_positions = tuple(getattr(report.exchange_state, "positions", ()))
    if not exchange_positions:
        local = store.load_account()
        if not local.positions:
            return report
        store.save_account(
            AccountState(
                equity_usdt=report.exchange_state.equity_usdt,
                peak_equity_usdt=max(local.peak_equity_usdt, report.exchange_state.equity_usdt),
                daily_pnl_usdt=local.daily_pnl_usdt,
                positions=(),
            )
        )
        return ReconciliationReport(
            status=ReconciliationStatus.OK,
            reason="matched",
            exchange_state=report.exchange_state,
            local_account=store.load_account(),
        )
    stop_by_symbol = {
        order.symbol: order
        for order in getattr(report.exchange_state, "stop_orders", ())
        if getattr(order, "symbol", "") and getattr(order, "stop_price", None) is not None
    }
    if any(position.symbol not in stop_by_symbol for position in exchange_positions):
        return report

    local = store.load_account()
    adopted = tuple(
        Position(
            symbol=position.symbol,
            side=position.side,
            entry_price=position.entry_price,
            stop_loss=float(stop_by_symbol[position.symbol].stop_price),
            notional_usdt=position.notional_usdt,
            leverage=position.leverage,
            quantity=position.quantity,
            opened_at=utc_now(),
            stop_order_id=stop_by_symbol[position.symbol].order_id,
        )
        for position in exchange_positions
    )
    store.save_account(
        AccountState(
            equity_usdt=report.exchange_state.equity_usdt,
            peak_equity_usdt=max(local.peak_equity_usdt, report.exchange_state.equity_usdt),
            daily_pnl_usdt=local.daily_pnl_usdt,
            positions=adopted,
        )
    )
    return ReconciliationReport(
        status=ReconciliationStatus.OK,
        reason="matched",
        exchange_state=report.exchange_state,
        local_account=store.load_account(),
    )
def _agent_proficiency(
    *,
    status: str,
    reason: str,
    watchlist: tuple[str, ...],
    positions: list[dict[str, Any]],
    stop_orders: list[dict[str, Any]],
    equity_usdt: float,
    total_notional_usdt: float,
    pm_decision: str,
    max_positions: int,
) -> dict[str, Any]:
    position_count = len(positions)
    stop_count = len(stop_orders)
    watchlist_count = len(watchlist)
    status_ok = status == "ok"
    stop_coverage = 100.0 if position_count == 0 else min(100.0, (stop_count / position_count) * 100)
    exposure_ratio = 0.0 if equity_usdt <= 0 else min(100.0, (total_notional_usdt / equity_usdt) * 100)
    uncovered_positions = max(0, position_count - stop_count)
    stale_stops = max(0, stop_count - position_count)
    capacity_remaining = max(0, max_positions - position_count)

    agents = [
        _agent_score(
            "DATA_AGENT",
            "OKX scan",
            100 if equity_usdt > 0 and watchlist_count > 0 else 35,
            f"Equity {equity_usdt:.2f}; watchlist {watchlist_count} symbol(s).",
            "scan_ok" if equity_usdt > 0 else "scan_failed",
        ),
        _agent_score(
            "SIGNAL_AGENT",
            "exposure read",
            85 if position_count > 0 else 72,
            f"{position_count}/{max_positions} open demo position(s), {total_notional_usdt:.2f} USDT notional.",
            "active" if position_count > 0 else "idle",
        ),
        _agent_score(
            "RISK_AGENT",
            "stop coverage",
            95 if stop_coverage >= 100 else max(25, int(stop_coverage * 0.7)),
            f"{stop_count}/{position_count} position(s) have detected stop orders.",
            "guarded" if uncovered_positions == 0 else "uncovered_position",
        ),
        _agent_score(
            "PM_AGENT",
            "decision quality",
            92 if status_ok else 58,
            f"Decision {pm_decision}; reconcile reason {reason or 'none'}.",
            "approved" if status_ok else "halt_reconcile",
        ),
        _agent_score(
            "EXEC_AGENT",
            "execution control",
            88 if uncovered_positions == 0 and stale_stops == 0 and capacity_remaining > 0 else 48,
            f"Capacity {position_count}/{max_positions}; execution can add another guarded symbol." if capacity_remaining > 0 and uncovered_positions == 0 and stale_stops == 0 else f"Execution blocked: capacity {position_count}/{max_positions}, uncovered {uncovered_positions}, stale stops {stale_stops}.",
            "armed" if capacity_remaining > 0 and uncovered_positions == 0 and stale_stops == 0 else "blocked",
        ),
        _agent_score(
            "QA_AGENT",
            "audit trail",
            90 if status_ok else 64,
            f"Last scan recorded with status {status}; exposure/equity ratio {exposure_ratio:.2f}%.",
            "pass" if status_ok else "review",
        ),
    ]
    team_score = round(sum(agent["score"] for agent in agents) / len(agents), 1)
    recommendations: list[str] = []
    if uncovered_positions > 0:
        recommendations.append("Stop coverage missing: verify or recreate attached stop orders before new trades.")
    if stale_stops > 0:
        recommendations.append("Stale stop orders detected: cancel or reconcile them before new trades.")
    if position_count >= max_positions:
        recommendations.append(f"Max demo capacity reached: monitor {position_count}/{max_positions} positions.")
    if not status_ok:
        recommendations.append(f"Reconcile before execution: {reason or status}.")
    if position_count == 0:
        recommendations.append("No active demo exposure: wait for strategy signal before opening new trade.")
    elif capacity_remaining > 0 and uncovered_positions == 0 and stale_stops == 0:
        recommendations.append(f"Capacity remains: agents may open {capacity_remaining} more guarded position(s).")
    if not recommendations:
        recommendations.append("Team state acceptable: continue monitoring demo account.")
    return {"team_score": team_score, "agents": agents, "recommendations": recommendations}


def _agent_score(name: str, role: str, score: float, detail: str, state: str) -> dict[str, Any]:
    bounded = max(0.0, min(100.0, float(score)))
    return {
        "name": name,
        "role": role,
        "score": round(bounded, 1),
        "state": state,
        "detail": detail,
    }
def _notify_agents_stopped(
    store: SQLiteStore,
    payload: dict[str, Any],
    notifier: TelegramNotifier | None = None,
) -> dict[str, Any]:
    store.initialize()
    app_notifier = notifier or TelegramNotifier.from_env()
    message = agent_stopped_message(payload)
    result = app_notifier.send_message(message, reply_markup=agent_restart_keyboard(app_notifier.dashboard_url))
    detail = {
        "telegram_enabled": result.enabled,
        "telegram_sent": result.sent,
        "reason": result.reason,
        "payload": payload,
    }
    store.record_audit("agents_stopped_alert", None, detail)
    return detail

def _pm_decision(status: str, position_count: int, stop_order_count: int, max_positions: int) -> str:
    if status != "ok":
        return "PM_HALT_RECONCILE"
    if stop_order_count > position_count:
        return "PM_REVIEW_STALE_STOPS"
    if position_count > stop_order_count:
        return "PM_HALT_STOP_COVERAGE"
    if position_count >= max_positions:
        return "PM_MAX_POSITIONS_MONITOR"
    if position_count > 0:
        return "PM_SCAN_NEXT_POSITION"
    return "PM_WAIT_FOR_DEMO_POSITION"


def _symbols_label(symbols: tuple[str, ...]) -> str:
    compact = [symbol.split(":", 1)[0].replace("/", "") for symbol in symbols]
    return " / ".join(compact)


def _position_payload(position: Any) -> dict[str, Any]:
    return {
        "symbol": position.symbol,
        "side": position.side.value,
        "entry_price": round(position.entry_price, 6),
        "notional_usdt": round(position.notional_usdt, 2),
        "leverage": round(position.leverage, 2),
        "quantity": round(position.quantity, 8),
    }


def _stop_order_payload(order: Any) -> dict[str, Any]:
    return {
        "symbol": order.symbol,
        "order_id": order.order_id,
        "stop_price": order.stop_price,
    }


def _is_client_disconnect(exc: OSError) -> bool:
    errno_value = getattr(exc, "errno", None)
    winerror = getattr(exc, "winerror", None)
    return errno_value in {EPIPE, ECONNABORTED, ECONNRESET} or winerror in {10053, 10054, 10058}

def _iso_or_none(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()

def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0

def _json_default(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return asdict(value)
    return str(value)
