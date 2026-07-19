from __future__ import annotations

import sys
import types
from pathlib import Path

import pandas as pd

from app.optimization.average_rank_buffer import run_average_rank_buffer_optimization


def test_run_average_rank_buffer_optimization_writes_ranked_results(monkeypatch, tmp_path: Path) -> None:
    experiment = types.ModuleType("experiments.average_rank_buffer_grid")
    experiment.DATABASE_PATH = None
    experiment.UNIVERSE_JSON_PATH = None
    experiment.OUTPUT_DIR = None

    def run_optuna_grid(years: int, objective_metric: str, n_trials: int | None, seed: int):
        assert years == 10
        assert objective_metric == "cagr"
        assert n_trials == 2
        assert seed == 7
        return (
            object(),
            pd.DataFrame(
                [
                    {
                        "trial": 1,
                        "rebalances_per_month": 1,
                        "top_n": 20,
                        "sector_cap_pct": 0,
                        "high_cutoff_pct": 20,
                        "momentum_weight": 0.6,
                        "beta_weight": 0.2,
                        "volatility_weight": 0.2,
                        "buffer_pct": 40,
                        "cagr": 0.12,
                    },
                    {
                        "trial": 2,
                        "rebalances_per_month": 2,
                        "top_n": 40,
                        "sector_cap_pct": 0,
                        "high_cutoff_pct": 20,
                        "momentum_weight": 0.7,
                        "beta_weight": 0.15,
                        "volatility_weight": 0.15,
                        "buffer_pct": 60,
                        "cagr": 0.18,
                    },
                ]
            ),
            {},
        )

    experiment.run_optuna_grid = run_optuna_grid
    parent = types.ModuleType("experiments")
    monkeypatch.setitem(sys.modules, "experiments", parent)
    monkeypatch.setitem(sys.modules, "experiments.average_rank_buffer_grid", experiment)

    output = tmp_path / "results.csv"
    result = run_average_rank_buffer_optimization(
        years=10,
        objective="cagr",
        n_trials=2,
        seed=7,
        results_output_path=output,
        experiment_output_dir=tmp_path / "experiment-output",
        database_path=tmp_path / "research.db",
        universe_json_path=tmp_path / "universe.json",
    )

    rows = pd.read_csv(output)
    assert result.results_path == output
    assert result.rows == 2
    assert result.best_row["trial"] == 2
    assert rows.loc[0, "rank_by_cagr"] == 1
    assert rows.loc[0, "cagr"] == 0.18
    assert experiment.DATABASE_PATH == tmp_path / "research.db"
    assert experiment.UNIVERSE_JSON_PATH == tmp_path / "universe.json"
    assert experiment.OUTPUT_DIR == tmp_path / "experiment-output"
