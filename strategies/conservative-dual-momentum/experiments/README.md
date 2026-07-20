# Conservative Dual Momentum Experiments

This folder contains the production optimizer used by:

```bash
python -m app.main refresh-finalized-parameters --strategy-profile strategies/conservative-dual-momentum/strategy_profile.json
```

The optimization grid lives in `strategies/conservative-dual-momentum/strategy_profile.json` under `optimization.search_space`.
The optimizer engine lives in `optimizer.py` and is specific to Conservative Dual Momentum research logic.
