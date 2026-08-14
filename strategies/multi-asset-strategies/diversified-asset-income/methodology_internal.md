# Diversified Asset Income - Internal Methodology

## Objective

Create a simple fixed-ratio income-oriented multi-asset portfolio that diversifies across real assets, defensive assets, and equity beta.

## Asset Sleeves

| Sleeve | Default symbol | Target weight |
|---|---:|---:|
| InvIT | PGINVIT | 20% |
| REIT | EMBASSY | 20% |
| Gold | GOLDBEES | 20% |
| Debt | LIQUIDBEES | 20% |
| Nifty 50 | NIFTYBEES | 20% |

Symbols are profile-level configuration and can be replaced if a cleaner debt, REIT, or InvIT proxy is preferred.

## Rebalance

The portfolio rebalances on the first trading day of January, April, July, and October. The scheduler represents this as:

```json
{
  "type": "quarterly_first_trading_day",
  "quarter_start_months": [1, 4, 7, 10],
  "timezone": "Asia/Kolkata"
}
```

## Optimization

No parameter optimization is used. The allocation is fixed at 20% per sleeve.

## Distribution

The target operating cadence is quarterly distribution. The backtest reads dividend, interest, REIT, and InvIT events from:

```text
data/reference/diversified_asset_income_distributions.csv
```

Expected columns:

- `symbol`
- `ex_date`
- `amount_per_unit`

Optional descriptive columns such as `distribution_type` and `notes` are allowed. Events are included when `period_start < ex_date <= period_end`. The engine adds `amount_per_unit / period_start_price` to that sleeve's period return and carries the resulting cash into ending NAV before the next rebalance.

The current event file is sourced from Yahoo Finance chart dividend events for the configured sleeve symbols. Events are available for `PGINVIT`, `EMBASSY`, and `LIQUIDBEES`; Yahoo returned no dividend events for `GOLDBEES` or `NIFTYBEES` in the fetched timeline.

## Experiment Output

Each fixed-allocation historical run writes:

- `data/output/diversified-asset-income/fixed_allocation_summary.csv`
- `data/output/diversified-asset-income/fixed_allocation_net_returns_detail.csv`

The detailed file records each quarterly period, gross return, dividend/distribution cash, distribution return, estimated rebalance transaction costs, net return, turnover, and sleeve-level price/distribution/total return contribution fields.
