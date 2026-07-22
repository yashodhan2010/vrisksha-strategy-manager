from __future__ import annotations

import importlib
import importlib.util
import sys
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
    engine_module: str | None = None,
    engine_path: str | Path | None = None,
    search_space: dict[str, list[int | float]] | None = None,
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

    experiment = _load_average_rank_experiment(engine_module=engine_module, engine_path=engine_path)
    _bind_experiment_paths(experiment, Path(database_path), Path(universe_json_path))
    if search_space is not None:
        _bind_search_space(experiment, search_space)
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

    output = _with_rank_columns(results, years, objective)
    output_path = Path(results_output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(output_path, index=False)
    rank_column = f"rank_by_{objective}"
    best_row = output.sort_values(rank_column if rank_column in output.columns else "rank_by_cagr", ascending=True).iloc[0].to_dict()
    return OptimizationRunResult(output_path, len(output), _clean_mapping(best_row))


def _load_average_rank_experiment(engine_module: str | None = None, engine_path: str | Path | None = None) -> Any:
    engine_path = engine_path if engine_path is not None else (None if engine_module else config.OPTIMIZATION_ENGINE_PATH)
    if engine_path:
        path = Path(engine_path)
        if not path.exists():
            raise FileNotFoundError(f"Optimization engine file not found: {path}")
        module_name = f"_strategy_optimizer_{path.stem}_{abs(hash(path.resolve()))}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load optimization engine from: {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    module_name = engine_module or config.OPTIMIZATION_ENGINE_MODULE
    if not module_name:
        raise ImportError("No optimization engine_path or engine_module is configured.")
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        raise ImportError(
            "Average-rank/buffer experiment runner was not found. "
            f"Configured module '{module_name}' could not be imported. "
            "Set optimization.engine_path in the strategy profile, or provide an importable optimization.engine_module."
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


def _bind_search_space(experiment: Any, search_space: dict[str, list[int | float]]) -> None:
    expected = {
        "rebalances_per_month",
        "top_n",
        "sector_cap_pct",
        "high_cutoff_pct",
        "momentum_weight",
        "buffer_pct",
    }
    missing = sorted(expected.difference(search_space))
    if missing:
        raise ValueError(f"Optimization search_space is missing required keys: {', '.join(missing)}")
    for key, values in search_space.items():
        if not isinstance(values, list) or not values:
            raise ValueError(f"Optimization search_space.{key} must be a non-empty list.")

    def configured_search_space(momentum_weight_grid: Any = None) -> dict[str, list[int | float]]:
        if momentum_weight_grid is None:
            return search_space
        output = dict(search_space)
        output["momentum_weight"] = [float(value) for value in momentum_weight_grid]
        return output

    experiment.search_space = configured_search_space


def _with_rank_columns(results: pd.DataFrame, years: int, objective: str = "cagr") -> pd.DataFrame:
    output = results.copy()
    if "lowest_drawdown_cagr_gt_20_score" not in output.columns and {"cagr", "absolute_drawdown"}.issubset(output.columns):
        eligible = output["cagr"] >= 0.20
        output["lowest_drawdown_cagr_gt_20_eligible"] = eligible
        output["lowest_drawdown_cagr_gt_20_score"] = output["absolute_drawdown"].where(eligible, 1e9) * -1.0
    if "years" not in output.columns:
        output.insert(0, "years", years)
    if "rank_by_cagr" in output.columns:
        output = output.drop(columns=["rank_by_cagr"])
    output = output.sort_values("cagr", ascending=False).reset_index(drop=True)
    output.insert(0, "rank_by_cagr", range(1, len(output) + 1))
    rank_column = f"rank_by_{objective}"
    if objective != "cagr" and objective in output.columns:
        if rank_column in output.columns:
            output = output.drop(columns=[rank_column])
        output = output.sort_values(objective, ascending=False).reset_index(drop=True)
        output.insert(0, rank_column, range(1, len(output) + 1))
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
