from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

from app.export import model_portfolio_update
from app.export.model_portfolio_update import UPDATE_FILES, export_latest_model_portfolio_update
from app.storage.database import initialize_database
from app.storage.repositories import complete_strategy_run, create_strategy_run, insert_holding_snapshots
from app.strategy.models import RunMode, RunStatus, RunType, UniverseStock


def test_export_latest_model_portfolio_update_uses_monthly_holdings(monkeypatch, tmp_path: Path) -> None:
    db = tmp_path / "update.db"
    output_dir = tmp_path / "model-portfolio-update"
    initialize_database(db)
    monkeypatch.setattr(
        model_portfolio_update,
        "load_universe",
        lambda: [
            UniverseStock("AAA", "Alpha Ltd", "Software", "Technology", isin="INE000A01001"),
            UniverseStock("BBB", "Beta Ltd", "Banks", "Financial Services", isin="INE000B01001"),
        ],
    )
    monkeypatch.setattr("app.export.model_portfolio_update.config.STRATEGY_PACKAGE_ID", "dual_momentum_nifty500_v1")
    monkeypatch.setattr("app.export.model_portfolio_update.config.STRATEGY_PACKAGE_SLUG", "dual-momentum")

    first_run = create_strategy_run(RunType.MONTHLY, RunMode.PAPER, RunStatus.COMPLETED, database_path=db)
    stale_second_run = create_strategy_run(RunType.MONTHLY, RunMode.PAPER, RunStatus.COMPLETED, database_path=db)
    second_run = create_strategy_run(RunType.MONTHLY, RunMode.PAPER, RunStatus.COMPLETED, database_path=db)
    skipped_run = create_strategy_run(RunType.MONTHLY, RunMode.PAPER, RunStatus.STARTED, database_path=db)
    complete_strategy_run(skipped_run, RunStatus.SKIPPED, "Weekend skip", database_path=db)

    insert_holding_snapshots(
        [
            _holding(first_run, date(2024, 2, 1), "AAA", "Technology", 0.50, 110.0, "ENTERED", 1),
            _holding(first_run, date(2024, 2, 1), "BBB", "Financial Services", 0.50, 95.0, "ENTERED", 2),
            _holding(stale_second_run, date(2024, 3, 1), "AAA", "Technology", 0.55, 118.0, "HELD", 1),
            _holding(stale_second_run, date(2024, 3, 1), "BBB", "Financial Services", 0.45, 99.0, "HELD", 2),
            _holding(second_run, date(2024, 3, 1), "AAA", "Technology", 0.60, 120.0, "HELD", 1),
            _holding(second_run, date(2024, 3, 1), "BBB", "Financial Services", 0.40, 100.0, "HELD", 2),
        ],
        db,
    )

    path = export_latest_model_portfolio_update(output_dir, history_dates=2, database_path=db)

    assert sorted(item.name for item in path.iterdir()) == sorted(UPDATE_FILES)
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["update_type"] == "latest_model_portfolio"
    assert manifest["latest_run_id"] == second_run
    assert manifest["as_of_date"] == "2024-03-01"
    latest_rows = _read_csv(path / "latest_model_portfolio.csv")
    assert latest_rows[0]["as_of_date"] == "2024-03-01"
    assert latest_rows[0]["company_name"] == "Alpha Ltd"
    assert latest_rows[0]["target_weight"] == "0.6"
    rebalance_rows = _read_csv(path / "rebalance_history.csv")
    assert {row["action"] for row in rebalance_rows} >= {"ADDED", "WEIGHT_CHANGED"}


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
