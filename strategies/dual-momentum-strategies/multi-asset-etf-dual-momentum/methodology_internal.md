# Multi Asset ETF Dual Momentum Strategy Details

The tradable universe is maintained in `data/reference/multi_asset_etf_dual_momentum_universe.json`, synced from the matching Excel source of truth. The `sector` field is the uploaded asset class and is used when asset-class caps are enabled.

Signals:

- `return_3m`, `return_6m`, and `return_12m` are calculated from the momentum anchor after skipping the configured recent trading month.
- `momentum_score` is the simple average of the three returns.
- The ETF optimizer ranks by momentum only (`momentum_weight = 1.0`) unless the search space is changed later.

Filters:

- `MIN_AVG_MOMENTUM_RETURN` defaults to `0.0`.
- `MIN_12M_RETURN` defaults to `0.06`.
- `HIGH_52W_THRESHOLD` is derived from `high_cutoff_pct`; `0` disables this filter and `20` requires price within 20% of the 52-week high.
- `REQUIRE_PRICE_ABOVE_EMA` optionally requires price above the configured EMA, default 200 days.

Allocation:

- Top `STRATEGY_TOP_N` ETFs are selected.
- `BUFFER_PCT` defaults to zero for no rank buffer.
- Equal weights are capped by `MAX_STOCK_WEIGHT` and optional asset-class cap.
- Residual allocation goes to `SAFE_ASSET_SYMBOL`, default `LIQUIDCASE`, when prices are available.

Distributions:

- Dividend and distribution events are read from `data/reference/multi_asset_etf_dual_momentum_distributions.csv`.
- Events use `symbol,ex_date,amount_per_unit` and are included when `period_start < ex_date <= period_end`.
- The backtest adds `amount_per_unit / period_start_price` to the held asset's period return.
- The current event file was sourced from Yahoo Finance chart dividend events for the strategy universe and safe-asset fallback. Events were available for `EMBASSY`, `INDIGRID`, `IRBINVIT`, `NXST`, and `LIQUIDBEES`; the other ETF symbols had no Yahoo dividend events in the fetched timeline.
