from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from app.admin_dashboard_snapshot import build_admin_dashboard_snapshot, export_admin_dashboard_snapshot


def _write_profile(root: Path) -> Path:
    slug = "sample-strategy"
    folder = root / "strategies" / slug
    folder.mkdir(parents=True)
    (folder / "experiments").mkdir()
    (folder / "methodology.md").write_text("# Public\n", encoding="utf-8")
    (folder / "methodology_internal.md").write_text("# Internal\n", encoding="utf-8")
    (folder / "experiments" / "optimizer.py").write_text("# optimizer\n", encoding="utf-8")
    results = root / "data" / "output" / slug / "trials.csv"
    results.parent.mkdir(parents=True)
    pd.DataFrame([{"rank_by_cagr": 1, "cagr": 0.1}]).to_csv(results, index=False)
    finalized = root / "data" / "output" / "finalized" / "sample_strategy.json"
    finalized.parent.mkdir(parents=True)
    finalized.write_text(
        json.dumps(
            {
                "strategy_id": "sample_strategy_v1",
                "strategy_slug": slug,
                "selection": {"objective": "cagr", "rank_column": "rank_by_cagr"},
            }
        ),
        encoding="utf-8",
    )
    package_dir = root / "data" / "output" / "packages" / slug / "strategy-package"
    update_dir = package_dir.parent / "model-portfolio-update"
    update_dir.mkdir(parents=True)
    (update_dir / "manifest.json").write_text(
        json.dumps({"as_of_date": "2026-07-20", "latest_run_id": 7}),
        encoding="utf-8",
    )
    pd.DataFrame([{"strategy_id": "sample_strategy_v1", "as_of_date": "2026-07-20", "symbol": "EX"}]).to_csv(
        update_dir / "latest_model_portfolio.csv",
        index=False,
    )
    profile = folder / "strategy_profile.json"
    profile.write_text(
        json.dumps(
            {
                "strategy_id": "sample_strategy_v1",
                "slug": slug,
                "name": "Sample Strategy",
                "short_description": "Safe admin snapshot test.",
                "category_labels": ["Momentum"],
                "universe": "NIFTY 500",
                "benchmark": "NIFTY 500 TRI",
                "rebalance_schedule": {
                    "type": "monthly_target_days",
                    "target_days": [1, 15],
                    "timezone": "Asia/Kolkata",
                },
                "documents": {
                    "public_methodology_path": str(folder / "methodology.md"),
                    "internal_methodology_path": str(folder / "methodology_internal.md"),
                },
                "optimization": {
                    "engine_path": str(folder / "experiments" / "optimizer.py"),
                    "results_path": str(results),
                    "finalized_config_path": str(finalized),
                    "objective": "cagr",
                    "rank_column": "rank_by_cagr",
                    "search_space": {"top_n": [20]},
                },
                "package": {
                    "version": "1.0.0",
                    "output_dir": str(package_dir),
                },
            }
        ),
        encoding="utf-8",
    )
    return profile


def test_build_admin_dashboard_snapshot_contains_safe_operational_metadata(tmp_path: Path) -> None:
    profile = _write_profile(tmp_path)
    registry = tmp_path / "strategies" / "registry.json"
    registry.write_text(json.dumps({"strategies": [str(profile)]}), encoding="utf-8")

    snapshot = build_admin_dashboard_snapshot(registry_path=registry)

    strategy = snapshot["strategies"][0]
    assert snapshot["content_policy"]["performance_metrics_included"] is False
    assert snapshot["content_policy"]["holdings_rows_included"] is False
    assert strategy["latest_model_portfolio_as_of"] == "2026-07-20"
    assert strategy["last_successful_run"]["type"] == "model_portfolio_update"
    assert "refresh-finalized-parameters" in strategy["commands"]["refresh_finalized_parameters"]
    assert "target_weight" not in json.dumps(snapshot).lower()


def test_export_admin_dashboard_snapshot_writes_json(tmp_path: Path) -> None:
    profile = _write_profile(tmp_path)
    registry = tmp_path / "strategies" / "registry.json"
    registry.write_text(json.dumps({"strategies": [str(profile)]}), encoding="utf-8")
    output = tmp_path / "data" / "admin" / "strategy_dashboard.json"

    written = export_admin_dashboard_snapshot(output_path=output, registry_path=registry)

    assert written == output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["validation"]["ok"] is True
    assert payload["strategies"][0]["next_due_date"]
