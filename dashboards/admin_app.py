from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st


SNAPSHOT_PATH = Path("data/admin/strategy_dashboard.json")


def main() -> None:
    st.set_page_config(page_title="Vriksha Strategy Admin", layout="wide")
    st.title("Vriksha Strategy Admin")
    if not _authorized():
        st.stop()

    snapshot = _load_snapshot()
    if not snapshot:
        st.warning("No admin snapshot found. Run `python -m app.main export-admin-dashboard` first.")
        return

    strategies = snapshot.get("strategies", [])
    validation = snapshot.get("validation", {})
    st.caption(f"Snapshot: {snapshot.get('generated_at')} | As of: {snapshot.get('as_of_date')}")

    if not validation.get("ok"):
        st.error("Strategy registry validation has issues.")
    else:
        st.success("Strategy registry validation passed.")

    catalogue, schedule, files, commands, validation_tab = st.tabs(
        ["Catalogue", "Schedule", "Files", "Commands", "Validation"]
    )
    with catalogue:
        st.dataframe(_catalogue_frame(strategies), use_container_width=True, hide_index=True)
    with schedule:
        st.dataframe(_schedule_frame(strategies), use_container_width=True, hide_index=True)
    with files:
        st.dataframe(_files_frame(strategies), use_container_width=True, hide_index=True)
    with commands:
        selected = st.selectbox("Strategy", [item.get("name") for item in strategies])
        strategy = next((item for item in strategies if item.get("name") == selected), None)
        if strategy:
            for label, command in (strategy.get("commands") or {}).items():
                st.code(command, language="bash")
    with validation_tab:
        issues = validation.get("issues") or []
        if issues:
            st.dataframe(pd.DataFrame(issues), use_container_width=True, hide_index=True)
        else:
            st.write("No validation issues.")


def _authorized() -> bool:
    try:
        password = st.secrets.get("ADMIN_DASHBOARD_PASSWORD", "")
    except FileNotFoundError:
        password = ""
    if not password:
        return True
    entered = st.text_input("Password", type="password")
    if entered == password:
        return True
    if entered:
        st.error("Incorrect password.")
    return False


def _load_snapshot() -> dict[str, Any]:
    if not SNAPSHOT_PATH.exists():
        return {}
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def _catalogue_frame(strategies: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Strategy": item.get("name"),
                "Slug": item.get("slug"),
                "Universe": item.get("universe"),
                "Benchmark": item.get("benchmark"),
                "Labels": ", ".join(item.get("category_labels") or []),
            }
            for item in strategies
        ]
    )


def _schedule_frame(strategies: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for item in strategies:
        last_run = item.get("last_successful_run") or {}
        schedule = item.get("rebalance_schedule") or {}
        rows.append(
            {
                "Strategy": item.get("name"),
                "Next due": item.get("next_due_date"),
                "Last successful run": last_run.get("date"),
                "Last run type": last_run.get("type"),
                "Model portfolio as of": item.get("latest_model_portfolio_as_of"),
                "Target days": ", ".join(str(day) for day in schedule.get("target_days", [])),
            }
        )
    return pd.DataFrame(rows)


def _files_frame(strategies: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Strategy": item.get("name"),
                "Latest model portfolio": item.get("latest_model_portfolio_path"),
                "Exists": item.get("latest_model_portfolio_exists"),
                "Package folder": item.get("package_output_dir"),
                "Finalized config exists": (item.get("file_status") or {}).get("finalized_config_exists"),
                "Optimization output exists": (item.get("file_status") or {}).get("optimization_results_exists"),
            }
            for item in strategies
        ]
    )


if __name__ == "__main__":
    main()
