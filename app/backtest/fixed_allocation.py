from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from math import floor
from pathlib import Path
from typing import Any

import math
import pandas as pd

from app import config
from app.backtest.distributions import distribution_path_from_profile, distribution_per_unit, load_distribution_events
from app.storage.market_data_repository import load_market_prices
from app.storage.repositories import insert_holding_snapshots, insert_portfolio_snapshot, update_backtest_run_result
from app.strategy.models import RunStatus
from app.strategy_profile import load_strategy_profile


STT_DELIVERY_SELL_RATE = 0.001
EXCHANGE_TRANSACTION_RATE = 0.0000307
SEBI_TURNOVER_RATE = 0.000001
STAMP_DUTY_BUY_RATE = 0.00015
GST_RATE = 0.18
DP_CHARGE_PER_SOLD_SCRIP = 15.34


@dataclass(frozen=True)
class FixedAllocationBacktestResult:
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


class FixedAllocationBacktestEngine:
    def __init__(
        self,
        backtest_run_id: int,
        strategy_profile: str | Path,
        start_date: date,
        end_date: date,
        initial_capital: float = 1_000_000.0,
        database_path: str | Path = config.DATABASE_PATH,
    ) -> None:
        self.backtest_run_id = backtest_run_id
        self.strategy_profile = Path(strategy_profile)
        self.profile = load_strategy_profile(self.strategy_profile)
        self.start_date = start_date
        self.end_date = end_date
        self.initial_capital = initial_capital
        self.database_path = database_path
        self.warnings: list[str] = []
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be greater than zero.")
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date.")

    def run(self) -> FixedAllocationBacktestResult:
        assets = _assets_from_profile(self.profile)
        prices = self._load_price_frame()
        distributions = self._load_distribution_events([asset["symbol"] for asset in assets])
        if prices.empty:
            raise ValueError("No market prices found. Run fetch-history before backtest.")
        price_pivot = self._pivot_prices(prices, [asset["symbol"] for asset in assets])
        if price_pivot.empty:
            raise ValueError("No configured asset symbols have stored prices for the requested backtest window.")
        rebalance_dates = self._quarterly_rebalance_dates(price_pivot)
        if len(rebalance_dates) < 2:
            raise ValueError("Not enough quarterly price history to run a fixed-allocation backtest.")

        nav = self.initial_capital
        nav_values = [nav]
        period_returns: list[float] = []
        previous_holdings: set[str] = set()
        current_values: dict[str, float] = {}
        detail_rows: list[dict[str, Any]] = []

        for index, rebalance_date in enumerate(rebalance_dates[:-1], start=1):
            next_date = rebalance_dates[index]
            target_values_before_cost = {str(asset["symbol"]): nav * float(asset["weight"]) for asset in assets}
            trades = {
                symbol: target_values_before_cost[symbol] - current_values.get(symbol, 0.0)
                for symbol in target_values_before_cost
            }
            cost_breakdown = _estimate_transaction_costs(trades)
            nav_after_cost = max(0.0, nav - cost_breakdown["total_transaction_cost"])
            target_values = {str(asset["symbol"]): nav_after_cost * float(asset["weight"]) for asset in assets}
            gross_period_return, asset_returns, price_returns, distribution_returns = self._portfolio_period_return(
                price_pivot,
                distributions,
                rebalance_date,
                next_date,
                assets,
            )
            end_values = {
                symbol: target_values[symbol] * (1.0 + asset_returns.get(symbol, 0.0))
                for symbol in target_values
            }
            previous_nav = nav
            gross_nav_before_cost = previous_nav * (1.0 + gross_period_return)
            nav = sum(end_values.values())
            period_return = (nav / previous_nav) - 1.0 if previous_nav > 0 else 0.0
            nav_values.append(nav)
            period_returns.append(period_return)
            detail_rows.append(
                self._detail_row(
                    assets=assets,
                    rebalance_date=rebalance_date,
                    next_rebalance_date=next_date,
                    starting_nav=previous_nav,
                    nav_after_cost=nav_after_cost,
                    ending_nav=nav,
                    gross_nav_before_cost=gross_nav_before_cost,
                    gross_period_return=gross_period_return,
                    net_period_return=period_return,
                    trades=trades,
                    cost_breakdown=cost_breakdown,
                    asset_returns=asset_returns,
                    price_returns=price_returns,
                    distribution_returns=distribution_returns,
                )
            )
            insert_portfolio_snapshot(
                run_id=self.backtest_run_id,
                snapshot_date=next_date,
                portfolio_state="ACTIVE",
                portfolio_nav=nav,
                monthly_return=period_return,
                cumulative_return=(nav / self.initial_capital) - 1.0,
                liquidbees_weight=_weight_for_symbol(assets, "LIQUIDBEES"),
                selected_stock_count=len(assets),
                reshuffle_number=index,
                database_path=self.database_path,
            )
            insert_holding_snapshots(
                self._holding_rows(
                    assets,
                    price_pivot,
                    rebalance_date,
                    next_date,
                    nav,
                    previous_holdings,
                    end_values,
                ),
                database_path=self.database_path,
            )
            previous_holdings = {asset["symbol"] for asset in assets}
            current_values = end_values

        actual_start = rebalance_dates[0]
        actual_end = rebalance_dates[-1]
        total_return = (nav / self.initial_capital) - 1.0
        years = max((actual_end - actual_start).days / 365.25, 0)
        annualized_return = (nav / self.initial_capital) ** (1 / years) - 1 if years > 0 else None
        max_drawdown = _max_drawdown(nav_values)
        annualized_volatility = _annualized_volatility(period_returns, years)
        summary = {
            "strategy_type": "fixed_allocation",
            "allocation_method": "fixed_equal_weight",
            "assets": assets,
            "distribution_frequency": (self.profile.get("distribution") or {}).get("frequency", "quarterly"),
            "total_return": total_return,
            "annualized_return": annualized_return,
            "cagr": annualized_return,
            "max_drawdown": max_drawdown,
            "absolute_drawdown": abs(max_drawdown),
            "annualized_volatility": annualized_volatility,
            "volatility": annualized_volatility,
            "sharpe_like": annualized_return / annualized_volatility
            if annualized_return is not None and annualized_volatility > 0
            else None,
            "rebalance_count": len(rebalance_dates) - 1,
            "total_transaction_cost": float(sum(row["total_transaction_cost"] for row in detail_rows)),
            "total_transaction_cost_pct_initial_capital": float(
                sum(row["total_transaction_cost"] for row in detail_rows) / self.initial_capital
            ),
            "total_distribution_cash": float(sum(row["distribution_cash"] for row in detail_rows)),
            "total_distribution_return_pct_initial_capital": float(
                sum(row["distribution_cash"] for row in detail_rows) / self.initial_capital
            ),
            "net_total_return": total_return,
            "net_cagr": annualized_return,
            "rebalance_schedule": self.profile.get("rebalance_schedule"),
            "methodology": "Fixed 20% allocation across InvIT, REIT, gold, debt, and Nifty 50 sleeves, rebalanced on the first trading day of each quarter. Dividend and distribution events are included when present in the configured event file.",
        }
        self._write_experiment_outputs(summary, detail_rows)
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
        return FixedAllocationBacktestResult(
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
        frame = pd.DataFrame(load_market_prices(self.database_path))
        if frame.empty:
            return frame
        frame["price_date"] = pd.to_datetime(frame["price_date"]).dt.date
        frame = frame[frame["price_date"] <= self.end_date]
        frame["price"] = frame["adjusted_close"].fillna(frame["close"])
        return frame.dropna(subset=["price"])

    def _pivot_prices(self, prices: pd.DataFrame, symbols: list[str]) -> pd.DataFrame:
        filtered = prices[prices["symbol"].isin(symbols)]
        pivot = filtered.pivot_table(index="price_date", columns="symbol", values="price", aggfunc="last").sort_index()
        return pivot.ffill(limit=config.MAX_PRICE_FORWARD_FILL_DAYS)

    def _load_distribution_events(self, symbols: list[str]) -> pd.DataFrame:
        return load_distribution_events(
            distribution_path_from_profile(self.profile),
            symbols,
            self.start_date,
            self.end_date,
            self.warnings,
        )

    def _quarterly_rebalance_dates(self, price_pivot: pd.DataFrame) -> list[date]:
        dates = pd.Index(item for item in price_pivot.index if self.start_date <= item <= self.end_date)
        result: list[date] = []
        for year, month in sorted({(item.year, item.month) for item in dates}):
            if month not in {1, 4, 7, 10}:
                continue
            month_dates = [item for item in dates if item.year == year and item.month == month]
            if month_dates and month_dates[0] not in result:
                result.append(month_dates[0])
        return result

    def _portfolio_period_return(
        self,
        price_pivot: pd.DataFrame,
        distributions: pd.DataFrame,
        start_date: date,
        end_date: date,
        assets: list[dict[str, Any]],
    ) -> tuple[float, dict[str, float], dict[str, float], dict[str, float]]:
        result = 0.0
        asset_returns: dict[str, float] = {}
        price_returns: dict[str, float] = {}
        distribution_returns: dict[str, float] = {}
        for asset in assets:
            symbol = str(asset["symbol"])
            start_price = price_pivot.at[start_date, symbol]
            end_price = price_pivot.at[end_date, symbol]
            if pd.isna(start_price) or pd.isna(end_price) or start_price <= 0:
                self.warnings.append(f"Skipped {symbol} from {start_date} to {end_date}: missing or unusable price.")
                continue
            price_return = (float(end_price) / float(start_price)) - 1.0
            distribution_per_unit_value = distribution_per_unit(distributions, symbol, start_date, end_date)
            distribution_return = distribution_per_unit_value / float(start_price)
            symbol_return = price_return + distribution_return
            if abs(symbol_return) > config.MAX_BACKTEST_PERIOD_RETURN:
                self.warnings.append(
                    f"Skipped extreme backtest period return for {symbol} from {start_date} to {end_date}: {symbol_return:.2%}."
                )
                continue
            asset_returns[symbol] = symbol_return
            price_returns[symbol] = price_return
            distribution_returns[symbol] = distribution_return
            result += float(asset["weight"]) * symbol_return
        return result, asset_returns, price_returns, distribution_returns

    def _holding_rows(
        self,
        assets: list[dict[str, Any]],
        price_pivot: pd.DataFrame,
        period_start_date: date,
        snapshot_date: date,
        nav: float,
        previous_holdings: set[str],
        end_values: dict[str, float],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for rank, asset in enumerate(assets, start=1):
            symbol = str(asset["symbol"])
            weight = float(asset["weight"])
            start_price = price_pivot.at[period_start_date, symbol]
            price = price_pivot.at[snapshot_date, symbol]
            if pd.isna(start_price) or pd.isna(price) or price <= 0:
                continue
            price_float = float(price)
            start_price_float = float(start_price)
            market_value = end_values.get(symbol, nav * weight)
            actual_weight = market_value / nav if nav > 0 else weight
            quantity = floor(market_value / price_float)
            period_return = (price_float / start_price_float) - 1.0 if start_price_float > 0 else None
            rows.append(
                {
                    "run_id": self.backtest_run_id,
                    "snapshot_date": snapshot_date,
                    "symbol": symbol,
                    "industry": asset.get("sleeve"),
                    "sector": "MULTI_ASSET",
                    "rank": rank,
                    "selected": True,
                    "weight": actual_weight,
                    "quantity": quantity,
                    "reference_price": price_float,
                    "market_value": market_value,
                    "monthly_return": period_return,
                    "portfolio_contribution": weight * period_return if period_return is not None else None,
                    "holding_action": "HELD" if symbol in previous_holdings else "ENTERED",
                    "consecutive_months_held": 1,
                    "total_months_held": 1,
                }
            )
        return rows

    def _detail_row(
        self,
        assets: list[dict[str, Any]],
        rebalance_date: date,
        next_rebalance_date: date,
        starting_nav: float,
        nav_after_cost: float,
        ending_nav: float,
        gross_nav_before_cost: float,
        gross_period_return: float,
        net_period_return: float,
        trades: dict[str, float],
        cost_breakdown: dict[str, float],
        asset_returns: dict[str, float],
        price_returns: dict[str, float],
        distribution_returns: dict[str, float],
    ) -> dict[str, Any]:
        total_distribution_cash = sum(
            nav_after_cost * float(asset["weight"]) * distribution_returns.get(str(asset["symbol"]), 0.0)
            for asset in assets
        )
        row: dict[str, Any] = {
            "strategy_id": self.profile.get("strategy_id"),
            "strategy_slug": self.profile.get("slug"),
            "period_start": rebalance_date.isoformat(),
            "period_end": next_rebalance_date.isoformat(),
            "starting_nav": starting_nav,
            "gross_nav_before_cost": gross_nav_before_cost,
            "nav_after_rebalance_cost": nav_after_cost,
            "ending_nav": ending_nav,
            "gross_period_return": gross_period_return,
            "net_period_return": net_period_return,
            "transaction_cost_drag_return": cost_breakdown["total_transaction_cost"] / starting_nav
            if starting_nav > 0
            else 0.0,
            "distribution_cash": total_distribution_cash,
            "distribution_return": total_distribution_cash / starting_nav if starting_nav > 0 else 0.0,
            **cost_breakdown,
        }
        for asset in assets:
            symbol = str(asset["symbol"])
            sleeve = str(asset.get("sleeve") or symbol).lower().replace(" ", "_")
            weight = float(asset["weight"])
            asset_return = asset_returns.get(symbol, 0.0)
            distribution_return = distribution_returns.get(symbol, 0.0)
            row[f"{sleeve}_symbol"] = symbol
            row[f"{sleeve}_target_weight"] = weight
            row[f"{sleeve}_trade_value"] = trades.get(symbol, 0.0)
            row[f"{sleeve}_price_return"] = price_returns.get(symbol, 0.0)
            row[f"{sleeve}_distribution_return"] = distribution_return
            row[f"{sleeve}_distribution_cash"] = nav_after_cost * weight * distribution_return
            row[f"{sleeve}_return"] = asset_return
            row[f"{sleeve}_gross_contribution"] = weight * asset_return
        return row

    def _write_experiment_outputs(self, summary: dict[str, Any], detail_rows: list[dict[str, Any]]) -> None:
        output_config = self.profile.get("experiment_outputs") or {}
        default_dir = Path("data") / "output" / str(self.profile.get("slug"))
        detail_path = Path(
            str(output_config.get("net_returns_detail_path") or default_dir / "fixed_allocation_net_returns_detail.csv")
        )
        summary_path = Path(
            str(output_config.get("summary_path") or default_dir / "fixed_allocation_summary.csv")
        )
        detail_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(detail_rows).to_csv(detail_path, index=False)
        pd.DataFrame([summary]).to_csv(summary_path, index=False)


def _assets_from_profile(profile: dict[str, Any]) -> list[dict[str, Any]]:
    assets = _allocation_assets(profile)
    if not assets:
        raise ValueError("allocation.assets or data.universe_json_path is required for fixed-allocation backtests.")
    cleaned = [
        {
            "sleeve": str(asset.get("sleeve") or asset.get("symbol") or "").strip(),
            "symbol": str(asset.get("symbol") or "").strip().upper(),
            "weight": float(asset.get("weight")),
        }
        for asset in assets
    ]
    if any(not asset["symbol"] for asset in cleaned):
        raise ValueError("Every allocation asset must include a symbol.")
    total_weight = sum(float(asset["weight"]) for asset in cleaned)
    if not math.isclose(total_weight, 1.0, rel_tol=1e-9, abs_tol=1e-9):
        raise ValueError(f"Fixed allocation weights must sum to 1.0; got {total_weight:.6f}.")
    return cleaned


def _allocation_assets(profile: dict[str, Any]) -> list[dict[str, Any]]:
    allocation = profile.get("allocation") or {}
    assets = allocation.get("assets") or []
    if assets:
        return assets

    universe_path = (profile.get("data") or {}).get("universe_json_path")
    if not universe_path:
        return []

    path = Path(universe_path)
    if not path.exists():
        raise FileNotFoundError(f"Fixed allocation universe JSON not found at {path}.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Fixed allocation universe JSON must contain a list of assets: {path}.")
    return [asset for asset in payload if asset.get("is_active", True)]


def _estimate_transaction_costs(trades: dict[str, float]) -> dict[str, float]:
    buy_turnover = sum(value for value in trades.values() if value > 0)
    sell_turnover = sum(-value for value in trades.values() if value < 0)
    sell_legs = sum(1 for value in trades.values() if value < -1e-8)
    exchange_turnover = buy_turnover + sell_turnover
    exchange_transaction_charges = exchange_turnover * EXCHANGE_TRANSACTION_RATE
    sebi_charges = exchange_turnover * SEBI_TURNOVER_RATE
    stt = sell_turnover * STT_DELIVERY_SELL_RATE
    stamp_duty = buy_turnover * STAMP_DUTY_BUY_RATE
    gst = (exchange_transaction_charges + sebi_charges) * GST_RATE
    dp_charges = sell_legs * DP_CHARGE_PER_SOLD_SCRIP
    total = exchange_transaction_charges + sebi_charges + stt + stamp_duty + gst + dp_charges
    return {
        "buy_turnover": buy_turnover,
        "sell_turnover": sell_turnover,
        "exchange_transaction_charges": exchange_transaction_charges,
        "sebi_charges": sebi_charges,
        "stt": stt,
        "stamp_duty": stamp_duty,
        "gst": gst,
        "dp_charges": dp_charges,
        "estimated_tax": 0.0,
        "total_transaction_cost": total,
    }


def _weight_for_symbol(assets: list[dict[str, Any]], symbol: str) -> float:
    normalized = symbol.upper()
    return sum(float(asset["weight"]) for asset in assets if str(asset["symbol"]).upper() == normalized)


def _max_drawdown(nav_values: list[float]) -> float:
    peak = nav_values[0]
    max_drawdown = 0.0
    for value in nav_values:
        peak = max(peak, value)
        if peak > 0:
            max_drawdown = min(max_drawdown, (value / peak) - 1.0)
    return max_drawdown


def _annualized_volatility(period_returns: list[float], years: float) -> float:
    if not period_returns or years <= 0:
        return 0.0
    series = pd.Series(period_returns)
    periods_per_year = len(series) / years
    return float(series.std(ddof=0) * math.sqrt(periods_per_year)) if periods_per_year > 0 else 0.0
