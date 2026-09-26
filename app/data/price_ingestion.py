from __future__ import annotations

from datetime import date

from app.data.benchmark_comparison_sources import fetch_benchmark_comparison_bars
from app.data.historical_data import FetchResult, frame_to_price_bars, get_market_data_provider
from app.data.universe_loader import load_universe
from app.storage.market_data_repository import create_ingestion_run, upsert_price_bars
from app.strategy.models import RunStatus


def fetch_and_store_history(
    start_date: date,
    end_date: date,
    symbols: list[str] | None = None,
    include_benchmark: bool = True,
    include_safe_asset: bool = True,
    include_benchmark_comparisons: bool = True,
) -> FetchResult:
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date.")

    if symbols is None:
        symbols = [stock.symbol for stock in load_universe()]
    cleaned_symbols = sorted({symbol.strip().upper() for symbol in symbols if symbol.strip()})

    from app import config

    if include_benchmark and config.DEFAULT_BENCHMARK_SYMBOL not in cleaned_symbols:
        cleaned_symbols.append(config.DEFAULT_BENCHMARK_SYMBOL)
    if include_safe_asset:
        for safe_asset_symbol in config.SAFE_ASSET_SYMBOLS:
            if safe_asset_symbol not in cleaned_symbols:
                cleaned_symbols.append(safe_asset_symbol)

    provider = get_market_data_provider()
    frame = provider.get_daily_prices(cleaned_symbols, start_date, end_date)
    bars = frame_to_price_bars(frame, source=provider.source)
    comparison_warnings: list[str] = []
    comparison_rows = 0
    if include_benchmark_comparisons:
        comparison_bars, comparison_warnings = fetch_benchmark_comparison_bars(provider, start_date, end_date)
        comparison_rows = len(comparison_bars)
        bars.extend(comparison_bars)
    stored_rows = upsert_price_bars(bars)
    stored_symbols = {bar.symbol for bar in bars}
    missing_symbols = [symbol for symbol in cleaned_symbols if symbol not in stored_symbols]
    warnings = [f"No rows returned for {symbol}" for symbol in missing_symbols]
    warnings.extend(getattr(provider, "warnings", []))
    warnings.extend(comparison_warnings)

    status = RunStatus.COMPLETED if stored_rows else RunStatus.FAILED
    create_ingestion_run(
        source=provider.source,
        status=status,
        start_date=start_date,
        end_date=end_date,
        requested_symbols=len(cleaned_symbols),
        stored_rows=stored_rows,
        message=f"Stored {stored_rows} historical price rows.",
        details={
            "missing_symbols": missing_symbols,
            "warnings": warnings,
            "benchmark_comparison_rows": comparison_rows,
            "benchmark_comparisons_included": include_benchmark_comparisons,
        },
    )
    return FetchResult(len(cleaned_symbols), stored_rows, missing_symbols, warnings)
