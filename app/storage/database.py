from __future__ import annotations

import sqlite3
from pathlib import Path

from app import config


def get_connection(database_path: str | Path = config.DATABASE_PATH) -> sqlite3.Connection:
    config.ensure_runtime_directories()
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database(database_path: str | Path = config.DATABASE_PATH) -> None:
    with get_connection(database_path) as connection:
        connection.executescript(SCHEMA)


SCHEMA = """
CREATE TABLE IF NOT EXISTS strategy_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_type TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    message TEXT,
    config_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER,
    event_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER,
    snapshot_date TEXT NOT NULL,
    portfolio_state TEXT NOT NULL,
    portfolio_nav REAL,
    monthly_return REAL,
    cumulative_return REAL,
    liquidbees_weight REAL,
    selected_stock_count INTEGER,
    reshuffle_number INTEGER,
    cooldown_checked INTEGER,
    cooldown_triggered INTEGER,
    ema_value REAL
);
CREATE TABLE IF NOT EXISTS holding_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER,
    snapshot_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    industry TEXT,
    sector TEXT,
    rank INTEGER,
    selected INTEGER,
    weight REAL,
    quantity REAL,
    reference_price REAL,
    market_value REAL,
    monthly_return REAL,
    portfolio_contribution REAL,
    holding_action TEXT,
    consecutive_months_held INTEGER,
    total_months_held INTEGER
);
CREATE TABLE IF NOT EXISTS stock_history (
    symbol TEXT PRIMARY KEY,
    first_entry_date TEXT,
    latest_entry_date TEXT,
    latest_exit_date TEXT,
    currently_held INTEGER,
    current_consecutive_months INTEGER,
    total_months_held INTEGER,
    number_of_entry_periods INTEGER,
    longest_continuous_holding_period INTEGER,
    average_historical_weight REAL,
    cumulative_return_while_held REAL,
    cumulative_portfolio_contribution REAL,
    latest_rank INTEGER,
    best_historical_rank INTEGER,
    average_rank_while_held REAL,
    latest_entry_reason TEXT,
    latest_exit_reason TEXT
);
CREATE TABLE IF NOT EXISTS order_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER,
    created_at TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity REAL NOT NULL,
    reference_price REAL NOT NULL,
    estimated_value REAL NOT NULL,
    status TEXT NOT NULL,
    reason TEXT,
    broker_order_id TEXT,
    details_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS backtest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    requested_start_date TEXT,
    requested_end_date TEXT,
    actual_start_date TEXT,
    actual_end_date TEXT,
    initial_capital REAL,
    final_value REAL,
    benchmark_symbol TEXT NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}',
    summary_json TEXT NOT NULL DEFAULT '{}',
    warnings_json TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS backtest_artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    backtest_run_id INTEGER NOT NULL,
    artifact_type TEXT NOT NULL,
    file_path TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS market_prices (
    symbol TEXT NOT NULL,
    price_date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    adjusted_close REAL,
    volume INTEGER,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (symbol, price_date, source)
);
CREATE INDEX IF NOT EXISTS idx_market_prices_symbol_date
ON market_prices (symbol, price_date);
CREATE TABLE IF NOT EXISTS data_ingestion_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    requested_symbols INTEGER NOT NULL,
    stored_rows INTEGER NOT NULL,
    message TEXT,
    details_json TEXT NOT NULL DEFAULT '{}'
);
"""
