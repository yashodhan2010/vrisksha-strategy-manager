from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from app import config
from app.data.historical_data import PriceBar
from app.storage.database import get_connection
from app.strategy.models import RunStatus


def upsert_price_bars(
    bars: list[PriceBar],
    database_path: str | Path = config.DATABASE_PATH,
) -> int:
    if not bars:
        return 0
    rows = [
        (
            bar.symbol,
            bar.price_date.isoformat(),
            bar.open,
            bar.high,
            bar.low,
            bar.close,
            bar.adjusted_close,
            bar.volume,
            bar.source,
            bar.fetched_at,
        )
        for bar in bars
    ]
    with get_connection(database_path) as connection:
        connection.executemany(
            """
            INSERT INTO market_prices (
                symbol, price_date, open, high, low, close, adjusted_close, volume, source, fetched_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, price_date, source) DO UPDATE SET
                open = excluded.open,
                high = excluded.high,
                low = excluded.low,
                close = excluded.close,
                adjusted_close = excluded.adjusted_close,
                volume = excluded.volume,
                fetched_at = excluded.fetched_at
            """,
            rows,
        )
    return len(rows)


def create_ingestion_run(
    source: str,
    status: RunStatus,
    start_date: date,
    end_date: date,
    requested_symbols: int,
    stored_rows: int,
    message: str,
    details: dict[str, Any] | None = None,
    database_path: str | Path = config.DATABASE_PATH,
) -> int:
    with get_connection(database_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO data_ingestion_runs (
                created_at, source, status, start_date, end_date, requested_symbols, stored_rows, message, details_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                source,
                status.value,
                start_date.isoformat(),
                end_date.isoformat(),
                requested_symbols,
                stored_rows,
                message,
                json.dumps(details or {}),
            ),
        )
        return int(cursor.lastrowid)


def count_price_rows(database_path: str | Path = config.DATABASE_PATH) -> int:
    with get_connection(database_path) as connection:
        return int(connection.execute("SELECT COUNT(*) FROM market_prices").fetchone()[0])


def get_price_summary(database_path: str | Path = config.DATABASE_PATH) -> list[dict[str, Any]]:
    with get_connection(database_path) as connection:
        rows = connection.execute(
            """
            SELECT symbol, COUNT(*) AS row_count, MIN(price_date) AS first_date, MAX(price_date) AS last_date
            FROM market_prices
            GROUP BY symbol
            ORDER BY symbol
            """
        ).fetchall()
        return [dict(row) for row in rows]


def get_symbol_price_ranges(
    symbols: list[str],
    database_path: str | Path = config.DATABASE_PATH,
) -> dict[str, dict[str, Any]]:
    cleaned = sorted({symbol.strip().upper() for symbol in symbols if symbol.strip()})
    if not cleaned:
        return {}
    placeholders = ",".join("?" for _ in cleaned)
    with get_connection(database_path) as connection:
        try:
            rows = connection.execute(
                f"""
                SELECT symbol, COUNT(*) AS row_count, MIN(price_date) AS first_date, MAX(price_date) AS last_date
                FROM market_prices
                WHERE symbol IN ({placeholders})
                GROUP BY symbol
                """,
                tuple(cleaned),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return {}
            raise
    return {str(row["symbol"]).upper(): dict(row) for row in rows}


def get_latest_ingestion_run(database_path: str | Path = config.DATABASE_PATH) -> dict[str, Any] | None:
    with get_connection(database_path) as connection:
        row = connection.execute("SELECT * FROM data_ingestion_runs ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None


def load_market_prices(
    database_path: str | Path = config.DATABASE_PATH,
    source: str | None = None,
) -> list[dict[str, Any]]:
    query = """
        SELECT symbol, price_date, open, high, low, close, adjusted_close, volume, source
        FROM market_prices
    """
    params: tuple[Any, ...] = ()
    if source:
        query += " WHERE source = ?"
        params = (source,)
    query += " ORDER BY symbol, price_date"
    with get_connection(database_path) as connection:
        return [dict(row) for row in connection.execute(query, params)]
