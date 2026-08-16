# Diversified Asset Income - Internal Methodology

## Objective

Create a simple fixed-ratio income-oriented multi-asset portfolio that diversifies across real assets, defensive assets, and equity beta.

## Asset Sleeves

| Sleeve | Symbols | Target weight |
|---|---:|---:|
| Equity | NIFTYBEES | 20% |
| Debt | GILT5YBEES, GSEC10IETF, LTGILTBEES | 20% |
| InvIT | INDIGRID, PGINVIT, IRBINVIT | 20% |
| REIT | KRT, EMBASSY, MINDSPACE, BIRET, NXST | 20% |
| Gold | GOLDBEES | 20% |

Symbols and instrument-level weights are maintained in `data/reference/diversified_asset_income_universe.json` and referenced from the strategy profile. They can be replaced if a cleaner debt, REIT, or InvIT proxy is preferred.

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

The current event file is sourced from Yahoo Finance chart dividend events for the configured sleeve symbols. Events are available for `INDIGRID`, `PGINVIT`, `IRBINVIT`, `EMBASSY`, `MINDSPACE`, `BIRET`, and `NXST`; Yahoo returned no dividend events for the ETF sleeves or `KRT` in the fetched timeline.

## Experiment Output

Each fixed-allocation historical run writes:

- `data/output/diversified-asset-income/fixed_allocation_summary.csv`
- `data/output/diversified-asset-income/fixed_allocation_net_returns_detail.csv`

The detailed file records each quarterly period, gross return, dividend/distribution cash, distribution return, estimated rebalance transaction costs, net return, turnover, and sleeve-level price/distribution/total return contribution fields.
