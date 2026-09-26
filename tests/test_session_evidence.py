from datetime import date

import pandas as pd

from app.data.session_evidence import is_verified_non_session, session_evidence
from app.export import live_performance


def test_official_sessions_detect_dates_missing_from_both_curves():
    evidence = session_evidence(date(2026, 7, 20), date(2026, 7, 23),
                                ["2026-07-20", "2026-07-21", "2026-07-23"])
    assert evidence["missing_session_dates"] == ["2026-07-22"]
    assert not evidence["complete"]
    assert is_verified_non_session(date(2026, 1, 15))
    assert is_verified_non_session(date(2026, 9, 14))
    assert not is_verified_non_session(date(2026, 2, 1))
    assert not session_evidence(date(2027, 1, 1), date(2027, 1, 4), [])["window_covered"]


def test_live_does_not_forward_fill_missing_benchmark_or_move_inception(monkeypatch):
    monkeypatch.setattr(live_performance.config, "DEFAULT_BENCHMARK_SYMBOL", "INDEX")
    monkeypatch.setattr(live_performance.config, "DISTRIBUTION_EVENTS_PATH", "")
    start, second, third = date(2026, 7, 20), date(2026, 7, 21), date(2026, 7, 22)
    snapshot = live_performance.LiveSnapshot(1, start, {"AAA": 1.0}, {"AAA": 100}, [], 0)
    prices = pd.DataFrame([
        {"symbol": symbol, "price_date": day, "price": value}
        for symbol, day, value in [("AAA", start, 100), ("AAA", second, 110), ("AAA", third, 120),
                                   ("INDEX", start, 200), ("INDEX", third, 210)]
    ])
    daily, benchmark, *_, warnings = live_performance._compute_live_performance("s", [snapshot], prices, {})
    assert [r["date"] for r in daily] == [start.isoformat()]
    assert [r["date"] for r in benchmark] == [start.isoformat()]
    assert warnings and "2026-07-21" in warnings[0]
    prices = prices[~((prices.symbol == "INDEX") & (prices.price_date == start))]
    daily, benchmark, *_, warnings = live_performance._compute_live_performance("s", [snapshot], prices, {})
    assert daily == benchmark == []
    assert "inception" in warnings[0]
