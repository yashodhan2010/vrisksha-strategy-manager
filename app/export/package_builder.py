from __future__ import annotations

import json
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from app import config
from app.data.universe_loader import load_universe
from app.export.docs import disclosures_md, import_notes_md, internal_methodology_md, public_methodology_md
from app.export.schemas import CSV_HEADERS, PACKAGE_FILES
from app.export.validators import validate_csv_rows, validate_manifest, validate_package_files, validate_weights
from app.export.writers import write_csv, write_json, write_markdown
from app.storage.database import get_connection
from app.strategy.models import RunStatus

IST = timezone(timedelta(hours=5, minutes=30))


def build_strategy_package(
    backtest_run_id: int | None = None,
    output_dir: str | Path = config.STRATEGY_PACKAGE_OUTPUT_DIR,
    database_path: str | Path = config.DATABASE_PATH,
) -> Path:
    run = _load_backtest_run(backtest_run_id, database_path)
    run_id = int(run["id"])
    snapshots = _load_portfolio_snapshots(run_id, database_path)
    holdings = _load_holding_snapshots(run_id, database_path)
    if not snapshots:
        raise ValueError(f"Backtest run {run_id} has no portfolio snapshots to export.")
    if not holdings:
        raise ValueError(f"Backtest run {run_id} has no holding snapshots to export.")

    summary = json.loads(run.get("summary_json") or "{}")
    warnings = json.loads(run.get("warnings_json") or "[]")
    universe = {stock.symbol: stock for stock in load_universe()}
    prices = _load_price_frame(database_path)
    daily = _reconstruct_daily_returns(run, snapshots, holdings, prices)
    benchmark = _benchmark_returns(run, prices)
    monthly = _monthly_returns(snapshots)
    yearly = _yearly_returns(daily)
    drawdowns = _drawdowns(daily)
    metrics = _metrics(run, snapshots, daily, monthly, yearly, benchmark, holdings)
    manifest = _manifest(run, summary)
    latest_portfolio = _latest_model_portfolio(manifest["strategy_id"], holdings, universe)
    holdings_history = _holdings_history(manifest["strategy_id"], holdings, universe)
    rebalance_history = _rebalance_history(manifest["strategy_id"], holdings, universe)
    sector_exposure = _exposure_rows(manifest["strategy_id"], latest_portfolio, "sector")
    marketcap_exposure = _exposure_rows(manifest["strategy_id"], latest_portfolio, "marketcap_bucket")

    output_path = Path(output_dir)
    _prepare_output_path(output_path)

    validate_manifest(manifest)
    write_json(output_path / "manifest.json", manifest)
    write_json(output_path / "backtest_metrics.json", metrics)
    _write_csv(output_path, "returns_daily.csv", daily)
    _write_csv(output_path, "returns_monthly.csv", monthly)
    _write_csv(output_path, "returns_yearly.csv", yearly)
    _write_csv(output_path, "drawdowns.csv", drawdowns)
    _write_csv(output_path, "benchmark_returns.csv", benchmark)
    _write_csv(output_path, "latest_model_portfolio.csv", latest_portfolio)
    _write_csv(output_path, "rebalance_history.csv", rebalance_history)
    _write_csv(output_path, "holdings_history.csv", holdings_history)
    _write_csv(output_path, "sector_exposure.csv", sector_exposure)
    _write_csv(output_path, "marketcap_exposure.csv", marketcap_exposure)
    write_markdown(
        output_path / "methodology.md",
        _document_text(config.STRATEGY_PUBLIC_METHODOLOGY_PATH, public_methodology_md(manifest)),
    )
    write_markdown(
        output_path / "methodology_internal.md",
        _document_text(
            config.STRATEGY_INTERNAL_METHODOLOGY_PATH,
            internal_methodology_md(manifest, summary),
        ),
    )
    write_markdown(output_path / "disclosures.md", disclosures_md(manifest))
    write_markdown(output_path / "import_notes.md", import_notes_md(manifest, warnings))
    validate_package_files(output_path)
    return output_path


def _prepare_output_path(output_path: Path) -> None:
    output_path.mkdir(parents=True, exist_ok=True)
    for filename in PACKAGE_FILES:
        path = output_path / filename
        if path.exists():
            try:
                path.unlink()
            except PermissionError as exc:
                raise PermissionError(
                    f"Could not replace existing package file because Windows denied access: {path}. "
                    "Close any app using the package files, pause OneDrive sync if needed, and rerun."
                ) from exc


def _load_backtest_run(backtest_run_id: int | None, database_path: str | Path) -> dict[str, Any]:
    where = "WHERE id = ?" if backtest_run_id is not None else "WHERE status = ?"
    params: tuple[Any, ...] = (backtest_run_id,) if backtest_run_id is not None else (RunStatus.COMPLETED.value,)
    query = f"SELECT * FROM backtest_runs {where} ORDER BY id DESC LIMIT 1"
    with get_connection(database_path) as connection:
        row = connection.execute(query, params).fetchone()
    if row is None:
        target = f"id {backtest_run_id}" if backtest_run_id is not None else "latest completed run"
        raise ValueError(f"No completed backtest found for {target}.")
    item = dict(row)
    if item["status"] != RunStatus.COMPLETED.value:
        raise ValueError(f"Backtest run {item['id']} is not completed.")
    return item


def _load_portfolio_snapshots(run_id: int, database_path: str | Path) -> list[dict[str, Any]]:
    with get_connection(database_path) as connection:
        rows = connection.execute(
            "SELECT * FROM portfolio_snapshots WHERE run_id = ? ORDER BY snapshot_date",
            (run_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _load_holding_snapshots(run_id: int, database_path: str | Path) -> list[dict[str, Any]]:
    with get_connection(database_path) as connection:
        rows = connection.execute(
            "SELECT * FROM holding_snapshots WHERE run_id = ? AND selected = 1 ORDER BY snapshot_date, symbol",
            (run_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _load_price_frame(database_path: str | Path) -> pd.DataFrame:
    with get_connection(database_path) as connection:
        rows = connection.execute(
            """
            SELECT symbol, price_date, COALESCE(adjusted_close, close) AS price
            FROM market_prices
            WHERE COALESCE(adjusted_close, close) IS NOT NULL
            ORDER BY price_date, symbol
            """
        ).fetchall()
    frame = pd.DataFrame([dict(row) for row in rows])
    if frame.empty:
        return frame
    frame["price_date"] = pd.to_datetime(frame["price_date"]).dt.date
    return frame


def _manifest(run: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    config_payload = json.loads(run.get("config_json") or "{}")
    return {
        "package_schema_version": "1.0.0",
        "strategy_id": config.STRATEGY_PACKAGE_ID,
        "slug": config.STRATEGY_PACKAGE_SLUG,
        "name": config.STRATEGY_PACKAGE_NAME,
        "short_description": config.STRATEGY_PACKAGE_SHORT_DESCRIPTION,
        "category_labels": [
            item.strip()
            for item in config.STRATEGY_PACKAGE_CATEGORY_LABELS.split(",")
            if item.strip()
        ],
        "version": config.STRATEGY_PACKAGE_VERSION,
        "generated_at": datetime.now(IST).replace(microsecond=0).isoformat(),
        "generated_by": f"{config.STRATEGY_PACKAGE_SLUG}-research-project",
        "ra_entity": config.STRATEGY_PACKAGE_RA_ENTITY,
        "sebi_registration_number": config.STRATEGY_PACKAGE_SEBI_REGISTRATION_NUMBER,
        "universe": config.STRATEGY_PACKAGE_UNIVERSE,
        "benchmark": config.STRATEGY_PACKAGE_BENCHMARK,
        "base_currency": config.STRATEGY_PACKAGE_BASE_CURRENCY,
        "backtest_start_date": run["actual_start_date"],
        "backtest_end_date": run["actual_end_date"],
        "lookback_period": "Multi-window trend and risk lookbacks; exact finalized parameters are proprietary.",
        "rebalance_frequency": _rebalance_frequency(summary),
        "target_holdings": int(config_payload.get("strategy_top_n") or summary.get("strategy_top_n") or config.STRATEGY_TOP_N),
        "min_capital_guidance": config.STRATEGY_PACKAGE_MIN_CAPITAL_GUIDANCE,
        "portfolio_as_of_date": run["actual_end_date"],
        "data_frequency": "daily",
        "public_methodology_file": "methodology.md",
        "internal_methodology_file": "methodology_internal.md",
        "public_content_policy": "Do not render internal methodology, finalized config, exact ranking parameters, thresholds, or buffers on public pages.",
        "public_visibility": True,
    }


def _rebalance_frequency(summary: dict[str, Any]) -> str:
    per_month = int(summary.get("rebalances_per_month") or config.BACKTEST_REBALANCES_PER_MONTH)
    if per_month == 1:
        return "monthly"
    if per_month == 2:
        return "twice_monthly"
    return f"{per_month}_times_monthly"


def _reconstruct_daily_returns(
    run: dict[str, Any],
    snapshots: list[dict[str, Any]],
    holdings: list[dict[str, Any]],
    prices: pd.DataFrame,
) -> list[dict[str, Any]]:
    strategy_id = config.STRATEGY_PACKAGE_ID
    if prices.empty:
        return [{"strategy_id": strategy_id, "date": run["actual_start_date"], "return": 0.0, "equity_curve": 1.0}]
    pivot = prices.pivot_table(index="price_date", columns="symbol", values="price", aggfunc="last").sort_index().ffill()
    nav = float(run["initial_capital"])
    rows = [{"strategy_id": strategy_id, "date": run["actual_start_date"], "return": 0.0, "equity_curve": 1.0}]
    previous_date = pd.to_datetime(run["actual_start_date"]).date()
    by_date = _rows_by_date(holdings)
    for snapshot in snapshots:
        end_date = pd.to_datetime(snapshot["snapshot_date"]).date()
        period_holdings = by_date.get(snapshot["snapshot_date"], [])
        weights = {row["symbol"]: float(row.get("weight") or 0.0) for row in period_holdings}
        dates = [item for item in pivot.index if previous_date < item <= end_date]
        for current_date in dates:
            previous_prices = pivot.loc[previous_date] if previous_date in pivot.index else None
            current_prices = pivot.loc[current_date]
            day_return = 0.0
            if previous_prices is not None:
                for symbol, weight in weights.items():
                    if symbol not in pivot.columns:
                        continue
                    start_price = previous_prices[symbol]
                    end_price = current_prices[symbol]
                    if pd.notna(start_price) and pd.notna(end_price) and float(start_price) > 0:
                        day_return += weight * ((float(end_price) / float(start_price)) - 1.0)
            nav *= 1.0 + day_return
            rows.append(
                {
                    "strategy_id": strategy_id,
                    "date": current_date.isoformat(),
                    "return": _clean_float(day_return),
                    "equity_curve": _clean_float(nav / float(run["initial_capital"])),
                }
            )
            previous_date = current_date
        previous_date = end_date
    return rows


def _benchmark_returns(run: dict[str, Any], prices: pd.DataFrame) -> list[dict[str, Any]]:
    strategy_id = config.STRATEGY_PACKAGE_ID
    benchmark_symbol = run["benchmark_symbol"]
    if prices.empty:
        return []
    frame = prices[prices["symbol"] == benchmark_symbol].sort_values("price_date")
    if frame.empty:
        return []
    start = pd.to_datetime(run["actual_start_date"]).date()
    end = pd.to_datetime(run["actual_end_date"]).date()
    frame = frame[(frame["price_date"] >= start) & (frame["price_date"] <= end)].copy()
    if frame.empty:
        return []
    frame["return"] = frame["price"].pct_change(fill_method=None).fillna(0.0)
    first_price = float(frame.iloc[0]["price"])
    frame["equity_curve"] = frame["price"] / first_price if first_price > 0 else 1.0
    return [
        {
            "strategy_id": strategy_id,
            "date": row.price_date.isoformat(),
            "benchmark": config.STRATEGY_PACKAGE_BENCHMARK,
            "return": _clean_float(row.return_),
            "equity_curve": _clean_float(row.equity_curve),
        }
        for row in frame.rename(columns={"return": "return_"}).itertuples()
    ]


def _monthly_returns(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for snapshot in snapshots:
        date_value = pd.to_datetime(snapshot["snapshot_date"]).date()
        rows.append(
            {
                "strategy_id": config.STRATEGY_PACKAGE_ID,
                "year": date_value.year,
                "month": date_value.month,
                "return": _clean_float(snapshot.get("monthly_return") or 0.0),
            }
        )
    return rows


def _yearly_returns(daily: list[dict[str, Any]]) -> list[dict[str, Any]]:
    frame = pd.DataFrame(daily)
    if frame.empty:
        return []
    frame["date"] = pd.to_datetime(frame["date"])
    rows = []
    for year, group in frame.groupby(frame["date"].dt.year):
        cumulative = (1.0 + group["return"].astype(float)).prod() - 1.0
        rows.append({"strategy_id": config.STRATEGY_PACKAGE_ID, "year": int(year), "return": _clean_float(cumulative)})
    return rows


def _drawdowns(daily: list[dict[str, Any]]) -> list[dict[str, Any]]:
    peak = 0.0
    rows = []
    for row in daily:
        equity = float(row["equity_curve"])
        peak = max(peak, equity)
        drawdown = (equity / peak) - 1.0 if peak > 0 else 0.0
        rows.append({"strategy_id": config.STRATEGY_PACKAGE_ID, "date": row["date"], "drawdown": _clean_float(drawdown)})
    return rows


def _metrics(
    run: dict[str, Any],
    snapshots: list[dict[str, Any]],
    daily: list[dict[str, Any]],
    monthly: list[dict[str, Any]],
    yearly: list[dict[str, Any]],
    benchmark: list[dict[str, Any]],
    holdings: list[dict[str, Any]],
) -> dict[str, Any]:
    summary = json.loads(run.get("summary_json") or "{}")
    daily_returns = pd.Series([float(row["return"]) for row in daily if row["date"] != run["actual_start_date"]])
    benchmark_returns = pd.Series([float(row["return"]) for row in benchmark[1:]]) if benchmark else pd.Series(dtype=float)
    total_return = (float(run["final_value"]) / float(run["initial_capital"])) - 1.0
    start = pd.to_datetime(run["actual_start_date"]).date()
    end = pd.to_datetime(run["actual_end_date"]).date()
    years = max((end - start).days / 365.25, 0.0)
    cagr = ((1.0 + total_return) ** (1 / years) - 1.0) if years > 0 else 0.0
    volatility = float(daily_returns.std(ddof=0) * math.sqrt(252)) if len(daily_returns) else 0.0
    downside = daily_returns[daily_returns < 0]
    sortino = cagr / float(downside.std(ddof=0) * math.sqrt(252)) if len(downside) and downside.std(ddof=0) > 0 else 0.0
    sharpe = cagr / volatility if volatility > 0 else 0.0
    max_drawdown = min((row["drawdown"] for row in _drawdowns(daily)), default=0.0)
    calmar = cagr / abs(max_drawdown) if max_drawdown < 0 else 0.0
    beta, alpha = _alpha_beta(daily_returns, benchmark_returns, cagr)
    official_cagr = _summary_float(summary, "cagr", "annualized_return", default=cagr)
    official_total_return = _summary_float(summary, "total_return", default=total_return)
    official_volatility = _summary_float(summary, "volatility", "annualized_volatility", default=volatility)
    official_max_drawdown = _summary_float(summary, "max_drawdown", default=max_drawdown)
    official_sharpe = _summary_float(summary, "sharpe_ratio", "sharpe_like", default=sharpe)
    official_calmar = _summary_float(summary, "calmar_ratio", default=calmar)
    monthly_values = [float(row["return"]) for row in monthly]
    yearly_values = [float(row["return"]) for row in yearly]
    return {
        "cagr": _clean_float(official_cagr),
        "absolute_return": _clean_float(official_total_return),
        "volatility": _clean_float(official_volatility),
        "max_drawdown": _clean_float(official_max_drawdown),
        "sharpe": _clean_float(official_sharpe),
        "sortino": _clean_float(sortino),
        "calmar": _clean_float(official_calmar),
        "beta": _clean_float(beta),
        "alpha": _clean_float(alpha),
        "turnover": _clean_float(_average_turnover(holdings)),
        "average_holding_period_days": int(round(_average_holding_period_months(holdings) * 30.4375)),
        "win_rate": _clean_float(sum(1 for value in monthly_values if value > 0) / len(monthly_values)) if monthly_values else 0.0,
        "best_month": _clean_float(max(monthly_values)) if monthly_values else 0.0,
        "worst_month": _clean_float(min(monthly_values)) if monthly_values else 0.0,
        "best_year": _clean_float(max(yearly_values)) if yearly_values else 0.0,
        "worst_year": _clean_float(min(yearly_values)) if yearly_values else 0.0,
    }


def _alpha_beta(strategy: pd.Series, benchmark: pd.Series, cagr: float) -> tuple[float, float]:
    if strategy.empty or benchmark.empty:
        return 0.0, 0.0
    aligned = pd.concat([strategy.reset_index(drop=True), benchmark.reset_index(drop=True)], axis=1).dropna()
    if aligned.empty:
        return 0.0, 0.0
    variance = aligned.iloc[:, 1].var(ddof=0)
    if variance <= 0:
        return 0.0, 0.0
    beta = float(aligned.iloc[:, 0].cov(aligned.iloc[:, 1]) / variance)
    benchmark_cagr = (1.0 + aligned.iloc[:, 1]).prod() ** (252 / len(aligned)) - 1.0
    return beta, cagr - beta * benchmark_cagr


def _summary_float(summary: dict[str, Any], *keys: str, default: float) -> float:
    for key in keys:
        value = summary.get(key)
        if value is None:
            continue
        number = float(value)
        if math.isfinite(number):
            return number
    return default


def _latest_model_portfolio(
    strategy_id: str,
    holdings: list[dict[str, Any]],
    universe: dict[str, Any],
) -> list[dict[str, Any]]:
    latest_date = max(row["snapshot_date"] for row in holdings)
    entry_dates = _entry_dates(holdings)
    rows = []
    for row in holdings:
        if row["snapshot_date"] != latest_date:
            continue
        stock = universe.get(row["symbol"])
        rows.append(
            {
                "strategy_id": strategy_id,
                "as_of_date": latest_date,
                "symbol": row["symbol"],
                "company_name": getattr(stock, "company_name", row["symbol"]),
                "exchange": getattr(stock, "exchange", "NSE"),
                "isin": getattr(stock, "isin", "") or "",
                "sector": row.get("sector") or getattr(stock, "sector", ""),
                "marketcap_bucket": "",
                "target_weight": _clean_float(row.get("weight") or 0.0),
                "reference_price": _clean_float(row.get("reference_price")),
                "entry_date": entry_dates.get(row["symbol"], latest_date),
                "notes": _holding_note(row),
            }
        )
    validate_weights(rows, "target_weight")
    return rows


def _holdings_history(strategy_id: str, holdings: list[dict[str, Any]], universe: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for row in holdings:
        stock = universe.get(row["symbol"])
        rows.append(
            {
                "strategy_id": strategy_id,
                "date": row["snapshot_date"],
                "symbol": row["symbol"],
                "company_name": getattr(stock, "company_name", row["symbol"]),
                "exchange": getattr(stock, "exchange", "NSE"),
                "isin": getattr(stock, "isin", "") or "",
                "sector": row.get("sector") or getattr(stock, "sector", ""),
                "marketcap_bucket": "",
                "weight": _clean_float(row.get("weight") or 0.0),
                "reference_price": _clean_float(row.get("reference_price")),
            }
        )
    validate_weights(rows, "weight")
    return rows


def _rebalance_history(strategy_id: str, holdings: list[dict[str, Any]], universe: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    previous: dict[str, dict[str, Any]] = {}
    for snapshot_date in sorted(_rows_by_date(holdings)):
        current = {row["symbol"]: row for row in _rows_by_date(holdings)[snapshot_date]}
        symbols = sorted(set(previous) | set(current))
        for symbol in symbols:
            old = previous.get(symbol)
            new = current.get(symbol)
            old_weight = float(old.get("weight") or 0.0) if old else 0.0
            new_weight = float(new.get("weight") or 0.0) if new else 0.0
            if abs(old_weight - new_weight) < 1e-8 and old and new:
                continue
            stock = universe.get(symbol)
            rows.append(
                {
                    "strategy_id": strategy_id,
                    "rebalance_date": snapshot_date,
                    "symbol": symbol,
                    "company_name": getattr(stock, "company_name", symbol),
                    "action": _rebalance_action(old_weight, new_weight),
                    "old_weight": _clean_float(old_weight),
                    "new_weight": _clean_float(new_weight),
                    "old_reference_price": _clean_float(old.get("reference_price") if old else None),
                    "new_reference_price": _clean_float(new.get("reference_price") if new else None),
                    "rationale": f"Rebalanced according to the {config.STRATEGY_PACKAGE_NAME} model rules.",
                }
            )
        previous = current
    return rows


def _exposure_rows(strategy_id: str, latest_portfolio: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    exposure: dict[str, float] = {}
    as_of_date = latest_portfolio[0]["as_of_date"] if latest_portfolio else ""
    for row in latest_portfolio:
        bucket = row.get(field) or "Unclassified"
        exposure[bucket] = exposure.get(bucket, 0.0) + float(row["target_weight"])
    output_field = "sector" if field == "sector" else "marketcap_bucket"
    return [
        {"strategy_id": strategy_id, "as_of_date": as_of_date, output_field: key, "weight": _clean_float(value)}
        for key, value in sorted(exposure.items())
    ]


def _rows_by_date(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        result.setdefault(row["snapshot_date"], []).append(row)
    return result


def _entry_dates(holdings: list[dict[str, Any]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in holdings:
        if row.get("holding_action") in {"ENTERED", "SAFE_ASSET"} or row["symbol"] not in result:
            result[row["symbol"]] = row["snapshot_date"]
    return result


def _holding_note(row: dict[str, Any]) -> str:
    rank = row.get("rank")
    if rank:
        return f"Selected by model rank {rank}."
    if row.get("holding_action") == "SAFE_ASSET":
        return "Residual safe-asset/cash allocation."
    return "Selected by model rules."


def _rebalance_action(old_weight: float, new_weight: float) -> str:
    if old_weight <= 0 and new_weight > 0:
        return "ADDED"
    if old_weight > 0 and new_weight <= 0:
        return "REMOVED"
    return "WEIGHT_CHANGED"


def _average_turnover(holdings: list[dict[str, Any]]) -> float:
    previous: dict[str, float] = {}
    turnovers = []
    for snapshot_date in sorted(_rows_by_date(holdings)):
        current = {row["symbol"]: float(row.get("weight") or 0.0) for row in _rows_by_date(holdings)[snapshot_date]}
        symbols = set(previous) | set(current)
        turnovers.append(0.5 * sum(abs(current.get(symbol, 0.0) - previous.get(symbol, 0.0)) for symbol in symbols))
        previous = current
    return sum(turnovers) / len(turnovers) if turnovers else 0.0


def _average_holding_period_months(holdings: list[dict[str, Any]]) -> float:
    values = [float(row.get("total_months_held") or 0.0) for row in holdings if row.get("total_months_held")]
    return sum(values) / len(values) if values else 0.0


def _write_csv(output_path: Path, filename: str, rows: list[dict[str, Any]]) -> None:
    validate_csv_rows(filename, rows)
    write_csv(output_path / filename, CSV_HEADERS[filename], rows)


def _document_text(path_value: str | Path, fallback: str) -> str:
    path = Path(path_value)
    if path.exists():
        return path.read_text(encoding="utf-8")
    return fallback


def _clean_float(value: Any) -> float | str:
    if value in ("", None):
        return ""
    number = float(value)
    if not math.isfinite(number):
        return ""
    return round(number, 10)
