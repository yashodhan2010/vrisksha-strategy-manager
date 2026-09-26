"""Portable comparison curves from observed prices, with explicit coverage failures."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd

from app.export.writers import write_csv

# Price and total-return indices must never share a fallback symbol.
BENCHMARKS = (
    ("NIFTY 50", "NIFTY50", "nifty_50"),
    ("NIFTY 500", "NIFTY500", "nifty_500"),
    ("NIFTY 500 TRI", "NIFTY500TRI", "nifty_500_tri"),
    ("NIFTY Gsec Composite", "NIFTYGSECCOMPOSITE", "nifty_gsec_composite"),
    ("Gold", "GOLD", "gold"),
)
HEADERS = ["date", "benchmark", "return", "equity_curve"]


def export_benchmark_comparisons(
    output_path: Path,
    prices: pd.DataFrame,
    daily: list[dict[str, Any]],
    scope: str,
    existing: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Publish complete aligned curves only; unavailable scopes have null file refs.

    Each scope is rebased independently. The first zero return is an inception
    baseline, never a replacement for a missing observed price.
    """
    if scope not in {"historical", "live"}:
        raise ValueError(f"Unknown benchmark comparison scope: {scope}")
    dates = [str(row["date"]) for row in daily]
    if dates != sorted(set(dates)):
        raise ValueError("Benchmark comparison dates must be unique and increasing.")
    by_label = {entry["label"]: dict(entry) for entry in existing or []}
    entries = []
    for label, symbol, slug in BENCHMARKS:
        entry = by_label.get(label, {
            "label": label, "symbol": symbol, "return_unit": "decimal",
            "historical_file": None, "live_file": None,
        })
        filename = f"benchmarks/{slug}_{'live_' if scope == 'live' else ''}returns.csv"
        path = output_path / filename
        observations: dict[str, float] = {}
        if not prices.empty:
            frame = prices.loc[prices["symbol"] == symbol].copy()
            # Match the package preference for KITE when providers overlap.
            frame["_priority"] = frame["source"].map({"KITE": 0}).fillna(1) if "source" in frame else 1
            frame = frame.sort_values(["price_date", "_priority"], kind="stable")
            frame = frame.drop_duplicates("price_date", keep="first")
            for row in frame.to_dict("records"):
                value = float(row["price"]) if pd.notna(row["price"]) else float("nan")
                if math.isfinite(value) and value > 0:
                    observations[pd.Timestamp(row["price_date"]).date().isoformat()] = value
        missing = [day for day in dates if day not in observations]
        available = bool(dates) and not missing
        entry[f"{scope}_file"] = filename if available else None
        entry[f"{scope}_coverage"] = {
            "status": "available" if available else "unavailable",
            "reason": None if available else ("missing_observed_prices" if dates else "no_strategy_dates"),
            "required_dates": len(dates),
            "missing_dates": missing,
        }
        if available:
            base = previous = observations[dates[0]]
            rows = []
            for day in dates:
                value = observations[day]
                rows.append({"date": day, "benchmark": label,
                             "return": value / previous - 1.0,
                             "equity_curve": value / base})
                previous = value
            write_csv(path, HEADERS, rows)
        else:
            # Remove only this owned file, including on re-export after data loss.
            path.unlink(missing_ok=True)
        entries.append(entry)
    return entries
