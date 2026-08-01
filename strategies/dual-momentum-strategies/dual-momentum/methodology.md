# Dual Momentum Methodology

## Summary

Dual Momentum is a rules-based Nifty 500 model portfolio that seeks to participate in stronger equity trends while applying portfolio-level risk and diversification controls.

## Universe

The strategy uses the locally maintained Nifty 500 universe. The universe is refreshed from the research project's reference data before backtests and model-portfolio generation.

## Strategy Design

The model evaluates stocks using a proprietary blend of price trend, consistency of movement, and risk controls. Securities that do not meet the model's quality and trend requirements may be excluded before portfolio construction.

Exact ranking formulas, lookback windows, optimized weights, thresholds, buffers, and tie-break rules are private strategy parameters and are not exposed in the public methodology.

## Portfolio Construction

The strategy targets a diversified basket of holdings, subject to model constraints such as position sizing, sector exposure, and residual cash or cash-equivalent allocation rules. The exported model portfolio contains the current target weights for subscriber use.

## Rebalance

The strategy is designed for periodic rebalancing. At each rebalance, the model refreshes rankings, reviews existing holdings, applies its retention and risk controls, and produces the updated target portfolio.

## Cash Allocation Rules

When the model has fewer qualifying opportunities or portfolio constraints prevent full equity deployment, the residual allocation may remain in cash or a cash-equivalent proxy.

## Public Disclosure Boundary

This public methodology intentionally omits exact implementation parameters. Vriksha should not render internal methodology files, finalized configuration files, experiment outputs, or exact scoring parameters on public pages.
