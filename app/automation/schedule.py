from __future__ import annotations

import calendar
from datetime import date, timedelta

from app import config
from app.data.trading_calendar import TradingCalendar, WeekdayTradingCalendar


def parse_target_days(value: str = config.AUTO_REBALANCE_TARGET_DAYS) -> list[int]:
    days: list[int] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        day = int(item)
        if day < 1 or day > 31:
            raise ValueError("AUTO_REBALANCE_TARGET_DAYS must contain day numbers from 1 to 31.")
        days.append(day)
    if not days:
        raise ValueError("AUTO_REBALANCE_TARGET_DAYS must contain at least one day.")
    return sorted(set(days))


def rebalance_dates_for_month(
    year: int,
    month: int,
    target_days: list[int] | None = None,
    trading_calendar: TradingCalendar | None = None,
) -> list[date]:
    target_days = target_days or parse_target_days()
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


def is_rebalance_day(
    day: date | None = None,
    target_days: list[int] | None = None,
    trading_calendar: TradingCalendar | None = None,
) -> bool:
    day = day or date.today()
    return day in rebalance_dates_for_month(day.year, day.month, target_days, trading_calendar)
