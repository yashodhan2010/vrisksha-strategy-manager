from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import time
from typing import Callable, TypeVar

import pandas as pd
import yfinance as yf

from app import config
from app.data.universe_loader import load_universe
from app.execution.kite_session import get_login_url

T = TypeVar("T")


@dataclass(frozen=True)
class PriceBar:
    symbol: str
    price_date: date
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    adjusted_close: float | None
    volume: int | None
    source: str
    fetched_at: str


@dataclass(frozen=True)
class FetchResult:
    requested_symbols: int
    stored_rows: int
    missing_symbols: list[str]
    warnings: list[str]


def to_yahoo_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if normalized == config.DEFAULT_BENCHMARK_SYMBOL:
        return config.YAHOO_BENCHMARK_SYMBOL
    if normalized.startswith("^") or normalized.endswith(config.YAHOO_SYMBOL_SUFFIX):
        return normalized
    return f"{normalized}{config.YAHOO_SYMBOL_SUFFIX}"


class YahooFinanceMarketDataProvider:
    """Historical daily price provider using Yahoo Finance symbols.

    NSE equities are mapped as SYMBOL.NS. The Nifty 500 benchmark mapping is configurable
    because public data vendors differ in their index ticker support.
    """

    source = "YAHOO"

    def get_daily_prices(self, symbols: list[str], start_date: date, end_date: date) -> pd.DataFrame:
        if not symbols:
            return pd.DataFrame()
        yahoo_symbols = [to_yahoo_symbol(symbol) for symbol in symbols]
        data = yf.download(
            yahoo_symbols,
            start=start_date.isoformat(),
            end=end_date.isoformat(),
            auto_adjust=False,
            group_by="ticker",
            progress=False,
            threads=True,
        )
        return _normalize_download(data, symbols, yahoo_symbols)

    def get_benchmark_prices(self, benchmark_symbol: str, start_date: date, end_date: date) -> pd.DataFrame:
        return self.get_daily_prices([benchmark_symbol], start_date, end_date)


class KiteHistoricalMarketDataProvider:
    """Historical daily price provider using Zerodha Kite Connect.

    Requires KITE_API_KEY and KITE_ACCESS_TOKEN in .env. This does not automate
    Kite login, password entry, or TOTP generation.
    """

    source = "KITE"

    def __init__(self, api_key: str = config.KITE_API_KEY, access_token: str = config.KITE_ACCESS_TOKEN) -> None:
        if not api_key:
            raise ValueError("KITE_API_KEY is not configured.")
        if not access_token:
            login_hint = get_login_url() if api_key else "KITE_API_KEY is not configured."
            raise ValueError(
                "KITE_ACCESS_TOKEN is not configured. Open this Kite login URL, complete login manually, then run "
                "`python -m app.main fetch-history ... --request-token YOUR_REQUEST_TOKEN`: "
                f"{login_hint}"
            )
        try:
            from kiteconnect import KiteConnect
        except ImportError as exc:
            raise ImportError("kiteconnect is required for Kite historical data. Run pip install -r requirements.txt.") from exc
        self._kite = KiteConnect(api_key=api_key)
        self._kite.set_access_token(access_token)
        self._instrument_cache: dict[str, int] | None = None
        self.warnings: list[str] = []

    def get_daily_prices(self, symbols: list[str], start_date: date, end_date: date) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        for symbol in symbols:
            token = self._resolve_instrument_token(symbol)
            if token is None:
                self.warnings.append(f"No Kite instrument token found for {symbol.strip().upper()}; skipped.")
                continue
            candles: list[dict] = []
            for chunk_start, chunk_end in iter_date_chunks(
                start_date,
                end_date,
                config.KITE_HISTORICAL_DAY_CHUNK_DAYS,
            ):
                candles.extend(
                    self._kite_request(
                        lambda: self._kite.historical_data(
                            token,
                            chunk_start,
                            chunk_end,
                            "day",
                            continuous=False,
                            oi=False,
                        )
                    )
                )
                time.sleep(config.KITE_REQUEST_SLEEP_SECONDS)
            if not candles:
                continue
            frame = pd.DataFrame(candles)
            frame = frame.drop_duplicates(subset=["date"]).sort_values("date")
            frames.append(
                pd.DataFrame(
                    {
                        "symbol": symbol.strip().upper(),
                        "price_date": pd.to_datetime(frame["date"]).dt.date,
                        "open": frame["open"],
                        "high": frame["high"],
                        "low": frame["low"],
                        "close": frame["close"],
                        "adjusted_close": frame["close"],
                        "volume": frame["volume"],
                    }
                )
            )
        if not frames:
            return pd.DataFrame(
                columns=["symbol", "price_date", "open", "high", "low", "close", "adjusted_close", "volume"]
            )
        return pd.concat(frames, ignore_index=True)

    def get_benchmark_prices(self, benchmark_symbol: str, start_date: date, end_date: date) -> pd.DataFrame:
        return self.get_daily_prices([benchmark_symbol], start_date, end_date)

    def _resolve_instrument_token(self, symbol: str) -> int | None:
        normalized = symbol.strip().upper()
        if self._instrument_cache is None:
            self._instrument_cache = self._build_instrument_cache()
        if normalized not in self._instrument_cache:
            return None
        return self._instrument_cache[normalized]

    def _build_instrument_cache(self) -> dict[str, int]:
        cache: dict[str, int] = {}
        for stock in load_universe():
            tradingsymbol = (stock.kite_tradingsymbol or stock.symbol).strip().upper()
            if stock.kite_instrument_token:
                token = int(stock.kite_instrument_token)
                cache[stock.symbol.upper()] = token
                cache[tradingsymbol] = token

        for instrument in self._kite_request(lambda: self._kite.instruments(config.KITE_EXCHANGE)):
            tradingsymbol = str(instrument.get("tradingsymbol", "")).strip().upper()
            token = instrument.get("instrument_token")
            if tradingsymbol and token:
                cache.setdefault(tradingsymbol, int(token))

        benchmark = config.DEFAULT_BENCHMARK_SYMBOL.strip().upper()
        benchmark_tradingsymbol = config.KITE_BENCHMARK_TRADINGSYMBOL.strip().upper()
        if benchmark_tradingsymbol in cache:
            cache[benchmark] = cache[benchmark_tradingsymbol]
        return cache

    def _kite_request(self, call: Callable[[], T]) -> T:
        last_error: Exception | None = None
        for attempt in range(config.KITE_MAX_RETRIES + 1):
            try:
                return call()
            except Exception as exc:
                last_error = exc
                message = str(exc).lower()
                if "too many requests" not in message and "rate" not in message:
                    raise
                if attempt >= config.KITE_MAX_RETRIES:
                    break
                sleep_seconds = config.KITE_RETRY_BACKOFF_SECONDS * (attempt + 1)
                self.warnings.append(
                    f"Kite rate limit hit; retrying in {sleep_seconds:.1f}s "
                    f"(attempt {attempt + 1}/{config.KITE_MAX_RETRIES})."
                )
                time.sleep(sleep_seconds)
        assert last_error is not None
        raise last_error


def iter_date_chunks(start_date: date, end_date: date, max_days: int) -> list[tuple[date, date]]:
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date.")
    if max_days <= 0:
        raise ValueError("max_days must be greater than zero.")
    chunks: list[tuple[date, date]] = []
    cursor = start_date
    while cursor <= end_date:
        chunk_end = min(cursor + timedelta(days=max_days - 1), end_date)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks


def get_market_data_provider() -> YahooFinanceMarketDataProvider | KiteHistoricalMarketDataProvider:
    provider = config.MARKET_DATA_PROVIDER.strip().upper()
    if provider == "KITE":
        return KiteHistoricalMarketDataProvider()
    if provider == "YAHOO":
        return YahooFinanceMarketDataProvider()
    raise ValueError(f"Unsupported MARKET_DATA_PROVIDER: {config.MARKET_DATA_PROVIDER}")


def _normalize_download(data: pd.DataFrame, requested_symbols: list[str], yahoo_symbols: list[str]) -> pd.DataFrame:
    if data.empty:
        return pd.DataFrame(columns=["symbol", "price_date", "open", "high", "low", "close", "adjusted_close", "volume"])

    frames: list[pd.DataFrame] = []
    multi_ticker = isinstance(data.columns, pd.MultiIndex)
    for symbol, yahoo_symbol in zip(requested_symbols, yahoo_symbols, strict=True):
        if multi_ticker:
            if yahoo_symbol not in data.columns.get_level_values(0):
                continue
            symbol_frame = data[yahoo_symbol].copy()
        else:
            symbol_frame = data.copy()
        if symbol_frame.empty or "Close" not in symbol_frame.columns:
            continue
        symbol_frame = symbol_frame.reset_index()
        date_column = "Date" if "Date" in symbol_frame.columns else symbol_frame.columns[0]
        normalized = pd.DataFrame(
            {
                "symbol": symbol.strip().upper(),
                "price_date": pd.to_datetime(symbol_frame[date_column]).dt.date,
                "open": symbol_frame.get("Open"),
                "high": symbol_frame.get("High"),
                "low": symbol_frame.get("Low"),
                "close": symbol_frame.get("Close"),
                "adjusted_close": symbol_frame.get("Adj Close", symbol_frame.get("Close")),
                "volume": symbol_frame.get("Volume"),
            }
        )
        normalized = normalized.dropna(subset=["close"])
        frames.append(normalized)
    if not frames:
        return pd.DataFrame(columns=["symbol", "price_date", "open", "high", "low", "close", "adjusted_close", "volume"])
    return pd.concat(frames, ignore_index=True)


def frame_to_price_bars(frame: pd.DataFrame, source: str = "YAHOO") -> list[PriceBar]:
    fetched_at = datetime.now(timezone.utc).isoformat()
    bars: list[PriceBar] = []
    for row in frame.to_dict("records"):
        bars.append(
            PriceBar(
                symbol=str(row["symbol"]).upper(),
                price_date=row["price_date"],
                open=_none_or_float(row.get("open")),
                high=_none_or_float(row.get("high")),
                low=_none_or_float(row.get("low")),
                close=_none_or_float(row.get("close")),
                adjusted_close=_none_or_float(row.get("adjusted_close")),
                volume=_none_or_int(row.get("volume")),
                source=source,
                fetched_at=fetched_at,
            )
        )
    return bars


def _none_or_float(value: object) -> float | None:
    if pd.isna(value):
        return None
    return float(value)


def _none_or_int(value: object) -> int | None:
    if pd.isna(value):
        return None
    return int(value)
