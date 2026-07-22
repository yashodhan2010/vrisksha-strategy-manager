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
  _template/
    strategy_profile.json
    methodology.md
    methodology_internal.md
    experiments/
  dual-momentum/
    strategy_profile.json
    methodology.md
    methodology_internal.md
    experiments/
      optimizer.py
  conservative-dual-momentum/
    strategy_profile.json
    methodology.md
    methodology_internal.md
    experiments/
      optimizer.py

experiments/
  Scratch research notebooks/scripts and archived raw outputs. Production optimizers should live under strategies/<slug>/experiments/.

data/output/
  finalized/      Final selected strategy config JSON files.
  packages/       Vriksha import packages.
```

## Finalized Strategy Lifecycle

Every strategy follows the same lifecycle:

1. Run the strategy-local experiments/Optuna optimizer and write the results CSV.
2. Promote the best experiment row into a finalized strategy config, or run `refresh-finalized-parameters` to do both together for strategies using the average-rank/buffer optimizer.
3. Run the finalized backtest and export the full Vriksha strategy package.
4. Use the lightweight model-portfolio update command for routine subscriber updates.

Public website pages should render `methodology.md` only. `methodology_internal.md`, finalized config JSON, experiment outputs, and exact parameters are private/internal artifacts.

## Dual Momentum Pipeline

```bash
python -m app.main finalize-strategy-config --strategy-profile strategies/dual-momentum/strategy_profile.json
```

Or rerun the average-rank/buffer optimization and promote the new top-CAGR row in one command:

```bash
python -m app.main refresh-finalized-parameters --strategy-profile strategies/dual-momentum/strategy_profile.json
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

The full package is written to:

```text
data/output/packages/dual-momentum/strategy-package/
```

It includes public-safe `methodology.md` plus internal-only `methodology_internal.md`. Vriksha should use the `public_methodology_file` and `internal_methodology_file` fields in `manifest.json` to keep public and internal content separate.

## Live / Paper Model Portfolio

The scheduled model-portfolio workflow also applies the strategy profile and finalized config before generating holdings:

```bash
python -m app.main monthly-run --strategy-profile strategies/dual-momentum/strategy_profile.json
```

For Vriksha subscriber-page updates, use the command that refreshes only recent history, runs the model portfolio, and exports the update files:

```bash
python -m app.main build-model-portfolio-update --selenium-token --strategy-profile strategies/dual-momentum/strategy_profile.json
```

The update package is written to:

```text
data/output/packages/dual-momentum/model-portfolio-update/
```

Daily automation refreshes market data and runs `monthly-run` only on configured rebalance dates:

```bash
python -m app.main auto-daily-run --selenium-token --strategy-profile strategies/dual-momentum/strategy_profile.json
```

If `data/output/finalized/dual_momentum_best_config.json` does not exist, run `finalize-strategy-config` first. This prevents scheduled rebalances from silently using `.env` strategy knobs.

## Conservative Dual Momentum Pipeline

Conservative Dual Momentum uses the same strategy family but optimizes for net return-to-drawdown / net Calmar rather than pure CAGR. Its optimizer estimates delivery transaction charges and capital-gains tax drag per trial, then ranks on the net risk-adjusted result. Its profile owns the objective, search grid, optimizer path, and output paths:

```bash
python -m app.main refresh-finalized-parameters --strategy-profile strategies/conservative-dual-momentum/strategy_profile.json
```

```bash
python -m app.main build-finalized-package --strategy-profile strategies/conservative-dual-momentum/strategy_profile.json --start-date 2016-05-29 --end-date 2026-05-29 --initial-capital 1000000 --selenium-token
```

## Adding Another Strategy

1. Copy `strategies/_template/` to `strategies/<strategy-slug>/`.
2. Update `strategy_profile.json` identity fields, public metadata, RA details, universe, benchmark, and minimum capital guidance.
3. Write `methodology.md` as a public-safe website summary.
4. Write `methodology_internal.md` with exact research logic and parameters for internal review only.
5. Put that strategy's production optimizer under `strategies/<strategy-slug>/experiments/optimizer.py`.
6. Point `optimization.engine_path` at that optimizer file.
7. Put the tunable optimization grid in `optimization.search_space`.
8. Point `optimization.results_path` at that strategy's experiment/Optuna output.
9. Point `optimization.finalized_config_path` at a strategy-specific JSON file under `data/output/finalized/`.
10. Point `package.output_dir` at a strategy-specific package folder under `data/output/packages/`.
11. Add or swap strategy logic under `app/strategy/` only if the new strategy's ranking/allocation rules differ from the current shared implementation.
12. Run `refresh-finalized-parameters` when the strategy has a tracked optimizer, or `finalize-strategy-config` when an external experiment CSV has already been produced.
13. Run `build-finalized-package` with the new profile for the full public/import package.
14. Run `build-model-portfolio-update` with the new profile for routine latest portfolio exports.

Each generated package remains a portable artifact for Vriksha import.
