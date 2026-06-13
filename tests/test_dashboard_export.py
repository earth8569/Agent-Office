from __future__ import annotations

import csv
import io

from agent_office.dashboard_export import CSV_HEADERS, rows_from_summary, rows_to_csv


def _summary() -> dict:
    return {
        "starting_equity_usdt": 10000.0,
        "fees_usdt": 30.0,
        "equity_curve": [
            {"time": "2026-01-01T00:00:00+00:00", "equity": 10000.0},
            {"time": "2026-01-05T04:00:00+00:00", "equity": 10100.0},
            {"time": "2026-01-09T04:00:00+00:00", "equity": 10050.0},
            {"time": "2026-01-12T04:00:00+00:00", "equity": 10250.0},
        ],
    }


def test_rows_map_equity_steps_to_net_pnl() -> None:
    rows = rows_from_summary(_summary())
    assert len(rows) == 3
    assert [r["pnl"] for r in rows] == [100.0, -50.0, 200.0]
    assert rows[0]["validation_start"] == "2026-01-01"
    assert rows[0]["validation_end"] == "2026-01-05"
    assert all(r["start_equity"] == 10000.0 for r in rows)


def test_total_pnl_and_fees_reconcile() -> None:
    summary = _summary()
    rows = rows_from_summary(summary)
    cum_pnl = round(sum(r["pnl"] for r in rows), 2)
    assert cum_pnl == round(summary["equity_curve"][-1]["equity"] - 10000.0, 2)
    # fees are spread evenly and sum back to the backtest total
    assert round(sum(r["fees"] for r in rows), 2) == 30.0


def test_csv_has_expected_headers_and_is_parseable() -> None:
    text = rows_to_csv(rows_from_summary(_summary()))
    parsed = list(csv.DictReader(io.StringIO(text)))
    assert list(parsed[0].keys()) == CSV_HEADERS
    assert len(parsed) == 3


def test_empty_or_single_point_curve_yields_no_rows() -> None:
    assert rows_from_summary({"equity_curve": []}) == []
    assert rows_from_summary({"equity_curve": [{"time": "2026-01-01", "equity": 10000.0}]}) == []
