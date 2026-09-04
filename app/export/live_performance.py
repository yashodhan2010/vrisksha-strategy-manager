from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from app import config
from app.backtest.distributions import distribution_per_unit, load_distribution_events
from app.backtest.engine import _bounded_forward_fill
from app.data.universe_loader import load_universe
from app.export.writers import write_json
from app.storage.database import get_connection
from app.storage.market_data_repository import get_symbol_price_coverage, load_market_prices
from app.strategy_profile import load_strategy_profile
from app.strategy.models import RunStatus, RunType


@dataclass(frozen=True)
class LiveSnapshot:
    run_id: int
    snapshot_date: date
    weights: dict[str, float]
    reference_prices: dict[str, float | None]
    holding_rows: list[dict[str, Any]]
    liquidbees_weight: float


def export_live_performance_dashboard(
    output_dir: str | Path | None = None,
    strategy_id: str | None = None,
    strategy_slug: str | None = None,
    database_path: str | Path = config.DATABASE_PATH,
) -> Path:
    strategy_id = strategy_id or config.STRATEGY_PACKAGE_ID
    strategy_slug = strategy_slug or config.STRATEGY_PACKAGE_SLUG
    output_path = Path(output_dir or Path("data/output/live-performance") / strategy_slug)
    output_path.mkdir(parents=True, exist_ok=True)

    snapshots = _load_live_snapshots(strategy_id, database_path)
    prices = _price_frame(database_path)
    universe = {stock.symbol: stock for stock in load_universe()}
    warnings: list[str] = []

    if snapshots and not prices.empty:
        daily, benchmark, attribution, current_holdings, rebalance_rows, warnings = _compute_live_performance(
            strategy_id=strategy_id,
            snapshots=snapshots,
            prices=prices,
            universe=universe,
        )
    else:
        daily = []
        benchmark = []
        attribution = []
        current_holdings = []
        rebalance_rows = []
        if not snapshots:
            warnings.append("No completed live monthly rebalance snapshots found for this strategy.")
        if prices.empty:
            warnings.append("No market prices found.")

    backtest = _latest_backtest_series(strategy_id, database_path)
    drawdowns = _drawdowns(daily)
    metrics = _metrics(daily, benchmark)
    data_quality = _data_quality(snapshots, prices, database_path)
    manifest = _manifest(strategy_id, strategy_slug, snapshots, daily, metrics, warnings)
    dashboard_data = {
        "manifest": manifest,
        "metrics": metrics,
        "data_quality": data_quality,
        "daily": daily,
        "drawdowns": drawdowns,
        "benchmark": benchmark,
        "backtest": backtest,
        "attribution": attribution,
        "current_holdings": current_holdings,
        "rebalance_history": rebalance_rows,
        "warnings": warnings,
    }

    write_json(output_path / "manifest.json", manifest)
    write_json(output_path / "dashboard_data.json", dashboard_data)
    _write_csv(output_path / "live_nav.csv", ["date", "return", "equity_curve", "nav"], daily)
    _write_csv(output_path / "live_drawdowns.csv", ["date", "drawdown"], drawdowns)
    _write_csv(output_path / "live_benchmark.csv", ["date", "return", "equity_curve"], benchmark)
    _write_csv(output_path / "live_attribution.csv", ["symbol", "weight", "contribution"], attribution)
    _write_csv(
        output_path / "live_current_holdings.csv",
        ["symbol", "company_name", "sector", "weight", "reference_price", "current_price", "market_value", "notes"],
        current_holdings,
    )
    _write_csv(
        output_path / "live_rebalance_history.csv",
        ["run_id", "snapshot_date", "holding_count", "stock_weight", "safe_asset_weight"],
        rebalance_rows,
    )
    (output_path / "index.html").write_text(_html(dashboard_data), encoding="utf-8")
    return output_path


def export_live_performance_tracker_index(
    output_dir: str | Path = "data/output/live-performance",
    registry_path: str | Path = "strategies/registry.json",
) -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    strategies = _load_tracker_strategies(output_path, registry_path)
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "strategies": strategies,
    }
    write_json(output_path / "tracker_data.json", payload)
    (output_path / "index.html").write_text(_tracker_html(payload), encoding="utf-8")
    return output_path


def _load_tracker_strategies(output_path: Path, registry_path: str | Path) -> list[dict[str, Any]]:
    registry = _json_loads(Path(registry_path).read_text(encoding="utf-8")) if Path(registry_path).exists() else {}
    rows = []
    for profile_path in registry.get("strategies", []):
        profile = load_strategy_profile(profile_path)
        slug = str(profile["slug"])
        data_path = output_path / slug / "dashboard_data.json"
        if data_path.exists():
            data = json.loads(data_path.read_text(encoding="utf-8"))
            _normalize_strategy_dashboard(data)
        else:
            data = _package_proxy_dashboard(profile) or _empty_strategy_dashboard(profile)
        data["profile_path"] = profile_path
        rows.append(data)
    return rows


def _normalize_strategy_dashboard(data: dict[str, Any]) -> None:
    manifest = data.setdefault("manifest", {})
    if not manifest.get("report_source"):
        manifest["report_source"] = "live_rebalance"
    manifest.setdefault("distributions_included", False)
    manifest.setdefault("distribution_events_path", "")


def _package_proxy_dashboard(profile: dict[str, Any]) -> dict[str, Any] | None:
    package_dir = Path((profile.get("package") or {}).get("output_dir") or "")
    if not package_dir or not package_dir.exists():
        return None
    returns_daily = _read_csv(package_dir / "returns_daily.csv")
    if not returns_daily:
        return None
    benchmark = _read_csv(package_dir / "benchmark_returns.csv")
    drawdowns = _read_csv(package_dir / "drawdowns.csv")
    latest_portfolio = _read_csv(package_dir / "latest_model_portfolio.csv")
    rebalance_history = _read_csv(package_dir / "rebalance_history.csv")
    metrics_json = _json_loads((package_dir / "backtest_metrics.json").read_text(encoding="utf-8")) if (package_dir / "backtest_metrics.json").exists() else {}
    package_manifest = _json_loads((package_dir / "manifest.json").read_text(encoding="utf-8")) if (package_dir / "manifest.json").exists() else {}
    distribution_path = str((profile.get("distribution") or {}).get("events_path") or "")
    distributions_included = bool(distribution_path and Path(distribution_path).exists())
    daily = [
        {
            "date": row["date"],
            "return": _clean_float(row.get("return")),
            "equity_curve": _clean_float(row.get("equity_curve")),
            "nav": _clean_float(config.TARGET_PORTFOLIO_VALUE * float(row.get("equity_curve") or 0.0)),
        }
        for row in returns_daily
    ]
    benchmark_rows = [
        {
            "date": row["date"],
            "return": _clean_float(row.get("return")),
            "equity_curve": _clean_float(row.get("equity_curve")),
        }
        for row in benchmark
    ]
    drawdown_rows = [
        {"date": row["date"], "drawdown": _clean_float(row.get("drawdown"))}
        for row in drawdowns
    ] or _drawdowns(daily)
    current_holdings = [
        {
            "symbol": row.get("symbol"),
            "company_name": row.get("company_name"),
            "sector": row.get("sector"),
            "weight": _clean_float(row.get("target_weight")),
            "reference_price": _clean_float(row.get("reference_price")),
            "current_price": _clean_float(row.get("reference_price")),
            "market_value": _clean_float(config.TARGET_PORTFOLIO_VALUE * float(row.get("target_weight") or 0.0)),
            "notes": "Backtest/package proxy holding",
        }
        for row in latest_portfolio
    ]
    rebalance_rows = _package_rebalance_rows(rebalance_history)
    metrics = {
        "total_return": _clean_float(metrics_json.get("absolute_return")),
        "annualized_return": _clean_float(metrics_json.get("cagr")),
        "max_drawdown": _clean_float(metrics_json.get("max_drawdown")),
        "benchmark_total_return": _clean_float(float(benchmark_rows[-1]["equity_curve"]) - 1.0) if benchmark_rows else None,
        "excess_return": None,
        "win_rate": _clean_float(metrics_json.get("win_rate")),
        "day_count": len(daily),
    }
    if metrics["total_return"] is not None and metrics["benchmark_total_return"] is not None:
        metrics["excess_return"] = _clean_float(float(metrics["total_return"]) - float(metrics["benchmark_total_return"]))
    warning = "Backtest/package proxy, not actual live tracker data."
    if distributions_included:
        warning += " Dividend/distribution events are included where configured in the package backtest."
    manifest = {
        "report_type": "internal_live_performance",
        "report_source": "backtest_proxy",
        "strategy_id": profile["strategy_id"],
        "slug": profile["slug"],
        "name": profile.get("name") or profile["slug"],
        "public_name": profile.get("public_name") or profile.get("name") or profile["slug"],
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "live_inception_date": daily[0]["date"] if daily else None,
        "latest_live_date": daily[-1]["date"] if daily else None,
        "target_portfolio_value": config.TARGET_PORTFOLIO_VALUE,
        "benchmark": profile.get("benchmark") or package_manifest.get("benchmark") or "",
        "metrics": metrics,
        "warning_count": 1,
        "internal_only": True,
        "distributions_included": distributions_included,
        "distribution_events_path": distribution_path,
    }
    return {
        "manifest": manifest,
        "metrics": metrics,
        "data_quality": {
            "live_rebalance_count": 0,
            "live_inception_date": None,
            "latest_rebalance_date": None,
            "latest_price_date": daily[-1]["date"] if daily else None,
            "tracked_symbols": len(current_holdings),
            "missing_price_symbols": [],
            "stale_price_symbols": [],
            "source": "backtest_proxy",
            "distributions_included": distributions_included,
            "distribution_events_path": distribution_path,
        },
        "daily": daily,
        "drawdowns": drawdown_rows,
        "benchmark": benchmark_rows,
        "backtest": daily,
        "attribution": [],
        "current_holdings": current_holdings,
        "rebalance_history": rebalance_rows,
        "warnings": [warning],
    }


def _package_rebalance_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    by_date: dict[str, dict[str, float]] = {}
    for row in rows:
        date_value = str(row.get("rebalance_date") or "")
        if not date_value:
            continue
        item = by_date.setdefault(date_value, {"holding_count": 0, "stock_weight": 0.0, "safe_asset_weight": 0.0})
        item["holding_count"] += 1
        symbol = str(row.get("symbol") or "").upper()
        weight = float(row.get("new_weight") or 0.0)
        if symbol in {config.SAFE_ASSET_SYMBOL, config.SAFE_ASSET_FALLBACK_SYMBOL}:
            item["safe_asset_weight"] += weight
        else:
            item["stock_weight"] += weight
    return [
        {
            "run_id": "",
            "snapshot_date": date_value,
            "holding_count": int(item["holding_count"]),
            "stock_weight": _clean_float(item["stock_weight"]),
            "safe_asset_weight": _clean_float(item["safe_asset_weight"]),
        }
        for date_value, item in sorted(by_date.items())
    ]


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _empty_strategy_dashboard(profile: dict[str, Any]) -> dict[str, Any]:
    manifest = {
        "report_type": "internal_live_performance",
        "report_source": "missing",
        "strategy_id": profile["strategy_id"],
        "slug": profile["slug"],
        "name": profile.get("name") or profile["slug"],
        "public_name": profile.get("public_name") or profile.get("name") or profile["slug"],
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "live_inception_date": None,
        "latest_live_date": None,
        "target_portfolio_value": config.TARGET_PORTFOLIO_VALUE,
        "benchmark": profile.get("benchmark") or "",
        "metrics": _metrics([], []),
        "warning_count": 1,
        "internal_only": True,
        "distributions_included": False,
        "distribution_events_path": str((profile.get("distribution") or {}).get("events_path") or ""),
    }
    return {
        "manifest": manifest,
        "metrics": manifest["metrics"],
        "data_quality": {
            "live_rebalance_count": 0,
            "live_inception_date": None,
            "latest_rebalance_date": None,
            "latest_price_date": None,
            "tracked_symbols": 0,
            "missing_price_symbols": [],
            "stale_price_symbols": [],
        },
        "daily": [],
        "drawdowns": [],
        "benchmark": [],
        "backtest": [],
        "attribution": [],
        "current_holdings": [],
        "rebalance_history": [],
        "warnings": ["No live-performance artifact has been generated for this strategy yet."],
    }


def _load_live_snapshots(strategy_id: str, database_path: str | Path) -> list[LiveSnapshot]:
    with get_connection(database_path) as connection:
        runs = connection.execute(
            """
            SELECT *
            FROM strategy_runs
            WHERE run_type = ? AND status = ?
            ORDER BY id
            """,
            (RunType.MONTHLY.value, RunStatus.COMPLETED.value),
        ).fetchall()
        selected_run_ids = []
        for run in runs:
            payload = _json_loads(run["config_json"])
            if payload.get("strategy_id") == strategy_id:
                selected_run_ids.append(int(run["id"]))
        if not selected_run_ids:
            return []

        snapshots: list[LiveSnapshot] = []
        for run_id in selected_run_ids:
            holdings = connection.execute(
                """
                SELECT *
                FROM holding_snapshots
                WHERE run_id = ? AND selected = 1 AND monthly_return IS NULL
                ORDER BY snapshot_date, rank, symbol
                """,
                (run_id,),
            ).fetchall()
            if not holdings:
                continue
            dates = sorted({date.fromisoformat(str(row["snapshot_date"])) for row in holdings})
            snapshot_date = dates[-1]
            rows = [dict(row) for row in holdings if date.fromisoformat(str(row["snapshot_date"])) == snapshot_date]
            portfolio = connection.execute(
                """
                SELECT *
                FROM portfolio_snapshots
                WHERE run_id = ? AND snapshot_date = ? AND monthly_return IS NULL
                ORDER BY id DESC
                LIMIT 1
                """,
                (run_id, snapshot_date.isoformat()),
            ).fetchone()
            liquidbees_weight = float(portfolio["liquidbees_weight"] or 0.0) if portfolio else 0.0
            _add_virtual_safe_asset_row(rows, run_id, snapshot_date, liquidbees_weight)
            weights = {str(row["symbol"]).upper(): float(row.get("weight") or 0.0) for row in rows}
            reference_prices = {
                str(row["symbol"]).upper(): _optional_float(row.get("reference_price"))
                for row in rows
            }
            snapshots.append(
                LiveSnapshot(
                    run_id=run_id,
                    snapshot_date=snapshot_date,
                    weights=weights,
                    reference_prices=reference_prices,
                    holding_rows=rows,
                    liquidbees_weight=liquidbees_weight,
                )
            )

    by_date: dict[date, LiveSnapshot] = {}
    for snapshot in snapshots:
        existing = by_date.get(snapshot.snapshot_date)
        if existing is None or snapshot.run_id > existing.run_id:
            by_date[snapshot.snapshot_date] = snapshot
    return [by_date[item] for item in sorted(by_date)]


def _add_virtual_safe_asset_row(
    rows: list[dict[str, Any]],
    run_id: int,
    snapshot_date: date,
    liquidbees_weight: float,
) -> None:
    if liquidbees_weight <= 0:
        return
    safe_asset = config.SAFE_ASSET_SYMBOL
    if any(str(row["symbol"]).upper() == safe_asset for row in rows):
        return
    rows.append(
        {
            "run_id": run_id,
            "snapshot_date": snapshot_date.isoformat(),
            "symbol": safe_asset,
            "industry": "SAFE_ASSET",
            "sector": "SAFE_ASSET",
            "rank": None,
            "selected": 1,
            "weight": liquidbees_weight,
            "quantity": None,
            "reference_price": None,
            "market_value": None,
            "monthly_return": None,
            "portfolio_contribution": None,
            "holding_action": "SAFE_ASSET",
            "consecutive_months_held": 0,
            "total_months_held": 0,
        }
    )


def _price_frame(database_path: str | Path) -> pd.DataFrame:
    frame = pd.DataFrame(load_market_prices(database_path))
    if frame.empty:
        return frame
    frame["price_date"] = pd.to_datetime(frame["price_date"]).dt.date
    frame["price"] = frame["adjusted_close"].fillna(frame["close"])
    return frame.dropna(subset=["price"])


def _compute_live_performance(
    strategy_id: str,
    snapshots: list[LiveSnapshot],
    prices: pd.DataFrame,
    universe: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    start_date = snapshots[0].snapshot_date
    symbols = sorted({symbol for snapshot in snapshots for symbol in snapshot.weights} | {config.DEFAULT_BENCHMARK_SYMBOL})
    pivot = _bounded_forward_fill(
        prices[prices["symbol"].isin(symbols)].pivot_table(index="price_date", columns="symbol", values="price", aggfunc="last").sort_index()
    )
    if pivot.empty:
        return [], [], [], [], [], ["No usable price pivot found for live holdings."]
    end_date = max(pivot.index)
    price_dates = [item for item in pivot.index if start_date <= item <= end_date]
    if not price_dates:
        return [], [], [], [], [], ["No price dates overlap the live performance window."]
    distributions = load_distribution_events(config.DISTRIBUTION_EVENTS_PATH, symbols, start_date, end_date, warnings)

    snapshot_by_date = {snapshot.snapshot_date: snapshot for snapshot in snapshots}
    current_snapshot = snapshots[0]
    equity = 1.0
    daily = [{"date": start_date.isoformat(), "return": 0.0, "equity_curve": 1.0, "nav": config.TARGET_PORTFOLIO_VALUE}]
    contribution_by_symbol = {symbol: 0.0 for symbol in current_snapshot.weights}
    previous_date = start_date
    missing_pairs: set[str] = set()
    for current_date in price_dates:
        if current_date <= start_date:
            continue
        day_return = 0.0
        for symbol, weight in current_snapshot.weights.items():
            if symbol not in pivot.columns:
                missing_pairs.add(symbol)
                continue
            start_price = pivot.at[previous_date, symbol] if previous_date in pivot.index else pd.NA
            end_price = pivot.at[current_date, symbol]
            if pd.notna(start_price) and pd.notna(end_price) and float(start_price) > 0:
                distribution_return = distribution_per_unit(distributions, symbol, previous_date, current_date) / float(start_price)
                symbol_return = (float(end_price) / float(start_price)) - 1.0 + distribution_return
                contribution = weight * symbol_return
                day_return += contribution
                contribution_by_symbol[symbol] = contribution_by_symbol.get(symbol, 0.0) + contribution
            else:
                missing_pairs.add(symbol)
        equity *= 1.0 + day_return
        daily.append(
            {
                "date": current_date.isoformat(),
                "return": _clean_float(day_return),
                "equity_curve": _clean_float(equity),
                "nav": _clean_float(config.TARGET_PORTFOLIO_VALUE * equity),
            }
        )
        previous_date = current_date
        if current_date in snapshot_by_date:
            current_snapshot = snapshot_by_date[current_date]
            for symbol in current_snapshot.weights:
                contribution_by_symbol.setdefault(symbol, 0.0)

    if missing_pairs:
        warnings.append(f"Skipped live contribution for symbols with missing prices: {', '.join(sorted(missing_pairs)[:20])}.")

    benchmark = _benchmark_series(pivot, start_date, end_date)
    latest_snapshot = snapshots[-1]
    current_holdings = _current_holdings(latest_snapshot, pivot, universe)
    attribution = _attribution_rows(contribution_by_symbol, latest_snapshot.weights)
    rebalance_rows = _rebalance_rows(snapshots)
    return daily, benchmark, attribution, current_holdings, rebalance_rows, warnings


def _benchmark_series(pivot: pd.DataFrame, start_date: date, end_date: date) -> list[dict[str, Any]]:
    if config.DEFAULT_BENCHMARK_SYMBOL not in pivot.columns:
        return []
    frame = pivot.loc[(pivot.index >= start_date) & (pivot.index <= end_date), [config.DEFAULT_BENCHMARK_SYMBOL]].dropna()
    if frame.empty:
        return []
    prices = frame[config.DEFAULT_BENCHMARK_SYMBOL].astype(float)
    returns = prices.pct_change(fill_method=None).fillna(0.0)
    first_price = float(prices.iloc[0])
    equity = prices / first_price if first_price > 0 else prices * 0.0 + 1.0
    return [
        {
            "date": item.isoformat(),
            "return": _clean_float(float(returns.loc[item])),
            "equity_curve": _clean_float(float(equity.loc[item])),
        }
        for item in frame.index
    ]


def _current_holdings(snapshot: LiveSnapshot, pivot: pd.DataFrame, universe: dict[str, Any]) -> list[dict[str, Any]]:
    latest_price_date = max(pivot.index) if not pivot.empty else snapshot.snapshot_date
    rows = []
    for row in snapshot.holding_rows:
        symbol = str(row["symbol"]).upper()
        stock = universe.get(symbol)
        current_price = _pivot_price(pivot, symbol, latest_price_date)
        reference_price = _optional_float(row.get("reference_price")) or snapshot.reference_prices.get(symbol) or current_price
        weight = float(row.get("weight") or 0.0)
        rows.append(
            {
                "symbol": symbol,
                "company_name": getattr(stock, "company_name", symbol),
                "sector": row.get("sector") or getattr(stock, "sector", ""),
                "weight": _clean_float(weight),
                "reference_price": _clean_float(reference_price),
                "current_price": _clean_float(current_price),
                "market_value": _clean_float(config.TARGET_PORTFOLIO_VALUE * weight),
                "notes": "Safe asset allocation" if row.get("holding_action") == "SAFE_ASSET" else str(row.get("holding_action") or ""),
            }
        )
    return sorted(rows, key=lambda item: (-float(item["weight"]), str(item["symbol"])))


def _pivot_price(pivot: pd.DataFrame, symbol: str, price_date: date) -> float | None:
    if symbol not in pivot.columns or price_date not in pivot.index:
        return None
    value = pivot.at[price_date, symbol]
    return float(value) if pd.notna(value) else None


def _attribution_rows(contribution_by_symbol: dict[str, float], latest_weights: dict[str, float]) -> list[dict[str, Any]]:
    rows = [
        {
            "symbol": symbol,
            "weight": _clean_float(latest_weights.get(symbol, 0.0)),
            "contribution": _clean_float(contribution),
        }
        for symbol, contribution in contribution_by_symbol.items()
    ]
    return sorted(rows, key=lambda item: abs(float(item["contribution"])), reverse=True)


def _rebalance_rows(snapshots: list[LiveSnapshot]) -> list[dict[str, Any]]:
    rows = []
    for snapshot in snapshots:
        total_stock_weight = sum(
            weight for symbol, weight in snapshot.weights.items() if symbol not in {config.SAFE_ASSET_SYMBOL, config.SAFE_ASSET_FALLBACK_SYMBOL}
        )
        rows.append(
            {
                "run_id": snapshot.run_id,
                "snapshot_date": snapshot.snapshot_date.isoformat(),
                "holding_count": len(snapshot.weights),
                "stock_weight": _clean_float(total_stock_weight),
                "safe_asset_weight": _clean_float(snapshot.weights.get(config.SAFE_ASSET_SYMBOL, 0.0)),
            }
        )
    return rows


def _latest_backtest_series(strategy_id: str, database_path: str | Path) -> list[dict[str, Any]]:
    with get_connection(database_path) as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM backtest_runs
            WHERE status = ?
            ORDER BY id DESC
            """,
            (RunStatus.COMPLETED.value,),
        ).fetchall()
        run = None
        for row in rows:
            payload = _json_loads(row["config_json"])
            if payload.get("strategy_id") == strategy_id:
                run = dict(row)
                break
        if not run or not run.get("actual_start_date"):
            return []
        snapshots = connection.execute(
            """
            SELECT *
            FROM portfolio_snapshots
            WHERE run_id = ? AND monthly_return IS NOT NULL
                AND snapshot_date >= ? AND snapshot_date <= ?
            ORDER BY snapshot_date
            """,
            (run["id"], run["actual_start_date"], run["actual_end_date"]),
        ).fetchall()
    if not snapshots:
        return []
    initial_capital = float(run["initial_capital"] or config.TARGET_PORTFOLIO_VALUE)
    result = [{"date": run["actual_start_date"], "equity_curve": 1.0}]
    for snapshot in snapshots:
        nav = float(snapshot["portfolio_nav"] or 0.0)
        result.append({"date": snapshot["snapshot_date"], "equity_curve": _clean_float(nav / initial_capital if initial_capital > 0 else 1.0)})
    return result


def _drawdowns(daily: list[dict[str, Any]]) -> list[dict[str, Any]]:
    peak = 0.0
    rows = []
    for row in daily:
        equity = float(row["equity_curve"])
        peak = max(peak, equity)
        rows.append({"date": row["date"], "drawdown": _clean_float((equity / peak) - 1.0 if peak > 0 else 0.0)})
    return rows


def _metrics(daily: list[dict[str, Any]], benchmark: list[dict[str, Any]]) -> dict[str, Any]:
    if not daily:
        return {
            "total_return": None,
            "annualized_return": None,
            "max_drawdown": None,
            "benchmark_total_return": None,
            "excess_return": None,
            "win_rate": None,
            "day_count": 0,
        }
    start = date.fromisoformat(str(daily[0]["date"]))
    end = date.fromisoformat(str(daily[-1]["date"]))
    total_return = float(daily[-1]["equity_curve"]) - 1.0
    years = max((end - start).days / 365.25, 0.0)
    annualized = (1.0 + total_return) ** (1.0 / years) - 1.0 if years > 0 and total_return > -1.0 else None
    drawdown = min((float(row["drawdown"]) for row in _drawdowns(daily)), default=0.0)
    returns = [float(row["return"]) for row in daily[1:]]
    benchmark_total = float(benchmark[-1]["equity_curve"]) - 1.0 if benchmark else None
    return {
        "total_return": _clean_float(total_return),
        "annualized_return": _clean_float(annualized),
        "max_drawdown": _clean_float(drawdown),
        "benchmark_total_return": _clean_float(benchmark_total),
        "excess_return": _clean_float(total_return - benchmark_total) if benchmark_total is not None else None,
        "win_rate": _clean_float(sum(1 for item in returns if item > 0) / len(returns)) if returns else None,
        "day_count": len(daily),
    }


def _data_quality(snapshots: list[LiveSnapshot], prices: pd.DataFrame, database_path: str | Path) -> dict[str, Any]:
    symbols = sorted({symbol for snapshot in snapshots for symbol in snapshot.weights})
    end_date = max(prices["price_date"]) if not prices.empty else date.today()
    coverage = get_symbol_price_coverage(symbols, end_date, database_path) if symbols else {}
    missing = [symbol for symbol in symbols if symbol not in coverage]
    stale = [
        symbol
        for symbol in symbols
        if symbol in coverage and coverage[symbol].get("last_price_date") and coverage[symbol]["last_price_date"] < end_date.isoformat()
    ]
    return {
        "live_rebalance_count": len(snapshots),
        "live_inception_date": snapshots[0].snapshot_date.isoformat() if snapshots else None,
        "latest_rebalance_date": snapshots[-1].snapshot_date.isoformat() if snapshots else None,
        "latest_price_date": end_date.isoformat() if isinstance(end_date, date) else str(end_date),
        "tracked_symbols": len(symbols),
        "missing_price_symbols": missing,
        "stale_price_symbols": stale[:20],
    }


def _manifest(
    strategy_id: str,
    strategy_slug: str,
    snapshots: list[LiveSnapshot],
    daily: list[dict[str, Any]],
    metrics: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "report_type": "internal_live_performance",
        "report_source": "live_rebalance",
        "strategy_id": strategy_id,
        "slug": strategy_slug,
        "name": config.STRATEGY_PACKAGE_NAME,
        "public_name": config.STRATEGY_PACKAGE_PUBLIC_NAME,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "live_inception_date": snapshots[0].snapshot_date.isoformat() if snapshots else None,
        "latest_live_date": daily[-1]["date"] if daily else None,
        "target_portfolio_value": config.TARGET_PORTFOLIO_VALUE,
        "benchmark": config.STRATEGY_PACKAGE_BENCHMARK,
        "metrics": metrics,
        "warning_count": len(warnings),
        "internal_only": True,
        "distributions_included": bool(config.DISTRIBUTION_EVENTS_PATH),
        "distribution_events_path": config.DISTRIBUTION_EVENTS_PATH,
    }


def _write_csv(path: Path, headers: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in headers})


def _json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _optional_float(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _clean_float(value: Any) -> float | None:
    number = _optional_float(value)
    if number is None:
        return None
    return round(number, 10)


def _html(data: dict[str, Any]) -> str:
    payload = json.dumps(data).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Internal Live Performance - {data["manifest"]["public_name"]}</title>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <style>
    :root {{
      --ink: #18211f;
      --muted: #62706a;
      --line: #d9e1dc;
      --panel: #ffffff;
      --soft: #f3f7f4;
      --live: #16836b;
      --backtest: #7891a6;
      --danger: #a64242;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #eef3ef;
      color: var(--ink);
    }}
    header {{
      padding: 28px 34px 20px;
      background: linear-gradient(180deg, #fbfdfb, #eef3ef);
      border-bottom: 1px solid var(--line);
    }}
    .eyebrow {{ color: var(--live); font-weight: 700; font-size: 12px; letter-spacing: .08em; text-transform: uppercase; }}
    h1 {{ margin: 6px 0 6px; font-size: clamp(28px, 4vw, 48px); letter-spacing: 0; }}
    .subtitle {{ margin: 0; max-width: 980px; color: var(--muted); line-height: 1.5; }}
    main {{ padding: 22px 34px 38px; }}
    .toolbar {{ display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 18px; }}
    button {{
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      padding: 9px 13px;
      border-radius: 7px;
      cursor: pointer;
      font-weight: 650;
    }}
    button.active {{ background: var(--live); border-color: var(--live); color: #fff; }}
    .grid {{ display: grid; gap: 16px; }}
    .kpis {{ grid-template-columns: repeat(6, minmax(130px, 1fr)); }}
    .two {{ grid-template-columns: minmax(0, 2fr) minmax(320px, 1fr); align-items: start; }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
      box-shadow: 0 1px 2px rgba(20, 35, 30, .04);
    }}
    .metric-label {{ color: var(--muted); font-size: 12px; margin-bottom: 8px; }}
    .metric-value {{ font-size: 24px; font-weight: 760; white-space: nowrap; }}
    .metric-sub {{ color: var(--muted); font-size: 12px; margin-top: 6px; }}
    .section-title {{ margin: 0 0 12px; font-size: 18px; }}
    .chart {{ height: 390px; }}
    .small-chart {{ height: 260px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ padding: 10px 8px; border-bottom: 1px solid var(--line); text-align: left; }}
    th {{ color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .06em; }}
    .pill {{ display: inline-flex; align-items: center; padding: 4px 8px; border-radius: 999px; background: var(--soft); color: var(--muted); font-size: 12px; }}
    .warn {{ color: var(--danger); }}
    @media (max-width: 1050px) {{
      .kpis, .two {{ grid-template-columns: 1fr; }}
      main, header {{ padding-left: 18px; padding-right: 18px; }}
    }}
  </style>
</head>
<body>
  <script id="dashboard-data" type="application/json">{payload}</script>
  <header>
    <div class="eyebrow">Internal live tracker</div>
    <h1 id="title"></h1>
    <p class="subtitle" id="subtitle"></p>
  </header>
  <main>
    <div class="toolbar">
      <button data-mode="combined" class="active">Backtest + Live</button>
      <button data-mode="live">Live Only</button>
      <button data-mode="backtest">Backtest Only</button>
      <button data-mode="normalized">Normalize From Live Inception</button>
    </div>
    <section class="grid kpis" id="kpis"></section>
    <section class="grid two" style="margin-top:16px">
      <div class="panel">
        <h2 class="section-title">Growth Of Capital</h2>
        <div id="growth" class="chart"></div>
      </div>
      <div class="panel">
        <h2 class="section-title">Data Quality</h2>
        <div id="quality"></div>
      </div>
    </section>
    <section class="grid two" style="margin-top:16px">
      <div class="panel">
        <h2 class="section-title">Drawdown</h2>
        <div id="drawdown" class="small-chart"></div>
      </div>
      <div class="panel">
        <h2 class="section-title">Daily Returns</h2>
        <div id="returns" class="small-chart"></div>
      </div>
    </section>
    <section class="grid two" style="margin-top:16px">
      <div class="panel">
        <h2 class="section-title">Current Model Portfolio</h2>
        <div id="holdings"></div>
      </div>
      <div class="panel">
        <h2 class="section-title">Top Contribution Since Inception</h2>
        <div id="attribution"></div>
      </div>
    </section>
    <section class="panel" style="margin-top:16px">
      <h2 class="section-title">Rebalance Trail</h2>
      <div id="rebalances"></div>
    </section>
  </main>
  <script>
    const data = JSON.parse(document.getElementById('dashboard-data').textContent);
    const fmtPct = value => value === null || value === undefined ? 'n/a' : (value * 100).toFixed(2) + '%';
    const fmtNum = value => value === null || value === undefined ? 'n/a' : Number(value).toLocaleString('en-IN', {{ maximumFractionDigits: 2 }});
    document.getElementById('title').textContent = data.manifest.public_name || data.manifest.name;
    document.getElementById('subtitle').textContent = `Live inception: ${{data.manifest.live_inception_date || 'n/a'}}. Latest live date: ${{data.manifest.latest_live_date || 'n/a'}}. Internal-only model performance reconstructed from stored rebalance snapshots and market prices.`;

    const kpis = [
      ['Live return', fmtPct(data.metrics.total_return)],
      ['Annualized', fmtPct(data.metrics.annualized_return)],
      ['Max drawdown', fmtPct(data.metrics.max_drawdown)],
      ['Benchmark', fmtPct(data.metrics.benchmark_total_return)],
      ['Excess return', fmtPct(data.metrics.excess_return)],
      ['Win rate', fmtPct(data.metrics.win_rate)]
    ];
    document.getElementById('kpis').innerHTML = kpis.map(([label, value]) => `<div class="panel"><div class="metric-label">${{label}}</div><div class="metric-value">${{value}}</div></div>`).join('');

    function series(rows, key) {{ return rows.map(row => row[key]); }}
    function liveTrace(normalize=false) {{
      const y = series(data.daily, 'equity_curve');
      const base = normalize && y.length ? y[0] : 1;
      return {{ x: series(data.daily, 'date'), y: y.map(v => v / base), name: 'Live model', mode: 'lines', line: {{ color: '#16836b', width: 3 }} }};
    }}
    function backtestTrace() {{
      return {{ x: series(data.backtest, 'date'), y: series(data.backtest, 'equity_curve'), name: 'Backtest', mode: 'lines', line: {{ color: '#7891a6', width: 2 }} }};
    }}
    function benchmarkTrace() {{
      return {{ x: series(data.benchmark, 'date'), y: series(data.benchmark, 'equity_curve'), name: 'Benchmark', mode: 'lines', line: {{ color: '#9d7b39', width: 2, dash: 'dot' }} }};
    }}
    function layout(title) {{
      const inception = data.manifest.live_inception_date;
      return {{
        title: {{ text: title, x: 0, font: {{ size: 13 }} }},
        margin: {{ l: 44, r: 18, t: 32, b: 38 }},
        paper_bgcolor: '#ffffff',
        plot_bgcolor: '#ffffff',
        hovermode: 'x unified',
        legend: {{ orientation: 'h', y: 1.12 }},
        shapes: inception ? [{{
          type: 'rect', xref: 'x', yref: 'paper', x0: inception, x1: data.manifest.latest_live_date,
          y0: 0, y1: 1, fillcolor: 'rgba(22,131,107,.10)', line: {{ width: 0 }}
        }}] : []
      }};
    }}
    function draw(mode='combined') {{
      const traces = [];
      if (mode === 'combined') traces.push(backtestTrace(), liveTrace(), benchmarkTrace());
      if (mode === 'live') traces.push(liveTrace(), benchmarkTrace());
      if (mode === 'backtest') traces.push(backtestTrace());
      if (mode === 'normalized') traces.push(liveTrace(true), benchmarkTrace());
      Plotly.react('growth', traces.filter(t => t.x.length), layout('Growth of 1'), {{ responsive: true, displayModeBar: false }});
    }}
    draw();
    document.querySelectorAll('button[data-mode]').forEach(button => button.addEventListener('click', () => {{
      document.querySelectorAll('button[data-mode]').forEach(item => item.classList.remove('active'));
      button.classList.add('active');
      draw(button.dataset.mode);
    }}));
    Plotly.newPlot('drawdown', [{{ x: series(data.drawdowns, 'date'), y: series(data.drawdowns, 'drawdown'), type: 'scatter', fill: 'tozeroy', name: 'Drawdown', line: {{ color: '#a64242' }} }}], layout('Drawdown'), {{ responsive: true, displayModeBar: false }});
    Plotly.newPlot('returns', [{{ x: series(data.daily, 'date'), y: series(data.daily, 'return'), type: 'bar', name: 'Return', marker: {{ color: '#16836b' }} }}], layout('Daily return'), {{ responsive: true, displayModeBar: false }});

    const table = (rows, columns) => rows.length ? `<table><thead><tr>${{columns.map(c => `<th>${{c.label}}</th>`).join('')}}</tr></thead><tbody>${{rows.map(row => `<tr>${{columns.map(c => `<td>${{c.format ? c.format(row[c.key]) : (row[c.key] ?? '')}}</td>`).join('')}}</tr>`).join('')}}</tbody></table>` : '<span class="pill">No data</span>';
    document.getElementById('quality').innerHTML = `
      <p><span class="pill">Rebalances: ${{data.data_quality.live_rebalance_count}}</span></p>
      <p><b>Latest price date:</b> ${{data.data_quality.latest_price_date || 'n/a'}}</p>
      <p><b>Tracked symbols:</b> ${{data.data_quality.tracked_symbols}}</p>
      <p><b>Missing prices:</b> ${{(data.data_quality.missing_price_symbols || []).join(', ') || 'None'}}</p>
      <p><b>Stale prices:</b> ${{(data.data_quality.stale_price_symbols || []).join(', ') || 'None'}}</p>
      ${{data.warnings.length ? `<p class="warn">${{data.warnings.join('<br>')}}</p>` : ''}}
    `;
    document.getElementById('holdings').innerHTML = table(data.current_holdings, [
      {{ key: 'symbol', label: 'Symbol' }},
      {{ key: 'sector', label: 'Sector' }},
      {{ key: 'weight', label: 'Weight', format: fmtPct }},
      {{ key: 'current_price', label: 'Price', format: fmtNum }},
      {{ key: 'notes', label: 'Notes' }}
    ]);
    document.getElementById('attribution').innerHTML = table(data.attribution.slice(0, 12), [
      {{ key: 'symbol', label: 'Symbol' }},
      {{ key: 'weight', label: 'Latest Weight', format: fmtPct }},
      {{ key: 'contribution', label: 'Contribution', format: fmtPct }}
    ]);
    document.getElementById('rebalances').innerHTML = table(data.rebalance_history, [
      {{ key: 'snapshot_date', label: 'Date' }},
      {{ key: 'run_id', label: 'Run' }},
      {{ key: 'holding_count', label: 'Holdings' }},
      {{ key: 'stock_weight', label: 'Stock Weight', format: fmtPct }},
      {{ key: 'safe_asset_weight', label: 'Safe Asset', format: fmtPct }}
    ]);
  </script>
</body>
</html>
"""


def _tracker_html(data: dict[str, Any]) -> str:
    payload = json.dumps(data).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Internal Live Strategy Tracker</title>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <style>
    :root {{
      --ink:#17211e; --muted:#65736d; --line:#dbe4df; --panel:#fff; --soft:#f2f6f3;
      --green:#15866f; --gold:#a47d2d; --red:#a64242; --blue:#647f99;
    }}
    * {{ box-sizing:border-box; }}
    body {{
      margin:0; background:#edf3ef; color:var(--ink);
      font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
    }}
    header {{ padding:30px 34px 20px; border-bottom:1px solid var(--line); background:linear-gradient(180deg,#fbfdfb,#edf3ef); }}
    .eyebrow {{ color:var(--green); font-size:12px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }}
    h1 {{ margin:6px 0; font-size:clamp(30px,4vw,52px); letter-spacing:0; }}
    .subtitle {{ margin:0; color:var(--muted); max-width:1040px; line-height:1.5; }}
    main {{ padding:22px 34px 38px; }}
    .grid {{ display:grid; gap:16px; }}
    .cards {{ grid-template-columns:repeat(4,minmax(190px,1fr)); }}
    .two {{ grid-template-columns:minmax(0,2fr) minmax(360px,1fr); align-items:start; }}
    .panel {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; box-shadow:0 1px 2px rgba(20,35,30,.04); }}
    .card {{ cursor:pointer; transition:.15s ease; min-height:148px; }}
    .card.active {{ border-color:var(--green); box-shadow:0 0 0 2px rgba(21,134,111,.12); }}
    .label {{ color:var(--muted); font-size:12px; }}
    .name {{ font-size:18px; font-weight:760; margin:8px 0 12px; }}
    .value {{ font-size:26px; font-weight:820; }}
    .row {{ display:flex; justify-content:space-between; gap:12px; margin-top:8px; color:var(--muted); font-size:13px; }}
    .kpis {{ grid-template-columns:repeat(6,minmax(120px,1fr)); margin-top:16px; }}
    .metric-value {{ font-size:22px; font-weight:780; margin-top:6px; }}
    .section-title {{ margin:0 0 12px; font-size:18px; }}
    .chart {{ height:380px; }}
    .small-chart {{ height:250px; }}
    .toolbar {{ display:flex; gap:8px; flex-wrap:wrap; margin:16px 0; }}
    button {{ border:1px solid var(--line); background:#fff; color:var(--ink); padding:9px 13px; border-radius:7px; cursor:pointer; font-weight:680; }}
    button.active {{ background:var(--green); border-color:var(--green); color:#fff; }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }}
    th,td {{ padding:10px 8px; border-bottom:1px solid var(--line); text-align:left; }}
    th {{ color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.06em; }}
    .pill {{ display:inline-flex; padding:4px 8px; border-radius:999px; background:var(--soft); color:var(--muted); font-size:12px; }}
    .warn {{ color:var(--red); }}
    @media(max-width:1120px) {{ .cards,.kpis,.two {{ grid-template-columns:1fr; }} main,header {{ padding-left:18px; padding-right:18px; }} }}
  </style>
</head>
<body>
  <script id="tracker-data" type="application/json">{payload}</script>
  <header>
    <div class="eyebrow">Internal only</div>
    <h1>Live Strategy Tracker</h1>
    <p class="subtitle">One view for all live Vriksha strategies. Returns are reconstructed from stored live rebalance snapshots and market prices; backtest lines are shown only as context.</p>
  </header>
  <main>
    <section class="grid cards" id="cards"></section>
    <section class="grid kpis" id="kpis"></section>
    <div class="toolbar">
      <button data-mode="combined" class="active">Backtest + Live</button>
      <button data-mode="live">Live Only</button>
      <button data-mode="backtest">Backtest Only</button>
      <button data-mode="normalized">Normalize From Live Inception</button>
    </div>
    <section class="grid two">
      <div class="panel">
        <h2 class="section-title" id="chart-title">Growth Of Capital</h2>
        <div id="growth" class="chart"></div>
      </div>
      <div class="panel">
        <h2 class="section-title">Data Quality</h2>
        <div id="quality"></div>
      </div>
    </section>
    <section class="grid two" style="margin-top:16px">
      <div class="panel">
        <h2 class="section-title">Drawdown</h2>
        <div id="drawdown" class="small-chart"></div>
      </div>
      <div class="panel">
        <h2 class="section-title">Daily Returns</h2>
        <div id="returns" class="small-chart"></div>
      </div>
    </section>
    <section class="grid two" style="margin-top:16px">
      <div class="panel">
        <h2 class="section-title">Current Portfolio</h2>
        <div id="holdings"></div>
      </div>
      <div class="panel">
        <h2 class="section-title">Contribution Since Inception</h2>
        <div id="attribution"></div>
      </div>
    </section>
    <section class="panel" style="margin-top:16px">
      <h2 class="section-title">All Strategy Comparison</h2>
      <div id="comparison"></div>
    </section>
  </main>
  <script>
    const tracker = JSON.parse(document.getElementById('tracker-data').textContent);
    let selectedIndex = 0;
    let mode = 'combined';
    const fmtPct = v => v === null || v === undefined ? 'n/a' : (v * 100).toFixed(2) + '%';
    const fmtNum = v => v === null || v === undefined ? 'n/a' : Number(v).toLocaleString('en-IN', {{ maximumFractionDigits: 2 }});
    const nameOf = s => s.manifest.public_name || s.manifest.name || s.manifest.slug;
    const sourceLabel = s => s.manifest.report_source === 'backtest_proxy' ? 'Backtest proxy' : (s.manifest.report_source === 'live_rebalance' ? 'Live rebalance' : 'No data yet');
    const rows = () => tracker.strategies;
    const series = (items, key) => items.map(row => row[key]);
    function table(items, cols) {{
      if (!items.length) return '<span class="pill">No data</span>';
      return `<table><thead><tr>${{cols.map(c=>`<th>${{c.label}}</th>`).join('')}}</tr></thead><tbody>${{items.map(row=>`<tr>${{cols.map(c=>`<td>${{c.format ? c.format(row[c.key]) : (row[c.key] ?? '')}}</td>`).join('')}}</tr>`).join('')}}</tbody></table>`;
    }}
    function renderCards() {{
      document.getElementById('cards').innerHTML = rows().map((s, i) => `
        <div class="panel card ${{i === selectedIndex ? 'active' : ''}}" data-index="${{i}}">
          <div class="label">${{s.manifest.slug}}</div>
          <div class="name">${{nameOf(s)}}</div>
          <div class="value">${{fmtPct(s.metrics.total_return)}}</div>
          <div class="row"><span>Source</span><b>${{sourceLabel(s)}}</b></div>
          <div class="row"><span>From</span><b>${{s.manifest.live_inception_date || 'n/a'}}</b></div>
          <div class="row"><span>Drawdown</span><b>${{fmtPct(s.metrics.max_drawdown)}}</b></div>
          ${{s.manifest.distributions_included ? '<div class="row"><span>Income</span><b>Distributions included</b></div>' : ''}}
        </div>`).join('');
      document.querySelectorAll('.card').forEach(card => card.addEventListener('click', () => {{
        selectedIndex = Number(card.dataset.index);
        render();
      }}));
    }}
    function traceLive(s, normalize=false) {{
      const y = series(s.daily, 'equity_curve');
      const base = normalize && y.length ? y[0] : 1;
      return {{ x: series(s.daily, 'date'), y: y.map(v => v / base), name: 'Live model', mode: 'lines', line: {{ color:'#15866f', width:3 }} }};
    }}
    function traceBacktest(s) {{
      return {{ x: series(s.backtest, 'date'), y: series(s.backtest, 'equity_curve'), name:'Backtest', mode:'lines', line:{{ color:'#647f99', width:2 }} }};
    }}
    function traceBenchmark(s) {{
      return {{ x: series(s.benchmark, 'date'), y: series(s.benchmark, 'equity_curve'), name:'Benchmark', mode:'lines', line:{{ color:'#a47d2d', dash:'dot', width:2 }} }};
    }}
    function layout(s, title) {{
      const inception = s.manifest.live_inception_date;
      return {{
        title: {{ text:title, x:0, font:{{ size:13 }} }},
        margin:{{ l:44,r:18,t:32,b:38 }},
        paper_bgcolor:'#fff', plot_bgcolor:'#fff', hovermode:'x unified',
        legend:{{ orientation:'h', y:1.12 }},
        shapes: inception ? [{{ type:'rect', xref:'x', yref:'paper', x0:inception, x1:s.manifest.latest_live_date, y0:0, y1:1, fillcolor:'rgba(21,134,111,.10)', line:{{ width:0 }} }}] : []
      }};
    }}
    function renderCharts(s) {{
      const traces = [];
      if (mode === 'combined') traces.push(traceBacktest(s), traceLive(s), traceBenchmark(s));
      if (mode === 'live') traces.push(traceLive(s), traceBenchmark(s));
      if (mode === 'backtest') traces.push(traceBacktest(s));
      if (mode === 'normalized') traces.push(traceLive(s, true), traceBenchmark(s));
      Plotly.react('growth', traces.filter(t => t.x.length), layout(s, 'Growth of 1'), {{ responsive:true, displayModeBar:false }});
      Plotly.react('drawdown', [{{ x:series(s.drawdowns,'date'), y:series(s.drawdowns,'drawdown'), type:'scatter', fill:'tozeroy', name:'Drawdown', line:{{ color:'#a64242' }} }}], layout(s, 'Drawdown'), {{ responsive:true, displayModeBar:false }});
      Plotly.react('returns', [{{ x:series(s.daily,'date'), y:series(s.daily,'return'), type:'bar', name:'Return', marker:{{ color:'#15866f' }} }}], layout(s, 'Daily returns'), {{ responsive:true, displayModeBar:false }});
    }}
    function renderDetails(s) {{
      document.getElementById('chart-title').textContent = `${{nameOf(s)}} - Growth Of Capital`;
      document.getElementById('kpis').innerHTML = [
        ['Live Return', fmtPct(s.metrics.total_return)],
        ['Annualized', fmtPct(s.metrics.annualized_return)],
        ['Max Drawdown', fmtPct(s.metrics.max_drawdown)],
        ['Benchmark', fmtPct(s.metrics.benchmark_total_return)],
        ['Excess', fmtPct(s.metrics.excess_return)],
        ['Win Rate', fmtPct(s.metrics.win_rate)]
      ].map(([label,value]) => `<div class="panel"><div class="label">${{label}}</div><div class="metric-value">${{value}}</div></div>`).join('');
      document.getElementById('quality').innerHTML = `
        <p><span class="pill">Rebalances: ${{s.data_quality.live_rebalance_count}}</span></p>
        <p><b>Source:</b> ${{sourceLabel(s)}}</p>
        <p><b>From:</b> ${{s.manifest.live_inception_date || 'n/a'}}</p>
        <p><b>Latest date:</b> ${{s.manifest.latest_live_date || 'n/a'}}</p>
        <p><b>Latest price date:</b> ${{s.data_quality.latest_price_date || 'n/a'}}</p>
        <p><b>Distributions:</b> ${{s.manifest.distributions_included ? 'Included where configured' : 'Not included / no event file configured'}}</p>
        <p><b>Tracked symbols:</b> ${{s.data_quality.tracked_symbols}}</p>
        <p><b>Missing prices:</b> ${{(s.data_quality.missing_price_symbols || []).join(', ') || 'None'}}</p>
        ${{s.warnings.length ? `<p class="warn">${{s.warnings.join('<br>')}}</p>` : ''}}
      `;
      document.getElementById('holdings').innerHTML = table(s.current_holdings, [
        {{ key:'symbol', label:'Symbol' }},
        {{ key:'sector', label:'Sector' }},
        {{ key:'weight', label:'Weight', format:fmtPct }},
        {{ key:'current_price', label:'Price', format:fmtNum }},
        {{ key:'notes', label:'Notes' }}
      ]);
      document.getElementById('attribution').innerHTML = table(s.attribution.slice(0,12), [
        {{ key:'symbol', label:'Symbol' }},
        {{ key:'weight', label:'Latest Weight', format:fmtPct }},
        {{ key:'contribution', label:'Contribution', format:fmtPct }}
      ]);
    }}
    function renderComparison() {{
      document.getElementById('comparison').innerHTML = table(rows().map(s => ({{
        strategy:nameOf(s),
        slug:s.manifest.slug,
        inception:s.manifest.live_inception_date,
        latest:s.manifest.latest_live_date,
        source:sourceLabel(s),
        income:s.manifest.distributions_included ? 'Included' : '',
        live_return:s.metrics.total_return,
        benchmark:s.metrics.benchmark_total_return,
        excess:s.metrics.excess_return,
        drawdown:s.metrics.max_drawdown,
        rebalances:s.data_quality.live_rebalance_count
      }})), [
        {{ key:'strategy', label:'Strategy' }},
        {{ key:'source', label:'Source' }},
        {{ key:'income', label:'Income' }},
        {{ key:'inception', label:'Inception' }},
        {{ key:'latest', label:'Latest' }},
        {{ key:'live_return', label:'Live Return', format:fmtPct }},
        {{ key:'benchmark', label:'Benchmark', format:fmtPct }},
        {{ key:'excess', label:'Excess', format:fmtPct }},
        {{ key:'drawdown', label:'Max DD', format:fmtPct }},
        {{ key:'rebalances', label:'Runs' }}
      ]);
    }}
    function render() {{
      renderCards();
      const s = rows()[selectedIndex] || rows()[0];
      renderDetails(s);
      renderCharts(s);
      renderComparison();
    }}
    document.querySelectorAll('button[data-mode]').forEach(button => button.addEventListener('click', () => {{
      document.querySelectorAll('button[data-mode]').forEach(item => item.classList.remove('active'));
      button.classList.add('active');
      mode = button.dataset.mode;
      renderCharts(rows()[selectedIndex]);
    }}));
    render();
  </script>
</body>
</html>
"""
