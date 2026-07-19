from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pandas as pd


def _env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["DATABASE_PATH"] = str(tmp_path / "test.db")
    env["UNIVERSE_EXCEL_PATH"] = str(tmp_path / "nifty500_universe.xlsx")
    env["UNIVERSE_JSON_PATH"] = str(tmp_path / "nifty500_universe.json")
    env["UNIVERSE_VALIDATION_REPORT_PATH"] = str(tmp_path / "universe_validation_report.json")
    env["LOG_DIR"] = str(tmp_path / "logs")
    return env


def _run(args: list[str], tmp_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "app.main", *args],
        cwd=Path(__file__).resolve().parents[1],
        env=_env(tmp_path),
        text=True,
        capture_output=True,
        check=False,
    )


def test_show_config_works(tmp_path: Path) -> None:
    result = _run(["show-config"], tmp_path)
    assert result.returncode == 0
    assert "Strategy Research Factory" in result.stdout
    assert "KITE_API_SECRET" not in result.stdout


def test_init_db_works(tmp_path: Path) -> None:
    result = _run(["init-db"], tmp_path)
    assert result.returncode == 0
    assert (tmp_path / "test.db").exists()


def test_sync_universe_returns_useful_error_when_workbook_absent(tmp_path: Path) -> None:
    result = _run(["sync-universe"], tmp_path)
    assert result.returncode == 1
    assert "Universe workbook not found" in result.stdout


def test_manual_run_completes_without_orders(tmp_path: Path) -> None:
    result = _run(["manual-run"], tmp_path)
    assert result.returncode == 0
    assert "no orders were placed" in result.stdout


def test_backtest_years_stores_placeholder_without_fake_metrics(tmp_path: Path) -> None:
    result = _run(["backtest", "--years", "10"], tmp_path)
    assert result.returncode == 1
    assert "No market prices found" in result.stdout


def test_fetch_history_validates_missing_universe_workbook(tmp_path: Path) -> None:
    result = _run(["fetch-history", "--start-date", "2024-01-01", "--end-date", "2024-01-31"], tmp_path)
    assert result.returncode == 1
    assert "No runtime universe JSON is available" in result.stdout


def test_run_backtest_validates_date_order(tmp_path: Path) -> None:
    result = _run(["run-backtest", "--start-date", "2025-01-01", "--end-date", "2024-01-01"], tmp_path)
    assert result.returncode == 2
    assert "--start-date must be on or before --end-date" in result.stdout


def test_run_backtest_validates_initial_capital(tmp_path: Path) -> None:
    result = _run(
        [
            "run-backtest",
            "--start-date",
            "2024-01-01",
            "--end-date",
            "2024-12-31",
            "--initial-capital",
            "0",
        ],
        tmp_path,
    )
    assert result.returncode == 2
    assert "--initial-capital must be greater than zero" in result.stdout


def test_sync_universe_success_via_cli(tmp_path: Path) -> None:
    pd.DataFrame(
        [{"symbol": "EX", "company_name": "Example", "industry": "Fiction", "sector": "Test", "is_active": True}]
    ).to_excel(tmp_path / "nifty500_universe.xlsx", index=False)
    result = _run(["sync-universe"], tmp_path)
    assert result.returncode == 0
    assert (tmp_path / "nifty500_universe.json").exists()


def test_monthly_run_requires_finalized_config(tmp_path: Path) -> None:
    profile = tmp_path / "strategy_profile.json"
    profile.write_text(
        """
        {
          "strategy_id": "test_strategy_v1",
          "slug": "test-strategy",
          "name": "Test Strategy",
          "optimization": {
            "finalized_config_path": "missing_finalized_config.json"
          }
        }
        """,
        encoding="utf-8",
    )

    result = _run(["monthly-run", "--strategy-profile", str(profile)], tmp_path)

    assert result.returncode == 1
    assert "Monthly run failed before rebalance" in result.stdout
