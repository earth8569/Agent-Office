from __future__ import annotations

import os
import unittest
from pathlib import Path
from uuid import uuid4

from agent_office.alerts import TelegramResult, TelegramNotifier, agent_restart_keyboard, agent_stopped_message
from agent_office.storage import SQLiteStore
from agent_office.web import _notify_agents_stopped


class AlertsTests(unittest.TestCase):
    def test_telegram_notifier_is_disabled_without_env(self) -> None:
        with self._without_telegram_env():
            result = TelegramNotifier.from_env().send_message("agents stopped")

        self.assertFalse(result.enabled)
        self.assertFalse(result.sent)
        self.assertEqual(result.reason, "telegram_not_configured")

    def test_agent_stopped_message_contains_workflow_state(self) -> None:
        message = agent_stopped_message(
            {
                "mode": "complete",
                "pm_decision": "PM_WAIT_FOR_DEMO_POSITION",
                "position_count": 0,
                "stop_order_count": 0,
                "equity_usdt": 1234.56,
                "reason": "matched",
            }
        )

        self.assertIn("All agents stopped: complete", message)
        self.assertIn("PM_WAIT_FOR_DEMO_POSITION", message)
        self.assertIn("1234.56 USDT", message)

    def test_restart_keyboard_points_to_autostart_dashboard(self) -> None:
        keyboard = agent_restart_keyboard("https://example.test/reports/grid_pixel_dashboard.html?x=1")

        button = keyboard["inline_keyboard"][0][0]
        self.assertEqual(button["text"], "Restart agents")
        self.assertEqual(button["url"], "https://example.test/reports/grid_pixel_dashboard.html?x=1&autostart=1")

    def test_notify_agents_stopped_sends_and_records_audit(self) -> None:
        store = self._store()
        notifier = FakeNotifier()

        result = _notify_agents_stopped(store, {"mode": "complete"}, notifier)

        events = store.list_audit_events(limit=5, event_type="agents_stopped_alert")
        self.assertTrue(result["telegram_sent"])
        self.assertEqual(notifier.messages[0].splitlines()[1], "All agents stopped: complete")
        self.assertEqual(notifier.reply_markups[0]["inline_keyboard"][0][0]["text"], "Restart agents")
        self.assertEqual(events[0].payload["telegram_sent"], True)

    def _store(self) -> SQLiteStore:
        db_path = Path("data") / f"test-alerts-{uuid4().hex}.sqlite"
        self.addCleanup(lambda: db_path.unlink(missing_ok=True))
        store = SQLiteStore(db_path)
        store.initialize(10_000)
        return store

    def _without_telegram_env(self):
        class EnvGuard:
            def __enter__(self_inner):
                self_inner.old_token = os.environ.pop("TELEGRAM_BOT_TOKEN", None)
                self_inner.old_chat = os.environ.pop("TELEGRAM_CHAT_ID", None)
                return self_inner

            def __exit__(self_inner, *_args):
                if self_inner.old_token is not None:
                    os.environ["TELEGRAM_BOT_TOKEN"] = self_inner.old_token
                if self_inner.old_chat is not None:
                    os.environ["TELEGRAM_CHAT_ID"] = self_inner.old_chat

        return EnvGuard()


class FakeNotifier:
    def __init__(self) -> None:
        self.dashboard_url = "https://example.test/reports/grid_pixel_dashboard.html"
        self.messages: list[str] = []
        self.reply_markups: list[dict[str, object] | None] = []

    def send_message(self, text: str, reply_markup: dict[str, object] | None = None) -> TelegramResult:
        self.messages.append(text)
        self.reply_markups.append(reply_markup)
        return TelegramResult(enabled=True, sent=True, reason="sent")


if __name__ == "__main__":
    unittest.main()