"""Export this project's backtest results into the CSV the pixel dashboard reads.

The pixel office dashboard (`reports/grid_pixel_dashboard.html`) polls
`results/grid-raw-walk-forward.csv`. This project does not run walk-forward
windows; instead each backtest produces an equity curve plus per-trade PnL.
We map that real output onto the dashboard's columns: one row per equity-curve
step (i.e. per closed trade), so the cumulative-PnL chart, metrics and table
are populated entirely from this project's own data.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from agent_office.storage import SQLiteStore

CSV_HEADERS = [
    "window",
    "validation_start",
    "validation_end",
    "pnl",
    "fills",
    "fees",
    "funding_paid",
    "paused_refreshes",
    "flatten_fee",
    "start_equity",
]


def rows_from_summary(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn a stored `backtest_result` payload into dashboard CSV rows.

    Each step of the equity curve becomes one row. `pnl` is the net change in
    equity for that step (already net of fees). Total fees are spread evenly
    across rows so the "Fees" metric matches the backtest total. Funding,
    pauses and flatten fees are zero because this project does not model them.
    """
    curve = summary.get("equity_curve") or []
    start_equity = round(float(summary.get("starting_equity_usdt", 0.0)), 2)
    step_count = max(0, len(curve) - 1)
    if step_count == 0:
        return []

    total_fees = float(summary.get("fees_usdt", 0.0) or 0.0)
    fee_per_step = round(total_fees / step_count, 4)

    rows: list[dict[str, Any]] = []
    for index in range(1, len(curve)):
        previous = curve[index - 1]
        current = curve[index]
        pnl = round(float(current["equity"]) - float(previous["equity"]), 2)
        rows.append(
            {
                "window": index,
                "validation_start": _day(previous["time"]),
                "validation_end": _day(current["time"]),
                "pnl": pnl,
                "fills": 2,  # entry + exit per round-trip trade
                "fees": fee_per_step,
                "funding_paid": 0,
                "paused_refreshes": 0,
                "flatten_fee": 0,
                "start_equity": start_equity,
            }
        )
    return rows


def rows_to_csv(rows: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_HEADERS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def latest_backtest_summary(store: SQLiteStore, limit: int = 500) -> dict[str, Any] | None:
    for event in store.list_audit_events(limit=limit):
        if event.event_type == "backtest_result":
            return event.payload
    return None


def export_dashboard_csv(store: SQLiteStore, out_path: Path) -> int:
    """Write the latest backtest result to `out_path`. Returns row count."""
    summary = latest_backtest_summary(store)
    if summary is None:
        raise ValueError(
            "No backtest_result found in the store. Run `agent-office backtest ...` first."
        )
    rows = rows_from_summary(summary)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rows_to_csv(rows), encoding="utf-8")
    return len(rows)


def _day(value: str) -> str:
    return str(value)[:10]
