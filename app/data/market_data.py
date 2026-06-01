from __future__ import annotations

from datetime import date
from typing import Protocol

import pandas as pd


class MarketDataProvider(Protocol):
    def get_daily_prices(self, symbols: list[str], start_date: date, end_date: date) -> pd.DataFrame:
        ...

    def get_benchmark_prices(
        self,
        benchmark_symbol: str,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        ...


class PlaceholderMarketDataProvider:
    def get_daily_prices(self, symbols: list[str], start_date: date, end_date: date) -> pd.DataFrame:
        raise NotImplementedError("Market data ingestion will be implemented in a later sprint.")

    def get_benchmark_prices(
        self,
        benchmark_symbol: str,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        raise NotImplementedError("Benchmark market data ingestion will be implemented in a later sprint.")

