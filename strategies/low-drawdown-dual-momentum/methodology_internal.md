# Low Drawdown Dual Momentum Strategy Details

This strategy reuses the dual-momentum signal, ranking, allocation, and implementation-cost model used by the Conservative Dual Momentum optimizer.

## Finalization Rule

The target trial is selected using:

```text
eligible if gross 10-year CAGR >= 20%
objective score = -absolute_max_drawdown for eligible rows
objective score = -1e9 for ineligible rows
```

The highest objective score therefore selects the lowest absolute drawdown among parameter sets whose 10-year CAGR clears the 20% hurdle.

The current selected trial from the 10-year grid is trial `3236`.

## Selected Parameters

```text
top_n: 35
rebalances_per_month: 2
sector_cap_pct: 15
high_52w_threshold: 0.85
momentum_weight: 0.50
beta_weight: 0.25
volatility_weight: 0.25
buffer_pct: 80
max_stock_weight_pct: 2.5
```

## Selected Trial Metrics

```text
gross CAGR: 20.14%
net CAGR after estimated implementation drag: 20.00%
max drawdown: -16.37%
gross Calmar: 1.2301
net Calmar: 1.2219
estimated implementation drag on Rs 10L backtest: Rs 69,826
```

See `strategies/conservative-dual-momentum/methodology_internal.md` for the shared signal construction, ranking, allocation, and cost/tax estimation details.
