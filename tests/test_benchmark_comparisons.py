import csv
import math

import pandas as pd
import pytest

from app.export.benchmark_comparisons import BENCHMARKS, export_benchmark_comparisons


def read_rows(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_all_comparisons_align_and_rebase_each_scope(tmp_path):
    dates = ["2024-01-01", "2024-01-02", "2024-01-03"]
    prices = pd.DataFrame([
        {"symbol": symbol, "price_date": day, "price": value, "source": "KITE"}
        for _, symbol, _ in BENCHMARKS
        for day, value in zip(dates, [100, 110, 99])
    ])
    historical = export_benchmark_comparisons(tmp_path, prices, [{"date": d} for d in dates], "historical")
    entries = export_benchmark_comparisons(tmp_path, prices, [{"date": d} for d in dates[1:]], "live", historical)
    assert [e["label"] for e in entries] == [b[0] for b in BENCHMARKS]
    for entry in entries:
        rows = read_rows(tmp_path / entry["historical_file"])
        assert list(rows[0]) == ["date", "benchmark", "return", "equity_curve"]
        assert [r["date"] for r in rows] == dates
        assert {r["benchmark"] for r in rows} == {entry["label"]}
        assert [float(r["return"]) for r in rows] == pytest.approx([0, .1, -.1])
        assert [float(r["equity_curve"]) for r in rows] == pytest.approx([1, 1.1, .99])
        assert math.prod(1 + float(r["return"]) for r in rows) == pytest.approx(.99)
        live = read_rows(tmp_path / entry["live_file"])
        assert [r["date"] for r in live] == dates[1:]
        assert [float(r["return"]) for r in live] == pytest.approx([0, -.1])
        assert [float(r["equity_curve"]) for r in live] == pytest.approx([1, .9])


@pytest.mark.parametrize("bad", [None, 0, -1, float("inf"), float("nan")])
@pytest.mark.parametrize("gap_index", [0, 1, 2])
def test_missing_or_invalid_price_disables_curve_and_removes_stale_file(tmp_path, bad, gap_index):
    dates = ["2024-01-01", "2024-01-02", "2024-01-03"]
    daily = [{"date": d} for d in dates]
    prices = pd.DataFrame([{"symbol": "NIFTY500", "price_date": d, "price": 100.0} for d in dates])
    entry = export_benchmark_comparisons(tmp_path, prices, daily, "historical")[1]
    old_file = tmp_path / entry["historical_file"]
    prices.loc[gap_index, "price"] = bad
    entry = export_benchmark_comparisons(tmp_path, prices, daily, "historical")[1]
    assert entry["historical_file"] is None
    assert entry["historical_coverage"]["missing_dates"] == [dates[gap_index]]
    assert not old_file.exists()


def test_no_proxy_substitution_and_no_dates(tmp_path):
    prices = pd.DataFrame([
        {"symbol": s, "price_date": "2024-01-01", "price": 100}
        for s in ["NIFTY500", "GOLDBEES", "GSEC10IETF"]
    ])
    entries = export_benchmark_comparisons(tmp_path, prices, [{"date": "2024-01-01"}], "historical")
    assert [e["historical_coverage"]["status"] for e in entries] == [
        "unavailable", "available", "unavailable", "unavailable", "unavailable",
    ]
    entries = export_benchmark_comparisons(tmp_path, prices, [], "historical")
    assert all(e["historical_file"] is None for e in entries)
    assert all(e["historical_coverage"]["reason"] == "no_strategy_dates" for e in entries)
    assert not list(tmp_path.rglob("*.csv"))


def test_extra_dates_ignored_and_kite_preferred(tmp_path):
    prices = pd.DataFrame([
        {"symbol": "NIFTY50", "price_date": "2024-01-01", "price": 1, "source": "YAHOO"},
        {"symbol": "NIFTY50", "price_date": "2024-01-01", "price": 100, "source": "KITE"},
        {"symbol": "NIFTY50", "price_date": "2024-01-02", "price": 500, "source": "KITE"},
        {"symbol": "NIFTY50", "price_date": "2024-01-03", "price": 110, "source": "KITE"},
    ])
    entry = export_benchmark_comparisons(tmp_path, prices, [
        {"date": "2024-01-01"}, {"date": "2024-01-03"},
    ], "live")[0]
    rows = read_rows(tmp_path / entry["live_file"])
    assert len(rows) == 2
    assert float(rows[1]["return"]) == pytest.approx(.1)
