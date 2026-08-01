from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from app.automation.strategy_scheduler import due_rebalance_reminders, format_rebalance_reminder


def _write_registry(root: Path, target_days: list[int]) -> Path:
    strategy_dir = root / "strategies" / "dual-momentum"
    strategy_dir.mkdir(parents=True)
    profile = strategy_dir / "strategy_profile.json"
    profile.write_text(
        json.dumps(
            {
                "strategy_id": "dual_momentum_test_v1",
                "slug": "dual-momentum",
                "name": "Dual Momentum",
                "rebalance_schedule": {
                    "type": "monthly_target_days",
                    "target_days": target_days,
                    "timezone": "Asia/Kolkata",
                },
            }
        ),
        encoding="utf-8",
    )
    registry = root / "strategies" / "registry.json"
    registry.write_text(json.dumps({"strategies": [str(profile)]}), encoding="utf-8")
    return registry


def test_due_rebalance_reminders_include_day_before(tmp_path: Path) -> None:
    registry = _write_registry(tmp_path, [11, 21])

    reminders = due_rebalance_reminders(registry, as_of_date=date(2026, 8, 10))

    assert len(reminders) == 1
    assert reminders[0].reminder_type == "due_tomorrow"
    assert reminders[0].due_date == date(2026, 8, 11)
    assert "tomorrow" in format_rebalance_reminder(reminders[0])


def test_due_rebalance_reminders_include_rebalance_day(tmp_path: Path) -> None:
    registry = _write_registry(tmp_path, [11, 21])

    reminders = due_rebalance_reminders(registry, as_of_date=date(2026, 8, 11))

    assert len(reminders) == 1
    assert reminders[0].reminder_type == "due_today"
    assert reminders[0].due_date == date(2026, 8, 11)
    assert "today" in format_rebalance_reminder(reminders[0])


def test_due_rebalance_reminders_skip_other_days(tmp_path: Path) -> None:
    registry = _write_registry(tmp_path, [11, 21])

    assert due_rebalance_reminders(registry, as_of_date=date(2026, 8, 13)) == []
