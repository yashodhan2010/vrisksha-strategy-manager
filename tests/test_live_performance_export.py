from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from app.data.historical_data import PriceBar
from app.export import live_performance
from app.export.live_performance import export_live_performance_dashboard, export_live_performance_tracker_index
from app.storage.database import initialize_database
from app.storage.market_data_repository import upsert_price_bars
from app.storage.repositories import (
    complete_strategy_run,
    create_strategy_run,
    insert_holding_snapshots,
    insert_portfolio_snapshot,
)
from app.strategy.models import RunMode, RunStatus, RunType, UniverseStock


def test_export_live_performance_dashboard_tracks_selected_strategy_only(monkeypatch, tmp_path: Path) -> None:
    db = tmp_path / "live.db"
    output_dir = tmp_path / "live-dashboard"
    initialize_database(db)
    monkeypatch.setattr(live_performance.config, "STRATEGY_PACKAGE_ID", "dual_momentum_nifty500_v1")
    monkeypatch.setattr(live_performance.config, "STRATEGY_PACKAGE_SLUG", "dual-momentum")
    monkeypatch.setattr(live_performance.config, "STRATEGY_PACKAGE_NAME", "Momentum - Bamboo Canopy Edition")
    monkeypatch.setattr(live_performance.config, "STRATEGY_PACKAGE_PUBLIC_NAME", "Bamboo Canopy")
    monkeypatch.setattr(live_performance.config, "STRATEGY_PACKAGE_BENCHMARK", "NIFTY 500 TRI")
    monkeypatch.setattr(live_performance.config, "TARGET_PORTFOLIO_VALUE", 100_000.0)
    monkeypatch.setattr(live_performance.config, "SAFE_ASSET_SYMBOL", "LIQUIDBEES")
    monkeypatch.setattr(live_performance.config, "SAFE_ASSET_FALLBACK_SYMBOL", "")
    monkeypatch.setattr(
        live_performance,
        "load_universe",
        lambda: [UniverseStock("AAA", "Alpha Ltd", "Software", "Technology", isin="INE000A01001")],
    )

    _insert_prices(db)
    first_run = _monthly_run(db, "dual_momentum_nifty500_v1")
    other_strategy_run = _monthly_run(db, "other_strategy_v1")
    second_run = _monthly_run(db, "dual_momentum_nifty500_v1")
    insert_holding_snapshots(
        [
            _holding(first_run, date(2024, 1, 1), "AAA", 0.50, 100.0),
            _holding(other_strategy_run, date(2024, 1, 2), "AAA", 1.00, 110.0),
            _holding(second_run, date(2024, 1, 3), "AAA", 1.00, 121.0),
        ],
        db,
    )
    insert_portfolio_snapshot(first_run, date(2024, 1, 1), "ACTIVE", 100_000, None, None, 0.50, 1, first_run, db)
    insert_portfolio_snapshot(other_strategy_run, date(2024, 1, 2), "ACTIVE", 100_000, None, None, 0.0, 1, other_strategy_run, db)
    insert_portfolio_snapshot(second_run, date(2024, 1, 3), "ACTIVE", 100_000, None, None, 0.0, 1, second_run, db)

    path = export_live_performance_dashboard(
        output_dir=output_dir,
        strategy_id="dual_momentum_nifty500_v1",
        strategy_slug="dual-momentum",
        database_path=db,
    )

    assert (path / "index.html").exists()
    assert (path / "dashboard_data.json").exists()
    data = json.loads((path / "dashboard_data.json").read_text(encoding="utf-8"))
    assert data["manifest"]["live_inception_date"] == "2024-01-01"
    assert data["manifest"]["latest_live_date"] == "2024-01-03"
    assert [row["snapshot_date"] for row in data["rebalance_history"]] == ["2024-01-01", "2024-01-03"]
    assert data["rebalance_history"][0]["safe_asset_weight"] == 0.5
    assert data["metrics"]["total_return"] > 0
    assert any(row["symbol"] == "LIQUIDBEES" for row in data["attribution"])


def test_export_live_performance_tracker_index_includes_all_registry_profiles(tmp_path: Path) -> None:
    output_dir = tmp_path / "live-performance"
    strategy_dir = output_dir / "dual-momentum"
    strategy_dir.mkdir(parents=True)
    (strategy_dir / "dashboard_data.json").write_text(
        json.dumps(
            {
                "manifest": {
                    "strategy_id": "dual_momentum_nifty500_v1",
                    "slug": "dual-momentum",
                    "name": "Dual Momentum",
                    "public_name": "Bamboo Canopy",
                    "live_inception_date": "2024-01-01",
                    "latest_live_date": "2024-01-03",
                },
                "metrics": {"total_return": 0.10, "annualized_return": 0.10, "max_drawdown": -0.01},
                "data_quality": {"live_rebalance_count": 2, "tracked_symbols": 1},
                "daily": [],
                "drawdowns": [],
                "benchmark": [],
                "backtest": [],
                "attribution": [],
                "current_holdings": [],
                "rebalance_history": [],
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    first_profile = tmp_path / "dual.json"
    second_profile = tmp_path / "income.json"
    first_profile.write_text(
        json.dumps({"strategy_id": "dual_momentum_nifty500_v1", "slug": "dual-momentum", "name": "Dual Momentum"}),
        encoding="utf-8",
    )
    second_profile.write_text(
        json.dumps({"strategy_id": "diversified_asset_income_v1", "slug": "diversified-asset-income", "name": "Income"}),
        encoding="utf-8",
    )
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"strategies": [str(first_profile), str(second_profile)]}), encoding="utf-8")

    path = export_live_performance_tracker_index(output_dir=output_dir, registry_path=registry)

    tracker = json.loads((path / "tracker_data.json").read_text(encoding="utf-8"))
    assert (path / "index.html").exists()
    assert [item["manifest"]["slug"] for item in tracker["strategies"]] == ["dual-momentum", "diversified-asset-income"]
    assert tracker["strategies"][0]["metrics"]["total_return"] == 0.10
    assert tracker["strategies"][1]["warnings"] == ["No live-performance artifact has been generated for this strategy yet."]


def test_tracker_index_uses_package_proxy_when_live_artifact_is_missing(tmp_path: Path) -> None:
    output_dir = tmp_path / "live-performance"
    package_dir = tmp_path / "packages" / "income" / "strategy-package"
    package_dir.mkdir(parents=True)
    (package_dir / "returns_daily.csv").write_text(
        "strategy_id,date,return,equity_curve\nincome,2024-01-01,0,1\nincome,2024-01-02,0.01,1.01\n",
        encoding="utf-8",
    )
    (package_dir / "benchmark_returns.csv").write_text(
        "strategy_id,date,benchmark,return,equity_curve\nincome,2024-01-01,NIFTY,0,1\nincome,2024-01-02,NIFTY,0.005,1.005\n",
        encoding="utf-8",
    )
    (package_dir / "drawdowns.csv").write_text(
        "strategy_id,date,drawdown\nincome,2024-01-01,0\nincome,2024-01-02,0\n",
        encoding="utf-8",
    )
    (package_dir / "latest_model_portfolio.csv").write_text(
        "strategy_id,as_of_date,symbol,company_name,exchange,isin,sector,marketcap_bucket,target_weight,reference_price,entry_date,notes\n"
        "income,2024-01-02,AAA,Alpha,NSE,,ETF,,1.0,101,2024-01-01,test\n",
        encoding="utf-8",
    )
    (package_dir / "rebalance_history.csv").write_text(
        "strategy_id,rebalance_date,symbol,company_name,action,old_weight,new_weight,old_reference_price,new_reference_price,rationale\n"
        "income,2024-01-01,AAA,Alpha,ADDED,0,1.0,,100,test\n",
        encoding="utf-8",
    )
    (package_dir / "backtest_metrics.json").write_text(
        json.dumps({"absolute_return": 0.01, "cagr": 0.12, "max_drawdown": 0.0, "win_rate": 1.0}),
        encoding="utf-8",
    )
    distributions = tmp_path / "distributions.csv"
    distributions.write_text("symbol,ex_date,amount_per_unit\nAAA,2024-01-02,1\n", encoding="utf-8")
    profile = tmp_path / "income.json"
    profile.write_text(
        json.dumps(
            {
                "strategy_id": "income_v1",
                "slug": "income",
                "name": "Income",
                "package": {"output_dir": str(package_dir)},
                "distribution": {"events_path": str(distributions)},
            }
        ),
        encoding="utf-8",
    )
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"strategies": [str(profile)]}), encoding="utf-8")

    path = export_live_performance_tracker_index(output_dir=output_dir, registry_path=registry)

    tracker = json.loads((path / "tracker_data.json").read_text(encoding="utf-8"))
    strategy = tracker["strategies"][0]
    assert strategy["manifest"]["report_source"] == "backtest_proxy"
    assert strategy["manifest"]["distributions_included"] is True
    assert strategy["metrics"]["total_return"] == 0.01
    assert strategy["current_holdings"][0]["symbol"] == "AAA"


def _insert_prices(db: Path) -> None:
    bars = []
    rows = [
        (date(2024, 1, 1), "AAA", 100.0),
        (date(2024, 1, 2), "AAA", 110.0),
        (date(2024, 1, 3), "AAA", 121.0),
        (date(2024, 1, 1), "LIQUIDBEES", 1000.0),
        (date(2024, 1, 2), "LIQUIDBEES", 1000.0),
        (date(2024, 1, 3), "LIQUIDBEES", 1000.0),
        (date(2024, 1, 1), "NIFTY500", 1000.0),
        (date(2024, 1, 2), "NIFTY500", 1010.0),
        (date(2024, 1, 3), "NIFTY500", 1020.0),
    ]
    for price_date, symbol, price in rows:
        bars.append(PriceBar(symbol, price_date, price, price, price, price, price, 1000, "TEST", "now"))
    upsert_price_bars(bars, db)


def _monthly_run(db: Path, strategy_id: str) -> int:
    run_id = create_strategy_run(
        RunType.MONTHLY,
        RunMode.PAPER,
        RunStatus.STARTED,
        config_payload={"strategy_id": strategy_id, "strategy_slug": strategy_id.replace("_", "-")},
        database_path=db,
    )
    complete_strategy_run(run_id, RunStatus.COMPLETED, "ok", database_path=db)
    return run_id


def _holding(run_id: int, snapshot_date: date, symbol: str, weight: float, reference_price: float) -> dict[str, object]:
    return {
        "run_id": run_id,
        "snapshot_date": snapshot_date,
        "symbol": symbol,
        "industry": "Software",
        "sector": "Technology",
        "rank": 1,
        "selected": True,
        "weight": weight,
        "quantity": 10,
        "reference_price": reference_price,
        "market_value": 1000,
        "monthly_return": None,
        "portfolio_contribution": None,
        "holding_action": "ENTERED",
        "consecutive_months_held": 1,
        "total_months_held": 1,
    }
