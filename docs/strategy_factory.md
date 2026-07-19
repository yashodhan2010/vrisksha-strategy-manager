# Strategy Factory Workflow

This repository is organized as a research and packaging factory for model-portfolio strategies. It does not own Vriksha website accounts, payments, subscriptions, or access control.

The repository/folder should use the generic name `vrisksha-strategy-manager`. Strategy-specific folders, such as `strategies/dual-momentum`, are intentionally named by strategy slug.

## Folder Responsibilities

```text
app/
  backtest/       Shared backtest engine and result persistence.
  data/           Universe, historical prices, and market-data ingestion.
  export/         Vriksha strategy-package builder and validators.
  optimization/   Promotion of experiment/Optuna results into finalized configs.
  strategy/       Current strategy logic: ranking, allocation, buffer selection, rebalance.
  storage/        SQLite schema and repositories.

strategies/
  dual-momentum/
    strategy_profile.json

experiments/
  Research notebooks/scripts and raw experiment outputs.

data/output/
  finalized/      Final selected strategy config JSON files.
  packages/       Vriksha import packages.
```

## Dual Momentum Pipeline

```bash
python -m app.main finalize-strategy-config --strategy-profile strategies/dual-momentum/strategy_profile.json
```

```bash
python -m app.main run-finalized-backtest --strategy-profile strategies/dual-momentum/strategy_profile.json --start-date 2016-01-01 --end-date 2025-12-31 --initial-capital 1000000 --force
```

```bash
python -m app.main export-strategy-package --strategy-profile strategies/dual-momentum/strategy_profile.json
```

Or run the complete chain:

```bash
python -m app.main build-finalized-package --strategy-profile strategies/dual-momentum/strategy_profile.json --start-date 2016-01-01 --end-date 2025-12-31 --initial-capital 1000000
```

`build-finalized-package` syncs the universe and checks local price coverage before the backtest. If required history is missing or stale, it fetches Kite history from the earliest missing date through the requested end date. Use `--selenium-token` to let the command refresh today's Kite token through the configured Selenium auto-login flow:

```bash
python -m app.main build-finalized-package --strategy-profile strategies/dual-momentum/strategy_profile.json --start-date 2016-01-01 --end-date 2025-12-31 --initial-capital 1000000 --selenium-token
```

Use `--no-fetch-history` only when intentionally running against already stored local data.

## Live / Paper Model Portfolio

The scheduled model-portfolio workflow also applies the strategy profile and finalized config before generating holdings:

```bash
python -m app.main monthly-run --strategy-profile strategies/dual-momentum/strategy_profile.json
```

Daily automation refreshes market data and runs `monthly-run` only on configured rebalance dates:

```bash
python -m app.main auto-daily-run --selenium-token --strategy-profile strategies/dual-momentum/strategy_profile.json
```

If `data/output/finalized/dual_momentum_best_config.json` does not exist, run `finalize-strategy-config` first. This prevents scheduled rebalances from silently using `.env` strategy knobs.

## Adding Another Strategy

1. Create `strategies/<strategy-slug>/strategy_profile.json`.
2. Point `optimization.results_path` at that strategy's experiment/Optuna output.
3. Point `optimization.finalized_config_path` at a strategy-specific JSON file under `data/output/finalized/`.
4. Point `package.output_dir` at a strategy-specific package folder under `data/output/packages/`.
5. Add or swap strategy logic under `app/strategy/` only if the new strategy's ranking/allocation rules differ from Dual Momentum.
6. Run `build-finalized-package` with the new profile.

Each generated package remains a portable artifact for Vriksha import.
