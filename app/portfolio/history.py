from __future__ import annotations


class PortfolioHistoryService:
    def summarize_stock_history(self, symbol: str) -> dict:
        """Summarize holding duration, entry periods, contribution, weights, and ranks for a stock."""
        raise NotImplementedError("Stock-level portfolio history will be implemented in a later sprint.")

    def list_currently_held_symbols(self) -> list[str]:
        """Return symbols marked as currently held in stock history."""
        raise NotImplementedError("Stock history queries will be implemented in a later sprint.")

