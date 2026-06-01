from __future__ import annotations

from datetime import date
from typing import Protocol


class TradingCalendar(Protocol):
    def is_trading_day(self, date: date) -> bool:
        ...


class WeekdayTradingCalendar:
    """Temporary calendar: Monday-Friday only. NSE holiday support is deferred."""

    def is_trading_day(self, date: date) -> bool:
        return date.weekday() < 5

