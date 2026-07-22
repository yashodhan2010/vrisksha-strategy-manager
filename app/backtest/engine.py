from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from math import floor
from pathlib import Path
from typing import Any

import math
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
        self._safe_asset_warning_added = False
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be greater than zero.")

    def run(self) -> BacktestResult:
        prices = self._load_price_frame()
        if prices.empty:
            raise ValueError("No market prices found. Run fetch-history before backtest.")

        universe = load_universe()
        symbols = [stock.symbol for stock in universe]
        universe_by_symbol = {stock.symbol: stock for stock in universe}
        price_pivot = self._pivot_prices(prices, symbols)
        if price_pivot.empty:
            raise ValueError("No universe symbols have stored prices for the requested backtest window.")

        benchmark_returns = self._benchmark_returns(prices)
        rebalance_dates = self._rebalance_dates(price_pivot)
        if len(rebalance_dates) < 2:
            raise ValueError("Not enough monthly price history to run a backtest.")

        nav = self.initial_capital
        nav_values: list[float] = [nav]
        period_returns: list[float] = []
        previous_holdings: set[str] = set()
        total_months_held: dict[str, int] = {}
        consecutive_months_held: dict[str, int] = {}

        for index, rebalance_date in enumerate(rebalance_dates[:-1], start=1):
            next_date = rebalance_dates[index]
            ranking = self._rank_on_date(price_pivot, benchmark_returns, rebalance_date)
            strategy_allocation = allocate_from_ranking(
                ranking,
                sector_by_symbol={symbol: stock.sector for symbol, stock in universe_by_symbol.items()},
                previous_symbols=previous_holdings,
            )
            allocation = strategy_allocation.allocation
            selected = strategy_allocation.selected_symbols
            month_return = self._portfolio_period_return(
                price_pivot,
                rebalance_date,
                next_date,
                allocation.stock_weights,
                allocation.safe_asset_symbol,
                allocation.safe_asset_weight,
            )
            previous_nav = nav
            nav = nav * (1.0 + month_return)
            nav_values.append(nav)
            period_returns.append(month_return)

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
                    universe_by_symbol=universe_by_symbol,
                    safe_asset_symbol=allocation.safe_asset_symbol,
                    safe_asset_weight=allocation.safe_asset_weight,
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
        annualized_volatility = self._annualized_volatility(period_returns, years)
        sharpe_like = annualized_return / annualized_volatility if annualized_return is not None and annualized_volatility > 0 else None
        summary = {
            "total_return": total_return,
            "annualized_return": annualized_return,
            "cagr": annualized_return,
            "max_drawdown": max_drawdown,
            "absolute_drawdown": abs(max_drawdown),
            "annualized_volatility": annualized_volatility,
            "volatility": annualized_volatility,
            "sharpe_like": sharpe_like,
            "sharpe_ratio": sharpe_like,
            "calmar_ratio": annualized_return / abs(max_drawdown) if annualized_return is not None and max_drawdown < 0 else None,
            "rebalance_count": len(rebalance_dates) - 1,
            "rebalances_per_month": config.BACKTEST_REBALANCES_PER_MONTH,
            "strategy_ranking_method": config.STRATEGY_RANKING_METHOD,
            "ranking_momentum_weight": config.RANKING_MOMENTUM_WEIGHT,
            "ranking_beta_weight": config.RANKING_BETA_WEIGHT,
            "ranking_volatility_weight": config.RANKING_VOLATILITY_WEIGHT,
            "strategy_allocation_mode": config.STRATEGY_ALLOCATION_MODE,
            "strategy_top_n": config.STRATEGY_TOP_N,
            "buffer_pct": config.BUFFER_PCT,
            "max_stock_weight": config.MAX_STOCK_WEIGHT,
            "max_sector_weight": config.MAX_SECTOR_WEIGHT,
            "safe_asset_symbol": config.SAFE_ASSET_SYMBOL,
            "dynamic_min_weight": config.DYNAMIC_MIN_WEIGHT,
            "dynamic_max_weight": config.DYNAMIC_MAX_WEIGHT,
            "methodology": "Configurable-period dual momentum prototype using stored prices, 3M/6M/12M momentum, beta, volatility, 52-week-high filter, configured ranking method, configured allocation mode, sector caps, and configured safe asset/cash residual.",
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
        frame = frame[frame["price_date"] <= self.end_date]
        frame["price"] = frame["adjusted_close"].fillna(frame["close"])
        return frame.dropna(subset=["price"])

    def _pivot_prices(self, prices: pd.DataFrame, symbols: list[str]) -> pd.DataFrame:
        filtered = prices[prices["symbol"].isin(symbols)]
        pivot = filtered.pivot_table(index="price_date", columns="symbol", values="price", aggfunc="last").sort_index()
        pivot = _bounded_forward_fill(pivot)
        if config.SAFE_ASSET_SYMBOL:
            safe_asset = prices[prices["symbol"] == config.SAFE_ASSET_SYMBOL]
            if not safe_asset.empty and not pivot.empty:
                safe_series = safe_asset.pivot_table(index="price_date", values="price", aggfunc="last").sort_index()["price"]
                pivot[config.SAFE_ASSET_SYMBOL] = _bounded_forward_fill(safe_series.reindex(pivot.index))
        return pivot

    def _benchmark_returns(self, prices: pd.DataFrame) -> pd.Series | None:
        benchmark = prices[prices["symbol"] == config.DEFAULT_BENCHMARK_SYMBOL]
        if benchmark.empty:
            self.warnings.append("Benchmark prices not found; beta adjustment used beta=1.0.")
            return None
        series = _bounded_forward_fill(benchmark.pivot_table(index="price_date", values="price", aggfunc="last").sort_index()["price"])
        return series.pct_change(fill_method=None).replace([float("inf"), float("-inf")], pd.NA).dropna()

    def _rebalance_dates(self, price_pivot: pd.DataFrame) -> list[date]:
        rebalances_per_month = config.BACKTEST_REBALANCES_PER_MONTH
        if rebalances_per_month <= 0:
            raise ValueError("BACKTEST_REBALANCES_PER_MONTH must be greater than zero.")

        dates = pd.Index(item for item in price_pivot.index if self.start_date <= item <= self.end_date)
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
        required_history_days = config.BETA_LOOKBACK_DAYS + max(config.MOMENTUM_SKIP_RECENT_DAYS, 0)
        history = price_pivot.loc[:rebalance_date, [symbol for symbol in price_pivot.columns if symbol != config.SAFE_ASSET_SYMBOL]]
        history = history.tail(required_history_days + 5)
        if len(history) <= required_history_days:
            return pd.DataFrame(columns=["symbol", "score", "rank"])

        valid_columns = history.columns[history.notna().sum() > required_history_days]
        if len(valid_columns) == 0:
            return pd.DataFrame(columns=["symbol", "score", "rank"])
        history = history[valid_columns]
        current = history.iloc[-1]
        momentum_anchor = history.iloc[-1 - max(config.MOMENTUM_SKIP_RECENT_DAYS, 0)]
        high_52w = history.tail(252).max()
        lookback_3m = history.iloc[-64 - max(config.MOMENTUM_SKIP_RECENT_DAYS, 0)]
        lookback_6m = history.iloc[-127 - max(config.MOMENTUM_SKIP_RECENT_DAYS, 0)]
        lookback_12m = history.iloc[-253 - max(config.MOMENTUM_SKIP_RECENT_DAYS, 0)]
        valid = (
            current.notna()
            & high_52w.gt(0)
            & (current / high_52w).ge(config.HIGH_52W_THRESHOLD)
            & lookback_3m.gt(0)
            & lookback_6m.gt(0)
            & lookback_12m.gt(0)
        )
        if not valid.any():
            return pd.DataFrame(columns=["symbol", "score", "rank"])

        selected_history = history.loc[:, valid]
        recent_returns = selected_history.pct_change(fill_method=None).replace([float("inf"), float("-inf")], pd.NA)
        clean_columns = (recent_returns.abs().le(config.MAX_SIGNAL_DAILY_RETURN) | recent_returns.isna()).all(axis=0)
        selected_history = selected_history.loc[:, clean_columns]
        if selected_history.empty:
            return pd.DataFrame(columns=["symbol", "score", "rank"])

        valid_symbols = selected_history.columns
        returns = pd.DataFrame(
            {
                "return_3m": momentum_anchor.loc[valid_symbols] / lookback_3m.loc[valid_symbols] - 1.0,
                "return_6m": momentum_anchor.loc[valid_symbols] / lookback_6m.loc[valid_symbols] - 1.0,
                "return_12m": momentum_anchor.loc[valid_symbols] / lookback_12m.loc[valid_symbols] - 1.0,
            }
        ).replace([float("inf"), float("-inf")], pd.NA)
        stock_returns = selected_history.pct_change(fill_method=None).replace([float("inf"), float("-inf")], pd.NA)
        volatility = stock_returns.tail(config.BETA_LOOKBACK_DAYS).std(ddof=0) * (252**0.5)
        beta = self._beta_frame(stock_returns, benchmark_returns)
        frame = returns.assign(
            symbol=returns.index,
            momentum_score=returns[["return_3m", "return_6m", "return_12m"]].mean(axis=1),
            beta=beta.reindex(returns.index).fillna(1.0).clip(lower=config.BETA_FLOOR),
            volatility=volatility.reindex(returns.index),
        ).dropna(subset=["momentum_score", "beta", "volatility"])
        frame.index.name = None
        if frame.empty:
            return pd.DataFrame(columns=["symbol", "score", "rank"])
        if config.STRATEGY_RANKING_METHOD.strip().upper() == "AVERAGE_RANK":
            frame = self._add_average_rank_columns(frame)
        frame["score"] = self._ranking_score(frame)
        frame = frame.sort_values(["score", "symbol"], ascending=[False, True]).reset_index(drop=True)
        frame["rank"] = frame.index + 1
        return frame

    def _add_average_rank_columns(self, frame: pd.DataFrame) -> pd.DataFrame:
        ranked = frame.copy()
        ranked["momentum_rank"] = ranked["momentum_score"].rank(method="average", ascending=False)
        ranked["beta_rank"] = ranked["beta"].rank(method="average", ascending=True)
        ranked["volatility_rank"] = ranked["volatility"].rank(method="average", ascending=True)
        ranked["average_rank"] = ranked[["momentum_rank", "beta_rank", "volatility_rank"]].mean(axis=1)
        total = config.RANKING_MOMENTUM_WEIGHT + config.RANKING_BETA_WEIGHT + config.RANKING_VOLATILITY_WEIGHT
        if total <= 0:
            raise ValueError("RANKING_MOMENTUM_WEIGHT + RANKING_BETA_WEIGHT + RANKING_VOLATILITY_WEIGHT must be greater than zero.")
        momentum_weight = config.RANKING_MOMENTUM_WEIGHT / total
        beta_weight = config.RANKING_BETA_WEIGHT / total
        volatility_weight = config.RANKING_VOLATILITY_WEIGHT / total
        ranked["weighted_average_rank"] = (
            momentum_weight * ranked["momentum_rank"]
            + beta_weight * ranked["beta_rank"]
            + volatility_weight * ranked["volatility_rank"]
        )
        return ranked

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
        if method == "AVERAGE_RANK":
            if "weighted_average_rank" in frame.columns:
                return -frame["weighted_average_rank"]
            return -self._add_average_rank_columns(frame)["weighted_average_rank"]
        raise ValueError("STRATEGY_RANKING_METHOD must be MOMENTUM, BETA_ADJUSTED, VOLATILITY_ADJUSTED, COMBINED_RANK, or AVERAGE_RANK.")

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

    def _beta_frame(self, stock_returns: pd.DataFrame, benchmark_returns: pd.Series | None) -> pd.Series:
        if benchmark_returns is None or stock_returns.empty:
            return pd.Series(1.0, index=stock_returns.columns)
        benchmark = benchmark_returns.reindex(stock_returns.index).replace([float("inf"), float("-inf")], pd.NA)
        variance = benchmark.var()
        if pd.isna(variance) or variance <= 0:
            return pd.Series(1.0, index=stock_returns.columns)
        mask = stock_returns.notna() & benchmark.notna().to_numpy()[:, None]
        counts = mask.sum(axis=0)
        demeaned_benchmark = benchmark - benchmark.mean()
        demeaned_stocks = stock_returns - stock_returns.mean(axis=0)
        covariance = demeaned_stocks.mul(demeaned_benchmark, axis=0).where(mask).sum(axis=0) / (counts - 1)
        beta = covariance / variance
        beta = beta.where(counts >= 30, 1.0).fillna(1.0)
        return beta.where(beta > 0, config.BETA_FLOOR)

    def _portfolio_period_return(
        self,
        price_pivot: pd.DataFrame,
        start_date: date,
        end_date: date,
        weights: dict[str, float],
        safe_asset_symbol: str,
        safe_asset_weight: float,
    ) -> float:
        result = 0.0
        for symbol, weight in weights.items():
            start_price = price_pivot.at[start_date, symbol]
            end_price = price_pivot.at[end_date, symbol]
            if pd.isna(start_price) or pd.isna(end_price) or start_price <= 0:
                continue
            symbol_return = (float(end_price) / float(start_price)) - 1.0
            if abs(symbol_return) > config.MAX_BACKTEST_PERIOD_RETURN:
                self.warnings.append(
                    f"Skipped extreme backtest period return for {symbol} from {start_date} to {end_date}: {symbol_return:.2%}."
                )
                continue
            result += weight * symbol_return
        result += self._safe_asset_period_return(price_pivot, start_date, end_date, safe_asset_symbol, safe_asset_weight)
        return result

    def _safe_asset_period_return(
        self,
        price_pivot: pd.DataFrame,
        start_date: date,
        end_date: date,
        safe_asset_symbol: str,
        safe_asset_weight: float,
    ) -> float:
        if safe_asset_weight <= 0:
            return 0.0
        if safe_asset_symbol not in price_pivot.columns:
            if not self._safe_asset_warning_added:
                self.warnings.append(f"Safe asset {safe_asset_symbol} prices not found; residual allocation treated as cash.")
                self._safe_asset_warning_added = True
            return 0.0
        start_price = price_pivot.at[start_date, safe_asset_symbol]
        end_price = price_pivot.at[end_date, safe_asset_symbol]
        if pd.isna(start_price) or pd.isna(end_price) or start_price <= 0:
            if not self._safe_asset_warning_added:
                self.warnings.append(f"Safe asset {safe_asset_symbol} had unusable prices; residual allocation treated as cash.")
                self._safe_asset_warning_added = True
            return 0.0
        symbol_return = (float(end_price) / float(start_price)) - 1.0
        if abs(symbol_return) > config.MAX_BACKTEST_PERIOD_RETURN:
            self.warnings.append(
                f"Skipped extreme backtest period return for {safe_asset_symbol} from {start_date} to {end_date}: {symbol_return:.2%}."
            )
            return 0.0
        return safe_asset_weight * symbol_return

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
        universe_by_symbol: dict[str, object],
        safe_asset_symbol: str,
        safe_asset_weight: float,
    ) -> list[dict[str, Any]]:
        rank_by_symbol = dict(zip(ranking["symbol"], ranking["rank"], strict=False)) if not ranking.empty else {}
        rows: list[dict[str, Any]] = []
        for symbol, weight in weights.items():
            stock = universe_by_symbol.get(symbol)
            start_price = float(price_pivot.at[period_start_date, symbol])
            price = float(price_pivot.at[snapshot_date, symbol])
            quantity = floor((nav * weight) / price) if price > 0 else None
            monthly_return = (price / start_price) - 1.0 if start_price > 0 else None
            portfolio_contribution = weight * monthly_return if monthly_return is not None else None
            rows.append(
                {
                    "run_id": self.backtest_run_id,
                    "snapshot_date": snapshot_date,
                    "symbol": symbol,
                    "industry": getattr(stock, "industry", None),
                    "sector": getattr(stock, "sector", None),
                    "rank": int(rank_by_symbol.get(symbol, 0)) or None,
                    "selected": True,
                    "weight": weight,
                    "quantity": quantity,
                    "reference_price": price,
                    "market_value": (quantity * price) if quantity is not None else None,
                    "monthly_return": monthly_return,
                    "portfolio_contribution": portfolio_contribution,
                    "holding_action": "HELD" if symbol in previous_holdings else "ENTERED",
                    "consecutive_months_held": consecutive_months_held.get(symbol, 0),
                    "total_months_held": total_months_held.get(symbol, 0),
                }
            )
        if safe_asset_weight > 0:
            rows.extend(
                self._safe_asset_holding_row(
                    safe_asset_symbol=safe_asset_symbol,
                    safe_asset_weight=safe_asset_weight,
                    period_start_date=period_start_date,
                    snapshot_date=snapshot_date,
                    nav=nav,
                    price_pivot=price_pivot,
                )
            )
        return rows

    def _safe_asset_holding_row(
        self,
        safe_asset_symbol: str,
        safe_asset_weight: float,
        period_start_date: date,
        snapshot_date: date,
        nav: float,
        price_pivot: pd.DataFrame,
    ) -> list[dict[str, Any]]:
        if safe_asset_symbol not in price_pivot.columns:
            return []
        start_price = price_pivot.at[period_start_date, safe_asset_symbol]
        price = price_pivot.at[snapshot_date, safe_asset_symbol]
        if pd.isna(start_price) or pd.isna(price) or price <= 0:
            return []
        start_price_float = float(start_price)
        price_float = float(price)
        quantity = floor((nav * safe_asset_weight) / price_float)
        monthly_return = (price_float / start_price_float) - 1.0 if start_price_float > 0 else None
        portfolio_contribution = safe_asset_weight * monthly_return if monthly_return is not None else None
        return [
            {
                "run_id": self.backtest_run_id,
                "snapshot_date": snapshot_date,
                "symbol": safe_asset_symbol,
                "industry": "SAFE_ASSET",
                "sector": "SAFE_ASSET",
                "rank": None,
                "selected": True,
                "weight": safe_asset_weight,
                "quantity": quantity,
                "reference_price": price_float,
                "market_value": quantity * price_float,
                "monthly_return": monthly_return,
                "portfolio_contribution": portfolio_contribution,
                "holding_action": "SAFE_ASSET",
                "consecutive_months_held": 0,
                "total_months_held": 0,
            }
        ]

    def _max_drawdown(self, nav_values: list[float]) -> float:
        peak = nav_values[0]
        max_drawdown = 0.0
        for value in nav_values:
            peak = max(peak, value)
            if peak > 0:
                max_drawdown = min(max_drawdown, (value / peak) - 1.0)
        return max_drawdown

    def _annualized_volatility(self, period_returns: list[float], years: float) -> float:
        if not period_returns or years <= 0:
            return 0.0
        series = pd.Series(period_returns)
        periods_per_year = len(series) / years
        return float(series.std(ddof=0) * math.sqrt(periods_per_year)) if periods_per_year > 0 else 0.0


def _bounded_forward_fill(frame: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    limit = config.MAX_PRICE_FORWARD_FILL_DAYS
    if limit <= 0:
        return frame
    return frame.ffill(limit=limit)
