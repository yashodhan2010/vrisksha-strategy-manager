from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from app.automation.schedule import rebalance_dates_for_schedule
from app.automation.telegram import TelegramSendResult, send_telegram_message
from app.data.trading_calendar import TradingCalendar, WeekdayTradingCalendar
from app.strategy_profile import load_strategy_profile
from app.strategy_registry import DEFAULT_REGISTRY_PATH, load_strategy_registry


@dataclass(frozen=True)
class StrategySchedule:
    profile_path: Path
    strategy_id: str
    slug: str
    name: str
    target_days: list[int]
    schedule: dict[str, Any]
    timezone: str


@dataclass(frozen=True)
class StrategyReminder:
    schedule: StrategySchedule
    reminder_type: str
    due_date: date
    as_of_date: date

    @property
    def days_until_due(self) -> int:
        return (self.due_date - self.as_of_date).days


def load_strategy_schedules(registry_path: str | Path = DEFAULT_REGISTRY_PATH) -> list[StrategySchedule]:
    schedules: list[StrategySchedule] = []
    for profile_path in load_strategy_registry(registry_path):
        profile = load_strategy_profile(profile_path)
        schedule = profile.get("rebalance_schedule") or {}
        target_days = _target_days_from_schedule(schedule, profile_path) if schedule.get("type") == "monthly_target_days" else []
        schedules.append(
            StrategySchedule(
                profile_path=profile_path,
                strategy_id=str(profile["strategy_id"]),
                slug=str(profile["slug"]),
                name=str(profile["name"]),
                target_days=target_days,
                schedule=schedule,
                timezone=str(schedule.get("timezone") or "Asia/Kolkata"),
            )
        )
    return schedules


def _target_days_from_schedule(schedule: dict[str, Any], profile_path: Path) -> list[int]:
    target_days = schedule.get("target_days")
    if not target_days:
        raise ValueError(f"Strategy profile has no rebalance_schedule.target_days: {profile_path}")
    days = [int(day) for day in target_days]
    invalid_days = [day for day in days if day < 1 or day > 31]
    if invalid_days:
        raise ValueError(f"rebalance_schedule.target_days must contain day numbers from 1 to 31: {profile_path}")
    return sorted(set(days))


def due_rebalance_reminders(
    registry_path: str | Path = DEFAULT_REGISTRY_PATH,
    as_of_date: date | None = None,
    trading_calendar: TradingCalendar | None = None,
) -> list[StrategyReminder]:
    today = as_of_date or date.today()
    calendar = trading_calendar or WeekdayTradingCalendar()
    reminders: list[StrategyReminder] = []
    for schedule in load_strategy_schedules(registry_path):
        due_dates = _nearby_rebalance_dates(today, schedule.schedule, calendar)
        for due_date in due_dates:
            if due_date == today:
                reminders.append(StrategyReminder(schedule, "due_today", due_date, today))
            elif due_date == today + timedelta(days=1):
                reminders.append(StrategyReminder(schedule, "due_tomorrow", due_date, today))
    return reminders


def _nearby_rebalance_dates(
    today: date,
    schedule: dict[str, Any],
    trading_calendar: TradingCalendar,
) -> list[date]:
    months = [(today.year, today.month)]
    next_month = today.replace(day=28) + timedelta(days=4)
    months.append((next_month.year, next_month.month))
    dates: list[date] = []
    for year, month in months:
        dates.extend(rebalance_dates_for_schedule(year, month, schedule, trading_calendar))
    return sorted(set(dates))


def format_rebalance_reminder(reminder: StrategyReminder) -> str:
    when = "today" if reminder.reminder_type == "due_today" else "tomorrow"
    return (
        f"Rebalance reminder: {reminder.schedule.name} is scheduled for {when} "
        f"({reminder.due_date.isoformat()}). Schedule: "
        f"{_schedule_label(reminder.schedule)}."
    )


def _schedule_label(schedule: StrategySchedule) -> str:
    if schedule.target_days:
        return f"target days {', '.join(str(day) for day in schedule.target_days)}"
    if schedule.schedule.get("type") == "quarterly_first_trading_day":
        return "first trading day of each quarter"
    return str(schedule.schedule.get("type") or "unknown")


def send_due_rebalance_reminders(
    registry_path: str | Path = DEFAULT_REGISTRY_PATH,
    as_of_date: date | None = None,
    dry_run: bool = False,
) -> tuple[list[StrategyReminder], list[TelegramSendResult]]:
    reminders = due_rebalance_reminders(registry_path=registry_path, as_of_date=as_of_date)
    if dry_run:
        return reminders, []
    results = [send_telegram_message(format_rebalance_reminder(reminder)) for reminder in reminders]
    return reminders, results
