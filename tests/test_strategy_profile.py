from __future__ import annotations

import json
from pathlib import Path

from app import config
from app.strategy_profile import apply_strategy_profile, load_strategy_profile


def test_load_strategy_profile_requires_identity_fields(tmp_path: Path) -> None:
    path = tmp_path / "strategy_profile.json"
    path.write_text(json.dumps({"strategy_id": "x", "slug": "x", "name": "X"}), encoding="utf-8")

    profile = load_strategy_profile(path)

    assert profile["strategy_id"] == "x"


def test_apply_strategy_profile_updates_package_and_pipeline_config(monkeypatch, tmp_path: Path) -> None:
    for name in [
        "STRATEGY_PROFILE_PATH",
        "STRATEGY_PACKAGE_ID",
        "STRATEGY_PACKAGE_SLUG",
        "STRATEGY_PACKAGE_NAME",
        "STRATEGY_PACKAGE_PUBLIC_NAME",
        "STRATEGY_PACKAGE_INTERNAL_NAME",
        "STRATEGY_PACKAGE_REBALANCE_FREQUENCY",
        "STRATEGY_PACKAGE_TARGET_HOLDINGS",
        "STRATEGY_PACKAGE_SHORT_DESCRIPTION",
        "STRATEGY_PACKAGE_CATEGORY_LABELS",
        "STRATEGY_PACKAGE_PORTFOLIO_OBJECTIVE",
        "STRATEGY_PACKAGE_VERSION",
        "STRATEGY_PACKAGE_OUTPUT_DIR",
        "STRATEGY_PUBLIC_METHODOLOGY_PATH",
        "STRATEGY_INTERNAL_METHODOLOGY_PATH",
        "OPTIMIZATION_RESULTS_PATH",
        "FINALIZED_STRATEGY_CONFIG_PATH",
        "OPTIMIZATION_ENGINE_PATH",
        "OPTIMIZATION_ENGINE_MODULE",
    ]:
        monkeypatch.setattr(config, name, getattr(config, name))
    path = tmp_path / "strategy_profile.json"
    path.write_text(
        json.dumps(
            {
                "strategy_id": "sample_strategy_v1",
                "slug": "sample-strategy",
                "name": "Sample Strategy",
                "public_name": "Sample Public Strategy",
                "short_description": "Sample profile.",
                "category_labels": ["Momentum"],
                "portfolio_objective": "Fill a Gap",
                "ra_entity": "Prathamesh Gupta",
                "universe": "NIFTY 500",
                "benchmark": "NIFTY 500 TRI",
                "rebalance_schedule": {
                    "type": "quarterly_first_trading_day",
                    "quarter_start_months": [1, 4, 7, 10],
                },
                "allocation": {
                    "assets": [
                        {"symbol": "AAA", "weight": 0.5},
                        {"symbol": "BBB", "weight": 0.5},
                    ]
                },
                "optimization": {
                    "engine_path": "strategies/sample-strategy/experiments/optimizer.py",
                    "engine_module": "sample.optimizer",
                    "results_path": "data/output/sample_trials.csv",
                    "finalized_config_path": "data/output/finalized/sample.json",
                },
                "package": {
                    "version": "1.2.3",
                    "output_dir": "data/output/packages/sample-strategy/strategy-package",
                },
                "documents": {
                    "public_methodology_path": "strategies/sample-strategy/methodology.md",
                    "internal_methodology_path": "strategies/sample-strategy/methodology_internal.md",
                },
            }
        ),
        encoding="utf-8",
    )

    apply_strategy_profile(path)

    assert config.STRATEGY_PACKAGE_ID == "sample_strategy_v1"
    assert config.STRATEGY_PACKAGE_SLUG == "sample-strategy"
    assert config.STRATEGY_PACKAGE_NAME == "Sample Public Strategy"
    assert config.STRATEGY_PACKAGE_PUBLIC_NAME == "Sample Public Strategy"
    assert config.STRATEGY_PACKAGE_INTERNAL_NAME == "Sample Strategy"
    assert config.STRATEGY_PACKAGE_PORTFOLIO_OBJECTIVE == "Fill a Gap"
    assert config.STRATEGY_PACKAGE_REBALANCE_FREQUENCY == "quarterly"
    assert config.STRATEGY_PACKAGE_TARGET_HOLDINGS == 2
    assert config.STRATEGY_PACKAGE_VERSION == "1.2.3"
    assert config.STRATEGY_PUBLIC_METHODOLOGY_PATH == "strategies/sample-strategy/methodology.md"
    assert config.STRATEGY_INTERNAL_METHODOLOGY_PATH == "strategies/sample-strategy/methodology_internal.md"
    assert config.OPTIMIZATION_RESULTS_PATH == "data/output/sample_trials.csv"
    assert config.FINALIZED_STRATEGY_CONFIG_PATH == "data/output/finalized/sample.json"
    assert config.OPTIMIZATION_ENGINE_PATH == "strategies/sample-strategy/experiments/optimizer.py"
    assert config.OPTIMIZATION_ENGINE_MODULE == "sample.optimizer"


def test_apply_strategy_profile_counts_reference_universe_holdings(monkeypatch, tmp_path: Path) -> None:
    for name in [
        "STRATEGY_PROFILE_PATH",
        "STRATEGY_CATALOGUE_METADATA",
        "STRATEGY_PACKAGE_ID",
        "STRATEGY_PACKAGE_SLUG",
        "STRATEGY_PACKAGE_INTERNAL_NAME",
        "STRATEGY_PACKAGE_PUBLIC_NAME",
        "STRATEGY_PACKAGE_NAME",
        "STRATEGY_PACKAGE_REBALANCE_FREQUENCY",
        "STRATEGY_PACKAGE_TARGET_HOLDINGS",
        "STRATEGY_PACKAGE_SHORT_DESCRIPTION",
        "STRATEGY_PACKAGE_CATEGORY_LABELS",
        "STRATEGY_PACKAGE_PORTFOLIO_OBJECTIVE",
        "STRATEGY_PACKAGE_UNIVERSE",
        "STRATEGY_PACKAGE_BENCHMARK",
        "STRATEGY_PACKAGE_RA_ENTITY",
        "STRATEGY_PACKAGE_SEBI_REGISTRATION_NUMBER",
        "STRATEGY_PACKAGE_MIN_CAPITAL_GUIDANCE",
        "STRATEGY_PUBLIC_METHODOLOGY_PATH",
        "STRATEGY_INTERNAL_METHODOLOGY_PATH",
        "STRATEGY_PACKAGE_OUTPUT_DIR",
        "STRATEGY_PACKAGE_VERSION",
        "UNIVERSE_EXCEL_PATH",
        "UNIVERSE_JSON_PATH",
        "UNIVERSE_VALIDATION_REPORT_PATH",
        "DISTRIBUTION_EVENTS_PATH",
        "OPTIMIZATION_RESULTS_PATH",
        "FINALIZED_STRATEGY_CONFIG_PATH",
        "OPTIMIZATION_ENGINE_PATH",
        "OPTIMIZATION_ENGINE_MODULE",
    ]:
        monkeypatch.setattr(config, name, getattr(config, name))
    universe = tmp_path / "universe.json"
    universe.write_text(
        json.dumps(
            [
                {"symbol": "AAA", "company_name": "AAA", "industry": "A", "sector": "A", "weight": 0.5},
                {"symbol": "BBB", "company_name": "BBB", "industry": "B", "sector": "B", "weight": 0.5},
                {"symbol": "OLD", "company_name": "OLD", "industry": "O", "sector": "O", "weight": 0.0, "is_active": False},
            ]
        ),
        encoding="utf-8",
    )
    path = tmp_path / "strategy_profile.json"
    path.write_text(
        json.dumps(
            {
                "strategy_id": "fixed_strategy_v1",
                "slug": "fixed-strategy",
                "name": "Fixed Strategy",
                "data": {"universe_json_path": str(universe)},
                "allocation": {"method": "fixed_equal_weight"},
            }
        ),
        encoding="utf-8",
    )

    apply_strategy_profile(path)

    assert config.STRATEGY_PACKAGE_TARGET_HOLDINGS == 2
