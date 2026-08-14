# Multi Asset ETF Dual Momentum

This strategy selects a diversified basket from the local multi-asset ETF universe using rules-based price momentum.

The model ranks eligible ETFs by the average of their three, six, and twelve month returns, skipping the most recent trading month by default. It can require positive average momentum, a twelve month absolute return hurdle, proximity to the 52-week high, and price above the 200-day EMA. The current research grid tests four to eight equal-weight holdings with no holding buffer and monthly rebalancing.

If no ETF qualifies, residual capital is allocated to the configured safe asset/cash sleeve.

Backtests include declared dividends and distributions where event data is available for the held asset during the holding period.
