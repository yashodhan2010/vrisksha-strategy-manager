from __future__ import annotations

from pathlib import Path
from datetime import date

from app.storage.database import get_connection, initialize_database
from app.storage.market_data_repository import get_symbol_price_ranges
from app.storage.repositories import (
    add_audit_event,
    create_backtest_run,
    find_completed_backtest_run_by_scenario,
    create_strategy_run,
    get_latest_backtest_run,
    get_latest_strategy_run,
    insert_holding_snapshots,
    insert_portfolio_snapshot,
    list_holding_snapshots,
    list_portfolio_snapshots,
    summarize_stock_contributions,
)
from app.strategy.models import RunMode, RunStatus, RunType


def test_schema_initializes_and_reruns_safely(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    initialize_database(db)
    initialize_database(db)
    with get_connection(db) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "strategy_runs" in tables
    assert "backtest_runs" in tables
    assert "market_prices" in tables
    assert "data_ingestion_runs" in tables


def test_strategy_run_can_be_inserted_and_read(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    initialize_database(db)
    create_strategy_run(RunType.MANUAL, RunMode.RANK_ONLY, database_path=db)
    latest = get_latest_strategy_run(db)
    assert latest is not None
    assert latest["run_type"] == "MANUAL"


def test_audit_event_can_be_inserted_and_read(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    initialize_database(db)
    event_id = add_audit_event(None, "TEST", "INFO", "hello", database_path=db)
    assert event_id == 1


def test_placeholder_backtest_run_can_be_inserted_and_read(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    initialize_database(db)
    create_backtest_run(None, None, "NIFTY500", {"years": 10}, RunStatus.COMPLETED, db)
    latest = get_latest_backtest_run(db)
    assert latest is not None
    assert latest["benchmark_symbol"] == "NIFTY500"
    assert latest["final_value"] is None


def test_completed_backtest_run_can_be_found_by_scenario_key(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    initialize_database(db)
    create_backtest_run(date(2024, 1, 1), date(2024, 12, 31), "NIFTY500", {"scenario_key": "abc"}, RunStatus.STARTED, db)
    completed_id = create_backtest_run(
        date(2024, 1, 1),
        date(2024, 12, 31),
        "NIFTY500",
        {"scenario_key": "abc"},
        RunStatus.COMPLETED,
        db,
    )

    cached = find_completed_backtest_run_by_scenario("abc", db)

    assert cached is not None
    assert cached["id"] == completed_id


def test_backtest_snapshot_readers(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    initialize_database(db)
    run_id = create_backtest_run(None, None, "NIFTY500", {}, RunStatus.STARTED, db)
    insert_portfolio_snapshot(
        run_id,
        __import__("datetime").date(2024, 1, 31),
        "ACTIVE",
        100_000,
        0.01,
        0.01,
        0.0,
        1,
        1,
        db,
    )
    insert_holding_snapshots(
        [
            {
                "run_id": run_id,
                "snapshot_date": __import__("datetime").date(2024, 1, 31),
                "symbol": "ABC",
                "rank": 1,
                "selected": True,
                "weight": 0.05,
            }
        ],
        db,
    )

    assert list_portfolio_snapshots(run_id, db)[0]["portfolio_nav"] == 100_000
    assert list_holding_snapshots(run_id, "2024-01-31", db)[0]["symbol"] == "ABC"
    assert summarize_stock_contributions(run_id, db)[0]["symbol"] == "ABC"


def test_symbol_price_ranges_report_coverage(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    initialize_database(db)
    with get_connection(db) as connection:
        connection.execute(
            """
            INSERT INTO market_prices (
                symbol, price_date, open, high, low, close, adjusted_close, volume, source, fetched_at
            )
            VALUES ('AAA', '2024-01-01', 1, 1, 1, 1, 1, 10, 'TEST', 'now')
            """
        )

    ranges = get_symbol_price_ranges(["AAA", "BBB"], db)

    assert ranges["AAA"]["first_date"] == "2024-01-01"
    assert ranges["AAA"]["last_date"] == "2024-01-01"
    assert "BBB" not in ranges


def test_symbol_price_ranges_tolerates_uninitialized_database(tmp_path: Path) -> None:
    ranges = get_symbol_price_ranges(["AAA"], tmp_path / "empty.db")

    assert ranges == {}
