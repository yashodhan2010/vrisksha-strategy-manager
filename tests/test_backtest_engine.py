from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from app.backtest import engine as backtest_engine
from app.backtest.engine import BacktestEngine
from app.storage.database import get_connection, initialize_database
from app.storage.market_data_repository import upsert_price_bars
from app.storage.repositories import create_backtest_run, get_latest_backtest_run
from app.strategy.models import RunStatus, UniverseStock
from app.data.historical_data import PriceBar
import pytest


def _business_dates(start: date, count: int) -> list[date]:
    dates: list[date] = []
    current = start
    while len(dates) < count:
        if current.weekday() < 5:
            dates.append(current)
        current += timedelta(days=1)
    return dates


def test_backtest_engine_persists_results(monkeypatch, tmp_path: Path) -> None:
    db = tmp_path / "backtest.db"
    initialize_database(db)
    monkeypatch.setattr(
        backtest_engine,
        "load_universe",
        lambda: [
            UniverseStock("AAA", "A", "I", "S"),
            UniverseStock("BBB", "B", "I", "S"),
        ],
    )
    dates = _business_dates(date(2023, 1, 2), 340)
    bars: list[PriceBar] = []
    for index, price_date in enumerate(dates):
        for symbol, base, drift in [("AAA", 100.0, 0.35), ("BBB", 90.0, 0.15), ("NIFTY500", 1000.0, 0.2)]:
            price = base + index * drift
            bars.append(PriceBar(symbol, price_date, price, price, price, price, price, 1000, "TEST", "now"))
    upsert_price_bars(bars, db)
    run_id = create_backtest_run(date(2023, 1, 2), dates[-1], "NIFTY500", {}, RunStatus.STARTED, db)

    result = BacktestEngine(run_id, date(2023, 1, 2), dates[-1], 100_000, db).run()

    assert result.final_value > 100_000
    latest = get_latest_backtest_run(db)
    assert latest is not None
    assert latest["status"] == "COMPLETED"
    with get_connection(db) as connection:
        snapshots = connection.execute("SELECT COUNT(*) FROM portfolio_snapshots").fetchone()[0]
        holdings = connection.execute("SELECT COUNT(*) FROM holding_snapshots").fetchone()[0]
        contribution = connection.execute(
            "SELECT portfolio_contribution FROM holding_snapshots WHERE portfolio_contribution IS NOT NULL LIMIT 1"
        ).fetchone()
    assert snapshots > 0
    assert holdings > 0
    assert contribution is not None


def test_backtest_engine_rejects_zero_initial_capital(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="initial_capital"):
        BacktestEngine(1, date(2024, 1, 1), date(2024, 12, 31), 0, tmp_path / "x.db")


def test_rank_on_date_skips_zero_lookback_price(monkeypatch, tmp_path: Path) -> None:
    engine = BacktestEngine(1, date(2023, 1, 1), date(2024, 12, 31), 100_000, tmp_path / "x.db")
    dates = _business_dates(date(2023, 1, 2), 260)
    values = [100.0 + index for index in range(260)]
    values[-253] = 0.0
    prices = pd.DataFrame({"AAA": values}, index=dates)
    monkeypatch.setattr("app.backtest.engine.config.BETA_LOOKBACK_DAYS", 252)

    ranking = engine._rank_on_date(prices, None, dates[-1])

    assert ranking.empty
