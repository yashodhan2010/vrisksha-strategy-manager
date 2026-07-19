# Strategy Profiles

Each finalized strategy gets one folder here. The folder should contain:

- `strategy_profile.json`: metadata, optimization paths, finalized config path, and package output path.
- `methodology.md`: public-safe methodology for the Vriksha public strategy page.
- `methodology_internal.md`: full internal research methodology, not for public rendering.
- `experiments/`: the strategy-specific production optimizer, notebooks, and research scripts.

To add another strategy, copy `strategies/_template/` into `strategies/<strategy-slug>/` and update the metadata, document text, `optimization.engine_path`, `optimization.search_space`, finalized config path, and package output path.

The strategy profile and methodology files do not contain website, payment, login, subscription, or access-control logic.
