from __future__ import annotations

from datetime import date

import pytest

from app.automation.schedule import is_rebalance_day, parse_target_days, rebalance_dates_for_month


def test_rebalance_dates_roll_weekend_targets_forward() -> None:
    assert rebalance_dates_for_month(2024, 6, [1, 15]) == [
        date(2024, 6, 3),
        date(2024, 6, 17),
    ]


def test_is_rebalance_day_uses_configured_targets() -> None:
    assert is_rebalance_day(date(2024, 6, 17), [1, 15])
    assert not is_rebalance_day(date(2024, 6, 18), [1, 15])


def test_parse_target_days_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="1 to 31"):
        parse_target_days("1,32")
