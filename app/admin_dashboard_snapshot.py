from __future__ import annotations

import csv
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.automation.schedule import rebalance_dates_for_schedule
from app.data.trading_calendar import WeekdayTradingCalendar
from app.strategy_registry import DEFAULT_REGISTRY_PATH, load_strategy_registry, validate_strategy_registry


DEFAULT_ADMIN_DASHBOARD_PATH = Path("data/admin/strategy_dashboard.json")


def export_admin_dashboard_snapshot(
    output_path: str | Path = DEFAULT_ADMIN_DASHBOARD_PATH,
    registry_path: str | Path = DEFAULT_REGISTRY_PATH,
    as_of_date: date | None = None,
) -> Path:
    snapshot = build_admin_dashboard_snapshot(registry_path=registry_path, as_of_date=as_of_date)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")
    return path


def build_admin_dashboard_snapshot(
    registry_path: str | Path = DEFAULT_REGISTRY_PATH,
    as_of_date: date | None = None,
) -> dict[str, Any]:
    today = as_of_date or date.today()
    validation = validate_strategy_registry(registry_path)
    strategies = [_strategy_status(profile_path, today) for profile_path in load_strategy_registry(registry_path)]
    return {
        "schema_version": "1.0.0",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "as_of_date": today.isoformat(),
        "source_registry": _display_path(registry_path),
        "content_policy": {
            "performance_metrics_included": False,
            "holdings_rows_included": False,
            "broker_secrets_included": False,
            "subscriber_logic_included": False,
        },
        "validation": {
            "ok": validation.ok,
            "profile_count": validation.profile_count,
            "issues": [
                {
                    "profile_path": issue.profile_path,
                    "severity": issue.severity,
                    "message": issue.message,
                }
                for issue in validation.issues
            ],
        },
        "strategies": strategies,
    }


def _strategy_status(profile_path: Path, today: date) -> dict[str, Any]:
    profile = _read_json(profile_path)
    slug = str(profile.get("slug") or profile_path.parent.name)
    package = profile.get("package") or {}
    optimization = profile.get("optimization") or {}
    package_dir = Path(str(package.get("output_dir") or f"data/output/packages/{slug}/strategy-package"))
    model_update_dir = package_dir.parent / "model-portfolio-update"
    package_manifest = _read_json(package_dir / "manifest.json")
    update_manifest = _read_json(model_update_dir / "manifest.json")
    package_portfolio = package_dir / "latest_model_portfolio.csv"
    update_portfolio = model_update_dir / "latest_model_portfolio.csv"
    preferred_portfolio = update_portfolio if update_portfolio.exists() else package_portfolio
    latest_portfolio_as_of = _latest_portfolio_as_of(preferred_portfolio)
    last_successful_run = _last_successful_run(update_manifest, package_manifest, latest_portfolio_as_of)
    schedule = _schedule_status(profile.get("rebalance_schedule") or {}, today)
    distribution = _distribution_status(profile.get("distribution") or {})
    return {
        "strategy_id": profile.get("strategy_id"),
        "slug": slug,
        "name": profile.get("name"),
        "category_labels": profile.get("category_labels", []),
        "universe": profile.get("universe"),
        "benchmark": profile.get("benchmark"),
        "profile_path": _display_path(profile_path),
        "finalized_config_path": _display_path(optimization.get("finalized_config_path") or ""),
        "package_output_dir": _display_path(package_dir),
        "model_portfolio_update_dir": _display_path(model_update_dir),
        "latest_model_portfolio_path": _display_path(preferred_portfolio),
        "latest_model_portfolio_exists": preferred_portfolio.exists(),
        "latest_model_portfolio_as_of": latest_portfolio_as_of,
        "last_successful_run": last_successful_run,
        "next_due_date": schedule["next_due_date"],
        "rebalance_schedule": schedule["schedule"],
        "distribution": distribution,
        "file_status": {
            "profile_exists": profile_path.exists(),
            "finalized_config_exists": _path_exists(optimization.get("finalized_config_path")),
            "optimization_results_exists": _path_exists(optimization.get("results_path")),
            "strategy_package_exists": package_dir.exists(),
            "model_update_exists": model_update_dir.exists(),
        },
        "commands": _commands(profile_path, slug, profile),
    }


def _read_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path)
    if not resolved.exists():
        return {}
    return json.loads(resolved.read_text(encoding="utf-8"))


def _display_path(path: str | Path) -> str:
    return Path(str(path)).as_posix() if path else ""


def _path_exists(path: object) -> bool:
    return bool(path) and Path(str(path)).exists()


def _latest_portfolio_as_of(path: Path) -> str | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        first = next(reader, None)
    if not first:
        return None
    value = first.get("as_of_date")
    return value if value else None


def _last_successful_run(
    update_manifest: dict[str, Any],
    package_manifest: dict[str, Any],
    latest_portfolio_as_of: str | None,
) -> dict[str, Any] | None:
    if update_manifest:
        return {
            "type": "model_portfolio_update",
            "run_id": update_manifest.get("latest_run_id"),
            "date": update_manifest.get("as_of_date") or latest_portfolio_as_of,
            "generated_at": update_manifest.get("generated_at"),
        }
    if package_manifest:
        return {
            "type": "strategy_package",
            "run_id": None,
            "date": package_manifest.get("portfolio_as_of_date") or package_manifest.get("backtest_end_date"),
            "generated_at": package_manifest.get("generated_at"),
        }
    return None


def _schedule_status(schedule: dict[str, Any], today: date) -> dict[str, Any]:
    normalized_schedule = _normalize_schedule(schedule)
    calendar = WeekdayTradingCalendar()
    for year, month in _month_cursor(today):
        candidates = rebalance_dates_for_schedule(year, month, normalized_schedule, calendar)
        future = [item for item in candidates if item >= today]
        if future:
            return {
                "next_due_date": min(future).isoformat(),
                "schedule": normalized_schedule,
            }
    return {
        "next_due_date": None,
        "schedule": normalized_schedule,
    }


def _normalize_schedule(schedule: dict[str, Any]) -> dict[str, Any]:
    schedule_type = str(schedule.get("type") or "monthly_target_days")
    result: dict[str, Any] = {
        "type": schedule_type,
        "timezone": schedule.get("timezone") or "Asia/Kolkata",
    }
    if schedule_type == "monthly_target_days":
        result["target_days"] = [int(item) for item in (schedule.get("target_days") or [1, 15])]
    elif schedule_type == "quarterly_first_trading_day":
        result["quarter_start_months"] = [int(item) for item in (schedule.get("quarter_start_months") or [1, 4, 7, 10])]
    return result


def _distribution_status(distribution: dict[str, Any]) -> dict[str, Any]:
    events_path = (
        distribution.get("events_path")
        or distribution.get("dividend_events_path")
        or distribution.get("distributions_path")
        or ""
    )
    return {
        "frequency": distribution.get("frequency"),
        "mode": distribution.get("mode"),
        "events_path": _display_path(events_path),
        "events_file_exists": _path_exists(events_path),
    }


def _month_cursor(start: date) -> list[tuple[int, int]]:
    months: list[tuple[int, int]] = []
    year = start.year
    month = start.month
    for _ in range(14):
        months.append((year, month))
        month += 1
        if month == 13:
            month = 1
            year += 1
    return months


def _commands(profile_path: Path, slug: str, profile: dict[str, Any]) -> dict[str, str]:
    profile_arg = str(profile_path).replace("\\", "/")
    if str(profile.get("strategy_type") or "").strip().lower() == "fixed_allocation":
        return {
            "run_fixed_allocation_backtest": (
                "python -m app.main run-fixed-allocation-backtest "
                f"--strategy-profile {profile_arg} "
                "--start-date YYYY-MM-DD --end-date YYYY-MM-DD --initial-capital 1000000"
            ),
            "export_admin_dashboard": "python -m app.main export-admin-dashboard",
            "validate_strategies": "python -m app.main validate-strategies",
            "open_admin_dashboard": "streamlit run dashboards/admin_app.py",
        }
    return {
        "refresh_finalized_parameters": f"python -m app.main refresh-finalized-parameters --strategy-profile {profile_arg}",
        "build_finalized_package": (
            "python -m app.main build-finalized-package "
            f"--strategy-profile {profile_arg} "
            "--start-date 2016-01-01 --end-date YYYY-MM-DD --initial-capital 1000000 --selenium-token"
        ),
        "build_model_portfolio_update": (
            "python -m app.main build-model-portfolio-update "
            f"--strategy-profile {profile_arg} --selenium-token"
        ),
        "local_model_portfolio_update_no_fetch": (
            "python -m app.main build-model-portfolio-update "
            f"--strategy-profile {profile_arg} --no-fetch-history"
        ),
        "export_admin_dashboard": "python -m app.main export-admin-dashboard",
        "validate_strategies": "python -m app.main validate-strategies",
        "open_admin_dashboard": "streamlit run dashboards/admin_app.py",
    }
