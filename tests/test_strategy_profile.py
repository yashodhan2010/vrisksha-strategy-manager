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
        "STRATEGY_PACKAGE_SHORT_DESCRIPTION",
        "STRATEGY_PACKAGE_CATEGORY_LABELS",
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
                "short_description": "Sample profile.",
                "category_labels": ["Momentum"],
                "ra_entity": "Prathamesh Gupta",
                "universe": "NIFTY 500",
                "benchmark": "NIFTY 500 TRI",
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
    assert config.STRATEGY_PACKAGE_VERSION == "1.2.3"
    assert config.STRATEGY_PUBLIC_METHODOLOGY_PATH == "strategies/sample-strategy/methodology.md"
    assert config.STRATEGY_INTERNAL_METHODOLOGY_PATH == "strategies/sample-strategy/methodology_internal.md"
    assert config.OPTIMIZATION_RESULTS_PATH == "data/output/sample_trials.csv"
    assert config.FINALIZED_STRATEGY_CONFIG_PATH == "data/output/finalized/sample.json"
    assert config.OPTIMIZATION_ENGINE_PATH == "strategies/sample-strategy/experiments/optimizer.py"
    assert config.OPTIMIZATION_ENGINE_MODULE == "sample.optimizer"
