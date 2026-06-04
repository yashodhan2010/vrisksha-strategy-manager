from __future__ import annotations

import pandas as pd
import pytest

from app.strategy.selection import allocate_from_ranking


def _ranking() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"symbol": "AAA", "score": 0.30, "rank": 1},
            {"symbol": "BBB", "score": 0.20, "rank": 2},
            {"symbol": "CCC", "score": 0.10, "rank": 3},
        ]
    )


def test_top_n_equal_selects_top_n_with_equal_cap() -> None:
    result = allocate_from_ranking(_ranking(), mode="TOP_N_EQUAL", top_n=2)

    assert result.selected_symbols == ["AAA", "BBB"]
    assert result.allocation.stock_weights == {"AAA": 0.05, "BBB": 0.05}
    assert result.allocation.liquidbees_weight == pytest.approx(0.90)


def test_dynamic_weights_tilt_toward_higher_scores() -> None:
    result = allocate_from_ranking(_ranking(), mode="DYNAMIC", top_n=3, dynamic_min_weight=0.01, dynamic_max_weight=0.40)

    weights = result.allocation.stock_weights
    assert weights["AAA"] > weights["BBB"] > weights["CCC"]
    assert all(0.01 <= weight <= 0.40 for weight in weights.values())
    assert result.allocation.liquidbees_weight == pytest.approx(1.0 - sum(weights.values()))


def test_unknown_allocation_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="STRATEGY_ALLOCATION_MODE"):
        allocate_from_ranking(_ranking(), mode="NOPE", top_n=2)
