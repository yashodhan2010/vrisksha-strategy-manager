from __future__ import annotations

from pathlib import Path
from typing import Any

from app import config
from app.data.universe_loader import load_universe
from app.export.package_builder import (
    _exposure_rows,
    _holdings_history,
    _latest_model_portfolio,
    _rebalance_history,
)
from app.export.schemas import CSV_HEADERS
from app.export.validators import validate_csv_rows
from app.export.writers import write_csv, write_json
from app.storage.repositories import get_latest_monthly_strategy_run, list_monthly_holding_snapshots

UPDATE_FILES = [
    "manifest.json",
    "latest_model_portfolio.csv",
    "rebalance_history.csv",
    "holdings_history.csv",
    "sector_exposure.csv",
    "marketcap_exposure.csv",
]


def export_latest_model_portfolio_update(
    output_dir: str | Path | None = None,
    history_dates: int = 6,
    database_path: str | Path = config.DATABASE_PATH,
) -> Path:
    output_path = Path(output_dir or _default_update_output_dir())
    holdings = list_monthly_holding_snapshots(database_path=database_path, limit_dates=history_dates)
    if not holdings:
        raise ValueError("No monthly model portfolio holdings found. Run monthly-run first.")
    latest_run = get_latest_monthly_strategy_run(database_path)
    universe = {stock.symbol: stock for stock in load_universe()}
    strategy_id = config.STRATEGY_PACKAGE_ID
    latest_portfolio = _latest_model_portfolio(strategy_id, holdings, universe)
    holdings_history = _holdings_history(strategy_id, holdings, universe)
    rebalance_history = _rebalance_history(strategy_id, holdings, universe)
    sector_exposure = _exposure_rows(strategy_id, latest_portfolio, "sector")
    marketcap_exposure = _exposure_rows(strategy_id, latest_portfolio, "marketcap_bucket")

    output_path.mkdir(parents=True, exist_ok=True)
    write_json(
        output_path / "manifest.json",
        _manifest(latest_run, latest_portfolio[0]["as_of_date"] if latest_portfolio else ""),
    )
    _write_csv(output_path, "latest_model_portfolio.csv", latest_portfolio)
    _write_csv(output_path, "rebalance_history.csv", rebalance_history)
    _write_csv(output_path, "holdings_history.csv", holdings_history)
    _write_csv(output_path, "sector_exposure.csv", sector_exposure)
    _write_csv(output_path, "marketcap_exposure.csv", marketcap_exposure)
    validate_package_files_subset(output_path, UPDATE_FILES)
    return output_path


def _manifest(latest_run: dict[str, Any] | None, as_of_date: str) -> dict[str, Any]:
    return {
        "package_schema_version": "1.0.0",
        "update_type": "latest_model_portfolio",
        "strategy_id": config.STRATEGY_PACKAGE_ID,
        "slug": config.STRATEGY_PACKAGE_SLUG,
        "name": config.STRATEGY_PACKAGE_NAME,
        "version": config.STRATEGY_PACKAGE_VERSION,
        "as_of_date": as_of_date,
        "latest_run_id": latest_run.get("id") if latest_run else None,
        "base_currency": config.STRATEGY_PACKAGE_BASE_CURRENCY,
        "output_scope": "subscriber_model_portfolio_update",
    }


def _default_update_output_dir() -> Path:
    package_dir = Path(config.STRATEGY_PACKAGE_OUTPUT_DIR)
    return package_dir.parent / "model-portfolio-update"


def _write_csv(output_path: Path, filename: str, rows: list[dict[str, Any]]) -> None:
    validate_csv_rows(filename, rows)
    write_csv(output_path / filename, CSV_HEADERS[filename], rows)


def validate_package_files_subset(output_dir: Path, filenames: list[str]) -> None:
    missing = [name for name in filenames if not (output_dir / name).exists()]
    if missing:
        raise ValueError(f"Model portfolio update is missing files: {', '.join(missing)}")
