from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import pytest

from app.automation.schedule import is_rebalance_day, parse_target_days, rebalance_dates_for_month
from app.cli import _target_days_for_strategy_profile


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


def test_auto_daily_target_days_prefer_strategy_profile_schedule(tmp_path: Path) -> None:
    profile = tmp_path / "strategy_profile.json"
    profile.write_text(
        json.dumps(
            {
                "strategy_id": "test_strategy_v1",
                "slug": "test-strategy",
                "name": "Test Strategy",
                "rebalance_schedule": {
                    "type": "monthly_target_days",
                    "target_days": [11, 21],
                },
            }
        ),
        encoding="utf-8",
    )

    assert _target_days_for_strategy_profile(str(profile)) == [11, 21]


def test_auto_daily_target_days_require_strategy_profile_schedule(tmp_path: Path) -> None:
    profile = tmp_path / "strategy_profile.json"
    profile.write_text(
        json.dumps(
            {
                "strategy_id": "test_strategy_v1",
                "slug": "test-strategy",
                "name": "Test Strategy",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="rebalance_schedule.target_days"):
        _target_days_for_strategy_profile(str(profile))
