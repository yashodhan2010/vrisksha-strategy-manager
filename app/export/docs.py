from __future__ import annotations

from typing import Any


def public_methodology_md(manifest: dict[str, Any]) -> str:
    return f"""# {manifest["name"]} Methodology

## Summary

{manifest["short_description"]}

## Universe

The strategy uses the locally maintained {manifest["universe"]} universe. The runtime universe is synced from the reference data maintained by the research project before backtests and model-portfolio generation.

## Strategy Design

The model ranks stocks using a rules-based blend of price trend, quality of price movement, and portfolio risk controls. The exact scoring formula, optimized parameters, thresholds, buffers, and tie-break rules are proprietary and are not part of the public methodology.

## Allocation

The strategy targets {manifest["target_holdings"]} holdings, subject to diversification and risk controls. Position weights are model-driven and may include residual cash or a cash-equivalent allocation when suitable opportunities are limited or portfolio constraints apply.

## Rebalance

The strategy is rebalanced {manifest["rebalance_frequency"]}. Backtest execution uses stored adjusted-close prices where available, falling back to close prices.

## Cash Allocation Rules

Residual allocation from stock caps, sector caps, or insufficient qualifying stocks is assigned to the configured safe asset/cash proxy.

## Proprietary Details

Exact ranking weights, lookback windows, buffers, thresholds, and implementation rules are retained internally by the research project and are not exposed on the public strategy page.
"""


def internal_methodology_md(manifest: dict[str, Any], summary: dict[str, Any]) -> str:
    return f"""# {manifest["name"]} Internal Methodology

This internal methodology is intended for Vriksha admin/research review only. It may contain proprietary strategy implementation details and should not be rendered on the public strategy page.

## Summary

{manifest["short_description"]}

## Implementation Notes

The finalized strategy configuration used for the exported backtest is captured in the research database run payload and the strategy-specific finalized config file. Treat exact scoring methods, allocation settings, buffers, thresholds, and rebalance mechanics as private strategy intellectual property.

## Backtest Configuration Snapshot

- Ranking method: `{summary.get("strategy_ranking_method", "")}`
- Allocation mode: `{summary.get("strategy_allocation_mode", "")}`
- Rebalance frequency: `{manifest["rebalance_frequency"]}`
- Target holdings: `{manifest["target_holdings"]}`
- Universe: `{manifest["universe"]}`
- Benchmark: `{manifest["benchmark"]}`
"""


def disclosures_md(manifest: dict[str, Any]) -> str:
    return f"""# {manifest["name"]} Risk Disclosures

This package is a research and model-portfolio export for use by Vriksha. It does not provide user account, payment, subscription, or website access-control logic.

Backtested performance is hypothetical and does not guarantee future returns. Equity investments are subject to market risk, liquidity risk, concentration risk, execution risk, and tracking error. Actual investor returns may differ due to transaction costs, taxes, slippage, execution timing, corporate actions, data quality, and portfolio-size constraints.

The model portfolio is generated for a SEBI RA-backed strategy package. Suitability, investor communication, legal disclosures, and access control are handled outside this research project.
"""


def import_notes_md(manifest: dict[str, Any], warnings: list[str]) -> str:
    warning_text = "\n".join(f"- {warning}" for warning in warnings) if warnings else "- None recorded."
    return f"""# Vriksha Import Notes

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

{warning_text}
"""
