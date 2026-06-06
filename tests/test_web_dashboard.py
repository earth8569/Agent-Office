from __future__ import annotations

import json
import unittest
from pathlib import Path
from uuid import uuid4

from agent_office.storage import SQLiteStore
from agent_office.web import load_action_rows, render_dashboard


class WebDashboardTests(unittest.TestCase):
    def test_loads_audit_rows_with_actor_status_and_summary(self) -> None:
        store = self._store()
        store.record_audit(
            "risk_decision",
            "BTC/USDT:USDT",
            {"accepted": False, "reason": "max_leverage", "data": {"requested": 6}},
        )

        rows = load_action_rows(store)

        self.assertEqual(rows[0]["actor"], "Risk Layer")
        self.assertEqual(rows[0]["status"], "rejected")
        self.assertIn("max_leverage", rows[0]["summary"])

    def test_render_dashboard_contains_events_without_external_assets(self) -> None:
        events = [
            {
                "id": 1,
                "created_at": "2026-06-06T10:00:00+00:00",
                "event_type": "trade_opened",
                "symbol": "BTC/USDT:USDT",
                "actor": "Execution",
                "status": "executed",
                "summary": "Opened long",
                "payload": {"side": "long"},
            }
        ]

        page = render_dashboard(events, Path("data/paper.sqlite"))

        self.assertIn("Operator Console", page)
        self.assertIn("Agent action audit trail", page)
        self.assertIn(json.dumps(events), page)

    def _store(self) -> SQLiteStore:
        db_path = Path("data") / f"test-web-{uuid4().hex}.sqlite"
        self.addCleanup(lambda: db_path.unlink(missing_ok=True))
        store = SQLiteStore(db_path)
        store.initialize(10_000)
        return store


if __name__ == "__main__":
    unittest.main()
