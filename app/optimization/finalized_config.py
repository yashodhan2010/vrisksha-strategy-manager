from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from app import config


def build_finalized_config_from_results(
    results_path: str | Path = config.OPTIMIZATION_RESULTS_PATH,
    objective: str = "cagr",
    rank_column: str = "rank_by_cagr",
    row_index: int | None = None,
) -> dict[str, Any]:
    path = Path(results_path)
    if not path.exists():
        raise FileNotFoundError(f"Optimization results file not found: {path}")
    frame = _read_results(path)
    if frame.empty:
        raise ValueError(f"Optimization results file is empty: {path}")
    row = _select_row(frame, objective, rank_column, row_index)
    parameters = _parameters_from_row(row)
    return {
        "schema_version": "1.0.0",
        "strategy_id": config.STRATEGY_PACKAGE_ID,
        "strategy_slug": config.STRATEGY_PACKAGE_SLUG,
        "strategy_name": config.STRATEGY_PACKAGE_NAME,
        "source_results_path": str(path),
        "selected_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "selection": {
            "objective": objective,
            "rank_column": rank_column if rank_column in frame.columns else None,
            "row_index": int(row.name) if row.name is not None else None,
        },
        "source_row": _clean_mapping(row.to_dict()),
        "strategy_parameters": parameters,
        "engine_notes": [
            "This config is intended to be applied programmatically before running the finalized backtest.",
            "buffer_pct is applied as a holding-retention rank buffer around the target top-N selection.",
        ],
    }


def write_finalized_config(payload: dict[str, Any], output_path: str | Path = config.FINALIZED_STRATEGY_CONFIG_PATH) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def apply_finalized_config(config_path: str | Path = config.FINALIZED_STRATEGY_CONFIG_PATH) -> dict[str, Any]:
    path = Path(config_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    parameters = payload.get("strategy_parameters") or {}
    if not parameters:
        raise ValueError(f"No strategy_parameters found in finalized config: {path}")
    _apply_parameters(parameters)
    return payload


def _read_results(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return pd.DataFrame(payload)
        if isinstance(payload, dict) and "trials" in payload:
            return pd.DataFrame(payload["trials"])
    raise ValueError(f"Unsupported optimization results format: {path.suffix}")


def _select_row(frame: pd.DataFrame, objective: str, rank_column: str, row_index: int | None) -> pd.Series:
    if row_index is not None:
        if row_index < 0 or row_index >= len(frame):
            raise ValueError(f"row_index {row_index} is outside the results range.")
        return frame.iloc[row_index]
    if rank_column in frame.columns:
        return frame.sort_values(rank_column, ascending=True).iloc[0]
    if objective in frame.columns:
        return frame.sort_values(objective, ascending=False).iloc[0]
    raise ValueError(f"Neither rank column '{rank_column}' nor objective '{objective}' exists in optimization results.")


def _parameters_from_row(row: pd.Series) -> dict[str, Any]:
    sector_cap_pct = _optional_float(row, "sector_cap_pct")
    high_cutoff_pct = _optional_float(row, "high_cutoff_pct")
    max_stock_weight = _optional_float(row, "max_stock_weight")
    max_stock_weight_pct = _optional_float(row, "max_stock_weight_pct")
    max_sector_weight = 1.0 if sector_cap_pct in (None, 0.0) else sector_cap_pct / 100.0
    high_52w_threshold = 0.80 if high_cutoff_pct is None else (100.0 - high_cutoff_pct) / 100.0
    if max_stock_weight is None and max_stock_weight_pct is not None:
        max_stock_weight = max_stock_weight_pct / 100.0
    return {
        "BACKTEST_REBALANCES_PER_MONTH": int(_required_float(row, "rebalances_per_month")),
        "STRATEGY_RANKING_METHOD": "AVERAGE_RANK",
        "RANKING_MOMENTUM_WEIGHT": _required_float(row, "momentum_weight"),
        "RANKING_BETA_WEIGHT": _required_float(row, "beta_weight"),
        "RANKING_VOLATILITY_WEIGHT": _required_float(row, "volatility_weight"),
        "STRATEGY_ALLOCATION_MODE": "TOP_N_EQUAL",
        "STRATEGY_TOP_N": int(_required_float(row, "top_n")),
        "MAX_STOCK_WEIGHT": max_stock_weight or config.MAX_STOCK_WEIGHT,
        "MAX_SECTOR_WEIGHT": max_sector_weight,
        "HIGH_52W_THRESHOLD": high_52w_threshold,
        "SAFE_ASSET_SYMBOL": config.SAFE_ASSET_SYMBOL,
        "BUFFER_PCT": _optional_float(row, "buffer_pct"),
    }


def _apply_parameters(parameters: dict[str, Any]) -> None:
    config.BACKTEST_REBALANCES_PER_MONTH = int(parameters["BACKTEST_REBALANCES_PER_MONTH"])
    config.STRATEGY_RANKING_METHOD = str(parameters["STRATEGY_RANKING_METHOD"]).strip().upper()
    config.RANKING_MOMENTUM_WEIGHT = float(parameters["RANKING_MOMENTUM_WEIGHT"])
    config.RANKING_BETA_WEIGHT = float(parameters["RANKING_BETA_WEIGHT"])
    config.RANKING_VOLATILITY_WEIGHT = float(parameters["RANKING_VOLATILITY_WEIGHT"])
    config.STRATEGY_ALLOCATION_MODE = str(parameters["STRATEGY_ALLOCATION_MODE"]).strip().upper()
    config.STRATEGY_TOP_N = int(parameters["STRATEGY_TOP_N"])
    config.BUFFER_PCT = float(parameters.get("BUFFER_PCT") or 0.0)
    config.MAX_STOCK_WEIGHT = float(parameters["MAX_STOCK_WEIGHT"])
    config.MAX_SECTOR_WEIGHT = float(parameters["MAX_SECTOR_WEIGHT"])
    config.HIGH_52W_THRESHOLD = float(parameters["HIGH_52W_THRESHOLD"])
    config.SAFE_ASSET_SYMBOL = str(parameters["SAFE_ASSET_SYMBOL"]).strip().upper()


def _required_float(row: pd.Series, key: str) -> float:
    if key not in row or pd.isna(row[key]):
        raise ValueError(f"Optimization result is missing required parameter column: {key}")
    return float(row[key])


def _optional_float(row: pd.Series, key: str) -> float | None:
    if key not in row or pd.isna(row[key]):
        return None
    return float(row[key])


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
