from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app import config
from app.backtest.distributions import distribution_path_from_profile


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
    documents = profile.get("documents", {})
    data = profile.get("data", {})
    allocation = profile.get("allocation", {})
    parameters = profile.get("parameters", {})
    schedule = profile.get("rebalance_schedule", {})
    distribution_events_path = distribution_path_from_profile(profile)

    config.STRATEGY_PROFILE_PATH = str(profile_path)
    config.STRATEGY_CATALOGUE_METADATA = profile.get("catalogue") or {}
    config.STRATEGY_PACKAGE_ID = str(profile["strategy_id"])
    config.STRATEGY_PACKAGE_SLUG = str(profile["slug"])
    config.STRATEGY_PACKAGE_INTERNAL_NAME = str(profile["name"])
    config.STRATEGY_PACKAGE_PUBLIC_NAME = str(profile.get("public_name") or profile["name"])
    config.STRATEGY_PACKAGE_NAME = config.STRATEGY_PACKAGE_PUBLIC_NAME
    config.STRATEGY_PACKAGE_REBALANCE_FREQUENCY = _rebalance_frequency_from_schedule(schedule)
    config.STRATEGY_PACKAGE_TARGET_HOLDINGS = len(allocation.get("assets") or [])
    config.STRATEGY_PACKAGE_SHORT_DESCRIPTION = str(profile.get("short_description") or "")
    config.STRATEGY_PACKAGE_CATEGORY_LABELS = ",".join(profile.get("category_labels") or [])
    config.STRATEGY_PACKAGE_PORTFOLIO_OBJECTIVE = str(
        profile.get("portfolio_objective") or config.STRATEGY_PACKAGE_PORTFOLIO_OBJECTIVE
    )
    config.STRATEGY_PACKAGE_UNIVERSE = str(profile.get("universe") or config.STRATEGY_PACKAGE_UNIVERSE)
    config.STRATEGY_PACKAGE_BENCHMARK = str(profile.get("benchmark") or config.STRATEGY_PACKAGE_BENCHMARK)
    config.STRATEGY_PACKAGE_RA_ENTITY = str(profile.get("ra_entity") or config.STRATEGY_PACKAGE_RA_ENTITY)
    config.STRATEGY_PACKAGE_SEBI_REGISTRATION_NUMBER = str(
        profile.get("sebi_registration_number") or config.STRATEGY_PACKAGE_SEBI_REGISTRATION_NUMBER
    )
    config.STRATEGY_PACKAGE_MIN_CAPITAL_GUIDANCE = int(
        profile.get("min_capital_guidance") or config.STRATEGY_PACKAGE_MIN_CAPITAL_GUIDANCE
    )
    config.STRATEGY_PUBLIC_METHODOLOGY_PATH = str(
        documents.get("public_methodology_path")
        or documents.get("methodology_path")
        or config.STRATEGY_PUBLIC_METHODOLOGY_PATH
    )
    config.STRATEGY_INTERNAL_METHODOLOGY_PATH = str(
        documents.get("internal_methodology_path") or config.STRATEGY_INTERNAL_METHODOLOGY_PATH
    )
    config.STRATEGY_PACKAGE_OUTPUT_DIR = str(package.get("output_dir") or config.STRATEGY_PACKAGE_OUTPUT_DIR)
    config.STRATEGY_PACKAGE_VERSION = str(package.get("version") or config.STRATEGY_PACKAGE_VERSION)
    config.UNIVERSE_EXCEL_PATH = str(data.get("universe_excel_path") or config.UNIVERSE_EXCEL_PATH)
    config.UNIVERSE_JSON_PATH = str(data.get("universe_json_path") or config.UNIVERSE_JSON_PATH)
    config.UNIVERSE_VALIDATION_REPORT_PATH = str(
        data.get("universe_validation_report_path") or config.UNIVERSE_VALIDATION_REPORT_PATH
    )
    config.DISTRIBUTION_EVENTS_PATH = distribution_events_path
    config.OPTIMIZATION_RESULTS_PATH = str(optimization.get("results_path") or config.OPTIMIZATION_RESULTS_PATH)
    config.FINALIZED_STRATEGY_CONFIG_PATH = str(
        optimization.get("finalized_config_path") or config.FINALIZED_STRATEGY_CONFIG_PATH
    )
    config.OPTIMIZATION_ENGINE_PATH = str(
        optimization.get("engine_path") or config.OPTIMIZATION_ENGINE_PATH
    )
    config.OPTIMIZATION_ENGINE_MODULE = str(
        optimization.get("engine_module")
        or optimization.get("engine")
        or config.OPTIMIZATION_ENGINE_MODULE
    )
    if backtest.get("benchmark_symbol"):
        config.DEFAULT_BENCHMARK_SYMBOL = str(backtest["benchmark_symbol"])
    if backtest.get("kite_benchmark_tradingsymbol"):
        config.KITE_BENCHMARK_TRADINGSYMBOL = str(backtest["kite_benchmark_tradingsymbol"])
    if backtest.get("safe_asset_symbol"):
        config.SAFE_ASSET_SYMBOL = str(backtest["safe_asset_symbol"]).strip().upper()
    if backtest.get("safe_asset_fallback_symbol"):
        config.SAFE_ASSET_FALLBACK_SYMBOL = str(backtest["safe_asset_fallback_symbol"]).strip().upper()
    if backtest.get("safe_asset_symbol") or backtest.get("safe_asset_fallback_symbol"):
        config.SAFE_ASSET_SYMBOLS = sorted(
            {symbol for symbol in [config.SAFE_ASSET_SYMBOL, config.SAFE_ASSET_FALLBACK_SYMBOL] if symbol}
        )
    if "min_avg_momentum_return" in parameters:
        config.MIN_AVG_MOMENTUM_RETURN = float(parameters["min_avg_momentum_return"])
    if "min_12m_return" in parameters:
        config.MIN_12M_RETURN = float(parameters["min_12m_return"])
    if "require_price_above_ema" in parameters:
        config.REQUIRE_PRICE_ABOVE_EMA = bool(parameters["require_price_above_ema"])
    if "price_ema_days" in parameters:
        config.PRICE_EMA_DAYS = int(parameters["price_ema_days"])
    if "max_stock_weight" in parameters:
        config.MAX_STOCK_WEIGHT = float(parameters["max_stock_weight"])
    if "max_sector_weight" in parameters:
        config.MAX_SECTOR_WEIGHT = float(parameters["max_sector_weight"])
    return profile


def _rebalance_frequency_from_schedule(schedule: dict[str, Any]) -> str:
    schedule_type = str(schedule.get("type") or "").strip().lower()
    if schedule_type == "quarterly_first_trading_day":
        return "quarterly"
    return ""
