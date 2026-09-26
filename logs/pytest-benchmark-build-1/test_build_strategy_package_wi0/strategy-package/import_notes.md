# Vriksha Import Notes

## Live Performance Files

This package also includes `live_manifest.json`, `live_metrics.json`, `live_nav.csv`,
`live_benchmark.csv`, and `live_drawdowns.csv`. Read `manifest.json.live_performance`
for availability and dates. Missing live history is never replaced with backtest data.
Returns are decimals; the live equity curve starts at 1. Join it to historical daily
data at live inception with matching date coverage, scaling to the historical curve
and excluding overlapping backtest returns. Recompute composite metrics and monthly
returns from that joined series. Live metrics and drawdowns cover only the live period.
The live manifest retains the internal tracker provenance, calculation method, and
data-quality warnings; availability is not publication approval.

## Data Source Used

Historical prices are loaded from the local SQLite `market_prices` table populated by the configured market-data ingestion flow.

## Survivorship Bias Handling

The export uses the locally maintained universe available to this project. Point-in-time constituent history is not guaranteed unless the reference universe file is maintained with effective dates.

## Corporate Action Adjustment Handling

The backtest and export use `adjusted_close` where available, falling back to `close` when adjusted prices are missing.

## Transaction Cost Assumption

No explicit transaction cost is deducted unless already included in the completed backtest run.

## Slippage Assumption

No explicit slippage is deducted unless already included in the completed backtest run.

## Tax Assumption

No tax impact is modeled in this package.

## Rebalance Execution Assumption

Rebalances are assumed to execute on the stored reference prices used by the backtest. Weights are exported as target model-portfolio weights.

## Known Limitations

The package does not contain website-specific logic, payments, user login, subscriptions, or subscriber access control. Minimum capital guidance and SEBI registration number may be finalized outside the beta package.

Public pages should render only the manifest fields and `methodology.md`. `methodology_internal.md`, finalized configs, experiment outputs, exact ranking settings, thresholds, and buffers are internal research artifacts and should not be exposed to unsubscribed users.

## Manual Overrides Applied

None recorded by the exporter.

## Backtest Warnings

- None recorded.
