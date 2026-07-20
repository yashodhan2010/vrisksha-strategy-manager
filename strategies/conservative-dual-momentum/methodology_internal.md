# Conservative Dual Momentum Strategy Details

This document explains the actual dual-momentum methodology implemented in code — the signals, filters, ranking math, allocation logic, rebalance cadence, and order sizing. See [README.md](../../README.md) for setup/architecture and command usage.

The conservative variant uses the same signal family as Dual Momentum, but its optimizer ranks candidates primarily by return-to-drawdown and searches broader diversification, tighter stock caps, sector caps, and higher holding buffers.

The same ranking/allocation logic (`app/backtest/engine.py::_rank_on_date` + `app/strategy/selection.py::allocate_from_ranking`) is shared by the backtest engine and the live/paper `RebalanceEngine`, so backtested behavior and live behavior are computed identically.

## 1. Universe

The tradable universe is the locally maintained Nifty 500 list (`data/reference/nifty500_universe.json`, synced from the Excel source of truth). Each stock carries a `sector` and `industry` used later for sector-cap enforcement. The configured safe asset (`SAFE_ASSET_SYMBOL`, default `LIQUIDBEES`) and the benchmark (`DEFAULT_BENCHMARK_SYMBOL`, default `NIFTY500`) are tracked separately from the equity universe.

## 2. Price Series

For every symbol, the daily price used for signals is `adjusted_close`, falling back to `close` when adjusted close is missing. Prices are pivoted into a date × symbol matrix and forward-filled only up to `MAX_PRICE_FORWARD_FILL_DAYS` rows (default 5). This tolerates small sparse-data gaps but prevents stale pre-listing or re-mapped symbol prices from being carried across long calendar gaps.

## 3. Signal Construction (per rebalance date)

For each non-safe-asset symbol with at least `BETA_LOOKBACK_DAYS` (default 252) days of price history:

### 3.1 52-week-high filter
```
high_52w = max(price over trailing 252 trading days)
qualifies only if current_price / high_52w >= HIGH_52W_THRESHOLD (default 0.80)
```
Stocks more than 20% below their 52-week high are dropped before scoring.

### 3.2 Momentum score
Simple (non-log) returns over three trailing windows, approximating 3/6/12 months in trading days, with the most recent trading month skipped:
```
momentum_anchor = price_21d_ago
return_3m  = (momentum_anchor / price_84d_ago)  - 1
return_6m  = (momentum_anchor / price_147d_ago) - 1
return_12m = (momentum_anchor / price_273d_ago) - 1
momentum_score = average(return_3m, return_6m, return_12m)
```
If any lookback price is unavailable or non-positive, the stock is excluded entirely (no partial momentum score).

### 3.3 Beta
```
stock_returns     = pct_change(price) over the lookback window
benchmark_returns = pct_change(benchmark price)
aligned = inner-join of stock_returns and benchmark_returns, inf/-inf dropped
beta = covariance(stock, benchmark) / variance(benchmark)
```
Fallbacks:
- Beta defaults to `1.0` if the benchmark has no stored prices, or fewer than 30 aligned daily observations exist, or benchmark variance is zero/undefined.
- A computed beta `<= 0` is floored to `BETA_FLOOR` (default `0.25`) rather than used as-is.

### 3.4 Volatility
```
daily_returns = pct_change(price), NaNs dropped
volatility = std(daily_returns over last BETA_LOOKBACK_DAYS, ddof=0) * sqrt(252)
```
Annualized population standard deviation of daily returns over the same lookback window used for beta.

Rows missing `momentum_score`, `beta`, or `volatility` are dropped before ranking.

## 4. Ranking (`STRATEGY_RANKING_METHOD`)

Five interchangeable scoring methods, all higher-score-is-better:

| Method | Score formula |
|---|---|
| `MOMENTUM` | `momentum_score` |
| `BETA_ADJUSTED` | `momentum_score / max(beta, BETA_FLOOR)` |
| `VOLATILITY_ADJUSTED` | `momentum_score / max(volatility, 0.01)` |
| `AVERAGE_RANK` (default) | negative weighted average of momentum, low-beta, and low-volatility ranks - see below |
| `COMBINED_RANK` | weighted blend of percentile ranks — see below |

### Average rank
```
momentum_rank   = rank(momentum_score, descending)  # higher momentum is better
beta_rank       = rank(beta, ascending)             # lower beta is better
volatility_rank = rank(volatility, ascending)       # lower volatility is better

total = RANKING_MOMENTUM_WEIGHT + RANKING_BETA_WEIGHT + RANKING_VOLATILITY_WEIGHT
momentum_weight   = RANKING_MOMENTUM_WEIGHT / total
beta_weight       = RANKING_BETA_WEIGHT / total
volatility_weight = RANKING_VOLATILITY_WEIGHT / total

average_rank = average(momentum_rank, beta_rank, volatility_rank)  # stored for diagnostics
weighted_average_rank = momentum_weight * momentum_rank
                      + beta_weight * beta_rank
                      + volatility_weight * volatility_rank
score = -weighted_average_rank
```
Stocks are sorted descending by `score`, which means the lowest `weighted_average_rank` receives final `rank = 1`. With `STRATEGY_TOP_N=25`, the allocation step uses the top 25 weighted-average-rank candidates.

### Combined rank
```
total = RANKING_MOMENTUM_WEIGHT + RANKING_BETA_WEIGHT + RANKING_VOLATILITY_WEIGHT
momentum_weight   = RANKING_MOMENTUM_WEIGHT / total
beta_weight       = RANKING_BETA_WEIGHT / total
volatility_weight = RANKING_VOLATILITY_WEIGHT / total

momentum_percentile      = percentile_rank(momentum_score, ascending)   # higher momentum -> higher percentile
low_beta_percentile      = percentile_rank(-beta, ascending)            # lower beta -> higher percentile
low_volatility_percentile= percentile_rank(-volatility, ascending)      # lower volatility -> higher percentile

score = momentum_weight * momentum_percentile
      + beta_weight * low_beta_percentile
      + volatility_weight * low_volatility_percentile
```
Weights are normalized internally, so `RANKING_*_WEIGHT` values don't need to sum to 1 (defaults: `0.60` / `0.25` / `0.15` for momentum/beta/volatility). Stocks are sorted descending by `score` and assigned `rank = 1, 2, 3, ...`.

## 5. Selection & Allocation (`STRATEGY_ALLOCATION_MODE`)

### 5.1 `TOP_N_EQUAL` (default)
- Select the top `STRATEGY_TOP_N` (default 25) ranked symbols.
- Equal-weight each: `weight = min(1/N, MAX_STOCK_WEIGHT)` (default cap 5%).
- Apply sector caps (see below).
- Any unallocated weight (from the per-stock cap, sector caps, or fewer than N qualifying stocks) becomes the safe-asset/cash residual.

### 5.2 `DYNAMIC`
- Take the top `STRATEGY_TOP_N` ranked symbols, then drop any with `score <= 0`.
- Investable weight is capped at `min(1.0, DYNAMIC_MAX_WEIGHT * count)`.
- Every selected stock gets at least `DYNAMIC_MIN_WEIGHT` (default 1%); the remaining "variable" budget is distributed proportionally to each stock's score, then weights are clipped to `[DYNAMIC_MIN_WEIGHT, DYNAMIC_MAX_WEIGHT]` (default 1%–7%) with iterative redistribution of any leftover budget to stocks still under their cap.
- Sector caps are applied after weights are computed; remaining weight goes to the safe asset.

### 5.3 Sector caps
`MAX_SECTOR_WEIGHT` (default 1.0 = disabled unless lowered, README examples use 0.25) limits the combined weight of any single sector. If a sector's total weight exceeds the cap, every stock in that sector is scaled down proportionally: `weight *= max_sector_weight / sector_total`. The weight removed is not reassigned to other stocks — it flows into the safe-asset residual.

### 5.4 Safe asset / cash residual
`safe_asset_weight = 1 - sum(stock_weights)`. `fetch-history`/`run-backtest`/`auto-daily-run` automatically include `SAFE_ASSET_SYMBOL` (alongside the benchmark) when pulling prices, so its actual returns are used. If the configured `SAFE_ASSET_SYMBOL` still has no usable stored price for a period (e.g. history was fetched with `--no-safe-asset`, or before this symbol existed in Kite), its return contribution falls back to `0` (cash-like) and a warning is recorded instead of failing the run.

## 6. Rebalance Cadence

- **Backtest**: `BACKTEST_REBALANCES_PER_MONTH` (default 1) controls how many rebalance dates are generated per month, spaced evenly across each month's available trading/pricing days (`1` = start of month only, `2` = start + mid-month, `4` ≈ weekly).
- **Live/paper**: `AUTO_REBALANCE_TARGET_DAYS` (default `1,15`) drives the daily-automation schedule — the workflow runs on the first trading/pricing day on or after each configured day-of-month.

At each rebalance date, ranking + allocation are recomputed from scratch (no explicit rank persistence between periods); "holding_action" (`HELD` vs `ENTERED`) and consecutive/total months-held counters are derived by comparing the new selected set to the previous snapshot's symbols.

## 7. Order Sizing (live/paper `RebalanceEngine`)

Live rebalances translate target weights into broker order proposals against real capital:

```
target_value(symbol)   = TARGET_PORTFOLIO_VALUE * target_weight(symbol)
previous_value(symbol) = last recorded market value for that symbol (0 if new)
delta_value             = target_value - previous_value   # ignored if |delta| < 1
side                    = BUY if delta_value > 0 else SELL
```

Buys are then scaled down if there isn't enough cash:
```
total_buy_value    = sum(delta_value) over all BUY-side symbols
buy_scaling_ratio  = min(1.0, AVAILABLE_PURCHASE_FUNDS / total_buy_value)
```
Every BUY's estimated value is multiplied by `buy_scaling_ratio` (SELLs are never scaled). Final order quantities are floored to whole units (`floor(estimated_value / reference_price)`); zero-quantity proposals are dropped. A warning is recorded whenever scaling kicks in. No live broker orders are submitted automatically — proposals are written to SQLite for review/execution.

## 8. Performance Accounting (backtest)

- Portfolio NAV compounds period-over-period: `nav *= (1 + month_return)`, where `month_return` is the weighted sum of each holding's period return plus the safe asset's weighted period return.
- `total_return = nav / initial_capital - 1`.
- `annualized_return = (nav / initial_capital) ** (1 / years) - 1`, using actual elapsed years between the first and last rebalance dates.
- Max drawdown is computed from the running NAV series (peak-to-trough decline).

## 9. Config Reference

| Env var | Default | Purpose |
|---|---|---|
| `HIGH_52W_THRESHOLD` | 0.80 | Minimum price / 52-week-high ratio to qualify |
| `BETA_LOOKBACK_DAYS` | 252 | Trading-day window for beta and volatility |
| `BETA_FLOOR` | 0.25 | Floor applied to non-positive computed beta (and divisor floor for `BETA_ADJUSTED`) |
| `STRATEGY_RANKING_METHOD` | `AVERAGE_RANK` | `MOMENTUM` \| `BETA_ADJUSTED` \| `VOLATILITY_ADJUSTED` \| `AVERAGE_RANK` \| `COMBINED_RANK` |
| `RANKING_MOMENTUM_WEIGHT` | 0.60 | Combined-rank momentum weight (normalized) |
| `RANKING_BETA_WEIGHT` | 0.25 | Combined-rank low-beta weight (normalized) |
| `RANKING_VOLATILITY_WEIGHT` | 0.15 | Combined-rank low-volatility weight (normalized) |
| `STRATEGY_ALLOCATION_MODE` | `TOP_N_EQUAL` | `TOP_N_EQUAL` \| `DYNAMIC` |
| `STRATEGY_TOP_N` | Optimized, usually broader than standard Dual Momentum | Number of stocks selected each rebalance |
| `MAX_STOCK_WEIGHT` | Optimized, usually lower than standard Dual Momentum | Per-stock weight cap (`TOP_N_EQUAL`) |
| `DYNAMIC_MIN_WEIGHT` / `DYNAMIC_MAX_WEIGHT` | 0.01 / 0.07 | Per-stock weight bounds (`DYNAMIC`) |
| `MAX_SECTOR_WEIGHT` | 1.0 | Cap on combined sector weight |
| `SAFE_ASSET_SYMBOL` | `LIQUIDBEES` | Residual/cash-proxy asset |
| `MAX_PRICE_FORWARD_FILL_DAYS` | 5 | Maximum rows to forward-fill missing prices before treating the symbol as unavailable |
| `BACKTEST_REBALANCES_PER_MONTH` | 1 | Rebalance frequency in backtests |
| `AUTO_REBALANCE_TARGET_DAYS` | `1,15` | Day-of-month triggers for scheduled live rebalances |
| `TARGET_PORTFOLIO_VALUE` | 1,000,000 | Notional portfolio size for live weight → quantity conversion |
| `AVAILABLE_PURCHASE_FUNDS` | = `TARGET_PORTFOLIO_VALUE` | Real cash available to scale BUY proposals |

## 10. Not Yet Active

The schema and config already reserve fields for a cooldown/EMA mechanism (`COOLDOWN_CHECK_EVERY_RESHUFFLES`, `COOLDOWN_DURATION_MONTHS`, `PORTFOLIO_EMA_PERIOD_MONTHS`, `cooldown_checked`/`cooldown_triggered`/`ema_value` columns, `PortfolioState.COOLDOWN`), and `app/strategy/engine.py` documents the intended behavior (every sixth reshuffle, compare NAV to its EMA and switch fully to the safe asset for one month if NAV is below the EMA). This logic is **not implemented yet** — current backtests and live rebalances always run in the `ACTIVE` state described above.
