from __future__ import annotations

import json
import os
import ssl
from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request

import certifi


@dataclass(frozen=True)
class TelegramResult:
    enabled: bool
    sent: bool
    reason: str


@dataclass(frozen=True)
class TelegramNotifier:
    bot_token: str | None
    chat_id: str | None
    dashboard_url: str = "http://127.0.0.1:8787/reports/grid_pixel_dashboard.html"
    timeout_seconds: float = 10.0

    @classmethod
    def from_env(cls) -> "TelegramNotifier":
        return cls(
            bot_token=_env_text("TELEGRAM_BOT_TOKEN"),
            chat_id=_env_text("TELEGRAM_CHAT_ID"),
            dashboard_url=_env_text("AGENT_OFFICE_DASHBOARD_URL")
            or "http://127.0.0.1:8787/reports/grid_pixel_dashboard.html",
        )

    def send_message(self, text: str, reply_markup: dict[str, Any] | None = None) -> TelegramResult:
        if not self.bot_token or not self.chat_id:
            return TelegramResult(enabled=False, sent=False, reason="telegram_not_configured")
        body: dict[str, Any] = {"chat_id": self.chat_id, "text": text}
        if reply_markup is not None:
            body["reply_markup"] = json.dumps(reply_markup)
        payload = parse.urlencode(body).encode("utf-8")
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        req = request.Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with request.urlopen(req, timeout=self.timeout_seconds, context=_telegram_ssl_context()) as response:
                body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            return TelegramResult(enabled=True, sent=False, reason=_telegram_error_reason(exc))
        except Exception as exc:
            return TelegramResult(enabled=True, sent=False, reason=str(exc))

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            return TelegramResult(enabled=True, sent=False, reason="invalid_telegram_response")
        if parsed.get("ok") is True:
            return TelegramResult(enabled=True, sent=True, reason="sent")
        return TelegramResult(enabled=True, sent=False, reason=str(parsed.get("description") or "telegram_send_failed"))


def agent_stopped_message(payload: dict[str, Any]) -> str:
    mode = str(payload.get("mode") or "stopped")
    pm_decision = str(payload.get("pm_decision") or "unknown")
    positions = _int_text(payload.get("position_count"))
    stops = _int_text(payload.get("stop_order_count"))
    equity = _money_text(payload.get("equity_usdt"))
    reason = str(payload.get("reason") or "workflow_finished")
    return (
        "Agent Office alert\n"
        f"All agents stopped: {mode}\n"
        f"PM: {pm_decision}\n"
        f"Positions: {positions}\n"
        f"Stop orders: {stops}\n"
        f"Equity: {equity}\n"
        f"Reason: {reason}"
    )




def trade_opened_message(payload: dict[str, Any]) -> str:
    return (
        "Agent Office trade opened\n"
        f"Symbol: {payload.get('symbol') or 'unknown'}\n"
        f"Side: {payload.get('side') or 'unknown'}\n"
        f"Entry: {_price_text(payload.get('entry_price'))}\n"
        f"Stop loss: {_price_text(payload.get('stop_loss'))}\n"
        f"Take profit: {_price_text(payload.get('take_profit'))}\n"
        f"Notional: {_money_text(payload.get('notional_usdt'))}\n"
        f"Order: {payload.get('order_id') or 'unknown'}"
    )


def trade_closed_message(payload: dict[str, Any]) -> str:
    return (
        "Agent Office trade closed\n"
        f"Reason: {payload.get('reason') or 'position_closed'}\n"
        f"Symbol: {payload.get('symbol') or 'unknown'}\n"
        f"Side: {payload.get('side') or 'unknown'}\n"
        f"Entry: {_price_text(payload.get('entry_price'))}\n"
        f"Last price: {_price_text(payload.get('last_price'))}\n"
        f"Stop loss: {_price_text(payload.get('stop_loss'))}\n"
        f"Take profit: {_price_text(payload.get('take_profit'))}\n"
        f"Notional: {_money_text(payload.get('notional_usdt'))}"
    )


def emergency_halt_message(payload: dict[str, Any]) -> str:
    return (
        "Agent Office emergency halt\n"
        f"Reason: {payload.get('reason') or payload.get('trade_blocker') or 'unknown'}\n"
        f"PM: {payload.get('pm_decision') or 'unknown'}\n"
        f"Execution: {payload.get('execution') or 'unknown'}\n"
        f"Positions: {_int_text(payload.get('position_count'))}\n"
        f"Stop orders: {_int_text(payload.get('stop_order_count'))}\n"
        f"Equity: {_money_text(payload.get('equity_usdt'))}"
    )
def agent_restart_keyboard(dashboard_url: str) -> dict[str, list[list[dict[str, str]]]]:
    return {"inline_keyboard": [[{"text": "Restart agents", "url": _autostart_url(dashboard_url)}]]}


def _autostart_url(dashboard_url: str) -> str:
    parts = parse.urlsplit(dashboard_url)
    query = dict(parse.parse_qsl(parts.query, keep_blank_values=True))
    query["autostart"] = "1"
    return parse.urlunsplit((parts.scheme, parts.netloc, parts.path, parse.urlencode(query), parts.fragment))

def _env_text(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return None
    return value.strip()


def _telegram_error_reason(exc: error.HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8")
    except Exception:
        return str(exc)
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return str(exc)
    return str(parsed.get("description") or str(exc))


def _telegram_ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=certifi.where())


def _int_text(value: Any) -> str:
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return "0"


def _money_text(value: Any) -> str:
    try:
        return f"{float(value):.2f} USDT"
    except (TypeError, ValueError):
        return "0.00 USDT"

def _price_text(value: Any) -> str:
    try:
        return f"{float(value):.6g}"
    except (TypeError, ValueError):
        return "--"
