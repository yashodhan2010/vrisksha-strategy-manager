from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_REGISTRY_PATH = Path("strategies/registry.json")
_KEBAB_CASE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_FORBIDDEN_PROFILE_TERMS = ("payment", "subscription", "login", "access_control", "access-control")


@dataclass(frozen=True)
class StrategyValidationIssue:
    profile_path: str
    severity: str
    message: str


@dataclass(frozen=True)
class StrategyValidationReport:
    registry_path: Path
    profile_count: int
    issues: list[StrategyValidationIssue]

    @property
    def ok(self) -> bool:
        return not any(issue.severity == "ERROR" for issue in self.issues)


def load_strategy_registry(registry_path: str | Path = DEFAULT_REGISTRY_PATH) -> list[Path]:
    path = Path(registry_path)
    if not path.exists():
        raise FileNotFoundError(f"Strategy registry not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    strategies = payload.get("strategies")
    if not isinstance(strategies, list) or not strategies:
        raise ValueError(f"Strategy registry must contain a non-empty 'strategies' list: {path}")
    return [Path(item) for item in strategies]


def validate_strategy_registry(registry_path: str | Path = DEFAULT_REGISTRY_PATH) -> StrategyValidationReport:
    path = Path(registry_path)
    profile_paths = load_strategy_registry(path)
    issues: list[StrategyValidationIssue] = []
    seen_ids: dict[str, Path] = {}
    seen_slugs: dict[str, Path] = {}

    for profile_path in profile_paths:
        issues.extend(_validate_profile(profile_path, seen_ids, seen_slugs))

    return StrategyValidationReport(path, len(profile_paths), issues)


def _validate_profile(
    profile_path: Path,
    seen_ids: dict[str, Path],
    seen_slugs: dict[str, Path],
) -> list[StrategyValidationIssue]:
    issues: list[StrategyValidationIssue] = []
    profile_label = str(profile_path)

    def error(message: str) -> None:
        issues.append(StrategyValidationIssue(profile_label, "ERROR", message))

    def warn(message: str) -> None:
        issues.append(StrategyValidationIssue(profile_label, "WARN", message))

    if not profile_path.exists():
        error("Profile path listed in registry does not exist.")
        return issues
    try:
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        error(f"Profile JSON is invalid: {exc}")
        return issues

    required = ["strategy_id", "slug", "name", "documents", "optimization", "package"]
    for key in required:
        if key not in profile:
            error(f"Missing required field: {key}")
    if any(key not in profile for key in required):
        return issues

    strategy_id = str(profile.get("strategy_id") or "")
    slug = str(profile.get("slug") or "")
    if not _KEBAB_CASE.match(slug):
        error(f"Slug must be lowercase kebab-case: {slug}")
    if profile_path.parent.name != slug:
        error(f"Profile folder name must match slug '{slug}', got '{profile_path.parent.name}'.")
    if strategy_id in seen_ids:
        error(f"Duplicate strategy_id also used by {seen_ids[strategy_id]}.")
    seen_ids[strategy_id] = profile_path
    if slug in seen_slugs:
        error(f"Duplicate slug also used by {seen_slugs[slug]}.")
    seen_slugs[slug] = profile_path

    serialized = json.dumps(profile, sort_keys=True).lower()
    for term in _FORBIDDEN_PROFILE_TERMS:
        if term in serialized:
            error(f"Profile contains website/account/payment/access-control term: {term}")

    documents = profile.get("documents") or {}
    for key in ["public_methodology_path", "internal_methodology_path"]:
        doc_path = Path(str(documents.get(key) or ""))
        if not doc_path.exists():
            error(f"{key} does not exist: {doc_path}")
        elif slug not in doc_path.as_posix():
            warn(f"{key} is not under the strategy slug folder: {doc_path}")

    optimization = profile.get("optimization") or {}
    objective = str(optimization.get("objective") or "")
    rank_column = str(optimization.get("rank_column") or "")
    for key in ["engine_path", "results_path", "finalized_config_path", "objective", "rank_column", "search_space"]:
        if key not in optimization:
            error(f"optimization.{key} is required.")
    engine_path = Path(str(optimization.get("engine_path") or ""))
    if not engine_path.exists():
        error(f"optimization.engine_path does not exist: {engine_path}")
    elif slug not in engine_path.as_posix():
        warn(f"optimization.engine_path is not under the strategy slug folder: {engine_path}")

    search_space = optimization.get("search_space") or {}
    if not isinstance(search_space, dict) or not search_space:
        error("optimization.search_space must be a non-empty object.")
    else:
        for key, values in search_space.items():
            if not isinstance(values, list) or not values:
                error(f"optimization.search_space.{key} must be a non-empty list.")

    results_path = Path(str(optimization.get("results_path") or ""))
    if not results_path.exists():
        warn(f"optimization.results_path does not exist yet: {results_path}")
    else:
        try:
            columns = set(pd.read_csv(results_path, nrows=1).columns)
            if objective and objective not in columns:
                error(f"objective column '{objective}' missing from results CSV: {results_path}")
            if rank_column and rank_column not in columns:
                error(f"rank column '{rank_column}' missing from results CSV: {results_path}")
        except Exception as exc:
            error(f"Could not read optimization results CSV {results_path}: {exc}")

    finalized_path = Path(str(optimization.get("finalized_config_path") or ""))
    if not finalized_path.exists():
        warn(f"optimization.finalized_config_path does not exist yet: {finalized_path}")
    else:
        try:
            payload = json.loads(finalized_path.read_text(encoding="utf-8"))
            selection = payload.get("selection") or {}
            if selection.get("objective") != objective:
                error(
                    "Finalized config objective does not match profile: "
                    f"{selection.get('objective')} != {objective}"
                )
            if selection.get("rank_column") != rank_column:
                error(
                    "Finalized config rank column does not match profile: "
                    f"{selection.get('rank_column')} != {rank_column}"
                )
            if payload.get("strategy_id") != strategy_id:
                error(f"Finalized config strategy_id does not match profile: {payload.get('strategy_id')} != {strategy_id}")
            if payload.get("strategy_slug") != slug:
                error(f"Finalized config strategy_slug does not match profile: {payload.get('strategy_slug')} != {slug}")
        except Exception as exc:
            error(f"Could not read finalized config {finalized_path}: {exc}")

    package = profile.get("package") or {}
    output_dir = Path(str(package.get("output_dir") or ""))
    if slug not in output_dir.as_posix():
        error(f"package.output_dir must be strategy-specific and include slug '{slug}': {output_dir}")
    if output_dir.name != "strategy-package":
        error(f"package.output_dir must end with strategy-package: {output_dir}")

    return issues
