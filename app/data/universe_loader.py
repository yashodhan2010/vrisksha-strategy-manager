from __future__ import annotations

import json
from pathlib import Path

from app import config
from app.data.universe_sync import sync_universe
from app.strategy.models import UniverseStock


def load_universe(
    excel_path: str | Path = config.UNIVERSE_EXCEL_PATH,
    json_path: str | Path = config.UNIVERSE_JSON_PATH,
) -> list[UniverseStock]:
    excel = Path(excel_path)
    runtime_json = Path(json_path)

    if excel.exists() and (not runtime_json.exists() or excel.stat().st_mtime > runtime_json.stat().st_mtime):
        sync_universe(excel, runtime_json)

    if not runtime_json.exists():
        raise FileNotFoundError(
            "No runtime universe JSON is available. Create data/reference/nifty500_universe.xlsx "
            "from the example workbook and run python -m app.main sync-universe."
        )

    payload = json.loads(runtime_json.read_text(encoding="utf-8"))
    return [UniverseStock(**item) for item in payload]

