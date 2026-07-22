from __future__ import annotations

import os
import json
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


def test_refresh_finalized_parameters_help_works(tmp_path: Path) -> None:
    result = _run(["refresh-finalized-parameters", "--help"], tmp_path)

    assert result.returncode == 0
    assert "--n-trials" in result.stdout


def test_validate_strategies_cli_works(tmp_path: Path) -> None:
    result = _run(["validate-strategies"], tmp_path)

    assert result.returncode == 0
    assert "Strategy registry validation passed" in result.stdout


def test_export_admin_dashboard_cli_works(tmp_path: Path) -> None:
    output = tmp_path / "strategy_dashboard.json"
    result = _run(["export-admin-dashboard", "--output", str(output)], tmp_path)

    assert result.returncode == 0
    assert "Admin dashboard snapshot written" in result.stdout
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["content_policy"]["performance_metrics_included"] is False
    assert payload["strategies"]


def test_build_finalized_package_can_skip_history_fetch(tmp_path: Path) -> None:
    trials = tmp_path / "trials.csv"
    pd.DataFrame(
        [
            {
                "rank_by_cagr": 1,
                "rebalances_per_month": 1,
                "top_n": 2,
                "sector_cap_pct": 0,
                "high_cutoff_pct": 20,
                "momentum_weight": 0.7,
                "beta_weight": 0.15,
                "volatility_weight": 0.15,
                "buffer_pct": 60,
                "cagr": 0.1,
            }
        ]
    ).to_csv(trials, index=False)
    profile = tmp_path / "strategy_profile.json"
    profile.write_text(
        f"""
        {{
          "strategy_id": "test_strategy_v1",
          "slug": "test-strategy",
          "name": "Test Strategy",
          "optimization": {{
            "results_path": "{trials.as_posix()}",
            "finalized_config_path": "{(tmp_path / 'finalized.json').as_posix()}"
          }},
          "package": {{
            "output_dir": "{(tmp_path / 'package').as_posix()}"
          }}
        }}
        """,
        encoding="utf-8",
    )

    result = _run(
        [
            "build-finalized-package",
            "--strategy-profile",
            str(profile),
            "--start-date",
            "2024-01-01",
            "--end-date",
            "2024-12-31",
            "--no-fetch-history",
        ],
        tmp_path,
    )

    assert result.returncode == 1
    assert "Skipping history fetch" in result.stdout
    assert "No market prices found" in result.stdout


def test_build_finalized_package_uses_profile_objective(tmp_path: Path) -> None:
    trials = tmp_path / "trials.csv"
    finalized = tmp_path / "finalized.json"
    pd.DataFrame(
        [
            {
                "rank_by_cagr": 1,
                "rank_by_net_return_to_drawdown": 2,
                "rebalances_per_month": 1,
                "top_n": 35,
                "sector_cap_pct": 15,
                "high_cutoff_pct": 20,
                "momentum_weight": 0.4,
                "beta_weight": 0.3,
                "volatility_weight": 0.3,
                "buffer_pct": 120,
                "max_stock_weight_pct": 2.5,
                "cagr": 0.35,
                "net_return_to_drawdown": 1.1,
            },
            {
                "rank_by_cagr": 2,
                "rank_by_net_return_to_drawdown": 1,
                "rebalances_per_month": 2,
                "top_n": 60,
                "sector_cap_pct": 30,
                "high_cutoff_pct": 15,
                "momentum_weight": 0.6,
                "beta_weight": 0.2,
                "volatility_weight": 0.2,
                "buffer_pct": 60,
                "max_stock_weight_pct": 3.5,
                "cagr": 0.31,
                "net_return_to_drawdown": 1.5,
            },
        ]
    ).to_csv(trials, index=False)
    profile = tmp_path / "strategy_profile.json"
    profile.write_text(
        f"""
        {{
          "strategy_id": "test_strategy_v1",
          "slug": "test-strategy",
          "name": "Test Strategy",
          "optimization": {{
            "results_path": "{trials.as_posix()}",
            "finalized_config_path": "{finalized.as_posix()}",
            "objective": "net_return_to_drawdown",
            "rank_column": "rank_by_net_return_to_drawdown"
          }},
          "package": {{
            "output_dir": "{(tmp_path / 'package').as_posix()}"
          }}
        }}
        """,
        encoding="utf-8",
    )

    result = _run(
        [
            "build-finalized-package",
            "--strategy-profile",
            str(profile),
            "--start-date",
            "2024-01-01",
            "--end-date",
            "2024-12-31",
            "--no-fetch-history",
        ],
        tmp_path,
    )

    payload = json.loads(finalized.read_text(encoding="utf-8"))
    assert result.returncode == 1
    assert payload["selection"]["objective"] == "net_return_to_drawdown"
    assert payload["strategy_parameters"]["STRATEGY_TOP_N"] == 60
    assert payload["strategy_parameters"]["MAX_STOCK_WEIGHT"] == 0.035


def test_build_finalized_package_uses_existing_config_when_trials_missing(tmp_path: Path) -> None:
    finalized = tmp_path / "finalized.json"
    finalized.write_text(
        json.dumps(
            {
                "strategy_parameters": {
                    "BACKTEST_REBALANCES_PER_MONTH": 2,
                    "STRATEGY_RANKING_METHOD": "AVERAGE_RANK",
                    "RANKING_MOMENTUM_WEIGHT": 0.7,
                    "RANKING_BETA_WEIGHT": 0.15,
                    "RANKING_VOLATILITY_WEIGHT": 0.15,
                    "STRATEGY_ALLOCATION_MODE": "TOP_N_EQUAL",
                    "STRATEGY_TOP_N": 40,
                    "BUFFER_PCT": 60,
                    "MAX_STOCK_WEIGHT": 0.05,
                    "MAX_SECTOR_WEIGHT": 1.0,
                    "HIGH_52W_THRESHOLD": 0.8,
                    "SAFE_ASSET_SYMBOL": "LIQUIDBEES",
                }
            }
        ),
        encoding="utf-8",
    )
    profile = tmp_path / "strategy_profile.json"
    profile.write_text(
        f"""
        {{
          "strategy_id": "test_strategy_v1",
          "slug": "test-strategy",
          "name": "Test Strategy",
          "optimization": {{
            "results_path": "{(tmp_path / 'missing_trials.csv').as_posix()}",
            "finalized_config_path": "{finalized.as_posix()}"
          }},
          "package": {{
            "output_dir": "{(tmp_path / 'package').as_posix()}"
          }}
        }}
        """,
        encoding="utf-8",
    )

    result = _run(
        [
            "build-finalized-package",
            "--strategy-profile",
            str(profile),
            "--start-date",
            "2024-01-01",
            "--end-date",
            "2024-12-31",
            "--no-fetch-history",
        ],
        tmp_path,
    )

    assert result.returncode == 1
    assert "Using existing finalized config" in result.stdout
    assert "Optimization results file not found" not in result.stdout
    assert "No market prices found" in result.stdout
