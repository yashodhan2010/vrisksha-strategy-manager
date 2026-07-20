# Strategy-Agnostic Experiments

Use this folder only for research that is shared across strategies or not yet assigned to a strategy.

Strategy-specific experiments should live under:

```text
strategies/<strategy-slug>/experiments/
```

Examples:

```text
strategies/dual-momentum/experiments/
strategies/conservative-dual-momentum/experiments/
```

Once an experiment becomes part of a production strategy pipeline, move its optimizer into that strategy folder and point `strategy_profile.json` to it with `optimization.engine_path`.

