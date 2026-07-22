from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from app.strategy_registry import validate_strategy_registry


def _write_profile(root: Path, slug: str, strategy_id: str = "sample_strategy_v1") -> Path:
    folder = root / "strategies" / slug
    folder.mkdir(parents=True)
    (folder / "experiments").mkdir()
    (folder / "methodology.md").write_text("# Public\n", encoding="utf-8")
    (folder / "methodology_internal.md").write_text("# Internal\n", encoding="utf-8")
    (folder / "experiments" / "optimizer.py").write_text("# optimizer\n", encoding="utf-8")
    results = root / "data" / "output" / slug / "trials.csv"
    results.parent.mkdir(parents=True)
    pd.DataFrame([{"rank_by_cagr": 1, "cagr": 0.1}]).to_csv(results, index=False)
    finalized = root / "data" / "output" / "finalized" / f"{slug.replace('-', '_')}.json"
    finalized.parent.mkdir(parents=True, exist_ok=True)
    finalized.write_text(
        json.dumps(
            {
                "strategy_id": strategy_id,
                "strategy_slug": slug,
                "selection": {"objective": "cagr", "rank_column": "rank_by_cagr"},
            }
        ),
        encoding="utf-8",
    )
    profile = folder / "strategy_profile.json"
    profile.write_text(
        json.dumps(
            {
                "strategy_id": strategy_id,
                "slug": slug,
                "name": "Sample Strategy",
                "documents": {
                    "public_methodology_path": str(folder / "methodology.md"),
                    "internal_methodology_path": str(folder / "methodology_internal.md"),
                },
                "optimization": {
                    "engine_path": str(folder / "experiments" / "optimizer.py"),
                    "results_path": str(results),
                    "finalized_config_path": str(finalized),
                    "objective": "cagr",
                    "rank_column": "rank_by_cagr",
                    "search_space": {"top_n": [20]},
                },
                "package": {
                    "version": "1.0.0",
                    "output_dir": str(root / "data" / "output" / "packages" / slug / "strategy-package"),
                },
            }
        ),
        encoding="utf-8",
    )
    return profile


def test_validate_strategy_registry_accepts_complete_profile(tmp_path: Path) -> None:
    profile = _write_profile(tmp_path, "sample-strategy")
    registry = tmp_path / "strategies" / "registry.json"
    registry.write_text(json.dumps({"strategies": [str(profile)]}), encoding="utf-8")

    report = validate_strategy_registry(registry)

    assert report.ok
    assert report.profile_count == 1


def test_validate_strategy_registry_reports_duplicate_slug_and_bad_results(tmp_path: Path) -> None:
    first = _write_profile(tmp_path, "sample-strategy", "sample_a")
    second = _write_profile(tmp_path, "sample-strategy-two", "sample_b")
    payload = json.loads(second.read_text(encoding="utf-8"))
    payload["slug"] = "sample-strategy"
    payload["optimization"]["objective"] = "missing_metric"
    second.write_text(json.dumps(payload), encoding="utf-8")
    registry = tmp_path / "strategies" / "registry.json"
    registry.write_text(json.dumps({"strategies": [str(first), str(second)]}), encoding="utf-8")

    report = validate_strategy_registry(registry)

    messages = "\n".join(issue.message for issue in report.issues)
    assert not report.ok
    assert "Duplicate slug" in messages
    assert "objective column 'missing_metric' missing" in messages
