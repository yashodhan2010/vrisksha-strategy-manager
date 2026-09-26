# Live performance in strategy packages

Both `build_strategy_package` (full historical package) and
`export_latest_model_portfolio_update` (rebalance update) regenerate these files
inside the package directory, using the selected strategy and the same database
as the portfolio export:

| File | Contents |
|---|---|
| `live_manifest.json` | Strategy identity, availability, inception, latest live date, provenance, calculation method, warnings and price quality |
| `live_nav.csv` | `date,return,equity_curve,nav` |
| `live_benchmark.csv` | `date,return,equity_curve` |
| `live_drawdowns.csv` | `date,drawdown` |
| `live_metrics.json` | Metrics for the live period only |

The main `manifest.json` has a `live_performance` object pointing to
`live_manifest.json`, with `status`, `live_inception_date` and `latest_live_date`.
The files are additive; existing historical and portfolio filenames stay the same.
The website importer must explicitly read these new files.

Returns and drawdowns are decimals: `0.01` is 1%. Live equity starts at 1;
NAV uses the tracker target capital. Dates use `YYYY-MM-DD`.
`status: available` means at least one return interval exists, not that the data
has passed publication checks. With no usable live history, the CSVs are empty
(or contain only the inception baseline), metrics may be null, and status is
`unavailable`. No backtest proxy is substituted. Every export overwrites these
files so an old live series cannot survive a new empty export.

## Website composite

### Additional benchmark comparisons

Full packages and model portfolio updates expose `manifest.json.benchmark_comparisons`.
Live exports also expose the list in `live_manifest.json`; standalone live dashboards
include it in their manifest. Labels and stored market-price symbols are:

| Website label | Stored symbol | Source | File stem |
| --- | --- | --- | --- |
| NIFTY 50 | NIFTY50 | Kite/Yahoo index close | nifty_50 |
| NIFTY 500 | NIFTY500 | Kite/Yahoo index close | nifty_500 |
| NIFTY 500 TRI | NIFTY500TRI | NSE Indices total return index | nifty_500_tri |
| NIFTY Gsec Composite | NIFTYGSECCOMPOSITE | NSE Indices fixed-income index | nifty_gsec_composite |
| Gold | GOLD | GoldBEES ETF close as the tradable INR gold proxy | gold |

Each entry has `label`, `symbol`, `return_unit: "decimal"`, `historical_file`,
`live_file`, and coverage metadata for each exported scope. Paths are relative to
the package root: `benchmarks/<stem>_returns.csv` and
`benchmarks/<stem>_live_returns.csv`. CSV headers are exactly
`date,benchmark,return,equity_curve`.

Historical dates match `returns_daily.csv` in order; live dates match `live_nav.csv`.
Each scope independently starts with return `0` and equity `1` at its first observed
price. Later returns are `price / previous_aligned_price - 1`, and equity is
`price / inception_price`. Extra source dates are ignored. These comparisons use
stored adjusted close when present, otherwise close, with KITE preferred when
providers overlap. Returns are decimals, so `0.01` means 1%.

The exporter never fills missing observations, substitutes ETFs, or relabels a
price index as TRI. A missing, nonpositive, or nonfinite price on any required date
makes that scope unavailable: its file reference is `null`, its coverage reports
`status: "unavailable"`, `reason: "missing_observed_prices"`, and `missing_dates`,
and any stale file for that scope is removed. No strategy dates gives reason
`no_strategy_dates`. Other benchmarks and scopes can still be available. Updates
have no historical file; retain the previously imported historical series.

Import only non-null file references with available coverage. Enable composite
comparisons only when both segments and their transition have valid coverage.
Load genuine observations under the stored symbols above before exporting to
enable missing options. In particular, `NIFTY500` cannot supply `NIFTY500TRI`,
and `GSEC10IETF` cannot supply the composite index. The ingestion flow stores
GoldBEES observations under `GOLD` so the website can show the clearer `Gold`
label while the source remains auditable as an ETF proxy. Existing primary
benchmark files and labels are unchanged.

`fetch-history`, `run-backtest`, `build-finalized-package`,
`build-model-portfolio-update`, `export-live-performance-tracker --fetch-history`,
and `auto-daily-run` fetch these comparison series by default. Use
`--no-benchmark-comparisons` when refreshing only the strategy symbols. NSE
Indices endpoint failures are recorded as warnings, so Kite/Yahoo-backed series
can still be stored even if TRI or G-sec download is temporarily unavailable.

For the historical segment use `returns_daily.csv` and `benchmark_returns.csv`
from the full package. A rebalance update supplies the live segment; retain the
previously imported historical segment for that same strategy.

Use an explicit transition date at live inception. Require historical coverage
at the transition and verify there is no data gap. Keep historical values through
that date, then append live values after it, scaled by the historical equity at
the transition. Apply the same rule independently to the benchmark. Never append
overlapping backtest returns or invent returns for a gap or missing benchmark.

Calculate composite metrics, drawdowns, monthly and yearly returns from the joined
daily series. Do not concatenate period summaries or use live-only metrics as
composite metrics. The transition month must compound the retained backtest days
and live days exactly once. Label the current month as month-to-date and distinguish
backtest from live model performance. Show the actual performance date, not export
generation time. Keep the last valid imported version if price quality fails.

## Current calculation limitations

This change packages the existing tracker calculation. Its `internal_only` flag
and model provenance are retained: it reconstructs returns from saved model
rebalance snapshots, not broker fills or website publication approvals. It applies
the latest target weights to each daily return; it does not yet track drifting
weights or fixed quantities between rebalances. Correct and validate that method
before treating the series as published buy-and-hold-between-rebalances results.
Inspect warnings and missing/stale prices before publication. `available` alone
does not imply complete, current or approved data.

Live returns now require observed positive prices for the benchmark and active
holdings. Missing inception prices produce no curve; a later price gap stops both
curves at the prior valid date and records a warning. Benchmark values are never
forward-filled to manufacture zero returns. Historical export rejects mismatched
strategy and benchmark dates. Verified NSE non-session dates are excluded before
daily strategy reconstruction; the saved holdings and rebalance snapshots are not
modified.

`live_manifest.json.session_completeness` includes an independent expected session
list, missing/unexpected dates, source circular URLs, and `complete`/`window_covered`
flags. The current evidence covers NSE cash sessions from 2026-01-01 through
2026-09-24, including the January 15 election holiday and February 1 special session.
It is not a timeless calendar: dates outside that window must not be treated as
verified. This detects sessions omitted from both exported curves. Full manifests
also include `session_completeness_2026` for their historical 2026 segment; it does
not claim authoritative calendar validation for earlier years.

Exports use stored prices and do not fetch prices themselves. The existing
`build-model-portfolio-update` command normally refreshes recent history before
exporting. Rebuilding a full package also includes live data through the latest
stored usable price date, which may differ from the backtest end date.
