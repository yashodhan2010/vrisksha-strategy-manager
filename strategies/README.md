# Strategy Profiles

Each finalized strategy gets one folder here. The folder should contain a `strategy_profile.json` that tells the shared pipeline where to find optimization results, where to write the finalized config, and where to export the Vriksha package.

To add another strategy, copy `dual-momentum/strategy_profile.json` into a new slug folder and update the metadata, optimization paths, and package output path.

The strategy profile does not contain website, payment, login, subscription, or access-control logic.
