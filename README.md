# Strategy Research Factory

Local Python foundation for Indian-equities strategy research, optimization, backtesting, model-portfolio generation, and portable Vriksha strategy-package exports.

Dual Momentum is the first strategy profile in this repository. See [strategies/dual-momentum/methodology.md](strategies/dual-momentum/methodology.md) for its momentum/beta/volatility signal math, ranking methods, allocation logic, holding buffer, and rebalance mechanics. See [docs/strategy_factory.md](docs/strategy_factory.md) for the reusable profile-based workflow.

This repository does not own Vriksha website accounts, payments, subscriptions, or access control.

## Repository Roles

```text
.env                              Runtime/provider settings only.
strategies/<slug>/strategy_profile.json
                                  Strategy identity, public metadata, optimization input, and package output path.
data/output/finalized/*.json       Best parameters promoted from experiment/Optuna output.
app/optimization/                  Converts experiment results into finalized configs.
app/backtest/                      Runs the finalized strategy simulation.
app/export/                        Creates the portable Vriksha strategy package.
```

## Dual Momentum Package Pipeline

Use the default Dual Momentum profile:

```bash
python -m app.main build-finalized-package --start-date 2016-01-01 --end-date 2025-12-31 --initial-capital 1000000
```

Or pass it explicitly:

```bash
python -m app.main build-finalized-package --strategy-profile strategies/dual-momentum/strategy_profile.json --start-date 2016-01-01 --end-date 2025-12-31 --initial-capital 1000000
```

That command selects the best CAGR-ranked experiment row, writes a finalized config, applies those parameters, runs the backtest, and exports the Vriksha package.

## Windows Conda Setup

Create and activate a Python 3.12 Conda environment from VS Code or Anaconda Prompt, then install dependencies:

```bash
conda activate vrisksha-strategy-manager
cd "C:\Users\Yashodhan\OneDrive\Documents\Algo\vrisksha-strategy-manager"
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
cd "C:\Users\Yashodhan\OneDrive\Documents\Algo\vrisksha-strategy-manager"
conda activate vrisksha-strategy-manager
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

Daily laptop-start automation uses Selenium to open Kite login when today's access token is missing, refresh recent history, and run the scheduled rebalance workflow only on configured rebalance dates:

```text
SELENIUM_LOGIN_TIMEOUT_SECONDS=180
AUTO_REBALANCE_TARGET_DAYS=1,15
AUTOMATION_HISTORY_LOOKBACK_DAYS=10
TARGET_PORTFOLIO_VALUE=1000000
AVAILABLE_PURCHASE_FUNDS=1000000
```

`AUTO_REBALANCE_TARGET_DAYS=1,15` means the rebalance workflow runs twice per month: on the first trading/pricing day on or after the 1st, and on the first trading/pricing day on or after the 15th. The current calendar is still the provisional weekday calendar, so NSE holiday support remains a future improvement.
On those dates, the scheduled workflow calculates the real target portfolio from stored prices, saves selected holdings/weights/quantities, and creates proposed buy/sell orders in SQLite. BUY proposals are scaled proportionally to `AVAILABLE_PURCHASE_FUNDS`, so if intended buys total 1,000,000 but available purchase funds are 500,000, every BUY is proposed at 50% of its target value. It does not submit live broker orders unattended.

Get a Kite login URL:

```bash
python -m app.main kite-login-url
```

Check whether today's saved token is still accepted by Kite:

```bash
python -m app.main kite-token-status
```

For unattended daily login, configure Selenium auto-login in `.env`:

```text
KITE_USER_ID=YOUR_ZERODHA_CLIENT_ID
KITE_PASSWORD=YOUR_ZERODHA_PASSWORD
KITE_TOTP_SECRET=YOUR_BASE32_TOTP_SECRET
```

`KITE_TOTP_SECRET` is the base32 secret from your authenticator setup, not the six-digit code. With these values present, `kite-selenium-token` runs headless Chrome, enters credentials, generates the TOTP code, captures the redirect `request_token`, and saves today's `KITE_ACCESS_TOKEN`.

Saved tokens are reused only when the token date is today and `kite.profile()` confirms the token is valid. If daily automation finds today's saved token is invalid, it refreshes the token through Selenium auto-login.

After Kite redirects, copy the `request_token` from the browser URL and run:

```bash
python -m app.main kite-save-token --request-token YOUR_REQUEST_TOKEN
```

Or use Selenium to open the Kite login page and capture the redirect token after you complete login in the browser:

```bash
python -m app.main kite-selenium-token
```

If the unattended Selenium credentials above are configured, the same command runs without manual browser input. If they are missing, it falls back to the visible manual Selenium login flow.

Or save the token and fetch historical data in one command:

```bash
python -m app.main fetch-history --start-date 2024-01-01 --end-date 2025-12-31 --request-token YOUR_REQUEST_TOKEN
```

Advanced: fetch full synced universe history after today's token has been saved:

```bash
python -m app.main fetch-history --start-date 2016-01-01 --end-date 2025-12-31
```

`fetch-history`, `run-backtest`, and `auto-daily-run` automatically include the benchmark (`DEFAULT_BENCHMARK_SYMBOL`) and the configured safe asset (`SAFE_ASSET_SYMBOL`) alongside the requested/universe symbols, so `LIQUIDBEES`/`GOLDBEES` prices are fetched without listing them explicitly. Use `--no-benchmark` or `--no-safe-asset` to skip either.

Quick Kite test for one stock:

```bash
python -m app.main fetch-history --start-date 2024-01-01 --end-date 2024-01-10 --symbols RELIANCE --no-benchmark --no-safe-asset
```

Advanced: run backtest using already stored local data only:

```bash
python -m app.main backtest --years 10
python -m app.main backtest --start-date 2016-01-01 --end-date 2025-12-31
```

Strategy knobs are not meant to live in `.env`. The finalized package pipeline gets them from experiment output and writes them to:

```text
data/output/finalized/dual_momentum_best_config.json
```

Strategy identity, public metadata, optimization input path, finalized config path, and package output path live in:

```text
strategies/dual-momentum/strategy_profile.json
```

Use `STRATEGY_RANKING_METHOD=AVERAGE_RANK` to rank stocks independently by raw 3M/6M/12M momentum, low beta, and low volatility, then sort by the average of those three ranks. With `STRATEGY_TOP_N=25`, the allocator uses the top 25 average-rank candidates. Other supported ranking methods are `MOMENTUM`, `BETA_ADJUSTED`, `VOLATILITY_ADJUSTED`, and `COMBINED_RANK`; `COMBINED_RANK` uses a weighted percentile blend and normalizes the three `RANKING_*_WEIGHT` values internally.

Use `STRATEGY_ALLOCATION_MODE=TOP_N_EQUAL` to buy the top N ranked stocks with equal weights capped by `MAX_STOCK_WEIGHT`. Use `STRATEGY_ALLOCATION_MODE=DYNAMIC` to buy the top N positive-score stocks with weights tilted toward stronger scores and constrained by `DYNAMIC_MIN_WEIGHT` / `DYNAMIC_MAX_WEIGHT`. `MAX_SECTOR_WEIGHT` caps the combined allocation to any one sector; excess weight moves to `SAFE_ASSET_SYMBOL` / cash. Set `SAFE_ASSET_SYMBOL=GOLDBEES`, `LIQUIDBEES`, or another stored symbol to use that asset for residual allocation when fewer than the target number of stocks qualify or caps leave unallocated weight.

Backtests store each scenario in SQLite using a stable scenario key derived from the dates, capital, and strategy knobs. With `BACKTEST_REUSE_SCENARIO=true`, repeated matching backtests reuse the completed DB result instead of rerunning; pass `--force` to run again. Holding snapshots and order proposals floor quantities to whole tradable units.

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
scripts\run_auto_daily.bat
scripts\install_auto_daily_startup.bat
scripts\run_live_dashboard.bat
scripts\run_backtest_dashboard.bat
```

To make the automation run when you log in to Windows, run:

```bat
scripts\install_auto_daily_startup.bat
```

After that, Windows launches `scripts\run_auto_daily.bat` at login. Output is appended to `logs\auto_daily.log`.
The batch file attempts to activate the `vrisksha-strategy-manager` Conda environment from common Miniconda/Anaconda install paths before running Python. Set `CONDA_ENV_NAME` before running the script if your environment has a different name.

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
python -m app.main kite-token-status
python -m app.main kite-save-token --request-token YOUR_REQUEST_TOKEN
python -m app.main kite-selenium-token
python -m app.main auto-daily-run --selenium-token
```

`monthly-run` and the scheduled rebalance step inside `auto-daily-run` calculate a real target portfolio and proposed order list from stored `market_prices`. They still never submit live broker orders. `manual-run` remains a safe placeholder.

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

The current simulation uses stored daily prices, configurable in-month rebalance dates, 3M/6M/12M momentum, beta, volatility, the 52-week-high filter, the configured ranking method, and the configured allocation mode. `BACKTEST_REBALANCES_PER_MONTH=1` preserves the original monthly cadence.

## Next Sprint

NSE holiday calendar, stronger benchmark validation, richer backtest metrics, and dashboard charts.
