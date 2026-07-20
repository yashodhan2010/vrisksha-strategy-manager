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
        quantity = connection.execute("SELECT quantity FROM holding_snapshots WHERE quantity IS NOT NULL LIMIT 1").fetchone()[0]
    assert snapshots > 0
    assert holdings > 0
    assert contribution is not None
    assert quantity == int(quantity)


def test_backtest_engine_keeps_pre_start_prices_for_signal_lookback(tmp_path: Path) -> None:
    db = tmp_path / "backtest.db"
    initialize_database(db)
    dates = _business_dates(date(2022, 1, 3), 320)
    bars = [
        PriceBar("AAA", price_date, 100 + index, 100 + index, 100 + index, 100 + index, 100 + index, 1000, "TEST", "now")
        for index, price_date in enumerate(dates)
    ]
    upsert_price_bars(bars, db)
    start_date = dates[260]
    engine = BacktestEngine(1, start_date, dates[-1], 100_000, db)

    frame = engine._load_price_frame()
    pivot = engine._pivot_prices(frame, ["AAA"])
    rebalance_dates = engine._rebalance_dates(pivot)

    assert min(frame["price_date"]) < start_date
    assert min(rebalance_dates) >= start_date


def test_backtest_engine_persists_safe_asset_holding(monkeypatch, tmp_path: Path) -> None:
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
    monkeypatch.setattr("app.backtest.engine.config.SAFE_ASSET_SYMBOL", "LIQUIDBEES")
    dates = _business_dates(date(2023, 1, 2), 340)
    bars: list[PriceBar] = []
    for index, price_date in enumerate(dates):
        for symbol, base, drift in [
            ("AAA", 100.0, 0.35),
            ("BBB", 90.0, 0.15),
            ("LIQUIDBEES", 1000.0, 0.02),
            ("NIFTY500", 1000.0, 0.2),
        ]:
            price = base + index * drift
            bars.append(PriceBar(symbol, price_date, price, price, price, price, price, 1000, "TEST", "now"))
    upsert_price_bars(bars, db)
    run_id = create_backtest_run(date(2023, 1, 2), dates[-1], "NIFTY500", {}, RunStatus.STARTED, db)

    BacktestEngine(run_id, date(2023, 1, 2), dates[-1], 100_000, db).run()

    with get_connection(db) as connection:
        safe_asset_rows = connection.execute(
            "SELECT COUNT(*) FROM holding_snapshots WHERE run_id = ? AND symbol = 'LIQUIDBEES'",
            (run_id,),
        ).fetchone()[0]
    assert safe_asset_rows > 0


def test_backtest_engine_rejects_zero_initial_capital(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="initial_capital"):
        BacktestEngine(1, date(2024, 1, 1), date(2024, 12, 31), 0, tmp_path / "x.db")


def test_rebalance_dates_can_run_more_than_once_per_month(monkeypatch, tmp_path: Path) -> None:
    engine = BacktestEngine(1, date(2024, 1, 1), date(2024, 2, 29), 100_000, tmp_path / "x.db")
    dates = _business_dates(date(2024, 1, 1), 44)
    prices = pd.DataFrame({"AAA": [100.0 + index for index in range(len(dates))]}, index=dates)
    monkeypatch.setattr("app.backtest.engine.config.BACKTEST_REBALANCES_PER_MONTH", 2)

    rebalance_dates = engine._rebalance_dates(prices)

    assert rebalance_dates == [
        date(2024, 1, 1),
        date(2024, 1, 16),
        date(2024, 2, 1),
        date(2024, 2, 15),
    ]


def test_rebalance_dates_reject_invalid_frequency(monkeypatch, tmp_path: Path) -> None:
    engine = BacktestEngine(1, date(2024, 1, 1), date(2024, 1, 31), 100_000, tmp_path / "x.db")
    prices = pd.DataFrame({"AAA": [100.0]}, index=[date(2024, 1, 1)])
    monkeypatch.setattr("app.backtest.engine.config.BACKTEST_REBALANCES_PER_MONTH", 0)

    with pytest.raises(ValueError, match="BACKTEST_REBALANCES_PER_MONTH"):
        engine._rebalance_dates(prices)


def test_safe_asset_prices_do_not_extend_universe_calendar(monkeypatch, tmp_path: Path) -> None:
    engine = BacktestEngine(1, date(2024, 1, 1), date(2024, 1, 31), 100_000, tmp_path / "x.db")
    prices = pd.DataFrame(
        [
            {"symbol": "AAA", "price_date": date(2024, 1, 1), "price": 100.0},
            {"symbol": "AAA", "price_date": date(2024, 1, 2), "price": 101.0},
            {"symbol": "LIQUIDBEES", "price_date": date(2024, 1, 1), "price": 1000.0},
            {"symbol": "LIQUIDBEES", "price_date": date(2024, 1, 3), "price": 1001.0},
        ]
    )
    monkeypatch.setattr("app.backtest.engine.config.SAFE_ASSET_SYMBOL", "LIQUIDBEES")

    pivot = engine._pivot_prices(prices, ["AAA"])

    assert list(pivot.index) == [date(2024, 1, 1), date(2024, 1, 2)]
    assert "LIQUIDBEES" in pivot.columns


def test_rank_on_date_skips_zero_lookback_price(monkeypatch, tmp_path: Path) -> None:
    engine = BacktestEngine(1, date(2023, 1, 1), date(2024, 12, 31), 100_000, tmp_path / "x.db")
    dates = _business_dates(date(2023, 1, 2), 260)
    values = [100.0 + index for index in range(260)]
    values[-253] = 0.0
    prices = pd.DataFrame({"AAA": values}, index=dates)
    monkeypatch.setattr("app.backtest.engine.config.BETA_LOOKBACK_DAYS", 252)

    ranking = engine._rank_on_date(prices, None, dates[-1])

    assert ranking.empty


def test_rank_on_date_does_not_carry_stale_prices_across_long_gap(monkeypatch, tmp_path: Path) -> None:
    engine = BacktestEngine(1, date(2021, 1, 1), date(2022, 6, 30), 100_000, tmp_path / "x.db")
    dates = _business_dates(date(2021, 1, 1), 380)
    rows = [{"symbol": "AAA", "price_date": item, "price": 100.0 + index * 0.1} for index, item in enumerate(dates)]
    rows.extend(
        [
            {"symbol": "STALEIPO", "price_date": dates[0], "price": 5.75},
            {"symbol": "STALEIPO", "price_date": dates[1], "price": 5.75},
            {"symbol": "STALEIPO", "price_date": dates[-4], "price": 530.25},
            {"symbol": "STALEIPO", "price_date": dates[-3], "price": 535.65},
            {"symbol": "STALEIPO", "price_date": dates[-2], "price": 570.45},
            {"symbol": "STALEIPO", "price_date": dates[-1], "price": 535.65},
        ]
    )
    prices = pd.DataFrame(rows)
    monkeypatch.setattr("app.backtest.engine.config.MAX_PRICE_FORWARD_FILL_DAYS", 5)
    monkeypatch.setattr("app.backtest.engine.config.BETA_LOOKBACK_DAYS", 252)

    pivot = engine._pivot_prices(prices, ["AAA", "STALEIPO"])
    ranking = engine._rank_on_date(pivot, None, dates[-1])

    assert pd.isna(pivot.at[dates[10], "STALEIPO"])
    assert "STALEIPO" not in set(ranking["symbol"])


def test_ranking_score_supports_combined_rank(monkeypatch, tmp_path: Path) -> None:
    engine = BacktestEngine(1, date(2023, 1, 1), date(2024, 12, 31), 100_000, tmp_path / "x.db")
    frame = pd.DataFrame(
        [
            {"symbol": "HIGHMOM", "momentum_score": 0.30, "beta": 1.30, "volatility": 0.45},
            {"symbol": "BALANCED", "momentum_score": 0.24, "beta": 0.60, "volatility": 0.18},
            {"symbol": "LOWMOM", "momentum_score": 0.08, "beta": 0.40, "volatility": 0.12},
        ]
    )
    monkeypatch.setattr("app.backtest.engine.config.STRATEGY_RANKING_METHOD", "COMBINED_RANK")
    monkeypatch.setattr("app.backtest.engine.config.RANKING_MOMENTUM_WEIGHT", 0.40)
    monkeypatch.setattr("app.backtest.engine.config.RANKING_BETA_WEIGHT", 0.30)
    monkeypatch.setattr("app.backtest.engine.config.RANKING_VOLATILITY_WEIGHT", 0.30)

    scores = engine._ranking_score(frame)

    assert scores.loc[1] > scores.loc[0]


def test_ranking_score_supports_average_rank(monkeypatch, tmp_path: Path) -> None:
    engine = BacktestEngine(1, date(2023, 1, 1), date(2024, 12, 31), 100_000, tmp_path / "x.db")
    frame = pd.DataFrame(
        [
            {"symbol": "HIGHMOM", "momentum_score": 0.30, "beta": 1.30, "volatility": 0.45},
            {"symbol": "BALANCED", "momentum_score": 0.24, "beta": 0.60, "volatility": 0.18},
            {"symbol": "LOWMOM", "momentum_score": 0.08, "beta": 0.40, "volatility": 0.12},
        ]
    )
    monkeypatch.setattr("app.backtest.engine.config.STRATEGY_RANKING_METHOD", "AVERAGE_RANK")
    monkeypatch.setattr("app.backtest.engine.config.RANKING_MOMENTUM_WEIGHT", 0.70)
    monkeypatch.setattr("app.backtest.engine.config.RANKING_BETA_WEIGHT", 0.15)
    monkeypatch.setattr("app.backtest.engine.config.RANKING_VOLATILITY_WEIGHT", 0.15)

    ranked = engine._add_average_rank_columns(frame)
    scores = engine._ranking_score(ranked)

    assert ranked.loc[2, "average_rank"] == pytest.approx(5 / 3)
    assert ranked.loc[0, "weighted_average_rank"] == pytest.approx(1.6)
    assert scores.loc[0] > scores.loc[1]
    assert scores.loc[0] == pytest.approx(-1.6)


def test_ranking_score_supports_legacy_beta_adjusted_mode(monkeypatch, tmp_path: Path) -> None:
    engine = BacktestEngine(1, date(2023, 1, 1), date(2024, 12, 31), 100_000, tmp_path / "x.db")
    frame = pd.DataFrame([{"symbol": "AAA", "momentum_score": 0.20, "beta": 2.0, "volatility": 0.20}])
    monkeypatch.setattr("app.backtest.engine.config.STRATEGY_RANKING_METHOD", "BETA_ADJUSTED")

    scores = engine._ranking_score(frame)

    assert scores.iloc[0] == pytest.approx(0.10)


def test_beta_falls_back_for_constant_returns_without_warning(tmp_path: Path) -> None:
    engine = BacktestEngine(1, date(2024, 1, 1), date(2024, 12, 31), 100_000, tmp_path / "x.db")
    dates = _business_dates(date(2024, 1, 1), 80)
    stock_prices = pd.Series([100.0] * len(dates), index=dates)
    benchmark_returns = pd.Series([0.0] * len(dates), index=dates)

    beta = engine._beta(stock_prices, benchmark_returns)

    assert beta == 1.0
