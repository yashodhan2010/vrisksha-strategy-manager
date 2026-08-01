from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest
import pandas as pd

from app.backtest.fixed_allocation import FixedAllocationBacktestEngine
from app.data.historical_data import PriceBar
from app.storage.database import get_connection, initialize_database
from app.storage.market_data_repository import upsert_price_bars
from app.storage.repositories import create_backtest_run, get_latest_backtest_run
from app.strategy.models import RunStatus


def _business_dates(start: date, end: date) -> list[date]:
    result: list[date] = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            result.append(cursor)
        cursor += timedelta(days=1)
    return result


def _write_profile(tmp_path: Path) -> Path:
    profile = tmp_path / "strategy_profile.json"
    distributions_path = tmp_path / "distributions.csv"
    distributions_path.write_text(
        "symbol,ex_date,amount_per_unit,distribution_type,notes\n"
        "EMBASSY,2024-02-15,1.50,distribution,test payout\n"
        "PGINVIT,2024-05-15,2.00,distribution,test payout\n",
        encoding="utf-8",
    )
    profile.write_text(
        json.dumps(
            {
                "strategy_id": "diversified_asset_income_v1",
                "slug": "diversified-asset-income",
                "name": "Diversified Asset Income",
                "rebalance_schedule": {
                    "type": "quarterly_first_trading_day",
                    "quarter_start_months": [1, 4, 7, 10],
                    "timezone": "Asia/Kolkata",
                },
                "distribution": {"frequency": "quarterly", "events_path": str(distributions_path)},
                "allocation": {
                    "assets": [
                        {"sleeve": "InvIT", "symbol": "PGINVIT", "weight": 0.2},
                        {"sleeve": "REIT", "symbol": "EMBASSY", "weight": 0.2},
                        {"sleeve": "Gold", "symbol": "GOLDBEES", "weight": 0.2},
                        {"sleeve": "Debt", "symbol": "LIQUIDBEES", "weight": 0.2},
                        {"sleeve": "Nifty 50", "symbol": "NIFTYBEES", "weight": 0.2},
                    ]
                },
                "experiment_outputs": {
                    "summary_path": str(tmp_path / "summary.csv"),
                    "net_returns_detail_path": str(tmp_path / "detail.csv"),
                },
            }
        ),
        encoding="utf-8",
    )
    return profile


def test_fixed_allocation_backtest_persists_quarterly_results(tmp_path: Path) -> None:
    db = tmp_path / "fixed.db"
    initialize_database(db)
    profile = _write_profile(tmp_path)
    dates = _business_dates(date(2024, 1, 1), date(2024, 10, 3))
    symbols = ["PGINVIT", "EMBASSY", "GOLDBEES", "LIQUIDBEES", "NIFTYBEES"]
    bars: list[PriceBar] = []
    for index, price_date in enumerate(dates):
        for symbol_index, symbol in enumerate(symbols):
            price = 100.0 + index * (0.05 + symbol_index * 0.01)
            bars.append(PriceBar(symbol, price_date, price, price, price, price, price, 1000, "TEST", "now"))
    upsert_price_bars(bars, db)
    run_id = create_backtest_run(date(2024, 1, 1), date(2024, 10, 3), "NIFTY50", {}, RunStatus.STARTED, db)

    result = FixedAllocationBacktestEngine(run_id, profile, date(2024, 1, 1), date(2024, 10, 3), 100_000, db).run()

    assert result.rebalance_count == 3
    assert result.final_value > 100_000
    latest = get_latest_backtest_run(db)
    assert latest is not None
    assert latest["status"] == "COMPLETED"
    summary = json.loads(latest["summary_json"])
    assert summary["strategy_type"] == "fixed_allocation"
    assert summary["distribution_frequency"] == "quarterly"
    assert summary["total_transaction_cost"] > 0
    assert summary["total_distribution_cash"] > 0
    detail = pd.read_csv(tmp_path / "detail.csv")
    with get_connection(db) as connection:
        snapshots = connection.execute("SELECT COUNT(*) FROM portfolio_snapshots WHERE run_id = ?", (run_id,)).fetchone()[0]
        holdings = connection.execute("SELECT COUNT(*) FROM holding_snapshots WHERE run_id = ?", (run_id,)).fetchone()[0]
    assert snapshots == 3
    assert holdings == 15
    assert (tmp_path / "summary.csv").exists()
    assert (tmp_path / "detail.csv").exists()
    assert "net_period_return" in detail.columns
    assert "total_transaction_cost" in detail.columns
    assert "distribution_cash" in detail.columns
    assert "reit_distribution_return" in detail.columns
    assert "invit_distribution_return" in detail.columns
    assert detail["distribution_cash"].sum() > 0
    assert detail["distribution_return"].sum() > 0
    assert detail["reit_distribution_cash"].sum() > 0
    assert detail["invit_distribution_cash"].sum() > 0


def test_fixed_allocation_backtest_rejects_non_100_percent_weights(tmp_path: Path) -> None:
    profile = _write_profile(tmp_path)
    payload = json.loads(profile.read_text(encoding="utf-8"))
    payload["allocation"]["assets"][0]["weight"] = 0.1
    profile.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="weights must sum"):
        FixedAllocationBacktestEngine(
            1,
            profile,
            date(2024, 1, 1),
            date(2024, 12, 31),
            100_000,
            tmp_path / "missing.db",
        ).run()
