from __future__ import annotations

from math import isclose

from app.config import MAX_SECTOR_WEIGHT, MAX_STOCK_WEIGHT, SAFE_ASSET_SYMBOL
from app.strategy.models import AllocationResult


def allocate_equal_weight_with_cap(
    selected_symbols: list[str],
    max_stock_weight: float = MAX_STOCK_WEIGHT,
    safe_asset_symbol: str = SAFE_ASSET_SYMBOL,
    sector_by_symbol: dict[str, str] | None = None,
    max_sector_weight: float = MAX_SECTOR_WEIGHT,
) -> AllocationResult:
    cleaned = [symbol.strip().upper() for symbol in selected_symbols]
    if len(cleaned) != len(set(cleaned)):
        raise ValueError("Duplicate symbols are not allowed in allocation input.")
    if max_stock_weight <= 0 or max_stock_weight > 1:
        raise ValueError("max_stock_weight must be greater than 0 and no more than 1.")
    if max_sector_weight <= 0 or max_sector_weight > 1:
        raise ValueError("max_sector_weight must be greater than 0 and no more than 1.")

    if not cleaned:
        return AllocationResult({}, safe_asset_symbol, 1.0, 1.0)

    equal_weight = 1.0 / len(cleaned)
    stock_weight = min(equal_weight, max_stock_weight)
    stock_weights = {symbol: stock_weight for symbol in cleaned}
    stock_weights = cap_sector_weights(stock_weights, sector_by_symbol or {}, max_sector_weight)
    safe_asset_weight = max(0.0, 1.0 - sum(stock_weights.values()))
    total_weight = sum(stock_weights.values()) + safe_asset_weight

    if any(weight > max_stock_weight for weight in stock_weights.values()):
        raise AssertionError("A stock allocation exceeded the configured maximum.")
    if not isclose(total_weight, 1.0, rel_tol=1e-12, abs_tol=1e-12):
        raise AssertionError("Total allocation must equal 100%.")

    return AllocationResult(stock_weights, safe_asset_symbol, safe_asset_weight, total_weight)


def cap_sector_weights(
    stock_weights: dict[str, float],
    sector_by_symbol: dict[str, str],
    max_sector_weight: float = MAX_SECTOR_WEIGHT,
) -> dict[str, float]:
    if max_sector_weight <= 0 or max_sector_weight > 1:
        raise ValueError("max_sector_weight must be greater than 0 and no more than 1.")
    if not stock_weights or max_sector_weight >= 1:
        return dict(stock_weights)

    normalized_sectors = {symbol.upper(): (sector or "UNKNOWN").strip().upper() for symbol, sector in sector_by_symbol.items()}
    sector_totals: dict[str, float] = {}
    for symbol, weight in stock_weights.items():
        sector = normalized_sectors.get(symbol.upper(), "UNKNOWN")
        sector_totals[sector] = sector_totals.get(sector, 0.0) + weight

    capped: dict[str, float] = {}
    for symbol, weight in stock_weights.items():
        sector = normalized_sectors.get(symbol.upper(), "UNKNOWN")
        sector_total = sector_totals[sector]
        if sector_total > max_sector_weight:
            capped[symbol] = weight * (max_sector_weight / sector_total)
        else:
            capped[symbol] = weight
    return capped
