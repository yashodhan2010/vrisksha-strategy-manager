# Strategy Harness

This document is the operating contract for adding and maintaining strategies in this repository. Follow it strictly. The purpose of the project is to research strategies, test parameter sets, finalize one reproducible configuration per strategy, and export model portfolios/packages for Vriksha. This repository must not implement Vriksha website accounts, payments, subscriptions, or access control.

## Non-Negotiables

1. Every finalized strategy has one folder under `strategies/<slug>/`.
2. The folder name and `strategy_profile.json.slug` must match exactly.
3. The slug must be lowercase kebab-case.
4. Every strategy must be listed in `strategies/registry.json`.
5. Strategy knobs live in `strategy_profile.json` and finalized config JSON, not `.env`.
6. Public methodology must stay public-safe and must not reveal exact scoring parameters or search grids.
7. Internal methodology must explain the exact objective, selected trial, selected parameters, and any special constraints.
8. Output paths must be strategy-specific.
9. Run `python -m app.main validate-strategies` before committing strategy work.
10. Website, payment, login, subscription, and access-control logic are out of scope.

## Required Folder Shape

```text
strategies/<strategy-slug>/
  strategy_profile.json
  methodology.md
  methodology_internal.md
  experiments/
    optimizer.py
```

Generated artifacts must follow this shape:

```text
data/output/<strategy-slug>/
  <strategy-specific-trials>.csv
  <strategy-specific-analysis>.xlsx

data/output/finalized/
  <strategy_slug>_best_config.json

data/output/packages/<strategy-slug>/
  strategy-package/
  model-portfolio-update/
```

## Lifecycle

1. Define or refresh the universe.
2. Create the strategy folder from `strategies/_template/`.
3. Fill out `strategy_profile.json` identity, public metadata, objective, rank column, search space, optimizer path, results path, finalized config path, and package output path.
4. Write public-safe `methodology.md`.
5. Write exact internal `methodology_internal.md`.
6. Run optimization:

```bash
python -m app.main refresh-finalized-parameters --strategy-profile strategies/<strategy-slug>/strategy_profile.json
```

7. Validate the registry:

```bash
python -m app.main validate-strategies
```

8. Build the full package when public metrics/charts need refreshing:

```bash
python -m app.main build-finalized-package --strategy-profile strategies/<strategy-slug>/strategy_profile.json --start-date YYYY-MM-DD --end-date YYYY-MM-DD --initial-capital 1000000 --no-fetch-history
```

9. Build the routine subscriber model-portfolio update:

```bash
python -m app.main build-model-portfolio-update --strategy-profile strategies/<strategy-slug>/strategy_profile.json --selenium-token
```

## Profile Requirements

Every profile must include:

```json
{
  "strategy_id": "stable_unique_id",
  "slug": "strategy-slug",
  "name": "Strategy Name",
  "short_description": "Public-safe one-line description.",
  "category_labels": ["Momentum", "Equity", "Model Portfolio"],
  "ra_entity": "Prathamesh Gupta",
  "sebi_registration_number": "",
  "universe": "NIFTY 500",
  "benchmark": "NIFTY 500 TRI",
  "documents": {
    "public_methodology_path": "strategies/strategy-slug/methodology.md",
    "internal_methodology_path": "strategies/strategy-slug/methodology_internal.md"
  },
  "optimization": {
    "engine_path": "strategies/strategy-slug/experiments/optimizer.py",
    "results_path": "data/output/strategy-slug/trials.csv",
    "finalized_config_path": "data/output/finalized/strategy_slug_best_config.json",
    "objective": "metric_to_maximize",
    "rank_column": "rank_by_metric_to_maximize",
    "search_space": {}
  },
  "package": {
    "version": "1.0.0",
    "output_dir": "data/output/packages/strategy-slug/strategy-package"
  }
}
```

## Objective Discipline

The `optimization.objective` and `optimization.rank_column` are authoritative. Documentation, finalized config, package pipeline, and model-portfolio updates must all align with the profile.

Current strategies:

| Strategy | Objective | Meaning |
|---|---|---|
| Dual Momentum | `cagr` | Highest gross CAGR |
| Conservative Dual Momentum | `net_return_to_drawdown` | Highest net Calmar after estimated implementation drag |
| Low Drawdown Dual Momentum | `lowest_drawdown_cagr_gt_20_score` | Lowest drawdown among rows with 10-year CAGR >= 20% |

## Validation Gate

Before pushing, run:

```bash
python -m app.main validate-strategies
pytest -q
```

Validation checks:

- Registry exists and lists profiles.
- Profile JSON is valid.
- Slugs are kebab-case and match folder names.
- Strategy ids and slugs are unique.
- Methodology files exist.
- Optimizer path exists.
- Search space is non-empty.
- Results CSV has the configured objective and rank columns when present.
- Finalized config selection matches profile objective and rank column when present.
- Package output path is strategy-specific.
- Profile does not contain website/payment/login/subscription/access-control terms.
