from __future__ import annotations

import pandas as pd
import pytest

from app.strategy.selection import allocate_from_ranking, select_with_buffer


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


def test_allocation_accepts_sector_cap_and_safe_asset() -> None:
    result = allocate_from_ranking(
        _ranking(),
        mode="TOP_N_EQUAL",
        top_n=3,
        safe_asset_symbol="GOLDBEES",
        sector_by_symbol={"AAA": "BANKS", "BBB": "BANKS", "CCC": "IT"},
        max_sector_weight=0.08,
    )

    assert result.allocation.safe_asset_symbol == "GOLDBEES"
    assert result.allocation.stock_weights["AAA"] == pytest.approx(0.04)
    assert result.allocation.stock_weights["BBB"] == pytest.approx(0.04)
    assert result.allocation.stock_weights["CCC"] == pytest.approx(0.05)
    assert result.allocation.safe_asset_weight == pytest.approx(0.87)


def test_select_with_buffer_retains_existing_holdings_inside_buffer() -> None:
    ranking = pd.DataFrame(
        [
            {"symbol": "AAA", "score": 1.0, "rank": 1},
            {"symbol": "BBB", "score": 0.9, "rank": 2},
            {"symbol": "CCC", "score": 0.8, "rank": 3},
            {"symbol": "DDD", "score": 0.7, "rank": 4},
            {"symbol": "EEE", "score": 0.6, "rank": 5},
        ]
    )

    selected = select_with_buffer(ranking, top_n=3, previous_symbols={"EEE"}, buffer_pct=100)

    assert selected == ["EEE", "AAA", "BBB"]


def test_select_with_buffer_replaces_existing_holdings_outside_buffer() -> None:
    ranking = pd.DataFrame(
        [
            {"symbol": "AAA", "score": 1.0, "rank": 1},
            {"symbol": "BBB", "score": 0.9, "rank": 2},
            {"symbol": "CCC", "score": 0.8, "rank": 3},
            {"symbol": "DDD", "score": 0.7, "rank": 4},
            {"symbol": "EEE", "score": 0.6, "rank": 5},
        ]
    )

    selected = select_with_buffer(ranking, top_n=3, previous_symbols={"EEE"}, buffer_pct=0)

    assert selected == ["AAA", "BBB", "CCC"]
