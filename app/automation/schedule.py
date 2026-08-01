from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Any

from app.data.trading_calendar import TradingCalendar, WeekdayTradingCalendar


def parse_target_days(value: str) -> list[int]:
    days: list[int] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        day = int(item)
        if day < 1 or day > 31:
            raise ValueError("Target days must contain day numbers from 1 to 31.")
        days.append(day)
    if not days:
        raise ValueError("Target days must contain at least one day.")
    return sorted(set(days))


def rebalance_dates_for_month(
    year: int,
    month: int,
    target_days: list[int] | None = None,
    trading_calendar: TradingCalendar | None = None,
) -> list[date]:
    if not target_days:
        raise ValueError("target_days is required.")
    trading_calendar = trading_calendar or WeekdayTradingCalendar()
    _, days_in_month = calendar.monthrange(year, month)
    result: list[date] = []
    for target_day in target_days:
        candidate = date(year, month, min(target_day, days_in_month))
        while candidate.month == month and not trading_calendar.is_trading_day(candidate):
            candidate += timedelta(days=1)
        if candidate.month == month and candidate not in result:
            result.append(candidate)
    return result


def rebalance_dates_for_schedule(
    year: int,
    month: int,
    schedule: dict[str, Any],
    trading_calendar: TradingCalendar | None = None,
) -> list[date]:
    schedule_type = str(schedule.get("type") or "monthly_target_days")
    trading_calendar = trading_calendar or WeekdayTradingCalendar()
    if schedule_type == "monthly_target_days":
        target_days = schedule.get("target_days")
        if not target_days:
            raise ValueError("rebalance_schedule.target_days is required for monthly_target_days.")
        return rebalance_dates_for_month(year, month, [int(day) for day in target_days], trading_calendar)
    if schedule_type == "quarterly_first_trading_day":
        quarter_start_months = schedule.get("quarter_start_months") or [1, 4, 7, 10]
        if month not in {int(item) for item in quarter_start_months}:
            return []
        return rebalance_dates_for_month(year, month, [1], trading_calendar)
    raise ValueError(f"Unsupported rebalance_schedule.type: {schedule_type}")


def is_rebalance_day(
    day: date | None = None,
    target_days: list[int] | None = None,
    trading_calendar: TradingCalendar | None = None,
) -> bool:
    day = day or date.today()
    return day in rebalance_dates_for_month(day.year, day.month, target_days, trading_calendar)
