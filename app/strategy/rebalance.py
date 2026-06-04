from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from app import config
from app.backtest.engine import BacktestEngine
from app.data.universe_loader import load_universe
from app.storage.market_data_repository import load_market_prices
from app.storage.repositories import (
    insert_holding_snapshots,
    insert_order_proposals,
    insert_portfolio_snapshot,
    list_latest_strategy_holdings,
)
from app.strategy.models import OrderProposal, OrderSide
from app.strategy.selection import allocate_from_ranking


@dataclass(frozen=True)
class RebalanceResult:
    run_id: int
    run_date: date
    selected_count: int
    proposal_count: int
    liquidbees_weight: float
    buy_scaling_ratio: float
    warnings: list[str]


class RebalanceEngine:
    def __init__(
        self,
        run_id: int,
        run_date: date | None = None,
        portfolio_value: float = config.TARGET_PORTFOLIO_VALUE,
        available_purchase_funds: float = config.AVAILABLE_PURCHASE_FUNDS,
        database_path: str | Path = config.DATABASE_PATH,
    ) -> None:
        self.run_id = run_id
        self.run_date = run_date or date.today()
        self.portfolio_value = portfolio_value
        self.available_purchase_funds = available_purchase_funds
        self.database_path = database_path
        self.warnings: list[str] = []
        if self.portfolio_value <= 0:
            raise ValueError("portfolio_value must be greater than zero.")
        if self.available_purchase_funds < 0:
            raise ValueError("available_purchase_funds cannot be negative.")

    def run(self) -> RebalanceResult:
        price_frame = self._load_price_frame()
        universe = load_universe()
        symbols = [stock.symbol for stock in universe]
        universe_by_symbol = {stock.symbol: stock for stock in universe}
        price_pivot = self._pivot_prices(price_frame, symbols)
        if price_pivot.empty:
            raise ValueError("No universe symbols have stored prices. Run fetch-history before rebalance.")

        rebalance_date = self._latest_price_date(price_pivot)
        benchmark_returns = self._benchmark_returns(price_frame)
        ranking = self._rank(price_pivot, benchmark_returns, rebalance_date)
        strategy_allocation = allocate_from_ranking(ranking)
        allocation = strategy_allocation.allocation
        selected = strategy_allocation.selected_symbols
        previous_holdings = {row["symbol"]: row for row in list_latest_strategy_holdings(self.database_path)}
        rows = self._holding_rows(
            ranking=ranking,
            weights=allocation.stock_weights,
            universe_by_symbol=universe_by_symbol,
            price_pivot=price_pivot,
            snapshot_date=rebalance_date,
            previous_holdings=set(previous_holdings),
        )
        insert_portfolio_snapshot(
            run_id=self.run_id,
            snapshot_date=rebalance_date,
            portfolio_state="ACTIVE",
            portfolio_nav=self.portfolio_value,
            monthly_return=None,
            cumulative_return=None,
            liquidbees_weight=allocation.liquidbees_weight,
            selected_stock_count=len(selected),
            reshuffle_number=self.run_id,
            database_path=self.database_path,
        )
        insert_holding_snapshots(rows, self.database_path)
        proposals, buy_scaling_ratio = self._order_proposals(
            target_weights=allocation.stock_weights,
            previous_holdings=previous_holdings,
            price_pivot=price_pivot,
            snapshot_date=rebalance_date,
        )
        insert_order_proposals(self.run_id, proposals, self.database_path)
        return RebalanceResult(
            run_id=self.run_id,
            run_date=rebalance_date,
            selected_count=len(selected),
            proposal_count=len(proposals),
            liquidbees_weight=allocation.liquidbees_weight,
            buy_scaling_ratio=buy_scaling_ratio,
            warnings=self.warnings,
        )

    def _load_price_frame(self) -> pd.DataFrame:
        frame = pd.DataFrame(load_market_prices(self.database_path))
        if frame.empty:
            raise ValueError("No market prices found. Run fetch-history before rebalance.")
        frame["price_date"] = pd.to_datetime(frame["price_date"]).dt.date
        frame = frame[frame["price_date"] <= self.run_date]
        frame["price"] = frame["adjusted_close"].fillna(frame["close"])
        return frame.dropna(subset=["price"])

    def _pivot_prices(self, prices: pd.DataFrame, symbols: list[str]) -> pd.DataFrame:
        filtered = prices[prices["symbol"].isin(symbols)]
        return filtered.pivot_table(index="price_date", columns="symbol", values="price", aggfunc="last").sort_index().ffill()

    def _benchmark_returns(self, prices: pd.DataFrame) -> pd.Series | None:
        benchmark = prices[prices["symbol"] == config.DEFAULT_BENCHMARK_SYMBOL]
        if benchmark.empty:
            self.warnings.append("Benchmark prices not found; beta adjustment used beta=1.0.")
            return None
        series = benchmark.pivot_table(index="price_date", values="price", aggfunc="last").sort_index()["price"].ffill()
        return series.pct_change()

    def _rank(
        self,
        price_pivot: pd.DataFrame,
        benchmark_returns: pd.Series | None,
        rebalance_date: date,
    ) -> pd.DataFrame:
        helper = BacktestEngine(self.run_id, rebalance_date, rebalance_date, self.portfolio_value, self.database_path)
        ranking = helper._rank_on_date(price_pivot, benchmark_returns, rebalance_date)
        if ranking.empty:
            self.warnings.append("No stocks qualified after momentum, 52-week-high, beta, and volatility filters.")
        return ranking

    def _latest_price_date(self, price_pivot: pd.DataFrame) -> date:
        return max(price_pivot.index)

    def _holding_rows(
        self,
        ranking: pd.DataFrame,
        weights: dict[str, float],
        universe_by_symbol: dict[str, object],
        price_pivot: pd.DataFrame,
        snapshot_date: date,
        previous_holdings: set[str],
    ) -> list[dict[str, object]]:
        rank_by_symbol = dict(zip(ranking["symbol"], ranking["rank"], strict=False)) if not ranking.empty else {}
        rows: list[dict[str, object]] = []
        for symbol, weight in weights.items():
            stock = universe_by_symbol.get(symbol)
            price = float(price_pivot.at[snapshot_date, symbol])
            rows.append(
                {
                    "run_id": self.run_id,
                    "snapshot_date": snapshot_date,
                    "symbol": symbol,
                    "industry": getattr(stock, "industry", None),
                    "sector": getattr(stock, "sector", None),
                    "rank": int(rank_by_symbol.get(symbol, 0)) or None,
                    "selected": True,
                    "weight": weight,
                    "quantity": (self.portfolio_value * weight) / price if price > 0 else None,
                    "reference_price": price,
                    "market_value": self.portfolio_value * weight,
                    "holding_action": "HELD" if symbol in previous_holdings else "ENTERED",
                    "consecutive_months_held": 0,
                    "total_months_held": 0,
                }
            )
        return rows

    def _order_proposals(
        self,
        target_weights: dict[str, float],
        previous_holdings: dict[str, dict],
        price_pivot: pd.DataFrame,
        snapshot_date: date,
    ) -> tuple[list[OrderProposal], float]:
        proposal_inputs: list[tuple[str, OrderSide, float, float, float, float]] = []
        symbols = sorted(set(target_weights) | set(previous_holdings))
        for symbol in symbols:
            target_value = self.portfolio_value * target_weights.get(symbol, 0.0)
            previous_value = float(previous_holdings.get(symbol, {}).get("market_value") or 0.0)
            delta_value = target_value - previous_value
            if abs(delta_value) < 1:
                continue
            price = float(price_pivot.at[snapshot_date, symbol]) if symbol in price_pivot.columns else 0.0
            if price <= 0:
                self.warnings.append(f"No usable reference price for {symbol}; order proposal skipped.")
                continue
            side = OrderSide.BUY if delta_value > 0 else OrderSide.SELL
            proposal_inputs.append((symbol, side, abs(delta_value), price, target_value, previous_value))

        total_buy_value = sum(value for _, side, value, _, _, _ in proposal_inputs if side == OrderSide.BUY)
        buy_scaling_ratio = min(1.0, self.available_purchase_funds / total_buy_value) if total_buy_value > 0 else 1.0
        if buy_scaling_ratio < 1.0:
            self.warnings.append(
                f"Buy proposals scaled to {buy_scaling_ratio:.2%} because available purchase funds "
                f"({self.available_purchase_funds:,.2f}) are below intended buys ({total_buy_value:,.2f})."
            )

        proposals: list[OrderProposal] = []
        for symbol, side, value, price, target_value, previous_value in proposal_inputs:
            estimated_value = value * buy_scaling_ratio if side == OrderSide.BUY else value
            proposals.append(
                OrderProposal(
                    symbol=symbol,
                    side=side,
                    quantity=estimated_value / price,
                    reference_price=price,
                    estimated_value=estimated_value,
                    reason="Target rebalance delta",
                    details={
                        "target_weight": target_weights.get(symbol, 0.0),
                        "available_purchase_funds": self.available_purchase_funds,
                        "buy_scaling_ratio": buy_scaling_ratio,
                        "previous_value": previous_value,
                        "target_value": target_value,
                    },
                )
            )
        return proposals, buy_scaling_ratio
