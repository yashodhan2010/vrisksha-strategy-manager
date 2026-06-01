from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pandas as pd
import pytest

from app.data.universe_loader import load_universe
from app.data.universe_sync import UniverseSyncError, sync_universe


def _write_excel(path: Path, rows: list[dict]) -> None:
    pd.DataFrame(rows).to_excel(path, index=False)


def _valid_rows() -> list[dict]:
    return [
        {"symbol": " abc ", "company_name": "A", "industry": "I", "sector": "S", "is_active": "yes"},
        {"symbol": "DEF", "company_name": "D", "industry": "I", "sector": "S", "is_active": "no"},
    ]


def test_valid_excel_converts_to_json_with_defaults(tmp_path: Path) -> None:
    excel = tmp_path / "universe.xlsx"
    runtime = tmp_path / "universe.json"
    report = tmp_path / "report.json"
    _write_excel(excel, _valid_rows())

    result = sync_universe(excel, runtime, report)

    payload = json.loads(runtime.read_text())
    assert result["status"] == "success"
    assert [row["symbol"] for row in payload] == ["ABC"]
    assert payload[0]["exchange"] == "NSE"
    assert payload[0]["instrument_type"] == "EQ"
    assert payload[0]["kite_tradingsymbol"] == "ABC"


def test_missing_required_column_raises_useful_error(tmp_path: Path) -> None:
    excel = tmp_path / "universe.xlsx"
    _write_excel(excel, [{"symbol": "ABC", "company_name": "A", "industry": "I", "is_active": True}])
    with pytest.raises(UniverseSyncError, match="Missing required universe columns"):
        sync_universe(excel, tmp_path / "out.json", tmp_path / "report.json")


def test_blank_symbols_are_rejected(tmp_path: Path) -> None:
    excel = tmp_path / "universe.xlsx"
    _write_excel(excel, [{"symbol": "", "company_name": "A", "industry": "I", "sector": "S", "is_active": True}])
    with pytest.raises(UniverseSyncError, match="validation failed"):
        sync_universe(excel, tmp_path / "out.json", tmp_path / "report.json")


def test_duplicate_symbols_appear_in_validation_output(tmp_path: Path) -> None:
    excel = tmp_path / "universe.xlsx"
    report = tmp_path / "report.json"
    rows = _valid_rows()
    rows.append({"symbol": "ABC", "company_name": "A2", "industry": "I", "sector": "S", "is_active": True})
    _write_excel(excel, rows)

    with pytest.raises(UniverseSyncError):
        sync_universe(excel, tmp_path / "out.json", report)
    payload = json.loads(report.read_text())
    assert payload["duplicate_symbols"] == ["ABC"]


def test_inactive_symbols_not_written(tmp_path: Path) -> None:
    excel = tmp_path / "universe.xlsx"
    runtime = tmp_path / "universe.json"
    _write_excel(excel, _valid_rows())
    sync_universe(excel, runtime, tmp_path / "report.json")
    assert [row["symbol"] for row in json.loads(runtime.read_text())] == ["ABC"]


def test_excel_newer_than_json_triggers_regeneration(tmp_path: Path) -> None:
    excel = tmp_path / "universe.xlsx"
    runtime = tmp_path / "universe.json"
    _write_excel(excel, _valid_rows())
    sync_universe(excel, runtime, tmp_path / "report.json")
    time.sleep(1.1)
    _write_excel(excel, [{"symbol": "XYZ", "company_name": "X", "industry": "I", "sector": "S", "is_active": True}])
    os.utime(excel, None)

    stocks = load_universe(excel, runtime)

    assert [stock.symbol for stock in stocks] == ["XYZ"]

