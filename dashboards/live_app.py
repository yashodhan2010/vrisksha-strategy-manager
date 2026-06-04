from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import config
from app.storage.database import initialize_database
from app.storage.market_data_repository import get_latest_ingestion_run, get_price_summary
from app.storage.repositories import (
    get_latest_audit_event,
    get_latest_strategy_run,
    list_latest_strategy_holdings,
    list_order_proposals_for_run,
)


def _count(table: str) -> int:
    try:
        with sqlite3.connect(config.DATABASE_PATH) as connection:
            return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    except sqlite3.Error:
        return 0


def main() -> None:
    st.set_page_config(page_title="Dual Momentum - Live / Paper", layout="wide")
    initialize_database()
    st.title("Dual Momentum - Live / Paper")

    latest_run = get_latest_strategy_run()
    latest_sync = get_latest_audit_event("UNIVERSE_SYNC")
    latest_ingestion = get_latest_ingestion_run()
    holdings = pd.DataFrame(list_latest_strategy_holdings())
    orders = pd.DataFrame(list_order_proposals_for_run(int(latest_run["id"]))) if latest_run else pd.DataFrame()

    tabs = st.tabs([
        "Overview",
        "Current Portfolio",
        "Ranking Explorer",
        "Stock History",
        "Proposed Execution",
        "Operational Logs",
    ])
    with tabs[0]:
        cols = st.columns(4)
        cols[0].metric("Current mode", config.DEFAULT_MODE)
        cols[1].metric("Latest run status", latest_run["status"] if latest_run else "No runs")
        cols[2].metric("Latest universe sync", latest_sync["timestamp"] if latest_sync else "No sync")
        cols[3].metric("Kite session status", "Token saved today" if config.KITE_ACCESS_TOKEN_DATE else "No token date")
        cols2 = st.columns(4)
        cols2[0].metric("Current selected stocks", len(holdings) if not holdings.empty else 0)
        cols2[1].metric("Current proposals", len(orders) if not orders.empty else 0)
        cols2[2].metric("Target portfolio value", f"{config.TARGET_PORTFOLIO_VALUE:,.0f}")
        cols2[3].metric("Available purchase funds", f"{config.AVAILABLE_PURCHASE_FUNDS:,.0f}")
        cols3 = st.columns(4)
        cols3[0].metric("Allocation mode", config.STRATEGY_ALLOCATION_MODE)
        cols3[1].metric("Top N", config.STRATEGY_TOP_N)
        cols3[2].metric("Dynamic min", f"{config.DYNAMIC_MIN_WEIGHT:.2%}")
        cols3[3].metric("Dynamic max", f"{config.DYNAMIC_MAX_WEIGHT:.2%}")
        cols4 = st.columns(4)
        cols4[0].metric("Ranking method", config.STRATEGY_RANKING_METHOD)
        cols4[1].metric("Momentum factor", f"{config.RANKING_MOMENTUM_WEIGHT:.2f}")
        cols4[2].metric("Beta factor", f"{config.RANKING_BETA_WEIGHT:.2f}")
        cols4[3].metric("Volatility factor", f"{config.RANKING_VOLATILITY_WEIGHT:.2f}")
        st.metric("Latest market-data ingestion", latest_ingestion["created_at"] if latest_ingestion else "No ingestion")

    with tabs[1]:
        if holdings.empty:
            st.info("No current rebalance holdings yet.")
        else:
            columns = ["snapshot_date", "symbol", "rank", "weight", "quantity", "reference_price", "market_value", "holding_action"]
            st.dataframe(holdings[[column for column in columns if column in holdings.columns]], use_container_width=True, hide_index=True)
    with tabs[2]:
        summary = get_price_summary()
        if summary:
            st.dataframe(summary, use_container_width=True)
        else:
            st.write("No historical market data loaded yet.")
    with tabs[3]:
        st.write("No stock history yet." if _count("stock_history") == 0 else "Stock history data is available.")
    with tabs[4]:
        if orders.empty:
            st.info("No proposed orders for the latest strategy run.")
        else:
            columns = ["symbol", "side", "quantity", "reference_price", "estimated_value", "status", "reason"]
            st.dataframe(orders[[column for column in columns if column in orders.columns]], use_container_width=True, hide_index=True)
    with tabs[5]:
        st.write("Audit events will appear here as operational workflows mature.")


if __name__ == "__main__":
    main()
