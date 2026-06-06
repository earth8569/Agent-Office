from __future__ import annotations

import html
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from agent_office.storage import SQLiteStore


def run_dashboard(db_path: Path, host: str = "127.0.0.1", port: int = 8787) -> None:
    store = SQLiteStore(db_path)
    store.initialize()
    server = ThreadingHTTPServer((host, port), _handler_for(store))
    print(f"Agent Office dashboard: http://{host}:{port}")
    server.serve_forever()


def render_dashboard(events: list[dict[str, Any]], db_path: Path) -> str:
    payload = json.dumps(events, default=_json_default)
    total = len(events)
    rejects = sum(1 for event in events if event["status"] == "rejected")
    aborts = sum(1 for event in events if event["status"] == "aborted")
    trades = sum(1 for event in events if event["event_type"] == "trade_opened")
    last_event = events[0]["created_at"] if events else "No events"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Agent Office Operator Console</title>
  <style>
    :root {{
      --bg: #f4f6f8;
      --surface: #ffffff;
      --surface-2: #f9fafb;
      --text: #161b22;
      --muted: #667085;
      --line: #d7dde5;
      --line-strong: #b8c1cc;
      --green: #14804a;
      --red: #c4362e;
      --amber: #a16207;
      --blue: #2563a8;
      --violet: #6f4dbf;
      --shadow: 0 1px 2px rgba(16, 24, 40, 0.06), 0 8px 24px rgba(16, 24, 40, 0.05);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.45 "Segoe UI", Arial, sans-serif;
    }}
    .shell {{
      min-height: 100vh;
      display: grid;
      grid-template-rows: auto 1fr;
    }}
    .topbar {{
      position: sticky;
      top: 0;
      z-index: 4;
      background: rgba(255, 255, 255, 0.96);
      border-bottom: 1px solid var(--line);
    }}
    .topbar-inner {{
      max-width: 1280px;
      margin: 0 auto;
      padding: 14px 24px;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 16px;
      align-items: center;
    }}
    .brand {{
      min-width: 0;
    }}
    .eyebrow {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
      text-transform: uppercase;
      letter-spacing: 0;
    }}
    h1 {{
      margin: 1px 0 0;
      font-size: 24px;
      font-weight: 700;
      letter-spacing: 0;
    }}
    .meta {{
      color: var(--muted);
      display: flex;
      justify-content: flex-end;
      gap: 8px;
      flex-wrap: wrap;
      font-size: 12px;
      max-width: 720px;
    }}
    .meta-pill {{
      display: inline-flex;
      align-items: center;
      gap: 7px;
      min-height: 28px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--surface-2);
      padding: 4px 10px;
      max-width: 100%;
      overflow-wrap: anywhere;
    }}
    .dot {{
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: var(--green);
      flex: 0 0 auto;
    }}
    main {{
      width: min(1280px, 100%);
      margin: 0 auto;
      padding: 20px 24px 36px;
      display: grid;
      gap: 14px;
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }}
    .stat {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px 16px;
      min-height: 84px;
      box-shadow: var(--shadow);
      display: grid;
      align-content: space-between;
    }}
    .stat span {{
      color: var(--muted);
      display: block;
      font-size: 12px;
      font-weight: 650;
      text-transform: uppercase;
      letter-spacing: 0;
    }}
    .stat strong {{
      font-size: 30px;
      line-height: 1;
      font-weight: 750;
    }}
    .stat[data-tone="green"] {{ border-top: 3px solid var(--green); }}
    .stat[data-tone="blue"] {{ border-top: 3px solid var(--blue); }}
    .stat[data-tone="amber"] {{ border-top: 3px solid var(--amber); }}
    .stat[data-tone="red"] {{ border-top: 3px solid var(--red); }}
    .toolbar {{
      display: grid;
      grid-template-columns: minmax(260px, 2fr) minmax(150px, 1fr) minmax(150px, 1fr);
      gap: 12px;
      align-items: end;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      box-shadow: var(--shadow);
    }}
    label {{
      display: grid;
      gap: 5px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
      text-transform: uppercase;
      letter-spacing: 0;
    }}
    input, select {{
      min-height: 40px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 11px;
      font: inherit;
      background: var(--surface-2);
      color: var(--text);
    }}
    input:focus, select:focus {{
      outline: 2px solid rgba(37, 99, 168, 0.22);
      border-color: var(--blue);
    }}
    .feed-head {{
      display: grid;
      grid-template-columns: 150px 180px 130px 1fr 82px;
      gap: 12px;
      padding: 0 14px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0;
    }}
    .timeline {{
      display: grid;
      gap: 8px;
    }}
    .event {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-left: 4px solid var(--blue);
      border-radius: 8px;
      display: grid;
      grid-template-columns: 150px 180px 130px 1fr 82px;
      gap: 12px;
      padding: 12px 14px;
      align-items: center;
      box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
    }}
    .event[data-status="accepted"], .event[data-status="executed"] {{ border-left-color: var(--green); }}
    .event[data-status="rejected"], .event[data-status="aborted"] {{ border-left-color: var(--red); }}
    .event[data-status="warning"] {{ border-left-color: var(--amber); }}
    .event:hover {{
      border-color: var(--line-strong);
      box-shadow: var(--shadow);
    }}
    .time, .summary, .payload {{
      color: var(--muted);
      overflow-wrap: anywhere;
    }}
    .time {{
      font-size: 12px;
      font-variant-numeric: tabular-nums;
    }}
    .actor {{
      font-weight: 700;
      color: var(--text);
      overflow-wrap: anywhere;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: fit-content;
      max-width: 100%;
      min-height: 24px;
      padding: 3px 9px;
      border-radius: 999px;
      background: #eef2f6;
      color: #344054;
      font-size: 12px;
      font-weight: 700;
      overflow-wrap: anywhere;
    }}
    .badge[data-status="accepted"], .badge[data-status="executed"] {{
      background: #e7f6ee;
      color: var(--green);
    }}
    .badge[data-status="rejected"], .badge[data-status="aborted"] {{
      background: #fdeceb;
      color: var(--red);
    }}
    .badge[data-status="warning"] {{
      background: #fff4df;
      color: var(--amber);
    }}
    .event-type {{
      font-weight: 700;
      overflow-wrap: anywhere;
    }}
    details {{
      margin-top: 6px;
    }}
    summary {{
      cursor: pointer;
      color: var(--blue);
      font-weight: 650;
      width: fit-content;
    }}
    pre {{
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      max-height: 260px;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      background: #0f172a;
      color: #e5eefb;
      font-size: 12px;
    }}
    .empty {{
      border: 1px dashed var(--line);
      border-radius: 8px;
      padding: 24px;
      color: var(--muted);
      background: var(--surface);
      text-align: center;
    }}
    @media (max-width: 980px) {{
      .topbar-inner {{
        grid-template-columns: 1fr;
      }}
      .meta {{
        justify-content: flex-start;
      }}
      .stats {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .toolbar {{ grid-template-columns: 1fr; }}
      .feed-head {{ display: none; }}
      .event {{ grid-template-columns: 1fr; align-items: start; }}
    }}
    @media (max-width: 560px) {{
      main, .topbar-inner {{ padding-left: 14px; padding-right: 14px; }}
      .stats {{ grid-template-columns: 1fr; }}
      h1 {{ font-size: 21px; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <header class="topbar">
      <div class="topbar-inner">
        <div class="brand">
          <div class="eyebrow">Agent action audit trail</div>
          <h1>Agent Office</h1>
        </div>
        <div class="meta">
          <span class="meta-pill"><span class="dot"></span>Paper runtime</span>
          <span class="meta-pill">DB: {html.escape(str(db_path))}</span>
          <span class="meta-pill">Last: <span id="last-event">{html.escape(last_event)}</span></span>
        </div>
      </div>
    </header>
    <main>
      <section class="stats" aria-label="Audit summary">
        <div class="stat" data-tone="blue"><span>Total actions</span><strong id="stat-total">{total}</strong></div>
        <div class="stat" data-tone="green"><span>Trades opened</span><strong id="stat-trades">{trades}</strong></div>
        <div class="stat" data-tone="amber"><span>Rejected</span><strong id="stat-rejects">{rejects}</strong></div>
        <div class="stat" data-tone="red"><span>Aborted</span><strong id="stat-aborts">{aborts}</strong></div>
      </section>
      <section class="toolbar" aria-label="Audit filters">
        <label>Search
          <input id="search" type="search" placeholder="BTC, Risk Layer, max_leverage">
        </label>
        <label>Actor
          <select id="actor-filter"><option value="">All actors</option></select>
        </label>
        <label>Status
          <select id="status-filter">
            <option value="">All statuses</option>
            <option value="accepted">Accepted</option>
            <option value="executed">Executed</option>
            <option value="rejected">Rejected</option>
            <option value="aborted">Aborted</option>
            <option value="warning">Warning</option>
            <option value="info">Info</option>
          </select>
        </label>
      </section>
      <div class="feed-head" aria-hidden="true">
        <span>Time</span>
        <span>Actor</span>
        <span>Status</span>
        <span>Action</span>
        <span>ID</span>
      </div>
      <section id="timeline" class="timeline" aria-live="polite"></section>
    </main>
  </div>
  <script>
    let events = {payload};
    const timeline = document.getElementById("timeline");
    const search = document.getElementById("search");
    const actorFilter = document.getElementById("actor-filter");
    const statusFilter = document.getElementById("status-filter");

    function escapeHtml(value) {{
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }}

    function populateActors() {{
      const current = actorFilter.value;
      const actors = [...new Set(events.map((event) => event.actor))].sort();
      actorFilter.innerHTML = '<option value="">All actors</option>' +
        actors.map((actor) => `<option value="${{escapeHtml(actor)}}">${{escapeHtml(actor)}}</option>`).join("");
      actorFilter.value = current;
    }}

    function filteredEvents() {{
      const term = search.value.toLowerCase().trim();
      return events.filter((event) => {{
        const blob = JSON.stringify(event).toLowerCase();
        const actorOk = !actorFilter.value || event.actor === actorFilter.value;
        const statusOk = !statusFilter.value || event.status === statusFilter.value;
        const termOk = !term || blob.includes(term);
        return actorOk && statusOk && termOk;
      }});
    }}

    function render() {{
      populateActors();
      const rows = filteredEvents();
      if (!rows.length) {{
        timeline.innerHTML = '<div class="empty">No matching agent actions.</div>';
        return;
      }}
      timeline.innerHTML = rows.map((event) => `
        <article class="event" data-status="${{escapeHtml(event.status)}}">
          <div>
            <div class="time">${{escapeHtml(event.created_at)}}</div>
          </div>
          <div>
            <div class="actor">${{escapeHtml(event.actor)}}</div>
            <div class="event-type">${{escapeHtml(event.event_type)}}</div>
          </div>
          <div>
            <span class="badge" data-status="${{escapeHtml(event.status)}}">${{escapeHtml(event.status)}}</span>
          </div>
          <div>
            <div>${{escapeHtml(event.symbol || "global")}}</div>
            <div class="summary">${{escapeHtml(event.summary)}}</div>
            <details>
              <summary>Payload</summary>
              <pre>${{escapeHtml(JSON.stringify(event.payload, null, 2))}}</pre>
            </details>
          </div>
          <div class="badge">#${{event.id}}</div>
        </article>
      `).join("");
    }}

    async function refresh() {{
      try {{
        const response = await fetch("/api/actions?limit=300");
        if (!response.ok) return;
        events = await response.json();
        document.getElementById("stat-total").textContent = events.length;
        document.getElementById("stat-trades").textContent = events.filter((event) => event.event_type === "trade_opened").length;
        document.getElementById("stat-rejects").textContent = events.filter((event) => event.status === "rejected").length;
        document.getElementById("stat-aborts").textContent = events.filter((event) => event.status === "aborted").length;
        document.getElementById("last-event").textContent = events[0]?.created_at || "No events";
        render();
      }} catch (error) {{
        console.warn(error);
      }}
    }}

    search.addEventListener("input", render);
    actorFilter.addEventListener("change", render);
    statusFilter.addEventListener("change", render);
    render();
    setInterval(refresh, 5000);
  </script>
</body>
</html>"""


def load_action_rows(store: SQLiteStore, limit: int = 300) -> list[dict[str, Any]]:
    return [_event_to_row(event) for event in store.list_audit_events(limit=limit)]


def _handler_for(store: SQLiteStore) -> type[BaseHTTPRequestHandler]:
    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_html(render_dashboard(load_action_rows(store), store.path))
                return
            if parsed.path == "/api/actions":
                params = parse_qs(parsed.query)
                limit = _parse_limit(params.get("limit", ["300"])[0])
                self._send_json(load_action_rows(store, limit=limit))
                return
            self.send_error(HTTPStatus.NOT_FOUND, "not found")

        def log_message(self, format: str, *args: object) -> None:
            return

        def _send_html(self, body: str) -> None:
            encoded = body.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _send_json(self, body: Any) -> None:
            encoded = json.dumps(body, default=_json_default).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    return DashboardHandler


def _event_to_row(event: Any) -> dict[str, Any]:
    return {
        "id": event.id,
        "created_at": event.created_at.isoformat(),
        "event_type": event.event_type,
        "symbol": event.symbol,
        "actor": _actor_for_event(event.event_type),
        "status": _status_for_event(event.event_type, event.payload),
        "summary": _summary_for_event(event.event_type, event.payload),
        "payload": event.payload,
    }


def _actor_for_event(event_type: str) -> str:
    if event_type.startswith("reconciliation"):
        return "Reconciliation"
    if event_type == "indicator_snapshot":
        return "Indicator Engine"
    if event_type.startswith("strategy"):
        return "Rule Baseline"
    if event_type == "risk_decision":
        return "Risk Layer"
    if event_type.startswith("execution") or event_type == "trade_opened":
        return "Execution"
    if event_type.startswith("operator"):
        return "Operator"
    if event_type.startswith("cycle"):
        return "Runtime"
    return "System"


def _status_for_event(event_type: str, payload: dict[str, Any]) -> str:
    if "aborted" in event_type:
        return "aborted"
    if event_type == "risk_decision":
        if payload.get("accepted") is True:
            return "accepted"
        return "rejected"
    if event_type == "execution_result":
        return "executed" if payload.get("success") else "aborted"
    if event_type == "trade_opened":
        return "executed"
    if event_type == "reconciliation" and payload.get("status") != "ok":
        return "warning"
    return "info"


def _summary_for_event(event_type: str, payload: dict[str, Any]) -> str:
    if event_type == "risk_decision":
        reason = payload.get("reason", "unknown")
        data = payload.get("data", {})
        return f"Risk gate: {reason}. {data}"
    if event_type == "strategy_intent":
        return str(payload.get("thesis", "Strategy produced trade intent."))
    if event_type == "indicator_snapshot":
        return f"Trend {payload.get('trend')} / 1D {payload.get('daily_trend')}, RSI {payload.get('rsi')}"
    if event_type == "execution_result":
        return str(payload.get("message", "Execution adapter returned result."))
    if event_type == "trade_opened":
        return f"Opened {payload.get('side')} notional {payload.get('notional_usdt')}, stop {payload.get('stop_loss')}"
    if event_type == "reconciliation":
        return str(payload.get("reason", "Reconciliation checked exchange vs local state."))
    if "error" in payload:
        return str(payload["error"])
    return str(payload.get("reason", event_type.replace("_", " ")))


def _parse_limit(value: str) -> int:
    try:
        return max(1, min(int(value), 1_000))
    except ValueError:
        return 300


def _json_default(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return asdict(value)
    return str(value)
