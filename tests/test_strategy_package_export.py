from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from pathlib import Path

from app.export import package_builder
from app.export.package_builder import build_strategy_package
from app.export.schemas import PACKAGE_FILES
from app.storage.database import get_connection, initialize_database
from app.storage.market_data_repository import upsert_price_bars
from app.storage.repositories import (
    create_backtest_run,
    insert_holding_snapshots,
    insert_portfolio_snapshot,
    update_backtest_run_result,
)
from app.strategy.models import RunStatus, UniverseStock
from app.data.historical_data import PriceBar


def test_build_strategy_package_exports_vriksha_contract(monkeypatch, tmp_path: Path) -> None:
    db = tmp_path / "package.db"
    output_dir = tmp_path / "strategy-package"
    initialize_database(db)
    monkeypatch.setattr(
        package_builder,
        "load_universe",
        lambda: [
            UniverseStock("AAA", "Alpha Ltd", "Software", "Technology", isin="INE000A01001"),
            UniverseStock("BBB", "Beta Ltd", "Banks", "Financial Services", isin="INE000B01001"),
        ],
    )
    monkeypatch.setattr("app.export.package_builder.config.STRATEGY_PACKAGE_RA_ENTITY", "Prathamesh Gupta")
    monkeypatch.setattr("app.export.package_builder.config.STRATEGY_PACKAGE_MIN_CAPITAL_GUIDANCE", 0)

    run_id = create_backtest_run(
        date(2024, 1, 1),
        date(2024, 3, 1),
        "NIFTY500",
        {"strategy_top_n": 2},
        RunStatus.STARTED,
        db,
    )
    _insert_prices(db)
    for index, snapshot_date in enumerate([date(2024, 2, 1), date(2024, 3, 1)], start=1):
        insert_portfolio_snapshot(
            run_id,
            snapshot_date,
            "ACTIVE",
            100_000 + index * 5_000,
            0.05,
            index * 0.05,
            0.0,
            2,
            index,
            db,
        )
    insert_holding_snapshots(
        [
            _holding(run_id, date(2024, 2, 1), "AAA", "Technology", 0.50, 110.0, "ENTERED", 1),
            _holding(run_id, date(2024, 2, 1), "BBB", "Financial Services", 0.50, 95.0, "ENTERED", 2),
            _holding(run_id, date(2024, 3, 1), "AAA", "Technology", 0.60, 120.0, "HELD", 1),
            _holding(run_id, date(2024, 3, 1), "BBB", "Financial Services", 0.40, 100.0, "HELD", 2),
        ],
        db,
    )
    update_backtest_run_result(
        run_id,
        RunStatus.COMPLETED,
        date(2024, 1, 1),
        date(2024, 3, 1),
        100_000,
        110_000,
        {"strategy_top_n": 2, "rebalances_per_month": 1, "strategy_ranking_method": "AVERAGE_RANK"},
        [],
        db,
    )

    path = build_strategy_package(run_id, output_dir, db)

    assert sorted(item.name for item in path.iterdir()) == sorted(PACKAGE_FILES)
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["ra_entity"] == "Prathamesh Gupta"
    assert manifest["slug"] == "dual-momentum"
    assert manifest["target_holdings"] == 2
    assert manifest["public_methodology_file"] == "methodology.md"
    assert manifest["internal_methodology_file"] == "methodology_internal.md"
    assert "holding_buffer_pct" not in manifest
    public_methodology = (path / "methodology.md").read_text(encoding="utf-8")
    internal_methodology = (path / "methodology_internal.md").read_text(encoding="utf-8")
    assert "exact implementation parameters" in public_methodology
    assert "Signal Construction" in internal_methodology
    latest_rows = _read_csv(path / "latest_model_portfolio.csv")
    assert latest_rows[0]["strategy_id"] == "dual_momentum_nifty500_v1"
    assert latest_rows[0]["company_name"] == "Alpha Ltd"
    assert latest_rows[0]["target_weight"] == "0.6"
    daily_rows = _read_csv(path / "returns_daily.csv")
    assert len(daily_rows) > 2
    rebalance_rows = _read_csv(path / "rebalance_history.csv")
    assert {row["action"] for row in rebalance_rows} >= {"ADDED", "WEIGHT_CHANGED"}


def _insert_prices(db: Path) -> None:
    bars: list[PriceBar] = []
    current = date(2024, 1, 1)
    while current <= date(2024, 3, 1):
        if current.weekday() < 5:
            offset = (current - date(2024, 1, 1)).days
            for symbol, base, drift in [("AAA", 100.0, 0.35), ("BBB", 90.0, 0.16), ("NIFTY500", 1000.0, 1.5)]:
                price = base + offset * drift
                bars.append(PriceBar(symbol, current, price, price, price, price, price, 1000, "TEST", "now"))
        current += timedelta(days=1)
    upsert_price_bars(bars, db)


def _holding(
    run_id: int,
    snapshot_date: date,
    symbol: str,
    sector: str,
    weight: float,
    reference_price: float,
    action: str,
    rank: int,
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "snapshot_date": snapshot_date,
        "symbol": symbol,
        "industry": sector,
        "sector": sector,
        "rank": rank,
        "selected": True,
        "weight": weight,
        "quantity": 10,
        "reference_price": reference_price,
        "market_value": 1000,
        "monthly_return": 0.05,
        "portfolio_contribution": 0.025,
        "holding_action": action,
        "consecutive_months_held": 1,
        "total_months_held": 1,
    }


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))
