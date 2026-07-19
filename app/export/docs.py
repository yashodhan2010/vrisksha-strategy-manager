from __future__ import annotations

from typing import Any


def methodology_md(manifest: dict[str, Any], summary: dict[str, Any]) -> str:
    return f"""# {manifest["name"]} Methodology

## Summary

{manifest["short_description"]}

## Universe

The strategy uses the locally maintained {manifest["universe"]} universe. The runtime universe is synced from the reference workbook before backtests and live model-portfolio generation.

## Signal Design

Stocks are evaluated on trailing 3-month, 6-month, and 12-month momentum, low beta, low volatility, and proximity to their 52-week high. The active ranking method is `{summary.get("strategy_ranking_method", "")}`.

## Allocation

The allocation mode is `{summary.get("strategy_allocation_mode", "")}` with a target of {manifest["target_holdings"]} holdings. Existing holdings are retained while they remain within the configured holding buffer of {manifest.get("holding_buffer_pct", 0)}% beyond the target selection rank, then open slots are filled from the highest-ranked candidates. Per-stock, sector, and safe-asset/cash residual rules follow the strategy configuration captured in the backtest run.

## Rebalance

The strategy is rebalanced {manifest["rebalance_frequency"]}. Backtest execution uses stored adjusted-close prices where available, falling back to close prices.

## Cash Allocation Rules

Residual allocation from stock caps, sector caps, or insufficient qualifying stocks is assigned to the configured safe asset/cash proxy.
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

## Manual Overrides Applied

None recorded by the exporter.

## Backtest Warnings

{warning_text}
"""
