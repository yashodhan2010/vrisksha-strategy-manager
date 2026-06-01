from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from app import config

COLUMNS = [
    "symbol",
    "company_name",
    "industry",
    "sector",
    "exchange",
    "instrument_type",
    "is_active",
    "kite_tradingsymbol",
    "kite_instrument_token",
    "isin",
    "effective_from",
    "effective_to",
]
REQUIRED_COLUMNS = ["symbol", "company_name", "industry", "sector", "is_active"]


class UniverseSyncError(ValueError):
    pass


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        return False
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y", "active"}:
        return True
    if text in {"false", "0", "no", "n", "inactive", ""}:
        return False
    raise UniverseSyncError(f"Invalid is_active value: {value!r}")


def _clean_cell(value: Any) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def sync_universe(
    excel_path: str | Path = config.UNIVERSE_EXCEL_PATH,
    json_path: str | Path = config.UNIVERSE_JSON_PATH,
    report_path: str | Path = config.UNIVERSE_VALIDATION_REPORT_PATH,
) -> dict[str, Any]:
    source = Path(excel_path)
    output = Path(json_path)
    report_file = Path(report_path)
    if not source.exists():
        raise FileNotFoundError(
            f"Universe workbook not found at {source}. Copy data/reference/nifty500_universe.example.xlsx "
            "to data/reference/nifty500_universe.xlsx and populate it with real Nifty 500 data."
        )

    frame = pd.read_excel(source, dtype=object)
    missing_columns = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing_columns:
        raise UniverseSyncError(f"Missing required universe columns: {', '.join(missing_columns)}")

    for column in COLUMNS:
        if column not in frame.columns:
            frame[column] = None

    records: list[dict[str, Any]] = []
    duplicate_symbols: list[str] = []
    missing_required_values: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen: set[str] = set()

    for index, row in frame.iterrows():
        cleaned = {column: _clean_cell(row[column]) for column in COLUMNS}
        symbol = (cleaned["symbol"] or "").upper()
        cleaned["symbol"] = symbol
        if not symbol:
            missing_required_values.append({"row": int(index) + 2, "column": "symbol"})
            continue
        for column in ["company_name", "industry", "sector"]:
            if not cleaned[column]:
                missing_required_values.append({"row": int(index) + 2, "column": column, "symbol": symbol})

        if symbol in seen and symbol not in duplicate_symbols:
            duplicate_symbols.append(symbol)
        seen.add(symbol)

        cleaned["exchange"] = cleaned["exchange"] or "NSE"
        cleaned["instrument_type"] = cleaned["instrument_type"] or "EQ"
        cleaned["kite_tradingsymbol"] = cleaned["kite_tradingsymbol"] or symbol
        cleaned["is_active"] = _parse_bool(row["is_active"])
        records.append(cleaned)

    if missing_required_values:
        status = "failed"
    elif duplicate_symbols:
        status = "failed"
    else:
        status = "success"

    active_records = [record for record in records if record["is_active"]]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_file": str(source),
        "total_rows": int(len(frame)),
        "active_rows": len(active_records),
        "inactive_rows": len(records) - len(active_records),
        "duplicate_symbols": duplicate_symbols,
        "missing_required_values": missing_required_values,
        "warnings": warnings,
        "status": status,
    }

    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if status != "success":
        raise UniverseSyncError(f"Universe validation failed. See {report_file}.")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(active_records, indent=2), encoding="utf-8")
    return report

