from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd
import requests

from app.data.historical_data import PriceBar
from app.data.market_data import MarketDataProvider


@dataclass(frozen=True)
class BenchmarkComparisonSpec:
    label: str
    symbol: str
    provider: str
    provider_symbol: str
    method: str
    source_note: str


BENCHMARK_COMPARISON_SPECS = (
    BenchmarkComparisonSpec(
        "NIFTY 50",
        "NIFTY50",
        "market_data",
        "NIFTY50",
        "daily_price",
        "Kite/Yahoo index close.",
    ),
    BenchmarkComparisonSpec(
        "NIFTY 500",
        "NIFTY500",
        "market_data",
        "NIFTY500",
        "daily_price",
        "Kite/Yahoo index close.",
    ),
    BenchmarkComparisonSpec(
        "NIFTY 500 TRI",
        "NIFTY500TRI",
        "nse_indices",
        "NIFTY 500",
        "total_return",
        "NSE Indices total return index.",
    ),
    BenchmarkComparisonSpec(
        "NIFTY Gsec Composite",
        "NIFTYGSECCOMPOSITE",
        "nse_indices",
        "NIFTY Composite G-sec Index",
        "historical_index",
        "NSE Indices fixed-income index.",
    ),
    BenchmarkComparisonSpec(
        "Gold",
        "GOLD",
        "market_data",
        "GOLDBEES",
        "daily_price",
        "GoldBEES ETF close used as the tradable INR gold proxy.",
    ),
)


class NseIndicesClient:
    """Small NSE Indices historical-data client for benchmark-only series."""

    base_url = "https://niftyindices.com"

    def __init__(self, timeout_seconds: int = 30, session: requests.Session | None = None) -> None:
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
                ),
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Content-Type": "application/json; charset=UTF-8",
                "Origin": self.base_url,
                "Referer": f"{self.base_url}/reports/historical-data",
                "X-Requested-With": "XMLHttpRequest",
            }
        )

    def get_index_history(self, index_name: str, start_date: date, end_date: date) -> pd.DataFrame:
        return self._request_index_series("getHistoricaldatatabletoString", index_name, start_date, end_date)

    def get_total_return_index(self, index_name: str, start_date: date, end_date: date) -> pd.DataFrame:
        return self._request_index_series("getTotalReturnIndexString", index_name, start_date, end_date)

    def _request_index_series(self, method: str, index_name: str, start_date: date, end_date: date) -> pd.DataFrame:
        self._prime_session()
        cinfo = {
            "name": index_name,
            "startDate": _nse_date(start_date),
            "endDate": _nse_date(end_date),
            "indexName": index_name,
        }
        response = self.session.post(
            f"{self.base_url}/Backpage.aspx/{method}",
            json={"cinfo": json.dumps(cinfo, separators=(",", ":"))},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            content_type = response.headers.get("content-type", "")
            raise ValueError(
                f"NSE Indices returned {content_type or 'non-JSON'} instead of JSON for {index_name}."
            ) from exc
        records = json.loads(payload.get("d") or "[]")
        return _normalize_nse_records(records)

    def _prime_session(self) -> None:
        self.session.get(f"{self.base_url}/reports/historical-data", timeout=self.timeout_seconds)


def fetch_benchmark_comparison_bars(
    market_provider: MarketDataProvider,
    start_date: date,
    end_date: date,
    nse_client: NseIndicesClient | None = None,
) -> tuple[list[PriceBar], list[str]]:
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date.")

    fetched_at = datetime.now(timezone.utc).isoformat()
    bars: list[PriceBar] = []
    warnings: list[str] = []

    for spec in BENCHMARK_COMPARISON_SPECS:
        try:
            if spec.provider == "market_data":
                frame = market_provider.get_daily_prices([spec.provider_symbol], start_date, end_date)
                frame = frame[frame["symbol"].str.upper() == spec.provider_symbol]
                if frame.empty:
                    warnings.append(f"No benchmark comparison rows returned for {spec.label} ({spec.provider_symbol}).")
                    continue
                bars.extend(_market_frame_to_bars(frame, spec.symbol, market_provider.source, fetched_at))
            elif spec.provider == "nse_indices":
                client = nse_client or NseIndicesClient()
                if spec.method == "total_return":
                    frame = client.get_total_return_index(spec.provider_symbol, start_date, end_date)
                else:
                    frame = client.get_index_history(spec.provider_symbol, start_date, end_date)
                if frame.empty:
                    warnings.append(f"No NSE Indices rows returned for {spec.label} ({spec.provider_symbol}).")
                    continue
                bars.extend(_series_frame_to_bars(frame, spec.symbol, "NSE_INDICES", fetched_at))
            else:
                warnings.append(f"Unsupported benchmark comparison provider for {spec.label}: {spec.provider}.")
        except Exception as exc:
            warnings.append(f"Benchmark comparison fetch failed for {spec.label}: {exc}")
    return bars, warnings


def _market_frame_to_bars(frame: pd.DataFrame, symbol: str, source: str, fetched_at: str) -> list[PriceBar]:
    bars: list[PriceBar] = []
    for row in frame.to_dict("records"):
        close = _none_or_float(row.get("close"))
        adjusted_close = _none_or_float(row.get("adjusted_close")) or close
        bars.append(
            PriceBar(
                symbol=symbol,
                price_date=row["price_date"],
                open=_none_or_float(row.get("open")),
                high=_none_or_float(row.get("high")),
                low=_none_or_float(row.get("low")),
                close=close,
                adjusted_close=adjusted_close,
                volume=_none_or_int(row.get("volume")),
                source=source,
                fetched_at=fetched_at,
            )
        )
    return bars


def _series_frame_to_bars(frame: pd.DataFrame, symbol: str, source: str, fetched_at: str) -> list[PriceBar]:
    return [
        PriceBar(symbol, row["price_date"], None, None, None, row["price"], row["price"], None, source, fetched_at)
        for row in frame.to_dict("records")
    ]


def _normalize_nse_records(records: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for record in records:
        price_date = _parse_record_date(record)
        price = _parse_record_price(record)
        if price_date and price is not None:
            rows.append({"price_date": price_date, "price": price})
    if not rows:
        return pd.DataFrame(columns=["price_date", "price"])
    frame = pd.DataFrame(rows).drop_duplicates(subset=["price_date"]).sort_values("price_date")
    return frame.reset_index(drop=True)


def _parse_record_date(record: dict[str, Any]) -> date | None:
    for key in ("HistoricalDate", "Date", "date", "TIMESTAMP", "timestamp", "Index Date", "TRI_DATE"):
        value = record.get(key)
        if not value:
            continue
        parsed = pd.to_datetime(value, dayfirst=True, errors="coerce")
        if pd.notna(parsed):
            return parsed.date()
    return None


def _parse_record_price(record: dict[str, Any]) -> float | None:
    keys = (
        "CLOSE",
        "Close",
        "close",
        "Closing Index Value",
        "TotalReturnsIndex",
        "TotalReturnIndex",
        "Total Returns Index",
        "TRI",
        "Index Value",
        "IndexValue",
    )
    for key in keys:
        if key not in record:
            continue
        value = record.get(key)
        if value in (None, ""):
            continue
        try:
            return float(str(value).replace(",", ""))
        except ValueError:
            continue
    for key, value in record.items():
        normalized = str(key).lower().replace(" ", "")
        if "close" not in normalized and "totalreturn" not in normalized and "indexvalue" not in normalized:
            continue
        try:
            return float(str(value).replace(",", ""))
        except (TypeError, ValueError):
            continue
    return None


def _nse_date(value: date) -> str:
    return value.strftime("%d-%b-%Y")


def _none_or_float(value: object) -> float | None:
    if pd.isna(value):
        return None
    return float(value)


def _none_or_int(value: object) -> int | None:
    if pd.isna(value):
        return None
    return int(value)
