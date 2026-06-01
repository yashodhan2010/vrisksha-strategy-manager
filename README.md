# Dual Momentum

Local Python foundation for an Indian-equities dual-momentum strategy using a locally maintained Nifty 500 universe, SQLite persistence, CLI workflows, and Streamlit dashboards.

## Sprint 0 Scope

This sprint creates a clean runnable base: configuration, logging, SQLite schema, typed models, universe Excel-to-JSON validation, allocation logic, CLI placeholders, Windows scripts, and dashboard shells.

## Deferred Functionality

Historical market-data ingestion, momentum calculations, beta calculations, 52-week-high filters, trading-calendar holidays, full backtests, paper execution, live order placement, Zerodha Kite order APIs, and real performance metrics are intentionally deferred.

## Windows Conda Setup

Create and activate a Python 3.12 Conda environment from VS Code or Anaconda Prompt, then install dependencies:

```bash
conda activate dual-momentum
cd "C:\Users\Yashodhan\OneDrive\Documents\Dual Momentum\dual-momentum"
```

```bash
pip install -r requirements.txt
```

Initialize the local database:

```bash
python -m app.main init-db
```

## Universe Setup

Copy `data/reference/nifty500_universe.example.xlsx` to `data/reference/nifty500_universe.xlsx` and replace the fictional rows with real Nifty 500 data.

Excel is the source of truth. The generated `data/reference/nifty500_universe.json` is the validated runtime artifact.

Synchronize the universe:

```bash
python -m app.main sync-universe
```

## Copy-Paste Commands

Use these from the project root:

```bash
cd "C:\Users\Yashodhan\OneDrive\Documents\Dual Momentum\dual-momentum"
conda activate dual-momentum
```

First-time setup:

```bash
pip install -r requirements.txt
python -m app.main show-config
```

## One-Command Client Run

Use this when you already have today's `KITE_ACCESS_TOKEN` saved in `.env`:

```bash
python -m app.main run-backtest --start-date 2016-01-01 --end-date 2025-12-31 --initial-capital 1000000
```

Use this when you have a fresh Kite `request_token` from today's browser login:

```bash
python -m app.main run-backtest --start-date 2016-01-01 --end-date 2025-12-31 --initial-capital 1000000 --request-token YOUR_REQUEST_TOKEN
```

That single command does all of this:

```text
1. Initialize SQLite.
2. Sync the Nifty 500 Excel universe to JSON.
3. Save the Kite access token for the day, if --request-token is provided.
4. Fetch required historical data from Kite, including lookback data before the backtest start date.
5. Run the local simulation engine.
6. Store backtest results, portfolio snapshots, and holding snapshots in SQLite.
```

Long Kite historical ranges are split automatically into safe day-candle chunks. The default chunk size is controlled by:

```text
KITE_HISTORICAL_DAY_CHUNK_DAYS=1900
```

If Kite does not return an instrument token for a universe symbol, the ingestion step skips that symbol, records a warning, and continues with the instruments it can fetch.

Kite requests are throttled and retried to reduce rate-limit failures:

```text
KITE_REQUEST_SLEEP_SECONDS=0.4
KITE_MAX_RETRIES=5
KITE_RETRY_BACKOFF_SECONDS=2.0
```

Get a Kite login URL:

```bash
python -m app.main kite-login-url
```

After Kite redirects, copy the `request_token` from the browser URL and run:

```bash
python -m app.main kite-save-token --request-token YOUR_REQUEST_TOKEN
```

Or save the token and fetch historical data in one command:

```bash
python -m app.main fetch-history --start-date 2024-01-01 --end-date 2025-12-31 --request-token YOUR_REQUEST_TOKEN
```

Advanced: fetch full synced universe history after today's token has been saved:

```bash
python -m app.main fetch-history --start-date 2016-01-01 --end-date 2025-12-31
```

Quick Kite test for one stock:

```bash
python -m app.main fetch-history --start-date 2024-01-01 --end-date 2024-01-10 --symbols RELIANCE --no-benchmark
```

Advanced: run backtest using already stored local data only:

```bash
python -m app.main backtest --years 10
python -m app.main backtest --start-date 2016-01-01 --end-date 2025-12-31
```

Open dashboards:

```bash
streamlit run dashboards/live_app.py
streamlit run dashboards/backtest_app.py
```

After `run-backtest` completes, open the report dashboard:

```bash
streamlit run dashboards/backtest_app.py
```

The report dashboard includes run selection, headline metrics, NAV curve, monthly returns, drawdown, monthly reshuffle records, holdings by snapshot date, and stock-level monthly/cumulative contribution.

Windows batch shortcuts:

```bat
scripts\run_manual.bat
scripts\run_monthly.bat
scripts\run_backtest.bat
scripts\run_live_dashboard.bat
scripts\run_backtest_dashboard.bat
```

## Full CLI Reference

```bash
python -m app.main init-db
python -m app.main sync-universe
python -m app.main manual-run
python -m app.main monthly-run
python -m app.main backtest --years 10
python -m app.main backtest --start-date 2016-01-01 --end-date 2025-12-31
python -m app.main show-config
python -m app.main run-backtest --start-date 2016-01-01 --end-date 2025-12-31 --initial-capital 1000000
python -m app.main fetch-history --start-date 2024-01-01 --end-date 2024-12-31 --symbols RELIANCE TCS
python -m app.main fetch-history --start-date 2024-01-01 --end-date 2024-12-31 --request-token YOUR_REQUEST_TOKEN
python -m app.main kite-login-url
python -m app.main kite-save-token --request-token YOUR_REQUEST_TOKEN
```

`manual-run` and `monthly-run` are safe placeholders. `backtest` now runs a local historical simulation from stored `market_prices`; it still never places live orders.

Historical price ingestion uses Kite Connect by default and stores daily OHLCV rows in SQLite:

```bash
python -m app.main fetch-history --start-date 2024-01-01 --end-date 2024-12-31
```

Without `--symbols`, the command uses the synced universe. Kite historical data requires `KITE_API_KEY` and a valid daily `KITE_ACCESS_TOKEN` in `.env`.

To get the token, run `python -m app.main kite-login-url`, open the URL, complete Kite login manually, copy the `request_token` from the redirect URL, then either save it with `python -m app.main kite-save-token --request-token YOUR_REQUEST_TOKEN` or pass it directly to `fetch-history` with `--request-token`. The app saves the access token and token date in `.env` and reuses it for that day.

## Dashboards

```bash
streamlit run dashboards/live_app.py
streamlit run dashboards/backtest_app.py
```

The Live / Paper dashboard shows operational metadata and market-data summaries. The Backtest dashboard displays backtest-run metadata from SQLite.

## Modes

`RANK_ONLY` is the current default and will eventually calculate rankings without execution. `PAPER` will model orders and holdings locally. `LIVE` is reserved for future Zerodha Kite execution after explicit implementation and safeguards.

## Architecture

`app/data` handles universe, calendar, and market-data interfaces. `app/strategy` holds strategy models and allocation. `app/storage` owns SQLite schema and repositories. `app/execution` contains broker placeholders. `app/backtest` and `app/portfolio` expose future-facing interfaces. `dashboards` contains separate Streamlit apps.

## Backtest Notes

Before running a useful backtest, fetch enough daily history for the universe and benchmark:

```bash
python -m app.main fetch-history --start-date 2015-01-01 --end-date 2025-12-31
python -m app.main backtest --start-date 2016-01-01 --end-date 2025-12-31 --initial-capital 1000000
```

The current simulation uses stored daily prices, first available trading day of each month, 3M/6M/12M momentum, the 52-week-high filter, beta-adjusted scores, and capped equal allocation with residual allocation treated as cash/LIQUIDBEES.

## Next Sprint

NSE holiday calendar, stronger benchmark validation, richer backtest metrics, and dashboard charts.
