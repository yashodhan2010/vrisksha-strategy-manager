from __future__ import annotations

import sys
import types
from pathlib import Path

import pandas as pd
import pytest

from app.optimization.average_rank_buffer import run_average_rank_buffer_optimization
from app.storage.database import initialize_database, get_connection


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

    db = tmp_path / "research.db"
    initialize_database(db)
    with get_connection(db) as connection:
        connection.execute(
            """
            INSERT INTO market_prices (
                symbol, price_date, open, high, low, close, adjusted_close, volume, source, fetched_at
            )
            VALUES ('AAA', '2024-01-01', 1, 1, 1, 1, 1, 1, 'TEST', 'now')
            """
        )
    output = tmp_path / "results.csv"
    result = run_average_rank_buffer_optimization(
        years=10,
        objective="cagr",
        n_trials=2,
        seed=7,
        results_output_path=output,
        experiment_output_dir=tmp_path / "experiment-output",
        engine_module="experiments.average_rank_buffer_grid",
        database_path=db,
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


def test_run_average_rank_buffer_optimization_requires_market_prices(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="No market_prices rows found"):
        run_average_rank_buffer_optimization(
            results_output_path=tmp_path / "results.csv",
            engine_module="experiments.average_rank_buffer_grid",
            database_path=tmp_path / "empty.db",
            universe_json_path=tmp_path / "universe.json",
        )


def test_run_average_rank_buffer_optimization_loads_engine_path_and_search_space(tmp_path: Path) -> None:
    engine_path = tmp_path / "optimizer.py"
    engine_path.write_text(
        """
from pathlib import Path

DATABASE_PATH = None
UNIVERSE_JSON_PATH = None
OUTPUT_DIR = None

def search_space(momentum_weight_grid=None):
    return {"top_n": [1]}

def run_optuna_grid(years, objective_metric, n_trials, seed):
    space = search_space()
    assert space["top_n"] == [25]
    assert space["buffer_pct"] == [60]
    import pandas as pd
    return object(), pd.DataFrame([
        {
            "trial": 1,
            "rebalances_per_month": 1,
            "top_n": 25,
            "sector_cap_pct": 0,
            "high_cutoff_pct": 20,
            "momentum_weight": 0.6,
            "beta_weight": 0.2,
            "volatility_weight": 0.2,
            "buffer_pct": 60,
            "cagr": 0.18,
        }
    ]), {}
""",
        encoding="utf-8",
    )
    db = tmp_path / "research.db"
    initialize_database(db)
    with get_connection(db) as connection:
        connection.execute(
            """
            INSERT INTO market_prices (
                symbol, price_date, open, high, low, close, adjusted_close, volume, source, fetched_at
            )
            VALUES ('AAA', '2024-01-01', 1, 1, 1, 1, 1, 1, 'TEST', 'now')
            """
        )

    output = tmp_path / "results.csv"
    result = run_average_rank_buffer_optimization(
        results_output_path=output,
        engine_path=engine_path,
        search_space={
            "rebalances_per_month": [1],
            "top_n": [25],
            "sector_cap_pct": [0],
            "high_cutoff_pct": [20],
            "momentum_weight": [0.6],
            "buffer_pct": [60],
        },
        database_path=db,
        universe_json_path=tmp_path / "universe.json",
    )

    assert result.rows == 1
    assert result.best_row["top_n"] == 25
