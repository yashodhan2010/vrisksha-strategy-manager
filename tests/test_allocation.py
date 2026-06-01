from __future__ import annotations

from math import isclose

import pytest

from app.strategy.allocation import allocate_equal_weight_with_cap


def _symbols(count: int) -> list[str]:
    return [f"STOCK{i}" for i in range(count)]


@pytest.mark.parametrize(
    ("count", "expected_stock_weight", "expected_liquidbees"),
    [(50, 0.02, 0.0), (25, 0.04, 0.0), (20, 0.05, 0.0), (15, 0.05, 0.25)],
)
def test_allocation_examples(count: int, expected_stock_weight: float, expected_liquidbees: float) -> None:
    result = allocate_equal_weight_with_cap(_symbols(count))
    assert all(isclose(weight, expected_stock_weight) for weight in result.stock_weights.values())
    assert isclose(result.liquidbees_weight, expected_liquidbees)
    assert isclose(result.total_weight, 1.0)


def test_no_stocks_allocates_all_to_liquidbees() -> None:
    result = allocate_equal_weight_with_cap([])
    assert result.stock_weights == {}
    assert result.liquidbees_weight == 1.0


def test_duplicate_stocks_rejected() -> None:
    with pytest.raises(ValueError, match="Duplicate"):
        allocate_equal_weight_with_cap(["ABC", "abc"])


def test_total_allocation_equals_100_percent() -> None:
    result = allocate_equal_weight_with_cap(_symbols(17))
    assert isclose(sum(result.stock_weights.values()) + result.liquidbees_weight, 1.0)
    assert max(result.stock_weights.values()) <= 0.05

