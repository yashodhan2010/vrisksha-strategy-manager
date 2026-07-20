from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from app.data.historical_data import PriceBar
from app.storage.database import get_connection, initialize_database
from app.storage.market_data_repository import upsert_price_bars
from app.storage.repositories import create_strategy_run
from app.strategy import rebalance as rebalance_module
from app.strategy.models import RunMode, RunStatus, RunType, UniverseStock
from app.strategy.rebalance import RebalanceEngine


def _business_dates(start: date, count: int) -> list[date]:
    dates: list[date] = []
    current = start
    while len(dates) < count:
        if current.weekday() < 5:
            dates.append(current)
        current += timedelta(days=1)
    return dates


def test_rebalance_engine_persists_holdings_and_order_proposals(monkeypatch, tmp_path: Path) -> None:
    db = tmp_path / "rebalance.db"
    initialize_database(db)
    monkeypatch.setattr(
        rebalance_module,
        "load_universe",
        lambda: [
            UniverseStock("AAA", "A", "Industry", "Sector"),
            UniverseStock("BBB", "B", "Industry", "Sector"),
        ],
    )
    dates = _business_dates(date(2023, 1, 2), 320)
    bars: list[PriceBar] = []
    for index, price_date in enumerate(dates):
        for symbol, base, drift in [("AAA", 100.0, 0.4), ("BBB", 90.0, 0.2), ("NIFTY500", 1000.0, 0.15)]:
            price = base + index * drift
            bars.append(PriceBar(symbol, price_date, price, price, price, price, price, 1000, "TEST", "now"))
    upsert_price_bars(bars, db)
    run_id = create_strategy_run(RunType.MONTHLY, RunMode.PAPER, RunStatus.STARTED, database_path=db)
    monkeypatch.setattr("app.strategy.selection.config.STRATEGY_ALLOCATION_MODE", "TOP_N_EQUAL")
    monkeypatch.setattr("app.strategy.selection.config.STRATEGY_TOP_N", 15)

    result = RebalanceEngine(run_id, dates[-1], 100_000, 5_000, db).run()

    assert result.selected_count == 2
    assert result.proposal_count == 2
    assert result.buy_scaling_ratio == 0.5
    with get_connection(db) as connection:
        holdings = connection.execute("SELECT COUNT(*) FROM holding_snapshots WHERE run_id = ?", (run_id,)).fetchone()[0]
        orders = connection.execute("SELECT COUNT(*) FROM order_proposals WHERE run_id = ?", (run_id,)).fetchone()[0]
        buy_value = connection.execute(
            "SELECT SUM(estimated_value) FROM order_proposals WHERE run_id = ? AND side = 'BUY'",
            (run_id,),
        ).fetchone()[0]
        fractional_quantities = connection.execute(
            "SELECT COUNT(*) FROM order_proposals WHERE run_id = ? AND quantity != CAST(quantity AS INTEGER)",
            (run_id,),
        ).fetchone()[0]
    assert holdings == 2
    assert orders == 2
    assert buy_value <= 5_000
    assert fractional_quantities == 0
