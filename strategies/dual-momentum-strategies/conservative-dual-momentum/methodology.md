# Conservative Dual Momentum Methodology

## Summary

Bamboo Trunk is rules-based momentum model portfolio that seeks to extract more persistent and systematic price momentum signals while applying greater portfolio-level risk and diversification controls to mitigate crash risk. 

## Universe

Nifty 500

## Strategy Design

Top 60 equal weight stocks ranked using a proprietary model combining price trend, price momentum, and risk controls. The greater number of stocks helps harvest momentum more systematically and smoothly, while diversifying individual security-level risks. It rebalances bi-weekly to optimally harvest price momentum.

## Portfolio Construction

The model portfolio includes a diversified basket of 60 equal weight holdings, subject to model constraints such as position sizing, sector exposure, and cash allocation rules. If no stocks are filtered, the portfolio sits in cash. Irregular rebalances may be triggered during extreme events.

## Rebalance

Bi-weekly

## Cash Allocation Rules

When the model has fewer qualifying opportunities or portfolio constraints prevent full equity deployment, the residual allocation may remain in cash or a cash-equivalent proxy.
