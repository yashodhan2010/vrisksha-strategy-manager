from __future__ import annotations

import os
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

from app import cli


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


def test_send_rebalance_reminders_cli_dry_run(tmp_path: Path) -> None:
    profile_dir = tmp_path / "strategies" / "dual-momentum"
    profile_dir.mkdir(parents=True)
    profile = profile_dir / "strategy_profile.json"
    profile.write_text(
        json.dumps(
            {
                "strategy_id": "dual_momentum_test_v1",
                "slug": "dual-momentum",
                "name": "Dual Momentum",
                "rebalance_schedule": {
                    "type": "monthly_target_days",
                    "target_days": [11, 21],
                    "timezone": "Asia/Kolkata",
                },
            }
        ),
        encoding="utf-8",
    )
    registry = tmp_path / "strategies" / "registry.json"
    registry.write_text(json.dumps({"strategies": [str(profile)]}), encoding="utf-8")

    result = _run(
        [
            "send-rebalance-reminders",
            "--registry",
            str(registry),
            "--as-of-date",
            "2026-08-10",
            "--dry-run",
        ],
        tmp_path,
    )

    assert result.returncode == 0
    assert "Dual Momentum" in result.stdout
    assert "tomorrow" in result.stdout


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


def test_build_finalized_package_rejects_fixed_allocation_profile(tmp_path: Path) -> None:
    profile = tmp_path / "strategy_profile.json"
    profile.write_text(
        json.dumps(
            {
                "strategy_id": "fixed_income_v1",
                "slug": "fixed-income",
                "name": "Fixed Income",
                "strategy_type": "fixed_allocation",
                "package": {
                    "output_dir": str(tmp_path / "package"),
                },
            }
        ),
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

    assert result.returncode == 2
    assert "Fixed-allocation multi-asset strategies do not use finalized parameter configs" in result.stdout
    assert "run-fixed-allocation-backtest" in result.stdout


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
    assert payload["strategy_parameters"]["MAX_STOCK_WEIGHT"] == 1 / 60


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


def test_build_model_portfolio_update_exports_live_dashboard(monkeypatch, tmp_path: Path, capsys) -> None:
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(cli, "initialize_database", lambda: None)
    monkeypatch.setattr(
        cli,
        "_apply_profile_and_finalized_config",
        lambda strategy_profile, finalized_config: {"finalized_config_path": "finalized.json"},
    )
    monkeypatch.setattr(cli, "sync_universe", lambda: {"active_rows": 1})
    monkeypatch.setattr(cli, "cmd_monthly_run", lambda args: 0)
    monkeypatch.setattr(
        cli,
        "export_latest_model_portfolio_update",
        lambda output_dir, history_dates: calls.append(("model", output_dir)) or tmp_path / "model-update",
    )
    monkeypatch.setattr(
        cli,
        "export_live_performance_dashboard",
        lambda strategy_id, strategy_slug: calls.append(("live", (strategy_id, strategy_slug))) or tmp_path / "live-performance",
    )
    monkeypatch.setattr(
        cli,
        "export_live_performance_tracker_index",
        lambda: calls.append(("tracker", None)) or tmp_path / "live-performance",
    )
    monkeypatch.setattr(cli.config, "STRATEGY_PACKAGE_ID", "test_strategy_v1")
    monkeypatch.setattr(cli.config, "STRATEGY_PACKAGE_SLUG", "test-strategy")

    status = cli.cmd_build_model_portfolio_update(
        __import__("argparse").Namespace(
            strategy_profile="profile.json",
            finalized_config=None,
            output_dir=None,
            history_dates=2,
            history_lookback_days=10,
            no_fetch_history=True,
            selenium_token=False,
            timeout_seconds=1,
            symbols=None,
            no_benchmark=False,
            no_safe_asset=False,
        )
    )

    assert status == 0
    assert calls == [("model", None), ("live", ("test_strategy_v1", "test-strategy")), ("tracker", None)]
    stdout = capsys.readouterr().out
    assert "Live performance dashboard exported" in stdout
    assert "All-strategy live tracker exported" in stdout


def test_export_live_performance_tracker_exports_all_registry_profiles(monkeypatch, tmp_path: Path, capsys) -> None:
    calls: list[tuple[str, object]] = []
    profiles = [
        {"strategy_id": "first_v1", "slug": "first-strategy"},
        {"strategy_id": "second_v1", "slug": "second-strategy"},
    ]
    output_root = tmp_path / "live-performance"
    monkeypatch.setattr(cli, "initialize_database", lambda: None)
    monkeypatch.setattr(cli, "load_strategy_registry", lambda registry: [Path("first.json"), Path("second.json")])
    monkeypatch.setattr(cli, "apply_strategy_profile", lambda profile_path: profiles.pop(0))
    monkeypatch.setattr(
        cli,
        "export_live_performance_dashboard",
        lambda output_dir, strategy_id, strategy_slug: calls.append(
            ("dashboard", (Path(output_dir), strategy_id, strategy_slug))
        )
        or Path(output_dir),
    )
    monkeypatch.setattr(
        cli,
        "export_live_performance_tracker_index",
        lambda output_dir, registry_path: calls.append(("tracker", (Path(output_dir), registry_path))) or Path(output_dir),
    )

    status = cli.cmd_export_live_performance_tracker(
        __import__("argparse").Namespace(
            registry="strategies/registry.json",
            output_dir=str(output_root),
        )
    )

    assert status == 0
    assert calls == [
        ("dashboard", (output_root / "first-strategy", "first_v1", "first-strategy")),
        ("dashboard", (output_root / "second-strategy", "second_v1", "second-strategy")),
        ("tracker", (output_root, "strategies/registry.json")),
    ]
    stdout = capsys.readouterr().out
    assert "All-strategy live tracker exported" in stdout


def test_export_live_performance_tracker_can_fetch_history_first(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[str, object]] = []
    profiles = [
        {"strategy_id": "first_v1", "slug": "first-strategy"},
        {"strategy_id": "second_v1", "slug": "second-strategy"},
    ]
    monkeypatch.setattr(cli, "initialize_database", lambda: None)
    monkeypatch.setattr(cli, "load_strategy_registry", lambda registry: [Path("first.json"), Path("second.json")])
    monkeypatch.setattr(cli, "apply_strategy_profile", lambda profile_path: profiles.pop(0))
    monkeypatch.setattr(cli, "_refresh_kite_token_if_needed", lambda use_selenium, timeout_seconds: calls.append(("token", (use_selenium, timeout_seconds))))
    monkeypatch.setattr(
        cli,
        "fetch_and_store_history",
        lambda start_date, end_date, symbols, include_benchmark, include_safe_asset: calls.append(
            ("fetch", (symbols, include_benchmark, include_safe_asset))
        )
        or __import__("app.data.historical_data", fromlist=["FetchResult"]).FetchResult(2, 4, [], []),
    )
    monkeypatch.setattr(
        cli,
        "export_live_performance_dashboard",
        lambda output_dir, strategy_id, strategy_slug: calls.append(("dashboard", strategy_slug)) or Path(output_dir),
    )
    monkeypatch.setattr(
        cli,
        "export_live_performance_tracker_index",
        lambda output_dir, registry_path: calls.append(("tracker", registry_path)) or Path(output_dir),
    )

    status = cli.cmd_export_live_performance_tracker(
        __import__("argparse").Namespace(
            registry="strategies/registry.json",
            output_dir=str(tmp_path / "live-performance"),
            fetch_history=True,
            history_lookback_days=5,
            selenium_token=True,
            timeout_seconds=12,
            symbols=None,
            no_benchmark=False,
            no_safe_asset=False,
        )
    )

    assert status == 0
    assert calls == [
        ("token", (True, 12)),
        ("fetch", (None, True, True)),
        ("dashboard", "first-strategy"),
        ("fetch", (None, True, True)),
        ("dashboard", "second-strategy"),
        ("tracker", "strategies/registry.json"),
    ]
