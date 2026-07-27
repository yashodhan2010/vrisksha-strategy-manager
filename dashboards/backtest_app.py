from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.storage.database import initialize_database
from app.storage.repositories import (
    list_backtest_runs,
    list_holding_snapshots,
    list_order_proposals_for_run,
    list_portfolio_snapshots,
    summarize_stock_contributions,
)


def _json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _format_percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2%}"


def _range_options() -> dict[str, pd.DateOffset | None]:
    return {
        "1M": pd.DateOffset(months=1),
        "6M": pd.DateOffset(months=6),
        "1Y": pd.DateOffset(years=1),
        "5Y": pd.DateOffset(years=5),
        "Max (10Y)": pd.DateOffset(years=10),
    }


def _filter_chart_range(chart_data: pd.DataFrame, range_label: str) -> pd.DataFrame:
    offset = _range_options()[range_label]
    if chart_data.empty:
        return chart_data.copy()
    end_date = chart_data.index.max()
    filtered = chart_data[chart_data.index >= end_date - offset].copy()
    return filtered if not filtered.empty else chart_data.tail(1).copy()


def _range_kpis(chart_data: pd.DataFrame) -> dict[str, float | None]:
    if chart_data.empty:
        return {
            "total_return": None,
            "annualized_return": None,
            "max_drawdown": None,
            "best_month": None,
            "worst_month": None,
            "win_rate": None,
        }
    nav = chart_data["portfolio_nav"].astype(float)
    start_nav = float(nav.iloc[0])
    normalized_nav = nav / start_nav if start_nav > 0 else nav * 0.0 + 1.0
    total_return = float(normalized_nav.iloc[-1] - 1.0)
    elapsed_years = max((chart_data.index[-1] - chart_data.index[0]).days / 365.25, 0.0)
    annualized_return = (
        (1.0 + total_return) ** (1 / elapsed_years) - 1.0
        if elapsed_years > 0 and total_return > -1.0
        else None
    )
    drawdown = normalized_nav / normalized_nav.cummax() - 1.0
    returns = chart_data["monthly_return"].astype(float).dropna()
    return {
        "total_return": total_return,
        "annualized_return": annualized_return,
        "max_drawdown": float(drawdown.min()) if len(drawdown) else None,
        "best_month": float(returns.max()) if len(returns) else None,
        "worst_month": float(returns.min()) if len(returns) else None,
        "win_rate": float((returns > 0).sum() / len(returns)) if len(returns) else None,
    }


def _selected_run(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not runs:
        return None
    options = {
        f"Run {run['id']} | {run['status']} | {run.get('requested_start_date')} to {run.get('requested_end_date')}": run
        for run in runs
    }
    label = st.sidebar.selectbox("Backtest run", list(options))
    return options[label]


def main() -> None:
    st.set_page_config(page_title="Vriksha Strategy Manager - Backtest", layout="wide")
    initialize_database()
    st.title("Vriksha Strategy Manager - Backtest Report")

    runs = list_backtest_runs()
    run = _selected_run(runs)
    if run is None:
        st.info("No backtests yet. Run `python -m app.main run-backtest --start-date 2016-01-01 --end-date 2025-12-31`.")
        return

    run_id = int(run["id"])
    snapshots = pd.DataFrame(list_portfolio_snapshots(run_id))
    holdings = pd.DataFrame(list_holding_snapshots(run_id))
    stock_contributions = pd.DataFrame(summarize_stock_contributions(run_id))
    orders = pd.DataFrame(list_order_proposals_for_run(run_id))
    summary = _json_loads(run.get("summary_json"), {})
    config_payload = _json_loads(run.get("config_json"), {})
    warnings = _json_loads(run.get("warnings_json"), [])

    tabs = st.tabs(
        [
            "Overview",
            "Equity Curve",
            "Monthly Reshuffles",
            "Holdings",
            "Stock Contributions",
            "Configuration",
            "Artifacts",
        ]
    )

    with tabs[0]:
        cols = st.columns(5)
        cols[0].metric("Status", run["status"])
        cols[1].metric("Initial capital", f"{run.get('initial_capital') or 0:,.0f}")
        cols[2].metric("Final value", f"{run.get('final_value') or 0:,.0f}")
        cols[3].metric("Total return", _format_percent(summary.get("total_return")))
        cols[4].metric("Max drawdown", _format_percent(summary.get("max_drawdown")))

        cols2 = st.columns(4)
        cols2[0].metric("Annualized return", _format_percent(summary.get("annualized_return")))
        cols2[1].metric("Rebalances", summary.get("rebalance_count", "n/a"))
        cols2[2].metric("Actual start", run.get("actual_start_date") or "n/a")
        cols2[3].metric("Actual end", run.get("actual_end_date") or "n/a")

        if warnings:
            st.warning("\n".join(str(item) for item in warnings[:10]))

    with tabs[1]:
        if snapshots.empty:
            st.info("No portfolio snapshots are available for this run.")
        else:
            chart_data = snapshots.copy()
            chart_data["snapshot_date"] = pd.to_datetime(chart_data["snapshot_date"])
            chart_data = chart_data.set_index("snapshot_date")
            selected_range = st.radio(
                "Performance range",
                list(_range_options()),
                index=2,
                horizontal=True,
            )
            range_data = _filter_chart_range(chart_data, selected_range)
            kpis = _range_kpis(range_data)
            kpi_cols = st.columns(6)
            kpi_cols[0].metric("Return", _format_percent(kpis["total_return"]))
            kpi_cols[1].metric("Annualized", _format_percent(kpis["annualized_return"]))
            kpi_cols[2].metric("Max drawdown", _format_percent(kpis["max_drawdown"]))
            kpi_cols[3].metric("Best month", _format_percent(kpis["best_month"]))
            kpi_cols[4].metric("Worst month", _format_percent(kpis["worst_month"]))
            kpi_cols[5].metric("Win rate", _format_percent(kpis["win_rate"]))

            normalized_nav = range_data[["portfolio_nav"]].copy()
            start_nav = float(normalized_nav["portfolio_nav"].iloc[0])
            normalized_nav["portfolio_nav"] = (
                normalized_nav["portfolio_nav"] / start_nav if start_nav > 0 else 1.0
            )
            st.caption(
                f"{range_data.index[0].date().isoformat()} to {range_data.index[-1].date().isoformat()}"
            )
            st.subheader("Portfolio Growth")
            st.line_chart(normalized_nav.rename(columns={"portfolio_nav": "growth_of_1"}))
            st.subheader("Monthly Return")
            st.bar_chart(range_data[["monthly_return"]])
            drawdown = normalized_nav["portfolio_nav"] / normalized_nav["portfolio_nav"].cummax() - 1.0
            st.subheader("Drawdown")
            st.line_chart(drawdown.rename("drawdown"))

    with tabs[2]:
        if snapshots.empty:
            st.info("No monthly reshuffle records are available.")
        else:
            columns = [
                "snapshot_date",
                "portfolio_nav",
                "monthly_return",
                "cumulative_return",
                "liquidbees_weight",
                "selected_stock_count",
                "reshuffle_number",
            ]
            st.dataframe(snapshots[columns], use_container_width=True, hide_index=True)

    with tabs[3]:
        if holdings.empty:
            st.info("No holding snapshots are available for this run.")
        else:
            dates = sorted(holdings["snapshot_date"].unique(), reverse=True)
            selected_date = st.selectbox("Snapshot date", dates)
            latest_holdings = holdings[holdings["snapshot_date"] == selected_date].copy()
            display_columns = [
                "symbol",
                "rank",
                "weight",
                "quantity",
                "reference_price",
                "market_value",
                "holding_action",
                "consecutive_months_held",
                "total_months_held",
            ]
            st.dataframe(latest_holdings[display_columns], use_container_width=True, hide_index=True)

    with tabs[4]:
        if stock_contributions.empty:
            st.info("No stock contribution data is available for this run.")
        else:
            st.subheader("Overall Stock Contribution")
            st.dataframe(stock_contributions, use_container_width=True, hide_index=True)

            if not holdings.empty:
                st.subheader("Monthly Stock Contribution")
                monthly = holdings[
                    [
                        "snapshot_date",
                        "symbol",
                        "rank",
                        "weight",
                        "monthly_return",
                        "portfolio_contribution",
                        "market_value",
                    ]
                ].copy()
                st.dataframe(monthly, use_container_width=True, hide_index=True)

    with tabs[5]:
        left, right = st.columns(2)
        with left:
            st.subheader("Run Configuration")
            st.json(config_payload)
        with right:
            st.subheader("Summary")
            st.json(summary)

    with tabs[6]:
        if orders.empty:
            st.info("No order proposals are generated by historical backtests.")
        else:
            st.dataframe(orders, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
