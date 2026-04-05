#!/usr/bin/env python3
"""
Structured event journal for trading activity and snapshots.
"""
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    import psycopg
except ImportError:  # pragma: no cover - optional until dependency is installed
    psycopg = None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): make_json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [make_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [make_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value

    if hasattr(value, "item"):
        try:
            return make_json_safe(value.item())
        except Exception:
            pass

    return str(value)


class TradingJournal:
    def __init__(self, database_url: Optional[str], sqlite_path: str, enabled: bool = True) -> None:
        self.database_url = database_url
        self.sqlite_path = sqlite_path
        self.enabled = enabled
        self.backend = "postgres" if database_url else "sqlite"
        self.param_token = "%s" if self.backend == "postgres" else "?"
        self._conn = None

    @classmethod
    def from_env(cls) -> "TradingJournal":
        enabled = os.getenv("TRADING_JOURNAL_ENABLED", "true").lower() == "true"
        database_url = os.getenv("DATABASE_URL")
        sqlite_path = os.getenv("TRADING_JOURNAL_DB_PATH", "data/trading_journal.db")
        return cls(database_url=database_url, sqlite_path=sqlite_path, enabled=enabled)

    def is_persistent(self) -> bool:
        return self.backend == "postgres"

    def describe_backend(self) -> str:
        if self.backend == "postgres":
            return "Postgres via DATABASE_URL"
        return f"SQLite at {self.sqlite_path}"

    def _ensure_connection(self) -> bool:
        if not self.enabled:
            return False

        if self._conn is not None:
            return True

        try:
            if self.backend == "postgres":
                if psycopg is None:
                    raise RuntimeError("psycopg is not installed but DATABASE_URL is set")
                self._conn = psycopg.connect(self.database_url, autocommit=True)
            else:
                directory = os.path.dirname(self.sqlite_path)
                if directory:
                    os.makedirs(directory, exist_ok=True)
                self._conn = sqlite3.connect(self.sqlite_path, check_same_thread=False)
            self._init_schema()
            return True
        except Exception as exc:
            print(f"⚠️ Journal connection failed: {exc}")
            self._conn = None
            return False

    def _init_schema(self) -> None:
        statements = [
            """
            CREATE TABLE IF NOT EXISTS bot_events (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                symbol TEXT,
                profile TEXT,
                regime TEXT,
                side TEXT,
                reason TEXT,
                order_id TEXT,
                status TEXT,
                price REAL,
                amount REAL,
                cost_usd REAL,
                profit_pct REAL,
                payload_json TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_bot_events_created_at ON bot_events(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_bot_events_type ON bot_events(event_type)",
            "CREATE INDEX IF NOT EXISTS idx_bot_events_symbol ON bot_events(symbol)",
            """
            CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                total_estimated_usd REAL,
                free_usd REAL,
                invested_usd REAL,
                positions_json TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_created_at ON portfolio_snapshots(created_at)",
        ]
        for statement in statements:
            self._execute(statement)

    def _commit_if_needed(self) -> None:
        if self.backend == "sqlite" and self._conn is not None:
            self._conn.commit()

    def _execute(self, sql: str, params: Optional[tuple] = None):
        if not self._ensure_connection():
            return None

        cursor = self._conn.cursor()
        try:
            cursor.execute(sql, params or ())
            self._commit_if_needed()
            return cursor
        except Exception as exc:
            print(f"⚠️ Journal query failed: {exc}")
            try:
                cursor.close()
            except Exception:
                pass
            try:
                if self.backend == "sqlite" and self._conn is not None:
                    self._conn.rollback()
            except Exception:
                pass
            self._conn = None
            return None

    def _rows_to_dicts(self, cursor) -> List[Dict[str, Any]]:
        if cursor is None:
            return []

        columns = [column[0] for column in cursor.description]
        rows = cursor.fetchall()
        results = []
        for row in rows:
            if isinstance(row, sqlite3.Row):
                results.append(dict(row))
            elif isinstance(row, dict):
                results.append(row)
            else:
                results.append(dict(zip(columns, row)))
        return results

    def log_event(
        self,
        event_type: str,
        *,
        symbol: Optional[str] = None,
        profile: Optional[str] = None,
        regime: Optional[str] = None,
        side: Optional[str] = None,
        reason: Optional[str] = None,
        order_id: Optional[str] = None,
        status: Optional[str] = None,
        price: Optional[float] = None,
        amount: Optional[float] = None,
        cost_usd: Optional[float] = None,
        profit_pct: Optional[float] = None,
        payload: Optional[Dict[str, Any]] = None,
        created_at: Optional[str] = None,
    ) -> None:
        if not self.enabled:
            return

        fields = [
            "id",
            "created_at",
            "event_type",
            "symbol",
            "profile",
            "regime",
            "side",
            "reason",
            "order_id",
            "status",
            "price",
            "amount",
            "cost_usd",
            "profit_pct",
            "payload_json",
        ]
        values = [
            str(uuid.uuid4()),
            created_at or utc_now_iso(),
            event_type,
            symbol,
            profile,
            regime,
            side,
            reason,
            order_id,
            status,
            price,
            amount,
            cost_usd,
            profit_pct,
            json.dumps(make_json_safe(payload or {}), sort_keys=True),
        ]
        placeholders = ", ".join([self.param_token] * len(fields))
        sql = f"INSERT INTO bot_events ({', '.join(fields)}) VALUES ({placeholders})"
        self._execute(sql, tuple(values))

    def log_portfolio_snapshot(
        self,
        *,
        total_estimated_usd: float,
        free_usd: float,
        invested_usd: float,
        positions: List[Dict[str, Any]],
        created_at: Optional[str] = None,
    ) -> None:
        if not self.enabled:
            return

        fields = [
            "id",
            "created_at",
            "total_estimated_usd",
            "free_usd",
            "invested_usd",
            "positions_json",
        ]
        values = [
            str(uuid.uuid4()),
            created_at or utc_now_iso(),
            total_estimated_usd,
            free_usd,
            invested_usd,
            json.dumps(make_json_safe(positions), sort_keys=True),
        ]
        placeholders = ", ".join([self.param_token] * len(fields))
        sql = f"INSERT INTO portfolio_snapshots ({', '.join(fields)}) VALUES ({placeholders})"
        self._execute(sql, tuple(values))

    def get_events_between(self, start_iso: str, end_iso: str) -> List[Dict[str, Any]]:
        token = self.param_token
        sql = (
            "SELECT * FROM bot_events "
            f"WHERE created_at >= {token} AND created_at < {token} "
            "ORDER BY created_at ASC"
        )
        return self._rows_to_dicts(self._execute(sql, (start_iso, end_iso)))

    def get_latest_snapshot_before(self, end_iso: str) -> Optional[Dict[str, Any]]:
        token = self.param_token
        sql = (
            "SELECT * FROM portfolio_snapshots "
            f"WHERE created_at <= {token} "
            "ORDER BY created_at DESC LIMIT 1"
        )
        rows = self._rows_to_dicts(self._execute(sql, (end_iso,)))
        return rows[0] if rows else None

    def get_first_snapshot_after(self, start_iso: str) -> Optional[Dict[str, Any]]:
        token = self.param_token
        sql = (
            "SELECT * FROM portfolio_snapshots "
            f"WHERE created_at >= {token} "
            "ORDER BY created_at ASC LIMIT 1"
        )
        rows = self._rows_to_dicts(self._execute(sql, (start_iso,)))
        return rows[0] if rows else None

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
