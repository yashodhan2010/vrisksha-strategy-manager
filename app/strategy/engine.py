from __future__ import annotations

from app.strategy.models import AllocationResult


class StrategyEngine:
    """Future strategy engine.

    MVP methodology to implement later:
    Universe: local Nifty 500 Excel / JSON file.
    Signals: 3M, 6M, 12M returns.
    Filter: stock price must be within 20% of 52-week high.
    Risk inputs: beta and realized volatility.
    Score: configured ranking method, defaulting to combined momentum/beta/volatility rank.
    Ranking: descending score.
    Selection: every qualifying stock.
    Allocation: equal weight with maximum 5% per stock.
    Residual: LIQUIDBEES.
    Rebalance: monthly.
    Cooldown: every sixth reshuffle, compare portfolio NAV with configured EMA; if below EMA,
    use LIQUIDBEES for one month, then calculate a fresh portfolio next month.
    """

    def generate_rankings(self) -> None:
        raise NotImplementedError("Strategy ranking calculations will be implemented in a later sprint.")

    def generate_target_portfolio(self) -> AllocationResult:
        raise NotImplementedError("Target portfolio generation will be implemented in a later sprint.")
