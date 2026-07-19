from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from app.export.schemas import CSV_HEADERS, PACKAGE_FILES

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def validate_manifest(manifest: dict[str, Any]) -> None:
    required = [
        "strategy_id",
        "slug",
        "name",
        "version",
        "generated_at",
        "ra_entity",
        "sebi_registration_number",
        "universe",
        "benchmark",
        "base_currency",
        "backtest_start_date",
        "backtest_end_date",
        "rebalance_frequency",
        "target_holdings",
        "min_capital_guidance",
        "public_visibility",
    ]
    missing = [key for key in required if key not in manifest]
    if missing:
        raise ValueError(f"manifest.json is missing required fields: {', '.join(missing)}")
    if not SLUG_RE.fullmatch(str(manifest["slug"])):
        raise ValueError("Strategy slug must be lowercase kebab-case.")
    _validate_iso_date(str(manifest["backtest_start_date"]), "backtest_start_date")
    _validate_iso_date(str(manifest["backtest_end_date"]), "backtest_end_date")
    if "+" not in str(manifest["generated_at"]):
        raise ValueError("generated_at must include a timezone offset.")


def validate_package_files(output_dir: Path) -> None:
    missing = [name for name in PACKAGE_FILES if not (output_dir / name).exists()]
    if missing:
        raise ValueError(f"Strategy package is missing files: {', '.join(missing)}")


def validate_csv_rows(filename: str, rows: list[dict[str, Any]]) -> None:
    headers = CSV_HEADERS[filename]
    for index, row in enumerate(rows, start=1):
        missing = [header for header in headers if header not in row]
        if missing:
            raise ValueError(f"{filename} row {index} is missing columns: {', '.join(missing)}")
        for key in row:
            if key.endswith("date") or key == "date":
                value = row.get(key)
                if value:
                    _validate_iso_date(str(value), f"{filename}.{key}")


def validate_weights(rows: list[dict[str, Any]], key: str, allow_empty: bool = False) -> None:
    for index, row in enumerate(rows, start=1):
        value = row.get(key)
        if value in ("", None) and allow_empty:
            continue
        weight = float(value)
        if weight < -1e-9 or weight > 1.000001:
            raise ValueError(f"Invalid {key} at row {index}: {weight}")


def _validate_iso_date(value: str, field_name: str) -> None:
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD dates.") from exc
