from __future__ import annotations

from dataclasses import dataclass
from math import ceil, isclose

import pandas as pd

from app import config
from app.strategy.allocation import allocate_equal_weight_with_cap, cap_sector_weights
from app.strategy.models import AllocationResult


@dataclass(frozen=True)
class StrategyAllocation:
    allocation: AllocationResult
    selected_symbols: list[str]
    mode: str


def allocate_from_ranking(
    ranking: pd.DataFrame,
    mode: str | None = None,
    top_n: int | None = None,
    dynamic_min_weight: float | None = None,
    dynamic_max_weight: float | None = None,
    safe_asset_symbol: str | None = None,
    max_sector_weight: float | None = None,
    sector_by_symbol: dict[str, str] | None = None,
    previous_symbols: set[str] | None = None,
    buffer_pct: float | None = None,
) -> StrategyAllocation:
    mode = mode or config.STRATEGY_ALLOCATION_MODE
    top_n = top_n if top_n is not None else config.STRATEGY_TOP_N
    dynamic_min_weight = dynamic_min_weight if dynamic_min_weight is not None else config.DYNAMIC_MIN_WEIGHT
    dynamic_max_weight = dynamic_max_weight if dynamic_max_weight is not None else config.DYNAMIC_MAX_WEIGHT
    safe_asset_symbol = safe_asset_symbol or config.SAFE_ASSET_SYMBOL
    max_sector_weight = max_sector_weight if max_sector_weight is not None else config.MAX_SECTOR_WEIGHT
    sector_by_symbol = sector_by_symbol or _sector_map_from_ranking(ranking)
    previous_symbols = {symbol.strip().upper() for symbol in (previous_symbols or set())}
    buffer_pct = buffer_pct if buffer_pct is not None else config.BUFFER_PCT
    if top_n <= 0:
        raise ValueError("STRATEGY_TOP_N must be greater than zero.")
    if buffer_pct < 0:
        raise ValueError("BUFFER_PCT cannot be negative.")
    normalized_mode = mode.strip().upper()
    if ranking.empty:
        allocation = allocate_equal_weight_with_cap([], safe_asset_symbol=safe_asset_symbol)
        return StrategyAllocation(allocation, [], normalized_mode)

    if normalized_mode == "TOP_N_EQUAL":
        selected = select_with_buffer(ranking, top_n, previous_symbols, buffer_pct)
        allocation = allocate_equal_weight_with_cap(
            selected,
            safe_asset_symbol=safe_asset_symbol,
            sector_by_symbol=sector_by_symbol,
            max_sector_weight=max_sector_weight,
        )
        return StrategyAllocation(allocation, selected, normalized_mode)

    if normalized_mode == "DYNAMIC":
        selected_frame = ranking.head(top_n).copy()
        selected_frame = selected_frame[selected_frame["score"] > 0]
        selected = selected_frame["symbol"].astype(str).str.upper().tolist()
        stock_weights = _dynamic_stock_weights(selected_frame, dynamic_min_weight, dynamic_max_weight)
        stock_weights = cap_sector_weights(stock_weights, sector_by_symbol, max_sector_weight)
        safe_asset_weight = max(0.0, 1.0 - sum(stock_weights.values()))
        total_weight = sum(stock_weights.values()) + safe_asset_weight
        if not isclose(total_weight, 1.0, rel_tol=1e-12, abs_tol=1e-12):
            raise AssertionError("Total allocation must equal 100%.")
        allocation = AllocationResult(stock_weights, safe_asset_symbol, safe_asset_weight, total_weight)
        return StrategyAllocation(allocation, selected, normalized_mode)

    raise ValueError("STRATEGY_ALLOCATION_MODE must be TOP_N_EQUAL or DYNAMIC.")


def select_with_buffer(
    ranking: pd.DataFrame,
    top_n: int,
    previous_symbols: set[str] | None = None,
    buffer_pct: float = 0.0,
) -> list[str]:
    if top_n <= 0:
        raise ValueError("top_n must be greater than zero.")
    if buffer_pct < 0:
        raise ValueError("buffer_pct cannot be negative.")
    if ranking.empty:
        return []
    ranked = ranking.copy()
    ranked["symbol"] = ranked["symbol"].astype(str).str.upper()
    if "rank" not in ranked.columns:
        ranked["rank"] = range(1, len(ranked) + 1)
    ranked = ranked.sort_values("rank", ascending=True)
    previous_symbols = {symbol.strip().upper() for symbol in (previous_symbols or set())}
    buffer_rank = max(top_n, ceil(top_n * (1.0 + buffer_pct / 100.0)))

    retained = ranked[(ranked["symbol"].isin(previous_symbols)) & (ranked["rank"] <= buffer_rank)]
    selected = retained.sort_values("rank", ascending=True)["symbol"].head(top_n).tolist()
    selected_set = set(selected)
    for symbol in ranked["symbol"].head(top_n).tolist():
        if len(selected) >= top_n:
            break
        if symbol not in selected_set:
            selected.append(symbol)
            selected_set.add(symbol)
    return selected


def _sector_map_from_ranking(ranking: pd.DataFrame) -> dict[str, str]:
    if ranking.empty or "sector" not in ranking.columns:
        return {}
    return dict(zip(ranking["symbol"].astype(str).str.upper(), ranking["sector"].astype(str), strict=False))


def _dynamic_stock_weights(ranking: pd.DataFrame, min_weight: float, max_weight: float) -> dict[str, float]:
    if min_weight < 0 or max_weight <= 0 or min_weight > max_weight:
        raise ValueError("DYNAMIC weights must satisfy 0 <= min <= max.")
    if ranking.empty:
        return {}

    selected = ranking["symbol"].astype(str).str.upper().tolist()
    scores = [float(value) for value in ranking["score"].tolist()]
    count = len(selected)
    if min_weight * count > 1.0 + 1e-12:
        raise ValueError("DYNAMIC_MIN_WEIGHT * selected_count cannot exceed 1.")
    if sum(scores) <= 0:
        return {}

    investable = min(1.0, max_weight * count)
    base_total = min_weight * count
    if base_total >= investable - 1e-12:
        return {symbol: min_weight for symbol in selected if min_weight > 0}

    variable_total = max(0.0, investable - base_total)
    raw = [min_weight + (score / sum(scores)) * variable_total for score in scores]
    weights = _cap_and_redistribute(raw, min_weight, max_weight, investable)
    return {symbol: weight for symbol, weight in zip(selected, weights, strict=True) if weight > 0}


def _cap_and_redistribute(raw: list[float], min_weight: float, max_weight: float, target_total: float) -> list[float]:
    weights = [min(max(value, min_weight), max_weight) for value in raw]
    for _ in range(20):
        leftover = target_total - sum(weights)
        if abs(leftover) < 1e-10:
            break
        if leftover <= 0:
            break
        capacities = [max_weight - weight for weight in weights]
        capacity_total = sum(value for value in capacities if value > 1e-10)
        if capacity_total <= 0:
            break
        weights = [
            min(max_weight, weight + leftover * capacity / capacity_total) if capacity > 1e-10 else weight
            for weight, capacity in zip(weights, capacities, strict=True)
        ]
    return weights
