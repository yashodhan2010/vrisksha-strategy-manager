from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from app import config
from app.data import price_ingestion
from app.data.historical_data import KiteHistoricalMarketDataProvider, PriceBar, frame_to_price_bars, iter_date_chunks, to_yahoo_symbol
from app.storage.database import initialize_database
from app.storage.market_data_repository import count_price_rows, get_price_summary, upsert_price_bars


def test_yahoo_symbol_mapping() -> None:
    assert to_yahoo_symbol("reliance") == "RELIANCE.NS"
    assert to_yahoo_symbol("TCS.NS") == "TCS.NS"


def test_iter_date_chunks_splits_long_ranges() -> None:
    chunks = iter_date_chunks(date(2014, 1, 1), date(2025, 12, 31), 1900)
    assert chunks[0] == (date(2014, 1, 1), date(2019, 3, 15))
    assert chunks[1] == (date(2019, 3, 16), date(2024, 5, 27))
    assert chunks[2] == (date(2024, 5, 28), date(2025, 12, 31))


def test_frame_to_price_bars() -> None:
    frame = pd.DataFrame(
        [
            {
                "symbol": "ABC",
                "price_date": date(2024, 1, 1),
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10.5,
                "adjusted_close": 10.4,
                "volume": 1000,
            }
        ]
    )
    bars = frame_to_price_bars(frame)
    assert bars[0].symbol == "ABC"
    assert bars[0].close == 10.5
    assert bars[0].volume == 1000


def test_price_bars_upsert_and_summary(tmp_path: Path) -> None:
    db = tmp_path / "prices.db"
    initialize_database(db)
    bar = PriceBar("ABC", date(2024, 1, 1), 1, 2, 0.5, 1.5, 1.5, 100, "TEST", "now")
    assert upsert_price_bars([bar], db) == 1
    assert upsert_price_bars([bar], db) == 1
    assert count_price_rows(db) == 1
    assert get_price_summary(db)[0]["symbol"] == "ABC"


def test_fetch_and_store_history_uses_provider_and_records_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db = tmp_path / "prices.db"
    initialize_database(db)

    class FakeProvider:
        source = "TEST"

        def get_daily_prices(self, symbols: list[str], start_date: date, end_date: date) -> pd.DataFrame:
            assert symbols == ["ABC", "MISSING"]
            return pd.DataFrame(
                [
                    {
                        "symbol": "ABC",
                        "price_date": date(2024, 1, 1),
                        "open": 1,
                        "high": 2,
                        "low": 0.5,
                        "close": 1.5,
                        "adjusted_close": 1.5,
                        "volume": 100,
                    }
                ]
            )

    monkeypatch.setattr(price_ingestion, "get_market_data_provider", lambda: FakeProvider())
    monkeypatch.setattr(price_ingestion, "upsert_price_bars", lambda bars: upsert_price_bars(bars, db))
    monkeypatch.setattr(
        price_ingestion,
        "create_ingestion_run",
        lambda **kwargs: 1,
    )

    result = price_ingestion.fetch_and_store_history(
        date(2024, 1, 1),
        date(2024, 1, 2),
        symbols=["ABC", "MISSING"],
        include_benchmark=False,
        include_safe_asset=False,
    )

    assert result.stored_rows == 1
    assert result.missing_symbols == ["MISSING"]
    assert count_price_rows(db) == 1


def test_fetch_and_store_history_includes_all_safe_assets(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db = tmp_path / "prices.db"
    initialize_database(db)
    requested: list[str] = []

    class FakeProvider:
        source = "TEST"

        def get_daily_prices(self, symbols: list[str], start_date: date, end_date: date) -> pd.DataFrame:
            requested.extend(symbols)
            return pd.DataFrame(
                [
                    {
                        "symbol": symbol,
                        "price_date": date(2024, 1, 1),
                        "open": 1,
                        "high": 2,
                        "low": 0.5,
                        "close": 1.5,
                        "adjusted_close": 1.5,
                        "volume": 100,
                    }
                    for symbol in symbols
                ]
            )

    monkeypatch.setattr(price_ingestion, "get_market_data_provider", lambda: FakeProvider())
    monkeypatch.setattr(price_ingestion, "upsert_price_bars", lambda bars: upsert_price_bars(bars, db))
    monkeypatch.setattr(price_ingestion, "create_ingestion_run", lambda **kwargs: 1)
    monkeypatch.setattr(config, "SAFE_ASSET_SYMBOLS", ["LIQUIDBEES", "GOLDBEES"])
    monkeypatch.setattr(config, "DEFAULT_BENCHMARK_SYMBOL", "NIFTY500")

    result = price_ingestion.fetch_and_store_history(
        date(2024, 1, 1),
        date(2024, 1, 2),
        symbols=["ABC"],
        include_benchmark=True,
        include_safe_asset=True,
    )

    assert requested == ["ABC", "NIFTY500", "LIQUIDBEES", "GOLDBEES"]
    assert result.stored_rows == 4


def test_kite_provider_fetches_daily_prices_in_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[date, date]] = []

    class FakeKite:
        def set_access_token(self, access_token: str) -> None:
            pass

        def historical_data(self, token: int, start_date: date, end_date: date, interval: str, continuous: bool, oi: bool):
            calls.append((start_date, end_date))
            return [
                {
                    "date": start_date,
                    "open": 1,
                    "high": 2,
                    "low": 0.5,
                    "close": 1.5,
                    "volume": 100,
                }
            ]

    provider = KiteHistoricalMarketDataProvider.__new__(KiteHistoricalMarketDataProvider)
    provider._kite = FakeKite()
    provider._instrument_cache = {"ABC": 123}
    monkeypatch.setattr("app.data.historical_data.config.KITE_HISTORICAL_DAY_CHUNK_DAYS", 2)
    monkeypatch.setattr("app.data.historical_data.config.KITE_REQUEST_SLEEP_SECONDS", 0)

    frame = provider.get_daily_prices([("ABC")], date(2024, 1, 1), date(2024, 1, 5))

    assert calls == [
        (date(2024, 1, 1), date(2024, 1, 2)),
        (date(2024, 1, 3), date(2024, 1, 4)),
        (date(2024, 1, 5), date(2024, 1, 5)),
    ]
    assert frame["symbol"].tolist() == ["ABC", "ABC", "ABC"]


def test_kite_provider_reads_current_runtime_token(monkeypatch: pytest.MonkeyPatch) -> None:
    tokens: list[str] = []

    class FakeKite:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key

        def set_access_token(self, access_token: str) -> None:
            tokens.append(access_token)

    monkeypatch.setattr("app.data.historical_data.config.KITE_API_KEY", "key")
    monkeypatch.setattr("app.data.historical_data.config.KITE_ACCESS_TOKEN", "fresh-token")
    monkeypatch.setitem(__import__("sys").modules, "kiteconnect", type("FakeModule", (), {"KiteConnect": FakeKite}))

    KiteHistoricalMarketDataProvider()

    assert tokens == ["fresh-token"]


def test_kite_request_retries_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = KiteHistoricalMarketDataProvider.__new__(KiteHistoricalMarketDataProvider)
    provider.warnings = []
    attempts = {"count": 0}

    def flaky_call() -> str:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise Exception("Too many requests")
        return "ok"

    monkeypatch.setattr("app.data.historical_data.config.KITE_MAX_RETRIES", 2)
    monkeypatch.setattr("app.data.historical_data.config.KITE_RETRY_BACKOFF_SECONDS", 0)
    monkeypatch.setattr("app.data.historical_data.time.sleep", lambda seconds: None)

    assert provider._kite_request(flaky_call) == "ok"
    assert attempts["count"] == 2
    assert provider.warnings


def test_kite_provider_skips_symbols_without_tokens() -> None:
    class FakeKite:
        def historical_data(self, *args, **kwargs):
            raise AssertionError("historical_data should not be called for missing tokens")

    provider = KiteHistoricalMarketDataProvider.__new__(KiteHistoricalMarketDataProvider)
    provider._kite = FakeKite()
    provider._instrument_cache = {}
    provider.warnings = []

    frame = provider.get_daily_prices(["MISSING"], date(2024, 1, 1), date(2024, 1, 5))

    assert frame.empty
    assert provider.warnings == ["No Kite instrument token found for MISSING; skipped."]
