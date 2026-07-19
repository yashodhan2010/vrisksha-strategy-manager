from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from app import config
from app.storage.database import initialize_database
from app.storage.market_data_repository import count_price_rows


@dataclass(frozen=True)
class OptimizationRunResult:
    results_path: Path
    rows: int
    best_row: dict[str, Any]


def run_average_rank_buffer_optimization(
    years: int = 10,
    objective: str = "cagr",
    n_trials: int | None = None,
    seed: int = 42,
    results_output_path: str | Path = config.OPTIMIZATION_RESULTS_PATH,
    experiment_output_dir: str | Path | None = None,
    database_path: str | Path = config.DATABASE_PATH,
    universe_json_path: str | Path = config.UNIVERSE_JSON_PATH,
) -> OptimizationRunResult:
    if years <= 0:
        raise ValueError("--years must be greater than zero.")
    if n_trials is not None and n_trials <= 0:
        raise ValueError("--n-trials must be greater than zero when supplied.")

    initialize_database(database_path)
    price_rows = count_price_rows(database_path)
    if price_rows == 0:
        raise ValueError(
            f"No market_prices rows found in {database_path}. "
            "Run sync-universe and fetch-history/build-finalized-package history refresh before refreshing parameters."
        )

    experiment = _load_average_rank_experiment()
    _bind_experiment_paths(experiment, Path(database_path), Path(universe_json_path))
    if experiment_output_dir is not None:
        experiment.OUTPUT_DIR = Path(experiment_output_dir)

    _, results, _ = experiment.run_optuna_grid(
        years=years,
        objective_metric=objective,
        n_trials=n_trials,
        seed=seed,
    )
    if results.empty:
        raise ValueError("Optimization produced no result rows.")

    output = _with_rank_columns(results, years)
    output_path = Path(results_output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(output_path, index=False)
    best_row = output.sort_values("rank_by_cagr", ascending=True).iloc[0].to_dict()
    return OptimizationRunResult(output_path, len(output), _clean_mapping(best_row))


def _load_average_rank_experiment() -> Any:
    try:
        return importlib.import_module("experiments.average_rank_buffer_grid")
    except ModuleNotFoundError as exc:
        raise ImportError(
            "Average-rank/buffer experiment runner was not found. "
            "Keep the local experiments/average_rank_buffer_grid.py folder available, "
            "or port that strategy's optimizer into app/optimization before running this command."
        ) from exc


def _bind_experiment_paths(experiment: Any, database_path: Path, universe_json_path: Path) -> None:
    experiment.DATABASE_PATH = database_path
    experiment.UNIVERSE_JSON_PATH = universe_json_path
    if not hasattr(experiment, "load_price_pivot") or not hasattr(experiment, "load_universe"):
        return
    original_load_price_pivot = experiment.load_price_pivot
    original_load_universe = experiment.load_universe

    def load_price_pivot_with_active_paths(*args: Any, **kwargs: Any) -> pd.DataFrame:
        if len(args) < 1:
            kwargs.setdefault("database_path", database_path)
        if len(args) < 2:
            kwargs.setdefault("universe_json_path", universe_json_path)
        return original_load_price_pivot(*args, **kwargs)

    def load_universe_with_active_path(*args: Any, **kwargs: Any) -> Any:
        if len(args) < 1:
            kwargs.setdefault("universe_json_path", universe_json_path)
        return original_load_universe(*args, **kwargs)

    experiment.load_price_pivot = load_price_pivot_with_active_paths
    experiment.load_universe = load_universe_with_active_path


def _with_rank_columns(results: pd.DataFrame, years: int) -> pd.DataFrame:
    output = results.copy()
    if "years" not in output.columns:
        output.insert(0, "years", years)
    output = output.sort_values("cagr", ascending=False).reset_index(drop=True)
    if "rank_by_cagr" in output.columns:
        output = output.drop(columns=["rank_by_cagr"])
    output.insert(0, "rank_by_cagr", range(1, len(output) + 1))
    return output


def _clean_mapping(payload: dict[str, Any]) -> dict[str, Any]:
    clean = {}
    for key, value in payload.items():
        if pd.isna(value):
            clean[key] = None
        elif hasattr(value, "item"):
            clean[key] = value.item()
        else:
            clean[key] = value
    return clean
