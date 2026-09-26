
from pathlib import Path

DATABASE_PATH = None
UNIVERSE_JSON_PATH = None
OUTPUT_DIR = None

def search_space(momentum_weight_grid=None):
    return {"top_n": [1]}

def run_optuna_grid(years, objective_metric, n_trials, seed):
    space = search_space()
    assert space["top_n"] == [25]
    assert space["buffer_pct"] == [60]
    import pandas as pd
    return object(), pd.DataFrame([
        {
            "trial": 1,
            "rebalances_per_month": 1,
            "top_n": 25,
            "sector_cap_pct": 0,
            "high_cutoff_pct": 20,
            "momentum_weight": 0.6,
            "beta_weight": 0.2,
            "volatility_weight": 0.2,
            "buffer_pct": 60,
            "cagr": 0.18,
        }
    ]), {}
