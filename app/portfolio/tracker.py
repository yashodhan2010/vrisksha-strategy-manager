from __future__ import annotations


class PortfolioTracker:
    def get_current_holdings(self) -> list[dict]:
        """Return currently held stocks once portfolio snapshots are populated."""
        raise NotImplementedError("Portfolio tracking will be implemented in a later sprint.")

    def get_monthly_entries(self) -> list[dict]:
        """Return stocks that entered the portfolio in the selected month."""
        raise NotImplementedError("Portfolio tracking will be implemented in a later sprint.")

    def get_monthly_exits(self) -> list[dict]:
        """Return stocks that exited the portfolio in the selected month."""
        raise NotImplementedError("Portfolio tracking will be implemented in a later sprint.")

