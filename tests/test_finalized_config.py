from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from app import config
from app.optimization.finalized_config import apply_finalized_config, build_finalized_config_from_results, write_finalized_config


def test_build_finalized_config_maps_best_experiment_row(tmp_path: Path) -> None:
    results_path = tmp_path / "trials.csv"
    pd.DataFrame(
        [
            {
                "rank_by_cagr": 2,
                "rebalances_per_month": 1,
                "top_n": 25,
                "sector_cap_pct": 25,
                "high_cutoff_pct": 15,
                "momentum_weight": 0.6,
                "beta_weight": 0.25,
                "volatility_weight": 0.15,
                "buffer_pct": 50,
                "cagr": 0.25,
            },
            {
                "rank_by_cagr": 1,
                "rebalances_per_month": 2,
                "top_n": 40,
                "sector_cap_pct": 0,
                "high_cutoff_pct": 20,
                "momentum_weight": 0.7,
                "beta_weight": 0.15,
                "volatility_weight": 0.15,
                "buffer_pct": 60,
                "max_stock_weight": 0.035,
                "cagr": 0.39,
            },
        ]
    ).to_csv(results_path, index=False)

    payload = build_finalized_config_from_results(results_path)

    params = payload["strategy_parameters"]
    assert params["STRATEGY_TOP_N"] == 40
    assert params["BACKTEST_REBALANCES_PER_MONTH"] == 2
    assert params["MAX_SECTOR_WEIGHT"] == 1.0
    assert params["MAX_STOCK_WEIGHT"] == 0.035
    assert params["HIGH_52W_THRESHOLD"] == 0.8
    assert params["RANKING_MOMENTUM_WEIGHT"] == 0.7
    assert params["BUFFER_PCT"] == 60
    assert payload["source_row"]["rank_by_cagr"] == 1


def test_apply_finalized_config_updates_runtime_config(tmp_path: Path) -> None:
    payload = {
        "strategy_parameters": {
            "BACKTEST_REBALANCES_PER_MONTH": 2,
            "STRATEGY_RANKING_METHOD": "AVERAGE_RANK",
            "RANKING_MOMENTUM_WEIGHT": 0.7,
            "RANKING_BETA_WEIGHT": 0.15,
            "RANKING_VOLATILITY_WEIGHT": 0.15,
            "STRATEGY_ALLOCATION_MODE": "TOP_N_EQUAL",
            "STRATEGY_TOP_N": 40,
            "BUFFER_PCT": 60,
            "MAX_STOCK_WEIGHT": 0.05,
            "MAX_SECTOR_WEIGHT": 1.0,
            "HIGH_52W_THRESHOLD": 0.8,
            "SAFE_ASSET_SYMBOL": "LIQUIDBEES",
        }
    }
    path = write_finalized_config(payload, tmp_path / "final.json")

    apply_finalized_config(path)

    assert config.STRATEGY_TOP_N == 40
    assert config.BACKTEST_REBALANCES_PER_MONTH == 2
    assert config.BUFFER_PCT == 60
    assert config.RANKING_MOMENTUM_WEIGHT == 0.7
    assert json.loads(path.read_text(encoding="utf-8"))["strategy_parameters"]["STRATEGY_TOP_N"] == 40
