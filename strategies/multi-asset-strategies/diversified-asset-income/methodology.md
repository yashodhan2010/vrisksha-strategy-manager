# Diversified Asset Income

Diversified Asset Income is a fixed-weight multi-asset model portfolio. It allocates equally across five sleeves:

- 20% InvIT
- 20% REIT
- 20% Gold
- 20% Debt
- 20% Nifty 50

The portfolio is rebalanced on the first trading day of each calendar quarter. There is no parameter optimization, ranking model, or tactical asset rotation. Historical performance is calculated from stored market prices for the configured instruments.

Quarterly distribution is a strategy-level operating policy. The historical backtest includes dividend, interest, REIT, and InvIT distributions when events are recorded in `data/reference/diversified_asset_income_distributions.csv`. Each event is treated as cash earned during the rebalance period and included in total return before the next quarterly rebalance.

Historical runs generate a summary CSV and a detailed quarterly net-returns CSV. The detailed file includes gross returns, dividend/distribution cash, distribution return, estimated rebalance costs, net returns, and sleeve-level contribution fields.
