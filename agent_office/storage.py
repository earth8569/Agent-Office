from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from agent_office.models import AccountState, AuditEvent, Position, Side, utc_now


class SQLiteStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def initialize(self, starting_equity_usdt: float = 10_000.0) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS equity_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    equity_usdt REAL NOT NULL,
                    peak_equity_usdt REAL NOT NULL,
                    daily_pnl_usdt REAL NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS positions (
                    symbol TEXT PRIMARY KEY,
                    side TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    stop_loss REAL NOT NULL,
                    notional_usdt REAL NOT NULL,
                    leverage REAL NOT NULL,
                    quantity REAL NOT NULL,
                    opened_at TEXT NOT NULL,
                    stop_order_id TEXT NOT NULL,
                    take_profit REAL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    symbol TEXT,
                    payload_json TEXT NOT NULL
                )
                """
            )
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(positions)")}
            if "take_profit" not in columns:
                conn.execute("ALTER TABLE positions ADD COLUMN take_profit REAL")

            existing = conn.execute("SELECT 1 FROM equity_state WHERE id = 1").fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO equity_state (id, equity_usdt, peak_equity_usdt, daily_pnl_usdt, updated_at)
                    VALUES (1, ?, ?, 0, ?)
                    """,
                    (starting_equity_usdt, starting_equity_usdt, utc_now().isoformat()),
                )

    def load_account(self) -> AccountState:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT equity_usdt, peak_equity_usdt, daily_pnl_usdt FROM equity_state WHERE id = 1"
            ).fetchone()
            if row is None:
                raise RuntimeError("store not initialized")
            positions = tuple(
                Position(
                    symbol=position["symbol"],
                    side=Side(position["side"]),
                    entry_price=position["entry_price"],
                    stop_loss=position["stop_loss"],
                    notional_usdt=position["notional_usdt"],
                    leverage=position["leverage"],
                    quantity=position["quantity"],
                    opened_at=datetime.fromisoformat(position["opened_at"]),
                    stop_order_id=position["stop_order_id"],
                    take_profit=position["take_profit"],
                )
                for position in conn.execute("SELECT * FROM positions ORDER BY opened_at")
            )
        return AccountState(
            equity_usdt=row["equity_usdt"],
            peak_equity_usdt=row["peak_equity_usdt"],
            daily_pnl_usdt=row["daily_pnl_usdt"],
            positions=positions,
        )

    def save_account(self, account: AccountState) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE equity_state
                SET equity_usdt = ?, peak_equity_usdt = ?, daily_pnl_usdt = ?, updated_at = ?
                WHERE id = 1
                """,
                (
                    account.equity_usdt,
                    account.peak_equity_usdt,
                    account.daily_pnl_usdt,
                    utc_now().isoformat(),
                ),
            )
            conn.execute("DELETE FROM positions")
            conn.executemany(
                """
                INSERT INTO positions (
                    symbol, side, entry_price, stop_loss, notional_usdt,
                    leverage, quantity, opened_at, stop_order_id, take_profit
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        position.symbol,
                        position.side.value,
                        position.entry_price,
                        position.stop_loss,
                        position.notional_usdt,
                        position.leverage,
                        position.quantity,
                        position.opened_at.isoformat(),
                        position.stop_order_id,
                        position.take_profit,
                    )
                    for position in account.positions
                ],
            )

    def record_audit(self, event_type: str, symbol: str | None, payload: Any) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_log (created_at, event_type, symbol, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (utc_now().isoformat(), event_type, symbol, json.dumps(payload, default=_json_default, sort_keys=True)),
            )

    def list_audit_events(
        self,
        limit: int = 200,
        event_type: str | None = None,
        symbol: str | None = None,
    ) -> tuple[AuditEvent, ...]:
        if limit <= 0:
            raise ValueError("limit must be positive")

        clauses: list[str] = []
        params: list[Any] = []
        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"""
            SELECT id, created_at, event_type, symbol, payload_json
            FROM audit_log
            {where}
            ORDER BY id DESC
            LIMIT ?
        """
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()

        return tuple(
            AuditEvent(
                id=row["id"],
                created_at=datetime.fromisoformat(row["created_at"]),
                event_type=row["event_type"],
                symbol=row["symbol"],
                payload=json.loads(row["payload_json"]),
            )
            for row in rows
        )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise
        else:
            conn.commit()
        finally:
            conn.close()


def _json_default(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return asdict(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
