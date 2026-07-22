from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any


_BASE_PATH = Path(__file__).resolve().parents[1].parent / "conservative-dual-momentum" / "experiments" / "optimizer.py"
_SPEC = importlib.util.spec_from_file_location("_low_drawdown_shared_optimizer", _BASE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Could not load shared optimizer from {_BASE_PATH}")
_BASE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _BASE
_SPEC.loader.exec_module(_BASE)
_BASE_SEARCH_SPACE = _BASE.search_space


PROJECT_ROOT = _BASE.PROJECT_ROOT
DATABASE_PATH = _BASE.DATABASE_PATH
UNIVERSE_JSON_PATH = _BASE.UNIVERSE_JSON_PATH
OUTPUT_DIR = PROJECT_ROOT / "data" / "output" / "low-drawdown-dual-momentum" / "experiments"

GridParams = _BASE.GridParams
DataQualityConfig = _BASE.DataQualityConfig
ExhaustiveGridStudy = _BASE.ExhaustiveGridStudy


def _sync_paths() -> None:
    _BASE.DATABASE_PATH = DATABASE_PATH
    _BASE.UNIVERSE_JSON_PATH = UNIVERSE_JSON_PATH
    _BASE.OUTPUT_DIR = OUTPUT_DIR


def __getattr__(name: str) -> Any:
    return getattr(_BASE, name)


def load_universe(*args: Any, **kwargs: Any) -> Any:
    _sync_paths()
    return _BASE.load_universe(*args, **kwargs)


def load_price_pivot(*args: Any, **kwargs: Any) -> Any:
    _sync_paths()
    return _BASE.load_price_pivot(*args, **kwargs)


def search_space(momentum_weight_grid: Any = None) -> dict[str, list[int | float]]:
    _sync_paths()
    return _BASE_SEARCH_SPACE(momentum_weight_grid)


_WRAPPER_SEARCH_SPACE = search_space


def run_optuna_grid(*args: Any, **kwargs: Any) -> Any:
    _sync_paths()
    active_search_space = globals()["search_space"]
    _BASE.search_space = _BASE_SEARCH_SPACE if active_search_space is _WRAPPER_SEARCH_SPACE else active_search_space
    return _BASE.run_optuna_grid(*args, **kwargs)
