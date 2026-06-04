from __future__ import annotations

from dataclasses import dataclass
from math import isclose

import pandas as pd

from app import config
from app.strategy.allocation import allocate_equal_weight_with_cap
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
) -> StrategyAllocation:
    mode = mode or config.STRATEGY_ALLOCATION_MODE
    top_n = top_n if top_n is not None else config.STRATEGY_TOP_N
    dynamic_min_weight = dynamic_min_weight if dynamic_min_weight is not None else config.DYNAMIC_MIN_WEIGHT
    dynamic_max_weight = dynamic_max_weight if dynamic_max_weight is not None else config.DYNAMIC_MAX_WEIGHT
    if top_n <= 0:
        raise ValueError("STRATEGY_TOP_N must be greater than zero.")
    normalized_mode = mode.strip().upper()
    if ranking.empty:
        allocation = allocate_equal_weight_with_cap([])
        return StrategyAllocation(allocation, [], normalized_mode)

    if normalized_mode == "TOP_N_EQUAL":
        selected = ranking.head(top_n)["symbol"].astype(str).str.upper().tolist()
        allocation = allocate_equal_weight_with_cap(selected)
        return StrategyAllocation(allocation, selected, normalized_mode)

    if normalized_mode == "DYNAMIC":
        selected_frame = ranking.head(top_n).copy()
        selected_frame = selected_frame[selected_frame["score"] > 0]
        selected = selected_frame["symbol"].astype(str).str.upper().tolist()
        stock_weights = _dynamic_stock_weights(selected_frame, dynamic_min_weight, dynamic_max_weight)
        liquidbees_weight = max(0.0, 1.0 - sum(stock_weights.values()))
        total_weight = sum(stock_weights.values()) + liquidbees_weight
        if not isclose(total_weight, 1.0, rel_tol=1e-12, abs_tol=1e-12):
            raise AssertionError("Total allocation must equal 100%.")
        allocation = AllocationResult(stock_weights, config.LIQUIDBEES_SYMBOL, liquidbees_weight, total_weight)
        return StrategyAllocation(allocation, selected, normalized_mode)

    raise ValueError("STRATEGY_ALLOCATION_MODE must be TOP_N_EQUAL or DYNAMIC.")


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
