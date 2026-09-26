"""Dated NSE cash-market evidence, independent of exported return series."""
from datetime import date, timedelta

SOURCES = [
    "https://nsearchives.nseindia.com/content/circulars/CMTR71775.pdf",
    "https://nsearchives.nseindia.com/content/circulars/CMTR72260.pdf",
    "https://nsearchives.nseindia.com/content/circulars/CMTR72349.pdf",
]
VERIFIED_THROUGH = date(2026, 9, 24)
HOLIDAYS = {
    date.fromisoformat(value) for value in (
        "2026-01-15", "2026-01-26", "2026-03-03", "2026-03-26",
        "2026-03-31", "2026-04-03", "2026-04-14", "2026-05-01",
        "2026-05-28", "2026-06-26", "2026-09-14",
    )
}
SPECIAL_SESSIONS = {date(2026, 2, 1)}


def is_verified_non_session(day: date) -> bool:
    return (date(2026, 1, 1) <= day <= VERIFIED_THROUGH
            and (day in HOLIDAYS or (day.weekday() >= 5 and day not in SPECIAL_SESSIONS)))


def session_evidence(start: date | None, end: date | None, actual_dates: list[str]) -> dict:
    covered = bool(start and end and date(2026, 1, 1) <= start <= end <= VERIFIED_THROUGH)
    expected = []
    if covered:
        current = start
        while current <= end:
            if not is_verified_non_session(current):
                expected.append(current.isoformat())
            current += timedelta(days=1)
    return {
        "exchange": "NSE", "segment": "cash", "timezone": "Asia/Kolkata",
        "sources": SOURCES, "verified_through": VERIFIED_THROUGH.isoformat(),
        "coverage_start": "2026-01-01", "window_covered": covered,
        "expected_session_dates": expected,
        "missing_session_dates": sorted(set(expected) - set(actual_dates)),
        "unexpected_session_dates": sorted(set(actual_dates) - set(expected)) if covered else [],
        "complete": covered and set(expected) == set(actual_dates),
    }
