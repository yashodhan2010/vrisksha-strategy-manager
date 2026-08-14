from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd


DISTRIBUTION_COLUMNS = ["symbol", "ex_date", "amount_per_unit"]


def load_distribution_events(
    events_path_value: str | Path | None,
    symbols: list[str],
    start_date: date,
    end_date: date,
    warnings: list[str],
) -> pd.DataFrame:
    if not events_path_value:
        return pd.DataFrame(columns=DISTRIBUTION_COLUMNS)

    events_path = Path(str(events_path_value))
    if not events_path.is_absolute():
        events_path = Path.cwd() / events_path
    if not events_path.exists():
        warnings.append(f"Distribution events file not found: {events_path_value}. Dividend return treated as zero.")
        return pd.DataFrame(columns=DISTRIBUTION_COLUMNS)

    events = pd.read_csv(events_path)
    missing_columns = set(DISTRIBUTION_COLUMNS) - set(events.columns)
    if missing_columns:
        warnings.append(
            f"Distribution events file {events_path_value} is missing columns: "
            f"{', '.join(sorted(missing_columns))}. Dividend return treated as zero."
        )
        return pd.DataFrame(columns=DISTRIBUTION_COLUMNS)

    events = events.copy()
    events["symbol"] = events["symbol"].astype(str).str.strip().str.upper()
    events["ex_date"] = pd.to_datetime(events["ex_date"], errors="coerce").dt.date
    events["amount_per_unit"] = pd.to_numeric(events["amount_per_unit"], errors="coerce")
    events = events.dropna(subset=["symbol", "ex_date", "amount_per_unit"])
    allowed_symbols = {symbol.upper() for symbol in symbols}
    events = events[events["symbol"].isin(allowed_symbols)]
    return events[(events["ex_date"] >= start_date) & (events["ex_date"] <= end_date)]


def distribution_path_from_profile(profile: dict[str, Any]) -> str:
    distribution_config = profile.get("distribution") or {}
    return str(
        distribution_config.get("events_path")
        or distribution_config.get("dividend_events_path")
        or distribution_config.get("distributions_path")
        or ""
    )


def distribution_per_unit(distributions: pd.DataFrame, symbol: str, start_date: date, end_date: date) -> float:
    if distributions.empty:
        return 0.0
    mask = (
        (distributions["symbol"] == symbol.upper())
        & (distributions["ex_date"] > start_date)
        & (distributions["ex_date"] <= end_date)
    )
    return float(distributions.loc[mask, "amount_per_unit"].sum())
