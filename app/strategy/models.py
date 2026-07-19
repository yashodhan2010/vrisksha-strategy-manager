from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any


class RunMode(StrEnum):
    RANK_ONLY = "RANK_ONLY"
    PAPER = "PAPER"
    LIVE = "LIVE"


class RunType(StrEnum):
    MANUAL = "MANUAL"
    MONTHLY = "MONTHLY"
    BACKTEST = "BACKTEST"
    UNIVERSE_SYNC = "UNIVERSE_SYNC"


class RunStatus(StrEnum):
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class PortfolioState(StrEnum):
    ACTIVE = "ACTIVE"
    COOLDOWN = "COOLDOWN"


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(StrEnum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class UniverseStock:
    symbol: str
    company_name: str
    industry: str
    sector: str
    exchange: str = "NSE"
    instrument_type: str = "EQ"
    is_active: bool = True
    kite_tradingsymbol: str | None = None
    kite_instrument_token: str | None = None
    isin: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None


@dataclass(frozen=True)
class AllocationResult:
    stock_weights: dict[str, float]
    liquidbees_symbol: str
    liquidbees_weight: float
    total_weight: float

    @property
    def safe_asset_symbol(self) -> str:
        return self.liquidbees_symbol

    @property
    def safe_asset_weight(self) -> float:
        return self.liquidbees_weight


@dataclass(frozen=True)
class StrategyRun:
    id: int | None
    run_type: RunType
    mode: RunMode
    status: RunStatus
    started_at: datetime
    completed_at: datetime | None = None
    message: str | None = None
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PortfolioSnapshot:
    run_id: int
    snapshot_date: date
    portfolio_state: PortfolioState
    portfolio_nav: float | None = None
    monthly_return: float | None = None
    cumulative_return: float | None = None
    liquidbees_weight: float = 0.0
    selected_stock_count: int = 0
    reshuffle_number: int | None = None
    cooldown_checked: bool = False
    cooldown_triggered: bool = False
    ema_value: float | None = None


@dataclass(frozen=True)
class HoldingSnapshot:
    run_id: int
    snapshot_date: date
    symbol: str
    industry: str | None = None
    sector: str | None = None
    rank: int | None = None
    selected: bool = False
    weight: float = 0.0
    quantity: float | None = None
    reference_price: float | None = None
    market_value: float | None = None
    monthly_return: float | None = None
    portfolio_contribution: float | None = None
    holding_action: str | None = None
    consecutive_months_held: int = 0
    total_months_held: int = 0


@dataclass(frozen=True)
class StockHistorySummary:
    symbol: str
    currently_held: bool
    total_months_held: int = 0
    current_consecutive_months: int = 0
    number_of_entry_periods: int = 0


@dataclass(frozen=True)
class OrderProposal:
    symbol: str
    side: OrderSide
    quantity: float
    reference_price: float
    estimated_value: float
    status: OrderStatus = OrderStatus.PROPOSED
    reason: str | None = None
    broker_order_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AuditEvent:
    run_id: int | None
    event_type: str
    timestamp: datetime
    level: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BacktestRun:
    id: int | None
    created_at: datetime
    status: RunStatus
    requested_start_date: date | None
    requested_end_date: date | None
    actual_start_date: date | None
    actual_end_date: date | None
    initial_capital: float | None
    final_value: float | None
    benchmark_symbol: str
    config: dict[str, Any] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
