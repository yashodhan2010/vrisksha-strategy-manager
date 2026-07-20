from __future__ import annotations

import calendar
import itertools
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATABASE_PATH = PROJECT_ROOT / "data" / "research_factory.db"
UNIVERSE_JSON_PATH = PROJECT_ROOT / "data" / "reference" / "nifty500_universe.json"
OUTPUT_DIR = PROJECT_ROOT / "data" / "output" / "dual-momentum" / "experiments"

DEFAULT_BENCHMARK_SYMBOL = "NIFTY500"
DEFAULT_SAFE_ASSET_SYMBOL = "LIQUIDBEES"
INITIAL_CAPITAL = 1_000_000.0
BETA_LOOKBACK_DAYS = 252
BETA_FLOOR = 0.25
MOMENTUM_SKIP_RECENT_DAYS = 21
MAX_FORWARD_FILL_DAYS = 5
MAX_SIGNAL_DAILY_RETURN = 1.0
MAX_BACKTEST_PERIOD_RETURN = 2.0


@dataclass(frozen=True)
class GridParams:
    rebalances_per_month: int
    top_n: int
    sector_cap_pct: int
    high_cutoff_pct: int
    momentum_weight: float
    buffer_pct: int
    max_stock_weight_pct: float = 5.0

    @property
    def beta_weight(self) -> float:
        return (1.0 - self.momentum_weight) / 2.0

    @property
    def volatility_weight(self) -> float:
        return (1.0 - self.momentum_weight) / 2.0

    @property
    def high_52w_threshold(self) -> float:
        return 1.0 - (self.high_cutoff_pct / 100.0)

    @property
    def max_sector_weight(self) -> float:
        return 1.0 if self.sector_cap_pct == 0 else self.sector_cap_pct / 100.0

    @property
    def max_stock_weight(self) -> float:
        return self.max_stock_weight_pct / 100.0


@dataclass(frozen=True)
class DataQualityConfig:
    max_forward_fill_days: int = MAX_FORWARD_FILL_DAYS
    max_signal_daily_return: float = MAX_SIGNAL_DAILY_RETURN
    max_backtest_period_return: float = MAX_BACKTEST_PERIOD_RETURN
    min_price: float = 1.0


def load_universe(
    universe_json_path: Path = UNIVERSE_JSON_PATH,
) -> tuple[list[str], dict[str, str]]:
    payload = json.loads(universe_json_path.read_text(encoding="utf-8"))
    symbols: list[str] = []
    sector_by_symbol: dict[str, str] = {}
    for row in payload:
        if not row.get("is_active", True):
            continue
        symbol = str(row["symbol"]).strip().upper()
        symbols.append(symbol)
        sector_by_symbol[symbol] = str(row.get("sector") or "UNKNOWN").strip().upper()
    return symbols, sector_by_symbol


def load_price_frame(
    database_path: Path = DATABASE_PATH,
    universe_json_path: Path = UNIVERSE_JSON_PATH,
    benchmark_symbol: str = DEFAULT_BENCHMARK_SYMBOL,
    safe_asset_symbol: str = DEFAULT_SAFE_ASSET_SYMBOL,
) -> pd.DataFrame:
    universe_symbols, _ = load_universe(universe_json_path)
    wanted = set(universe_symbols) | {benchmark_symbol.upper(), safe_asset_symbol.upper()}
    with sqlite3.connect(database_path) as connection:
        prices = pd.read_sql_query(
            """
            SELECT symbol, price_date, close, adjusted_close
            FROM market_prices
            ORDER BY symbol, price_date
            """,
            connection,
        )
    if prices.empty:
        raise ValueError("No market_prices rows found. Fetch history before running the experiment.")
    prices["symbol"] = prices["symbol"].astype(str).str.upper()
    prices = prices[prices["symbol"].isin(wanted)]
    prices["price_date"] = pd.to_datetime(prices["price_date"]).dt.date
    prices["price"] = prices["adjusted_close"].fillna(prices["close"])
    prices = prices.dropna(subset=["price"])
    prices = prices[prices["price"] > 0]
    return prices


def price_quality_report(
    prices: pd.DataFrame,
    quality: DataQualityConfig = DataQualityConfig(),
) -> pd.DataFrame:
    rows: list[dict[str, int | float | str | None]] = []
    for symbol, group in prices.sort_values(["symbol", "price_date"]).groupby("symbol"):
        group = group.copy()
        group["previous_date"] = group["price_date"].shift(1)
        group["previous_price"] = group["price"].shift(1)
        group["gap_days"] = (pd.to_datetime(group["price_date"]) - pd.to_datetime(group["previous_date"])).dt.days
        group["actual_return"] = group["price"] / group["previous_price"] - 1.0
        returns = group["actual_return"].replace([np.inf, -np.inf], np.nan).dropna()
        suspicious = returns[returns.abs() > quality.max_signal_daily_return]
        low_prices = group[group["price"] < quality.min_price]
        rows.append(
            {
                "symbol": symbol,
                "row_count": int(len(group)),
                "first_date": str(group["price_date"].min()),
                "last_date": str(group["price_date"].max()),
                "min_price": float(group["price"].min()),
                "max_price": float(group["price"].max()),
                "max_gap_days": int(group["gap_days"].max()) if group["gap_days"].notna().any() else 0,
                "max_abs_actual_return": float(returns.abs().max()) if not returns.empty else 0.0,
                "suspicious_return_count": int(len(suspicious)),
                "low_price_count": int(len(low_prices)),
                "largest_jump_date": str(group.loc[returns.abs().idxmax(), "price_date"]) if not returns.empty else None,
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["suspicious_return_count", "max_abs_actual_return", "max_gap_days"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def load_price_pivot(
    database_path: Path = DATABASE_PATH,
    universe_json_path: Path = UNIVERSE_JSON_PATH,
    benchmark_symbol: str = DEFAULT_BENCHMARK_SYMBOL,
    safe_asset_symbol: str = DEFAULT_SAFE_ASSET_SYMBOL,
    quality: DataQualityConfig = DataQualityConfig(),
) -> pd.DataFrame:
    prices = load_price_frame(database_path, universe_json_path, benchmark_symbol, safe_asset_symbol)
    if quality.min_price > 0:
        prices = prices[prices["price"] >= quality.min_price]
    pivot = prices.pivot_table(index="price_date", columns="symbol", values="price", aggfunc="last").sort_index()
    return pivot.ffill(limit=quality.max_forward_fill_days)


def rebalance_dates(price_pivot: pd.DataFrame, start_date: date, end_date: date, rebalances_per_month: int) -> list[date]:
    if rebalances_per_month <= 0:
        raise ValueError("rebalances_per_month must be greater than zero.")
    dates = [item for item in price_pivot.index if start_date <= item <= end_date]
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


def benchmark_returns(price_pivot: pd.DataFrame, benchmark_symbol: str = DEFAULT_BENCHMARK_SYMBOL) -> pd.Series | None:
    symbol = benchmark_symbol.upper()
    if symbol not in price_pivot.columns:
        return None
    return price_pivot[symbol].pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan).dropna()


def rank_on_date(
    price_pivot: pd.DataFrame,
    benchmark_return_series: pd.Series | None,
    rebalance_date: date,
    universe_symbols: list[str],
    high_52w_threshold: float,
    momentum_weight: float,
    quality: DataQualityConfig = DataQualityConfig(),
) -> pd.DataFrame:
    history = price_pivot.loc[:rebalance_date, [symbol for symbol in universe_symbols if symbol in price_pivot.columns]]
    required_history_days = BETA_LOOKBACK_DAYS + MOMENTUM_SKIP_RECENT_DAYS
    history = history.tail(required_history_days + 5)
    if len(history) <= required_history_days:
        return pd.DataFrame(columns=["symbol", "score", "rank"])

    valid_columns = history.columns[history.notna().sum() > required_history_days]
    if len(valid_columns) == 0:
        return pd.DataFrame(columns=["symbol", "score", "rank"])
    history = history[valid_columns]
    current = history.iloc[-1]
    momentum_anchor = history.iloc[-1 - MOMENTUM_SKIP_RECENT_DAYS]
    high_52w = history.tail(252).max()
    lookback_3m = history.iloc[-64 - MOMENTUM_SKIP_RECENT_DAYS]
    lookback_6m = history.iloc[-127 - MOMENTUM_SKIP_RECENT_DAYS]
    lookback_12m = history.iloc[-253 - MOMENTUM_SKIP_RECENT_DAYS]
    valid = (
        current.notna()
        & high_52w.gt(0)
        & (current / high_52w).ge(high_52w_threshold)
        & lookback_3m.gt(0)
        & lookback_6m.gt(0)
        & lookback_12m.gt(0)
    )
    if not valid.any():
        return pd.DataFrame(columns=["symbol", "score", "rank"])

    selected_history = history.loc[:, valid]
    recent_returns = selected_history.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)
    clean_return_columns = (recent_returns.abs().le(quality.max_signal_daily_return) | recent_returns.isna()).all(axis=0)
    selected_history = selected_history.loc[:, clean_return_columns]
    if selected_history.empty:
        return pd.DataFrame(columns=["symbol", "score", "rank"])
    valid_symbols = selected_history.columns
    current = current.loc[valid_symbols]
    returns = pd.DataFrame(
        {
            "return_3m": momentum_anchor.loc[valid_symbols] / lookback_3m.loc[valid_symbols] - 1.0,
            "return_6m": momentum_anchor.loc[valid_symbols] / lookback_6m.loc[valid_symbols] - 1.0,
            "return_12m": momentum_anchor.loc[valid_symbols] / lookback_12m.loc[valid_symbols] - 1.0,
        }
    ).replace([np.inf, -np.inf], np.nan)
    stock_returns = selected_history.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)
    volatility = stock_returns.tail(BETA_LOOKBACK_DAYS).std(ddof=0) * np.sqrt(252)
    beta = _beta_frame(stock_returns, benchmark_return_series)
    frame = returns.assign(
        symbol=returns.index,
        momentum_score=returns[["return_3m", "return_6m", "return_12m"]].mean(axis=1),
        beta=beta.reindex(returns.index).fillna(1.0).clip(lower=BETA_FLOOR),
        volatility=volatility.reindex(returns.index),
    ).dropna(subset=["momentum_score", "beta", "volatility"])
    frame.index.name = None
    if frame.empty:
        return pd.DataFrame(columns=["symbol", "score", "rank"])
    beta_weight = (1.0 - momentum_weight) / 2.0
    volatility_weight = beta_weight
    frame["momentum_rank"] = frame["momentum_score"].rank(method="average", ascending=False)
    frame["beta_rank"] = frame["beta"].rank(method="average", ascending=True)
    frame["volatility_rank"] = frame["volatility"].rank(method="average", ascending=True)
    frame["weighted_average_rank"] = (
        momentum_weight * frame["momentum_rank"]
        + beta_weight * frame["beta_rank"]
        + volatility_weight * frame["volatility_rank"]
    )
    frame["score"] = -frame["weighted_average_rank"]
    frame = frame.sort_values(["weighted_average_rank", "symbol"], ascending=[True, True]).reset_index(drop=True)
    frame["rank"] = frame.index + 1
    return frame


def _beta(stock_prices: pd.Series, benchmark_return_series: pd.Series | None) -> float:
    if benchmark_return_series is None:
        return 1.0
    stock_returns = stock_prices.pct_change(fill_method=None)
    aligned = pd.concat([stock_returns, benchmark_return_series], axis=1, join="inner")
    aligned = aligned.replace([np.inf, -np.inf], np.nan).dropna()
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
    return beta if beta > 0 else BETA_FLOOR


def _beta_frame(stock_returns: pd.DataFrame, benchmark_return_series: pd.Series | None) -> pd.Series:
    if benchmark_return_series is None or stock_returns.empty:
        return pd.Series(1.0, index=stock_returns.columns)
    benchmark = benchmark_return_series.reindex(stock_returns.index).replace([np.inf, -np.inf], np.nan)
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
    return beta.where(beta > 0, BETA_FLOOR)


def select_with_buffer(ranking: pd.DataFrame, previous_holdings: list[str], top_n: int, buffer_pct: int) -> list[str]:
    if ranking.empty:
        return []
    rank_by_symbol = dict(zip(ranking["symbol"], ranking["rank"], strict=False))
    hold_threshold = top_n * (1.0 + buffer_pct / 100.0)
    retained = [
        symbol
        for symbol in previous_holdings
        if symbol in rank_by_symbol and float(rank_by_symbol[symbol]) <= hold_threshold
    ]
    retained = sorted(retained, key=lambda symbol: (float(rank_by_symbol[symbol]), symbol))
    selected = list(retained)
    selected_set = set(selected)
    for symbol in ranking.head(top_n)["symbol"].astype(str).tolist():
        if len(selected) >= top_n:
            break
        if symbol not in selected_set:
            selected.append(symbol)
            selected_set.add(symbol)
    return selected


def equal_weights_with_sector_cap(
    selected_symbols: list[str],
    sector_by_symbol: dict[str, str],
    max_sector_weight: float,
    max_stock_weight: float = 0.05,
) -> tuple[dict[str, float], float]:
    if not selected_symbols:
        return {}, 1.0
    base_weight = min(1.0 / len(selected_symbols), max_stock_weight)
    weights = {symbol: base_weight for symbol in selected_symbols}
    if max_sector_weight >= 1.0:
        return weights, max(0.0, 1.0 - sum(weights.values()))
    sector_totals: dict[str, float] = {}
    for symbol, weight in weights.items():
        sector = sector_by_symbol.get(symbol, "UNKNOWN")
        sector_totals[sector] = sector_totals.get(sector, 0.0) + weight
    capped: dict[str, float] = {}
    for symbol, weight in weights.items():
        sector = sector_by_symbol.get(symbol, "UNKNOWN")
        sector_total = sector_totals[sector]
        capped[symbol] = weight * (max_sector_weight / sector_total) if sector_total > max_sector_weight else weight
    return capped, max(0.0, 1.0 - sum(capped.values()))


def portfolio_period_return(
    price_pivot: pd.DataFrame,
    start_date: date,
    end_date: date,
    stock_weights: dict[str, float],
    safe_asset_weight: float,
    safe_asset_symbol: str = DEFAULT_SAFE_ASSET_SYMBOL,
    quality: DataQualityConfig = DataQualityConfig(),
) -> tuple[float, int]:
    total = 0.0
    skipped_extreme_returns = 0
    for symbol, weight in stock_weights.items():
        start_price = price_pivot.at[start_date, symbol]
        end_price = price_pivot.at[end_date, symbol]
        if pd.isna(start_price) or pd.isna(end_price) or start_price <= 0:
            continue
        symbol_return = (float(end_price) / float(start_price)) - 1.0
        if abs(symbol_return) > quality.max_backtest_period_return:
            skipped_extreme_returns += 1
            continue
        total += weight * symbol_return
    safe_symbol = safe_asset_symbol.upper()
    if safe_asset_weight > 0 and safe_symbol in price_pivot.columns:
        start_price = price_pivot.at[start_date, safe_symbol]
        end_price = price_pivot.at[end_date, safe_symbol]
        if pd.notna(start_price) and pd.notna(end_price) and start_price > 0:
            symbol_return = (float(end_price) / float(start_price)) - 1.0
            if abs(symbol_return) <= quality.max_backtest_period_return:
                total += safe_asset_weight * symbol_return
            else:
                skipped_extreme_returns += 1
    return total, skipped_extreme_returns


def run_backtest(
    price_pivot: pd.DataFrame,
    universe_symbols: list[str],
    sector_by_symbol: dict[str, str],
    start_date: date,
    end_date: date,
    params: GridParams,
    ranking_cache: dict[tuple, pd.DataFrame] | None = None,
    safe_asset_symbol: str = DEFAULT_SAFE_ASSET_SYMBOL,
    benchmark_symbol: str = DEFAULT_BENCHMARK_SYMBOL,
    quality: DataQualityConfig = DataQualityConfig(),
) -> dict[str, pd.DataFrame | dict]:
    dates = rebalance_dates(price_pivot, start_date, end_date, params.rebalances_per_month)
    if len(dates) < 2:
        raise ValueError("Not enough rebalance dates for this window.")
    ranking_cache = ranking_cache if ranking_cache is not None else {}
    bench_returns = benchmark_returns(price_pivot, benchmark_symbol)
    nav = INITIAL_CAPITAL
    previous_holdings: list[str] = []
    rows = [{"date": dates[0], "nav": nav, "period_return": 0.0, "selected_count": 0, "safe_asset_weight": 0.0}]
    turnover_counts: list[int] = []
    selected_counts: list[int] = []
    safe_weights: list[float] = []
    skipped_extreme_returns = 0

    for index, start in enumerate(dates[:-1]):
        end = dates[index + 1]
        ranking_key = (start, params.high_52w_threshold, round(params.momentum_weight, 6))
        ranking = ranking_cache.get(ranking_key)
        if ranking is None:
            ranking = rank_on_date(
                price_pivot,
                bench_returns,
                start,
                universe_symbols,
                params.high_52w_threshold,
                params.momentum_weight,
                quality,
            )
            ranking_cache[ranking_key] = ranking
        selected = select_with_buffer(ranking, previous_holdings, params.top_n, params.buffer_pct)
        weights, safe_asset_weight = equal_weights_with_sector_cap(
            selected,
            sector_by_symbol,
            params.max_sector_weight,
            params.max_stock_weight,
        )
        period_return, skipped = portfolio_period_return(price_pivot, start, end, weights, safe_asset_weight, safe_asset_symbol, quality)
        skipped_extreme_returns += skipped
        nav *= 1.0 + period_return
        entries = len(set(selected) - set(previous_holdings))
        turnover_counts.append(entries)
        selected_counts.append(len(selected))
        safe_weights.append(safe_asset_weight)
        rows.append(
            {
                "date": end,
                "nav": nav,
                "period_return": period_return,
                "selected_count": len(selected),
                "safe_asset_weight": safe_asset_weight,
            }
        )
        previous_holdings = selected

    curve = pd.DataFrame(rows)
    metrics = performance_metrics(curve)
    metrics.update(
        {
            **asdict(params),
            "beta_weight": params.beta_weight,
            "volatility_weight": params.volatility_weight,
            "high_52w_threshold": params.high_52w_threshold,
            "max_sector_weight": params.max_sector_weight,
            "max_stock_weight": params.max_stock_weight,
            "average_selected_count": float(np.mean(selected_counts)) if selected_counts else 0.0,
            "average_safe_asset_weight": float(np.mean(safe_weights)) if safe_weights else 0.0,
            "average_entries_per_rebalance": float(np.mean(turnover_counts)) if turnover_counts else 0.0,
            "skipped_extreme_returns": skipped_extreme_returns,
        }
    )
    return {"metrics": metrics, "curve": curve}


@dataclass(frozen=True)
class ExhaustiveGridStudy:
    direction: str
    study_name: str
    best_value: float | None
    best_params: dict[str, int | float]


def precompute_ranking_cache(
    price_pivot: pd.DataFrame,
    universe_symbols: list[str],
    benchmark_return_series: pd.Series | None,
    dates_by_rebalance_frequency: dict[int, list[date]],
    high_cutoff_values: Iterable[int | float],
    momentum_weight_values: Iterable[int | float],
    quality: DataQualityConfig = DataQualityConfig(),
) -> dict[tuple, pd.DataFrame]:
    cache: dict[tuple, pd.DataFrame] = {}
    ranking_dates = sorted({item for dates in dates_by_rebalance_frequency.values() for item in dates[:-1]})
    for start in ranking_dates:
        for high_cutoff_pct in high_cutoff_values:
            high_52w_threshold = 1.0 - (float(high_cutoff_pct) / 100.0)
            for momentum_weight in momentum_weight_values:
                key = (start, high_52w_threshold, round(float(momentum_weight), 6))
                cache[key] = rank_on_date(
                    price_pivot,
                    benchmark_return_series,
                    start,
                    universe_symbols,
                    high_52w_threshold,
                    float(momentum_weight),
                    quality,
                )
    return cache


def run_backtest_on_dates(
    price_pivot: pd.DataFrame,
    sector_by_symbol: dict[str, str],
    dates: list[date],
    params: GridParams,
    ranking_cache: dict[tuple, pd.DataFrame],
    safe_asset_symbol: str = DEFAULT_SAFE_ASSET_SYMBOL,
    quality: DataQualityConfig = DataQualityConfig(),
) -> dict[str, pd.DataFrame | dict]:
    if len(dates) < 2:
        raise ValueError("Not enough rebalance dates for this window.")
    nav = INITIAL_CAPITAL
    previous_holdings: list[str] = []
    rows = [{"date": dates[0], "nav": nav, "period_return": 0.0, "selected_count": 0, "safe_asset_weight": 0.0}]
    turnover_counts: list[int] = []
    selected_counts: list[int] = []
    safe_weights: list[float] = []
    skipped_extreme_returns = 0

    for index, start in enumerate(dates[:-1]):
        end = dates[index + 1]
        ranking_key = (start, params.high_52w_threshold, round(params.momentum_weight, 6))
        ranking = ranking_cache[ranking_key]
        selected = select_with_buffer(ranking, previous_holdings, params.top_n, params.buffer_pct)
        weights, safe_asset_weight = equal_weights_with_sector_cap(
            selected,
            sector_by_symbol,
            params.max_sector_weight,
            params.max_stock_weight,
        )
        period_return, skipped = portfolio_period_return(price_pivot, start, end, weights, safe_asset_weight, safe_asset_symbol, quality)
        skipped_extreme_returns += skipped
        nav *= 1.0 + period_return
        turnover_counts.append(len(set(selected) - set(previous_holdings)))
        selected_counts.append(len(selected))
        safe_weights.append(safe_asset_weight)
        rows.append(
            {
                "date": end,
                "nav": nav,
                "period_return": period_return,
                "selected_count": len(selected),
                "safe_asset_weight": safe_asset_weight,
            }
        )
        previous_holdings = selected

    curve = pd.DataFrame(rows)
    metrics = performance_metrics(curve)
    metrics.update(
        {
            **asdict(params),
            "beta_weight": params.beta_weight,
            "volatility_weight": params.volatility_weight,
            "high_52w_threshold": params.high_52w_threshold,
            "max_sector_weight": params.max_sector_weight,
            "max_stock_weight": params.max_stock_weight,
            "average_selected_count": float(np.mean(selected_counts)) if selected_counts else 0.0,
            "average_safe_asset_weight": float(np.mean(safe_weights)) if safe_weights else 0.0,
            "average_entries_per_rebalance": float(np.mean(turnover_counts)) if turnover_counts else 0.0,
            "skipped_extreme_returns": skipped_extreme_returns,
        }
    )
    return {"metrics": metrics, "curve": curve}


def audit_period_contributors(
    price_pivot: pd.DataFrame,
    universe_symbols: list[str],
    sector_by_symbol: dict[str, str],
    start_date: date,
    end_date: date,
    params: GridParams,
    quality: DataQualityConfig = DataQualityConfig(),
    safe_asset_symbol: str = DEFAULT_SAFE_ASSET_SYMBOL,
    benchmark_symbol: str = DEFAULT_BENCHMARK_SYMBOL,
) -> pd.DataFrame:
    dates = rebalance_dates(price_pivot, start_date, end_date, params.rebalances_per_month)
    bench_returns = benchmark_returns(price_pivot, benchmark_symbol)
    ranking_cache: dict[tuple, pd.DataFrame] = {}
    previous_holdings: list[str] = []
    rows: list[dict[str, float | int | str | date]] = []
    for index, start in enumerate(dates[:-1]):
        end = dates[index + 1]
        ranking_key = (start, params.high_52w_threshold, round(params.momentum_weight, 6))
        ranking = ranking_cache.get(ranking_key)
        if ranking is None:
            ranking = rank_on_date(
                price_pivot,
                bench_returns,
                start,
                universe_symbols,
                params.high_52w_threshold,
                params.momentum_weight,
                quality,
            )
            ranking_cache[ranking_key] = ranking
        selected = select_with_buffer(ranking, previous_holdings, params.top_n, params.buffer_pct)
        weights, safe_asset_weight = equal_weights_with_sector_cap(
            selected,
            sector_by_symbol,
            params.max_sector_weight,
            params.max_stock_weight,
        )
        period_return = 0.0
        contributions: list[tuple[str, float, float, float, float, float, bool]] = []
        for symbol, weight in weights.items():
            start_price = price_pivot.at[start, symbol]
            end_price = price_pivot.at[end, symbol]
            if pd.isna(start_price) or pd.isna(end_price) or start_price <= 0:
                continue
            symbol_return = (float(end_price) / float(start_price)) - 1.0
            is_extreme = abs(symbol_return) > quality.max_backtest_period_return
            contribution = 0.0 if is_extreme else weight * symbol_return
            period_return += contribution
            contributions.append((symbol, weight, symbol_return, contribution, float(start_price), float(end_price), is_extreme))
        top = sorted(contributions, key=lambda item: abs(item[3]), reverse=True)[:5]
        for rank, item in enumerate(top, start=1):
            rows.append(
                {
                    "period_start": start,
                    "period_end": end,
                    "period_return": period_return,
                    "contribution_rank": rank,
                    "symbol": item[0],
                    "weight": item[1],
                    "symbol_return": item[2],
                    "contribution": item[3],
                    "start_price": item[4],
                    "end_price": item[5],
                    "extreme_return_skipped": item[6],
                    "safe_asset_weight": safe_asset_weight,
                    "selected_count": len(selected),
                }
            )
        previous_holdings = selected
    return pd.DataFrame(rows).sort_values(["period_return", "contribution"], ascending=[False, False]).reset_index(drop=True)


def performance_metrics(curve: pd.DataFrame) -> dict[str, float]:
    final_value = float(curve["nav"].iloc[-1])
    total_return = final_value / INITIAL_CAPITAL - 1.0
    years = (curve["date"].iloc[-1] - curve["date"].iloc[0]).days / 365.25
    cagr = (final_value / INITIAL_CAPITAL) ** (1.0 / years) - 1.0 if years > 0 else np.nan
    period_returns = curve["period_return"].iloc[1:]
    periods_per_year = len(period_returns) / years if years > 0 else np.nan
    annualized_volatility = float(period_returns.std(ddof=0) * np.sqrt(periods_per_year)) if len(period_returns) else np.nan
    sharpe_like = float(cagr / annualized_volatility) if annualized_volatility and annualized_volatility > 0 else np.nan
    drawdown = curve["nav"] / curve["nav"].cummax() - 1.0
    max_drawdown = float(drawdown.min())
    return_to_drawdown = float(cagr / abs(max_drawdown)) if max_drawdown < 0 else np.nan
    return {
        "final_value": final_value,
        "total_return": float(total_return),
        "cagr": float(cagr),
        "max_drawdown": max_drawdown,
        "return_to_drawdown": return_to_drawdown,
        "annualized_volatility": annualized_volatility,
        "sharpe_like": sharpe_like,
        "periods": int(len(period_returns)),
    }


def objective_score(metrics: dict, objective_metric: str = "cagr") -> float:
    value = metrics.get(objective_metric)
    if value is None or pd.isna(value):
        return -1e9
    return float(value)


def search_space(
    momentum_weight_grid: Iterable[float] | None = None,
) -> dict[str, list[int | float]]:
    weights = momentum_weight_grid or np.round(np.arange(0.30, 0.701, 0.1), 2)
    return {
        "rebalances_per_month": [1, 2],
        "top_n": [20, 25, 30, 35, 40],
        "sector_cap_pct": [0, 10, 20, 25, 30],
        "high_cutoff_pct": [25, 20, 15],
        "momentum_weight": [float(value) for value in weights],
        "buffer_pct": list(range(40, 101, 10)),
        "max_stock_weight_pct": [2.5, 3.0, 3.5, 4.0],
    }


def count_grid_trials(space: dict[str, list[int | float]]) -> int:
    total = 1
    for values in space.values():
        total *= len(values)
    return total


def run_optuna_grid(
    years: int,
    objective_metric: str = "cagr",
    momentum_weight_grid: Iterable[float] | None = None,
    n_trials: int | None = None,
    seed: int = 42,
    quality: DataQualityConfig = DataQualityConfig(),
) -> tuple[object, pd.DataFrame, dict[str, pd.DataFrame]]:
    price_pivot = load_price_pivot(quality=quality)
    universe_symbols, sector_by_symbol = load_universe()
    end_date = max(price_pivot.index)
    start_date = end_date - timedelta(days=round(years * 365.25))
    space = search_space(momentum_weight_grid)
    total_trials = count_grid_trials(space)
    if n_trials is None or n_trials >= total_trials:
        results, curves = run_exhaustive_grid_from_data(
            price_pivot,
            universe_symbols,
            sector_by_symbol,
            start_date,
            end_date,
            space,
            objective_metric,
            quality,
        )
        best = results.iloc[0] if not results.empty else {}
        return (
            ExhaustiveGridStudy(
                direction="maximize",
                study_name=f"average_rank_buffer_{years}y_exhaustive",
                best_value=float(best.get(objective_metric)) if len(results) and pd.notna(best.get(objective_metric)) else None,
                best_params={
                    key: best.get(key)
                    for key in space
                    if len(results) and key in best
                },
            ),
            results,
            curves,
        )

    try:
        import optuna
    except ImportError as exc:
        raise ImportError("optuna is required for partial trial runs. Run `pip install -r requirements.txt`.") from exc

    n_trials = n_trials or total_trials
    ranking_cache: dict[tuple, pd.DataFrame] = {}
    curves: dict[str, pd.DataFrame] = {}

    sampler = optuna.samplers.GridSampler(space, seed=seed)
    study = optuna.create_study(direction="maximize", sampler=sampler, study_name=f"average_rank_buffer_{years}y")

    def objective(trial: object) -> float:
        params = GridParams(
            rebalances_per_month=int(trial.suggest_categorical("rebalances_per_month", space["rebalances_per_month"])),
            top_n=int(trial.suggest_categorical("top_n", space["top_n"])),
            sector_cap_pct=int(trial.suggest_categorical("sector_cap_pct", space["sector_cap_pct"])),
            high_cutoff_pct=int(trial.suggest_categorical("high_cutoff_pct", space["high_cutoff_pct"])),
            momentum_weight=float(trial.suggest_categorical("momentum_weight", space["momentum_weight"])),
            buffer_pct=int(trial.suggest_categorical("buffer_pct", space["buffer_pct"])),
            max_stock_weight_pct=float(trial.suggest_categorical("max_stock_weight_pct", space["max_stock_weight_pct"])),
        )
        result = run_backtest(price_pivot, universe_symbols, sector_by_symbol, start_date, end_date, params, ranking_cache, quality=quality)
        metrics = result["metrics"]
        trial.set_user_attr("metrics", metrics)
        trial.set_user_attr("curve_key", trial.number)
        curves[str(trial.number)] = result["curve"]
        return objective_score(metrics, objective_metric)

    study.optimize(objective, n_trials=n_trials)
    rows: list[dict] = []
    for trial in study.trials:
        rows.append(
            {
                "trial": trial.number,
                "state": str(trial.state),
                "objective_metric": objective_metric,
                "objective_score": trial.value,
                **trial.params,
                **trial.user_attrs.get("metrics", {}),
            }
        )
    results = pd.DataFrame(rows).sort_values("objective_score", ascending=False).reset_index(drop=True)
    return study, results, curves


def run_exhaustive_grid(
    years: int,
    momentum_weight_grid: Iterable[float] | None = None,
    objective_metric: str = "cagr",
    quality: DataQualityConfig = DataQualityConfig(),
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    price_pivot = load_price_pivot(quality=quality)
    universe_symbols, sector_by_symbol = load_universe()
    end_date = max(price_pivot.index)
    start_date = end_date - timedelta(days=round(years * 365.25))
    space = search_space(momentum_weight_grid)
    return run_exhaustive_grid_from_data(
        price_pivot,
        universe_symbols,
        sector_by_symbol,
        start_date,
        end_date,
        space,
        objective_metric,
        quality,
    )


def run_exhaustive_grid_from_data(
    price_pivot: pd.DataFrame,
    universe_symbols: list[str],
    sector_by_symbol: dict[str, str],
    start_date: date,
    end_date: date,
    space: dict[str, list[int | float]],
    objective_metric: str = "cagr",
    quality: DataQualityConfig = DataQualityConfig(),
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    keys = list(space)
    dates_by_frequency = {
        int(rebalances_per_month): rebalance_dates(price_pivot, start_date, end_date, int(rebalances_per_month))
        for rebalances_per_month in space["rebalances_per_month"]
    }
    ranking_cache = precompute_ranking_cache(
        price_pivot,
        universe_symbols,
        benchmark_returns(price_pivot),
        dates_by_frequency,
        space["high_cutoff_pct"],
        space["momentum_weight"],
        quality,
    )
    rows: list[dict] = []
    curves: dict[str, pd.DataFrame] = {}
    for index, values in enumerate(itertools.product(*(space[key] for key in keys))):
        raw = dict(zip(keys, values, strict=True))
        params = GridParams(
            rebalances_per_month=int(raw["rebalances_per_month"]),
            top_n=int(raw["top_n"]),
            sector_cap_pct=int(raw["sector_cap_pct"]),
            high_cutoff_pct=int(raw["high_cutoff_pct"]),
            momentum_weight=float(raw["momentum_weight"]),
            buffer_pct=int(raw["buffer_pct"]),
            max_stock_weight_pct=float(raw.get("max_stock_weight_pct", 5.0)),
        )
        result = run_backtest_on_dates(
            price_pivot,
            sector_by_symbol,
            dates_by_frequency[params.rebalances_per_month],
            params,
            ranking_cache,
            quality=quality,
        )
        rows.append({"trial": index, **result["metrics"]})
        curves[str(index)] = result["curve"]
    sort_metric = objective_metric if objective_metric in rows[0] else "cagr"
    results = pd.DataFrame(rows).sort_values(sort_metric, ascending=False).reset_index(drop=True)
    return results, curves


def best_by_metric(results: pd.DataFrame, metrics: Iterable[str] = ("total_return", "cagr", "return_to_drawdown", "sharpe_like")) -> pd.DataFrame:
    rows = []
    for metric in metrics:
        if metric not in results.columns:
            continue
        best = results.sort_values(metric, ascending=False).head(1).copy()
        best.insert(0, "best_for", metric)
        rows.append(best)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def save_results(results_by_years: dict[int, pd.DataFrame], prefix: str = "average_rank_buffer_grid") -> pd.DataFrame:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    combined_rows = []
    for years, results in results_by_years.items():
        output = results.copy()
        output.insert(0, "years", years)
        output.to_csv(OUTPUT_DIR / f"{prefix}_{years}y.csv", index=False)
        combined_rows.append(output)
    combined = pd.concat(combined_rows, ignore_index=True)
    combined.to_csv(OUTPUT_DIR / f"{prefix}_combined.csv", index=False)
    best_rows = []
    for years, results in results_by_years.items():
        best = best_by_metric(results)
        best.insert(0, "years", years)
        best_rows.append(best)
    best_combined = pd.concat(best_rows, ignore_index=True)
    best_combined.to_csv(OUTPUT_DIR / f"{prefix}_best_by_metric.csv", index=False)
    return best_combined
