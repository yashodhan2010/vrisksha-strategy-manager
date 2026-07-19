from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app import config


def load_strategy_profile(profile_path: str | Path = config.STRATEGY_PROFILE_PATH) -> dict[str, Any]:
    path = Path(profile_path)
    if not path.exists():
        raise FileNotFoundError(f"Strategy profile not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "strategy_id" not in payload or "slug" not in payload or "name" not in payload:
        raise ValueError(f"Strategy profile is missing strategy_id, slug, or name: {path}")
    return payload


def apply_strategy_profile(profile_path: str | Path = config.STRATEGY_PROFILE_PATH) -> dict[str, Any]:
    profile = load_strategy_profile(profile_path)
    package = profile.get("package", {})
    optimization = profile.get("optimization", {})
    backtest = profile.get("backtest", {})

    config.STRATEGY_PROFILE_PATH = str(profile_path)
    config.STRATEGY_PACKAGE_ID = str(profile["strategy_id"])
    config.STRATEGY_PACKAGE_SLUG = str(profile["slug"])
    config.STRATEGY_PACKAGE_NAME = str(profile["name"])
    config.STRATEGY_PACKAGE_SHORT_DESCRIPTION = str(profile.get("short_description") or "")
    config.STRATEGY_PACKAGE_CATEGORY_LABELS = ",".join(profile.get("category_labels") or [])
    config.STRATEGY_PACKAGE_UNIVERSE = str(profile.get("universe") or config.STRATEGY_PACKAGE_UNIVERSE)
    config.STRATEGY_PACKAGE_BENCHMARK = str(profile.get("benchmark") or config.STRATEGY_PACKAGE_BENCHMARK)
    config.STRATEGY_PACKAGE_RA_ENTITY = str(profile.get("ra_entity") or config.STRATEGY_PACKAGE_RA_ENTITY)
    config.STRATEGY_PACKAGE_SEBI_REGISTRATION_NUMBER = str(
        profile.get("sebi_registration_number") or config.STRATEGY_PACKAGE_SEBI_REGISTRATION_NUMBER
    )
    config.STRATEGY_PACKAGE_MIN_CAPITAL_GUIDANCE = int(
        profile.get("min_capital_guidance") or config.STRATEGY_PACKAGE_MIN_CAPITAL_GUIDANCE
    )
    config.STRATEGY_PACKAGE_OUTPUT_DIR = str(package.get("output_dir") or config.STRATEGY_PACKAGE_OUTPUT_DIR)
    config.STRATEGY_PACKAGE_VERSION = str(package.get("version") or config.STRATEGY_PACKAGE_VERSION)
    config.OPTIMIZATION_RESULTS_PATH = str(optimization.get("results_path") or config.OPTIMIZATION_RESULTS_PATH)
    config.FINALIZED_STRATEGY_CONFIG_PATH = str(
        optimization.get("finalized_config_path") or config.FINALIZED_STRATEGY_CONFIG_PATH
    )
    if backtest.get("benchmark_symbol"):
        config.DEFAULT_BENCHMARK_SYMBOL = str(backtest["benchmark_symbol"])
    return profile
