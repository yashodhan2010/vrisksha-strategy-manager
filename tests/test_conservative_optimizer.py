from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd


def _load_optimizer():
    path = Path("strategies/conservative-dual-momentum/experiments/optimizer.py")
    module_name = "conservative_optimizer_test"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_full_grid_uses_direct_exhaustive_evaluator(monkeypatch) -> None:
    optimizer = _load_optimizer()
    price_pivot = pd.DataFrame({"AAA": [1.0, 1.1]}, index=pd.to_datetime(["2024-01-01", "2024-01-02"]).date)
    monkeypatch.setattr(optimizer, "load_price_pivot", lambda quality=optimizer.DataQualityConfig(): price_pivot)
    monkeypatch.setattr(optimizer, "load_universe", lambda: (["AAA"], {"AAA": "TEST"}))
    monkeypatch.setattr(
        optimizer,
        "search_space",
        lambda momentum_weight_grid=None: {
            "rebalances_per_month": [1],
            "top_n": [35],
            "sector_cap_pct": [20],
            "high_cutoff_pct": [25],
            "momentum_weight": [0.5],
            "buffer_pct": [80],
            "max_stock_weight_pct": [3.0],
        },
    )

    def fake_exhaustive(*args, **kwargs):
        return (
            pd.DataFrame(
                [
                    {
                        "trial": 0,
                        "rebalances_per_month": 1,
                        "top_n": 35,
                        "sector_cap_pct": 20,
                        "high_cutoff_pct": 25,
                        "momentum_weight": 0.5,
                        "buffer_pct": 80,
                        "max_stock_weight_pct": 3.0,
                        "cagr": 0.1,
                        "return_to_drawdown": 1.2,
                    }
                ]
            ),
            {"0": pd.DataFrame()},
        )

    monkeypatch.setattr(optimizer, "run_exhaustive_grid_from_data", fake_exhaustive)

    study, results, curves = optimizer.run_optuna_grid(years=1, objective_metric="return_to_drawdown")

    assert study.study_name.endswith("_exhaustive")
    assert study.best_value == 1.2
    assert results.loc[0, "trial"] == 0
    assert "0" in curves


def test_implementation_drag_metrics_reduce_net_cagr() -> None:
    optimizer = _load_optimizer()
    dates = pd.to_datetime(["2024-01-01", "2024-07-01", "2025-01-01"]).date
    price_pivot = pd.DataFrame({"AAA": [100.0, 120.0, 140.0], "BBB": [100.0, 90.0, 80.0]}, index=dates)
    allocations = [
        (dates[0], dates[1], {"AAA": 1.0}),
        (dates[1], dates[2], {"BBB": 1.0}),
    ]
    curve = pd.DataFrame(
        [
            {"date": dates[0], "nav": 1_000_000.0, "period_return": 0.0},
            {"date": dates[1], "nav": 1_200_000.0, "period_return": 0.2},
            {"date": dates[2], "nav": 1_066_666.67, "period_return": -0.111111},
        ]
    )
    gross = optimizer.performance_metrics(curve)

    metrics = optimizer._estimate_implementation_drag(
        price_pivot,
        allocations,
        gross["final_value"],
        gross["max_drawdown"],
    )

    assert metrics["estimated_implementation_drag"] > 0
    assert metrics["net_final_value"] < gross["final_value"]
    assert metrics["net_cagr"] < gross["cagr"]
