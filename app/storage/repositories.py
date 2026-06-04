from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from app import config
from app.storage.database import get_connection
from app.strategy.models import OrderProposal, RunMode, RunStatus, RunType


def _json(value: Any) -> str:
    return json.dumps(value or {})


def create_strategy_run(
    run_type: RunType,
    mode: RunMode,
    status: RunStatus = RunStatus.STARTED,
    message: str | None = None,
    config_payload: dict[str, Any] | None = None,
    database_path: str | Path = config.DATABASE_PATH,
) -> int:
    started_at = datetime.now(timezone.utc).isoformat()
    with get_connection(database_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO strategy_runs (run_type, mode, status, started_at, message, config_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (run_type.value, mode.value, status.value, started_at, message, _json(config_payload)),
        )
        return int(cursor.lastrowid)


def complete_strategy_run(
    run_id: int,
    status: RunStatus,
    message: str,
    database_path: str | Path = config.DATABASE_PATH,
) -> None:
    with get_connection(database_path) as connection:
        connection.execute(
            "UPDATE strategy_runs SET status = ?, completed_at = ?, message = ? WHERE id = ?",
            (status.value, datetime.now(timezone.utc).isoformat(), message, run_id),
        )


def get_latest_strategy_run(database_path: str | Path = config.DATABASE_PATH) -> dict[str, Any] | None:
    with get_connection(database_path) as connection:
        row = connection.execute("SELECT * FROM strategy_runs ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None


def add_audit_event(
    run_id: int | None,
    event_type: str,
    level: str,
    message: str,
    details: dict[str, Any] | None = None,
    database_path: str | Path = config.DATABASE_PATH,
) -> int:
    with get_connection(database_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO audit_events (run_id, event_type, timestamp, level, message, details_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (run_id, event_type, datetime.now(timezone.utc).isoformat(), level, message, _json(details)),
        )
        return int(cursor.lastrowid)


def get_latest_audit_event(event_type: str, database_path: str | Path = config.DATABASE_PATH) -> dict[str, Any] | None:
    with get_connection(database_path) as connection:
        row = connection.execute(
            "SELECT * FROM audit_events WHERE event_type = ? ORDER BY id DESC LIMIT 1",
            (event_type,),
        ).fetchone()
        return dict(row) if row else None


def create_backtest_run(
    requested_start_date: date | None,
    requested_end_date: date | None,
    benchmark_symbol: str,
    config_payload: dict[str, Any],
    status: RunStatus = RunStatus.COMPLETED,
    database_path: str | Path = config.DATABASE_PATH,
) -> int:
    with get_connection(database_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO backtest_runs (
                created_at, status, requested_start_date, requested_end_date, actual_start_date,
                actual_end_date, initial_capital, final_value, benchmark_symbol, config_json,
                summary_json, warnings_json
            )
            VALUES (?, ?, ?, ?, NULL, NULL, NULL, NULL, ?, ?, '{}', ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                status.value,
                requested_start_date.isoformat() if requested_start_date else None,
                requested_end_date.isoformat() if requested_end_date else None,
                benchmark_symbol,
                _json(config_payload),
                json.dumps([]),
            ),
        )
        return int(cursor.lastrowid)


def update_backtest_run_result(
    backtest_run_id: int,
    status: RunStatus,
    actual_start_date: date | None,
    actual_end_date: date | None,
    initial_capital: float | None,
    final_value: float | None,
    summary: dict[str, Any],
    warnings: list[str],
    database_path: str | Path = config.DATABASE_PATH,
) -> None:
    with get_connection(database_path) as connection:
        connection.execute(
            """
            UPDATE backtest_runs
            SET status = ?, actual_start_date = ?, actual_end_date = ?, initial_capital = ?,
                final_value = ?, summary_json = ?, warnings_json = ?
            WHERE id = ?
            """,
            (
                status.value,
                actual_start_date.isoformat() if actual_start_date else None,
                actual_end_date.isoformat() if actual_end_date else None,
                initial_capital,
                final_value,
                json.dumps(summary),
                json.dumps(warnings),
                backtest_run_id,
            ),
        )


def insert_portfolio_snapshot(
    run_id: int,
    snapshot_date: date,
    portfolio_state: str,
    portfolio_nav: float,
    monthly_return: float | None,
    cumulative_return: float | None,
    liquidbees_weight: float,
    selected_stock_count: int,
    reshuffle_number: int,
    database_path: str | Path = config.DATABASE_PATH,
) -> int:
    with get_connection(database_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO portfolio_snapshots (
                run_id, snapshot_date, portfolio_state, portfolio_nav, monthly_return, cumulative_return,
                liquidbees_weight, selected_stock_count, reshuffle_number, cooldown_checked,
                cooldown_triggered, ema_value
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, NULL)
            """,
            (
                run_id,
                snapshot_date.isoformat(),
                portfolio_state,
                portfolio_nav,
                monthly_return,
                cumulative_return,
                liquidbees_weight,
                selected_stock_count,
                reshuffle_number,
            ),
        )
        return int(cursor.lastrowid)


def insert_holding_snapshots(
    rows: list[dict[str, Any]],
    database_path: str | Path = config.DATABASE_PATH,
) -> int:
    if not rows:
        return 0
    with get_connection(database_path) as connection:
        connection.executemany(
            """
            INSERT INTO holding_snapshots (
                run_id, snapshot_date, symbol, industry, sector, rank, selected, weight,
                quantity, reference_price, market_value, monthly_return, portfolio_contribution,
                holding_action, consecutive_months_held, total_months_held
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row["run_id"],
                    row["snapshot_date"].isoformat(),
                    row["symbol"],
                    row.get("industry"),
                    row.get("sector"),
                    row.get("rank"),
                    1 if row.get("selected") else 0,
                    row.get("weight"),
                    row.get("quantity"),
                    row.get("reference_price"),
                    row.get("market_value"),
                    row.get("monthly_return"),
                    row.get("portfolio_contribution"),
                    row.get("holding_action"),
                    row.get("consecutive_months_held", 0),
                    row.get("total_months_held", 0),
                )
                for row in rows
            ],
        )
    return len(rows)


def get_latest_backtest_run(database_path: str | Path = config.DATABASE_PATH) -> dict[str, Any] | None:
    with get_connection(database_path) as connection:
        row = connection.execute("SELECT * FROM backtest_runs ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None


def list_backtest_runs(database_path: str | Path = config.DATABASE_PATH) -> list[dict[str, Any]]:
    with get_connection(database_path) as connection:
        return [dict(row) for row in connection.execute("SELECT * FROM backtest_runs ORDER BY id DESC")]


def list_portfolio_snapshots(
    run_id: int,
    database_path: str | Path = config.DATABASE_PATH,
) -> list[dict[str, Any]]:
    with get_connection(database_path) as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM portfolio_snapshots
            WHERE run_id = ?
            ORDER BY snapshot_date
            """,
            (run_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def list_holding_snapshots(
    run_id: int,
    snapshot_date: str | None = None,
    database_path: str | Path = config.DATABASE_PATH,
) -> list[dict[str, Any]]:
    query = """
        SELECT *
        FROM holding_snapshots
        WHERE run_id = ?
    """
    params: tuple[Any, ...] = (run_id,)
    if snapshot_date:
        query += " AND snapshot_date = ?"
        params = (run_id, snapshot_date)
    query += " ORDER BY snapshot_date, rank, symbol"
    with get_connection(database_path) as connection:
        rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def list_order_proposals_for_run(
    run_id: int,
    database_path: str | Path = config.DATABASE_PATH,
) -> list[dict[str, Any]]:
    with get_connection(database_path) as connection:
        rows = connection.execute(
            "SELECT * FROM order_proposals WHERE run_id = ? ORDER BY created_at, symbol",
            (run_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def list_latest_strategy_holdings(
    database_path: str | Path = config.DATABASE_PATH,
) -> list[dict[str, Any]]:
    with get_connection(database_path) as connection:
        row = connection.execute(
            """
            SELECT h.run_id, h.snapshot_date
            FROM holding_snapshots h
            JOIN strategy_runs s ON s.id = h.run_id
            WHERE h.selected = 1 AND s.run_type = ?
            ORDER BY h.snapshot_date DESC, h.run_id DESC
            LIMIT 1
            """,
            (RunType.MONTHLY.value,),
        ).fetchone()
        snapshot_date = row["snapshot_date"] if row else None
        run_id = row["run_id"] if row else None
        if not snapshot_date:
            return []
        rows = connection.execute(
            """
            SELECT h.*
            FROM holding_snapshots h
            WHERE h.selected = 1 AND h.run_id = ? AND h.snapshot_date = ?
            ORDER BY rank, symbol
            """,
            (run_id, snapshot_date),
        ).fetchall()
        return [dict(item) for item in rows]


def insert_order_proposals(
    run_id: int,
    proposals: list[OrderProposal],
    database_path: str | Path = config.DATABASE_PATH,
) -> int:
    if not proposals:
        return 0
    with get_connection(database_path) as connection:
        connection.executemany(
            """
            INSERT INTO order_proposals (
                run_id, created_at, symbol, side, quantity, reference_price,
                estimated_value, status, reason, broker_order_id, details_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    run_id,
                    datetime.now(timezone.utc).isoformat(),
                    proposal.symbol,
                    proposal.side.value,
                    proposal.quantity,
                    proposal.reference_price,
                    proposal.estimated_value,
                    proposal.status.value,
                    proposal.reason,
                    proposal.broker_order_id,
                    _json(proposal.details),
                )
                for proposal in proposals
            ],
        )
    return len(proposals)


def summarize_stock_contributions(
    run_id: int,
    database_path: str | Path = config.DATABASE_PATH,
) -> list[dict[str, Any]]:
    with get_connection(database_path) as connection:
        rows = connection.execute(
            """
            SELECT
                symbol,
                COUNT(*) AS months_held,
                SUM(COALESCE(portfolio_contribution, 0)) AS cumulative_portfolio_contribution,
                AVG(weight) AS average_weight,
                AVG(monthly_return) AS average_monthly_return,
                MIN(snapshot_date) AS first_snapshot_date,
                MAX(snapshot_date) AS latest_snapshot_date,
                MIN(rank) AS best_rank,
                AVG(rank) AS average_rank
            FROM holding_snapshots
            WHERE run_id = ? AND selected = 1
            GROUP BY symbol
            ORDER BY cumulative_portfolio_contribution DESC
            """,
            (run_id,),
        ).fetchall()
        return [dict(row) for row in rows]
