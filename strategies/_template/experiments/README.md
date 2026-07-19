# Strategy Experiments

Put this strategy's optimizer, notebooks, and strategy-specific research scripts here.

For the standard pipeline, `strategy_profile.json` should point `optimization.engine_path` to an optimizer file that exposes:

```python
def run_optuna_grid(years: int, objective_metric: str, n_trials: int | None, seed: int):
    ...
```

The command below will run that optimizer, write the results CSV, and promote the best row into the finalized config:

```bash
python -m app.main refresh-finalized-parameters --strategy-profile strategies/<strategy-slug>/strategy_profile.json
```

