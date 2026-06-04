from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from app import config
from app.data.universe_loader import load_universe
from app.storage.market_data_repository import load_market_prices
from app.storage.repositories import (
    insert_holding_snapshots,
    insert_portfolio_snapshot,
    update_backtest_run_result,
)
from app.strategy.models import RunStatus
from app.strategy.selection import allocate_from_ranking


@dataclass(frozen=True)
class BacktestResult:
    backtest_run_id: int
    actual_start_date: date
    actual_end_date: date
    initial_capital: float
    final_value: float
    total_return: float
    annualized_return: float | None
    max_drawdown: float
    rebalance_count: int
    warnings: list[str]


class BacktestEngine:
    def __init__(
        self,
        backtest_run_id: int,
        start_date: date,
        end_date: date,
        initial_capital: float = 1_000_000.0,
        database_path: str | Path = config.DATABASE_PATH,
    ) -> None:
        self.backtest_run_id = backtest_run_id
        self.start_date = start_date
        self.end_date = end_date
        self.initial_capital = initial_capital
        self.database_path = database_path
        self.warnings: list[str] = []
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be greater than zero.")

    def run(self) -> BacktestResult:
        prices = self._load_price_frame()
        if prices.empty:
            raise ValueError("No market prices found. Run fetch-history before backtest.")

        symbols = [stock.symbol for stock in load_universe()]
        price_pivot = self._pivot_prices(prices, symbols)
        if price_pivot.empty:
            raise ValueError("No universe symbols have stored prices for the requested backtest window.")

        benchmark_returns = self._benchmark_returns(prices)
        rebalance_dates = self._rebalance_dates(price_pivot)
        if len(rebalance_dates) < 2:
            raise ValueError("Not enough monthly price history to run a backtest.")

        nav = self.initial_capital
        nav_values: list[float] = [nav]
        previous_holdings: set[str] = set()
        total_months_held: dict[str, int] = {}
        consecutive_months_held: dict[str, int] = {}

        for index, rebalance_date in enumerate(rebalance_dates[:-1], start=1):
            next_date = rebalance_dates[index]
            ranking = self._rank_on_date(price_pivot, benchmark_returns, rebalance_date)
            strategy_allocation = allocate_from_ranking(ranking)
            allocation = strategy_allocation.allocation
            selected = strategy_allocation.selected_symbols
            month_return = self._portfolio_period_return(price_pivot, rebalance_date, next_date, allocation.stock_weights)
            previous_nav = nav
            nav = nav * (1.0 + month_return)
            nav_values.append(nav)

            holdings = set(allocation.stock_weights)
            for symbol in list(consecutive_months_held):
                if symbol not in holdings:
                    consecutive_months_held[symbol] = 0
            for symbol in holdings:
                total_months_held[symbol] = total_months_held.get(symbol, 0) + 1
                consecutive_months_held[symbol] = consecutive_months_held.get(symbol, 0) + 1

            insert_portfolio_snapshot(
                run_id=self.backtest_run_id,
                snapshot_date=next_date,
                portfolio_state="ACTIVE",
                portfolio_nav=nav,
                monthly_return=month_return,
                cumulative_return=(nav / self.initial_capital) - 1.0,
                liquidbees_weight=allocation.liquidbees_weight,
                selected_stock_count=len(selected),
                reshuffle_number=index,
                database_path=self.database_path,
            )
            insert_holding_snapshots(
                self._holding_rows(
                    ranking=ranking,
                    weights=allocation.stock_weights,
                    period_start_date=rebalance_date,
                    snapshot_date=next_date,
                    nav=nav,
                    previous_holdings=previous_holdings,
                    consecutive_months_held=consecutive_months_held,
                    total_months_held=total_months_held,
                    price_pivot=price_pivot,
                ),
                database_path=self.database_path,
            )
            previous_holdings = holdings

        actual_start = rebalance_dates[0]
        actual_end = rebalance_dates[-1]
        total_return = (nav / self.initial_capital) - 1.0
        years = max((actual_end - actual_start).days / 365.25, 0)
        annualized_return = (nav / self.initial_capital) ** (1 / years) - 1 if years > 0 else None
        max_drawdown = self._max_drawdown(nav_values)
        summary = {
            "total_return": total_return,
            "annualized_return": annualized_return,
            "max_drawdown": max_drawdown,
            "rebalance_count": len(rebalance_dates) - 1,
            "rebalances_per_month": config.BACKTEST_REBALANCES_PER_MONTH,
            "strategy_ranking_method": config.STRATEGY_RANKING_METHOD,
            "ranking_momentum_weight": config.RANKING_MOMENTUM_WEIGHT,
            "ranking_beta_weight": config.RANKING_BETA_WEIGHT,
            "ranking_volatility_weight": config.RANKING_VOLATILITY_WEIGHT,
            "strategy_allocation_mode": config.STRATEGY_ALLOCATION_MODE,
            "strategy_top_n": config.STRATEGY_TOP_N,
            "dynamic_min_weight": config.DYNAMIC_MIN_WEIGHT,
            "dynamic_max_weight": config.DYNAMIC_MAX_WEIGHT,
            "methodology": "Configurable-period dual momentum prototype using stored prices, 3M/6M/12M momentum, beta, volatility, 52-week-high filter, configured ranking method, and configured allocation mode.",
        }
        update_backtest_run_result(
            self.backtest_run_id,
            RunStatus.COMPLETED,
            actual_start,
            actual_end,
            self.initial_capital,
            nav,
            summary,
            self.warnings,
            self.database_path,
        )
        return BacktestResult(
            self.backtest_run_id,
            actual_start,
            actual_end,
            self.initial_capital,
            nav,
            total_return,
            annualized_return,
            max_drawdown,
            len(rebalance_dates) - 1,
            self.warnings,
        )

    def _load_price_frame(self) -> pd.DataFrame:
        rows = load_market_prices(self.database_path)
        frame = pd.DataFrame(rows)
        if frame.empty:
            return frame
        frame["price_date"] = pd.to_datetime(frame["price_date"]).dt.date
        frame = frame[(frame["price_date"] >= self.start_date) & (frame["price_date"] <= self.end_date)]
        frame["price"] = frame["adjusted_close"].fillna(frame["close"])
        return frame.dropna(subset=["price"])

    def _pivot_prices(self, prices: pd.DataFrame, symbols: list[str]) -> pd.DataFrame:
        filtered = prices[prices["symbol"].isin(symbols)]
        pivot = filtered.pivot_table(index="price_date", columns="symbol", values="price", aggfunc="last").sort_index()
        return pivot.ffill()

    def _benchmark_returns(self, prices: pd.DataFrame) -> pd.Series | None:
        benchmark = prices[prices["symbol"] == config.DEFAULT_BENCHMARK_SYMBOL]
        if benchmark.empty:
            self.warnings.append("Benchmark prices not found; beta adjustment used beta=1.0.")
            return None
        series = benchmark.pivot_table(index="price_date", values="price", aggfunc="last").sort_index()["price"].ffill()
        return series.pct_change(fill_method=None).replace([float("inf"), float("-inf")], pd.NA).dropna()

    def _rebalance_dates(self, price_pivot: pd.DataFrame) -> list[date]:
        rebalances_per_month = config.BACKTEST_REBALANCES_PER_MONTH
        if rebalances_per_month <= 0:
            raise ValueError("BACKTEST_REBALANCES_PER_MONTH must be greater than zero.")

        dates = pd.Index(price_pivot.index)
        months = sorted({(item.year, item.month) for item in dates})
        result: list[date] = []
        for year, month in months:
            month_dates = [item for item in dates if item.year == year and item.month == month]
            if not month_dates:
                continue
            _, days_in_month = calendar.monthrange(year, month)
            for offset in range(rebalances_per_month):
                target_day = 1 + (offset * days_in_month // rebalances_per_month)
                candidates = [item for item in month_dates if item.day >= target_day]
                if candidates and candidates[0] not in result:
                    result.append(candidates[0])
        return result

    def _rank_on_date(
        self,
        price_pivot: pd.DataFrame,
        benchmark_returns: pd.Series | None,
        rebalance_date: date,
    ) -> pd.DataFrame:
        history = price_pivot.loc[:rebalance_date].tail(config.BETA_LOOKBACK_DAYS + 5)
        rows: list[dict[str, Any]] = []
        for symbol in history.columns:
            series = history[symbol].dropna()
            if len(series) < config.BETA_LOOKBACK_DAYS:
                continue
            current = float(series.iloc[-1])
            high_52w = float(series.tail(252).max())
            if high_52w <= 0 or current / high_52w < config.HIGH_52W_THRESHOLD:
                continue
            returns = []
            for lookback in [63, 126, 252]:
                if len(series) <= lookback:
                    returns = []
                    break
                lookback_price = float(series.iloc[-lookback - 1])
                if lookback_price <= 0:
                    returns = []
                    break
                returns.append((current / lookback_price) - 1.0)
            if not returns:
                continue
            beta = self._beta(series, benchmark_returns)
            stock_returns = series.pct_change(fill_method=None).dropna()
            volatility = float(stock_returns.tail(config.BETA_LOOKBACK_DAYS).std(ddof=0) * (252**0.5)) if len(stock_returns) else None
            momentum_score = sum(returns) / len(returns)
            rows.append(
                {
                    "symbol": symbol,
                    "momentum_score": momentum_score,
                    "beta": beta,
                    "volatility": volatility,
                    "return_3m": returns[0],
                    "return_6m": returns[1],
                    "return_12m": returns[2],
                }
            )
        if not rows:
            return pd.DataFrame(columns=["symbol", "score", "rank"])
        frame = pd.DataFrame(rows).dropna(subset=["momentum_score", "beta", "volatility"])
        if frame.empty:
            return pd.DataFrame(columns=["symbol", "score", "rank"])
        frame["score"] = self._ranking_score(frame)
        frame = frame.sort_values("score", ascending=False).reset_index(drop=True)
        frame["rank"] = frame.index + 1
        return frame

    def _ranking_score(self, frame: pd.DataFrame) -> pd.Series:
        method = config.STRATEGY_RANKING_METHOD.strip().upper()
        if method == "MOMENTUM":
            return frame["momentum_score"]
        if method == "BETA_ADJUSTED":
            return frame["momentum_score"] / frame["beta"].clip(lower=config.BETA_FLOOR)
        if method == "VOLATILITY_ADJUSTED":
            return frame["momentum_score"] / frame["volatility"].clip(lower=0.01)
        if method == "COMBINED_RANK":
            total = config.RANKING_MOMENTUM_WEIGHT + config.RANKING_BETA_WEIGHT + config.RANKING_VOLATILITY_WEIGHT
            if total <= 0:
                raise ValueError("RANKING_MOMENTUM_WEIGHT + RANKING_BETA_WEIGHT + RANKING_VOLATILITY_WEIGHT must be greater than zero.")
            momentum_weight = config.RANKING_MOMENTUM_WEIGHT / total
            beta_weight = config.RANKING_BETA_WEIGHT / total
            volatility_weight = config.RANKING_VOLATILITY_WEIGHT / total
            momentum_percentile = frame["momentum_score"].rank(pct=True, ascending=True)
            low_beta_percentile = (-frame["beta"]).rank(pct=True, ascending=True)
            low_volatility_percentile = (-frame["volatility"]).rank(pct=True, ascending=True)
            return (
                momentum_weight * momentum_percentile
                + beta_weight * low_beta_percentile
                + volatility_weight * low_volatility_percentile
            )
        raise ValueError("STRATEGY_RANKING_METHOD must be MOMENTUM, BETA_ADJUSTED, VOLATILITY_ADJUSTED, or COMBINED_RANK.")

    def _beta(self, stock_prices: pd.Series, benchmark_returns: pd.Series | None) -> float:
        if benchmark_returns is None:
            return 1.0
        stock_returns = stock_prices.pct_change(fill_method=None)
        aligned = pd.concat([stock_returns, benchmark_returns], axis=1, join="inner")
        aligned = aligned.replace([float("inf"), float("-inf")], pd.NA).dropna()
        if len(aligned) < 30:
            return 1.0
        stock = aligned.iloc[:, 0]
        benchmark = aligned.iloc[:, 1]
        variance = benchmark.var()
        if pd.isna(variance) or variance <= 0:
            return 1.0
        covariance = stock.cov(benchmark)
        if pd.isna(covariance):
            return 1.0
        beta = float(covariance / variance)
        return beta if beta > 0 else config.BETA_FLOOR

    def _portfolio_period_return(
        self,
        price_pivot: pd.DataFrame,
        start_date: date,
        end_date: date,
        weights: dict[str, float],
    ) -> float:
        result = 0.0
        for symbol, weight in weights.items():
            start_price = price_pivot.at[start_date, symbol]
            end_price = price_pivot.at[end_date, symbol]
            if pd.isna(start_price) or pd.isna(end_price) or start_price <= 0:
                continue
            result += weight * ((float(end_price) / float(start_price)) - 1.0)
        return result

    def _holding_rows(
        self,
        ranking: pd.DataFrame,
        weights: dict[str, float],
        period_start_date: date,
        snapshot_date: date,
        nav: float,
        previous_holdings: set[str],
        consecutive_months_held: dict[str, int],
        total_months_held: dict[str, int],
        price_pivot: pd.DataFrame,
    ) -> list[dict[str, Any]]:
        rank_by_symbol = dict(zip(ranking["symbol"], ranking["rank"], strict=False)) if not ranking.empty else {}
        rows: list[dict[str, Any]] = []
        for symbol, weight in weights.items():
            start_price = float(price_pivot.at[period_start_date, symbol])
            price = float(price_pivot.at[snapshot_date, symbol])
            monthly_return = (price / start_price) - 1.0 if start_price > 0 else None
            portfolio_contribution = weight * monthly_return if monthly_return is not None else None
            rows.append(
                {
                    "run_id": self.backtest_run_id,
                    "snapshot_date": snapshot_date,
                    "symbol": symbol,
                    "rank": int(rank_by_symbol.get(symbol, 0)) or None,
                    "selected": True,
                    "weight": weight,
                    "quantity": (nav * weight) / price if price > 0 else None,
                    "reference_price": price,
                    "market_value": nav * weight,
                    "monthly_return": monthly_return,
                    "portfolio_contribution": portfolio_contribution,
                    "holding_action": "HELD" if symbol in previous_holdings else "ENTERED",
                    "consecutive_months_held": consecutive_months_held.get(symbol, 0),
                    "total_months_held": total_months_held.get(symbol, 0),
                }
            )
        return rows

    def _max_drawdown(self, nav_values: list[float]) -> float:
        peak = nav_values[0]
        max_drawdown = 0.0
        for value in nav_values:
            peak = max(peak, value)
            if peak > 0:
                max_drawdown = min(max_drawdown, (value / peak) - 1.0)
        return max_drawdown
