from __future__ import annotations

from math import isclose

from app.config import LIQUIDBEES_SYMBOL, MAX_STOCK_WEIGHT
from app.strategy.models import AllocationResult


def allocate_equal_weight_with_cap(
    selected_symbols: list[str],
    max_stock_weight: float = MAX_STOCK_WEIGHT,
    liquidbees_symbol: str = LIQUIDBEES_SYMBOL,
) -> AllocationResult:
    cleaned = [symbol.strip().upper() for symbol in selected_symbols]
    if len(cleaned) != len(set(cleaned)):
        raise ValueError("Duplicate symbols are not allowed in allocation input.")
    if max_stock_weight <= 0 or max_stock_weight > 1:
        raise ValueError("max_stock_weight must be greater than 0 and no more than 1.")

    if not cleaned:
        return AllocationResult({}, liquidbees_symbol, 1.0, 1.0)

    equal_weight = 1.0 / len(cleaned)
    stock_weight = min(equal_weight, max_stock_weight)
    stock_weights = {symbol: stock_weight for symbol in cleaned}
    liquidbees_weight = max(0.0, 1.0 - sum(stock_weights.values()))
    total_weight = sum(stock_weights.values()) + liquidbees_weight

    if any(weight > max_stock_weight for weight in stock_weights.values()):
        raise AssertionError("A stock allocation exceeded the configured maximum.")
    if not isclose(total_weight, 1.0, rel_tol=1e-12, abs_tol=1e-12):
        raise AssertionError("Total allocation must equal 100%.")

    return AllocationResult(stock_weights, liquidbees_symbol, liquidbees_weight, total_weight)

