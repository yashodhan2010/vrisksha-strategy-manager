# Dual Momentum Experiments

This folder contains the production optimizer used by:

```bash
python -m app.main refresh-finalized-parameters --strategy-profile strategies/dual-momentum/strategy_profile.json
```

The optimization grid lives in `strategies/dual-momentum/strategy_profile.json` under `optimization.search_space`.
The optimizer engine lives in `optimizer.py` and is specific to Dual Momentum research logic.

## Rebalance Day Sweep

To test which target trading days work best with the finalized Dual Momentum parameters:

```bash
python strategies/dual-momentum/experiments/rebalance_day_sweep.py
```

By default, the script applies `data/output/finalized/dual_momentum_best_config.json`, uses that config's
`BACKTEST_REBALANCES_PER_MONTH`, sweeps day-of-month combinations from 1 to 30, and writes a CSV plus charts under:

```text
data/output/dual-momentum/rebalance-day-sweep/<timestamp>/
```

For a one-rebalance sanity check:

```bash
python strategies/dual-momentum/experiments/rebalance_day_sweep.py --rebalances-per-month 1
```
