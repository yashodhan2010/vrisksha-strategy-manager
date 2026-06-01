from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import config
from app.storage.database import initialize_database
from app.storage.market_data_repository import get_latest_ingestion_run, get_price_summary
from app.storage.repositories import get_latest_audit_event, get_latest_strategy_run


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
    st.info("Foundation sprint complete. Strategy calculation and broker execution will be added in later sprints.")

    latest_run = get_latest_strategy_run()
    latest_sync = get_latest_audit_event("UNIVERSE_SYNC")
    latest_ingestion = get_latest_ingestion_run()

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
        cols[3].metric("Kite session status", "Not configured / Pending implementation")
        cols2 = st.columns(3)
        cols2[0].metric("Current portfolio state", "No snapshot")
        cols2[1].metric("Current LIQUIDBEES allocation", "No snapshot")
        cols2[2].metric("Latest reshuffle number", "No snapshot")
        st.metric("Latest market-data ingestion", latest_ingestion["created_at"] if latest_ingestion else "No ingestion")

    with tabs[1]:
        st.write("No portfolio snapshots yet." if _count("portfolio_snapshots") == 0 else "Portfolio data is available.")
    with tabs[2]:
        summary = get_price_summary()
        if summary:
            st.dataframe(summary, use_container_width=True)
        else:
            st.write("No historical market data loaded yet.")
    with tabs[3]:
        st.write("No stock history yet." if _count("stock_history") == 0 else "Stock history data is available.")
    with tabs[4]:
        st.write("No order proposals. Sprint 0 never places live orders.")
    with tabs[5]:
        st.write("Audit events will appear here as operational workflows mature.")


if __name__ == "__main__":
    main()
