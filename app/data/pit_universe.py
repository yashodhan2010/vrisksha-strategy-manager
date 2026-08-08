from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from app import config


DEFAULT_OUTPUT_DIR = Path("data/output/pit_universe")
DEFAULT_CHANGE_WORKBOOK = Path(r"C:\Users\Yashodhan\Downloads\Nifty500_Index_Changes_Database_mid_2017 to 2026.xlsx")


@dataclass(frozen=True)
class PitUniverseOutputs:
    snapshots_path: Path
    required_symbols_path: Path
    coverage_audit_path: Path
    summary_path: Path


def build_pit_universe_audit(
    changes_workbook: str | Path = DEFAULT_CHANGE_WORKBOOK,
    current_universe_json: str | Path = config.UNIVERSE_JSON_PATH,
    current_universe_excel: str | Path = config.UNIVERSE_EXCEL_PATH,
    database_path: str | Path = config.DATABASE_PATH,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    start_date: date = date(2017, 9, 29),
    end_date: date | None = None,
    anchor_date: date | None = None,
    lookback_days: int = 450,
) -> PitUniverseOutputs:
    workbook = Path(changes_workbook)
    current_json = Path(current_universe_json)
    current_excel = Path(current_universe_excel)
    db = Path(database_path)
    target_dir = Path(output_dir)
    if end_date is None:
        end_date = date.today()
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date.")
    if lookback_days < 0:
        raise ValueError("lookback_days must be non-negative.")

    current_records = _load_current_universe(current_json)
    changes = _load_changes(workbook)
    aliases = _load_aliases(workbook)
    inferred_anchor_date = anchor_date or _infer_anchor_date(current_excel, current_json, end_date)
    snapshots = _build_snapshots(
        current_symbols=set(current_records),
        changes=changes,
        start_date=start_date,
        end_date=end_date,
        anchor_date=inferred_anchor_date,
    )
    metadata = _symbol_metadata(current_records, changes)
    snapshot_frame = _snapshot_frame(snapshots, metadata)
    required_symbols = _required_symbol_frame(snapshots, metadata, aliases, lookback_days)
    price_ranges = _load_price_ranges(db)
    coverage = _coverage_frame(required_symbols, price_ranges)
    summary = _summary_payload(
        workbook=workbook,
        current_json=current_json,
        database_path=db,
        start_date=start_date,
        end_date=end_date,
        anchor_date=inferred_anchor_date,
        changes=changes,
        aliases=aliases,
        snapshots=snapshots,
        current_records=current_records,
        price_ranges=price_ranges,
        coverage=coverage,
        lookback_days=lookback_days,
    )

    target_dir.mkdir(parents=True, exist_ok=True)
    snapshots_path = target_dir / "nifty500_pit_membership_snapshots.csv"
    required_symbols_path = target_dir / "nifty500_pit_required_symbols.csv"
    coverage_audit_path = target_dir / "nifty500_pit_price_coverage_audit.csv"
    summary_path = target_dir / "nifty500_pit_summary.json"
    snapshot_frame.to_csv(snapshots_path, index=False)
    required_symbols.to_csv(required_symbols_path, index=False)
    coverage.to_csv(coverage_audit_path, index=False)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return PitUniverseOutputs(snapshots_path, required_symbols_path, coverage_audit_path, summary_path)


def _load_current_universe(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Current universe JSON not found: {path}")
    rows = json.loads(path.read_text(encoding="utf-8"))
    records: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = _clean_symbol(row.get("symbol"))
        if symbol:
            records[symbol] = dict(row)
    return records


def _load_changes(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Nifty 500 changes workbook not found: {path}")
    frame = pd.read_excel(path, sheet_name="Nifty500_Changes", dtype=object)
    required = {"Effective_Date", "Symbol", "Action", "Company_Name"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Missing required change workbook columns: {', '.join(missing)}")
    frame = frame.copy()
    frame["Effective_Date"] = pd.to_datetime(frame["Effective_Date"]).dt.date
    frame["Release_Date"] = pd.to_datetime(frame.get("Release_Date")).dt.date
    frame["Symbol"] = frame["Symbol"].map(_clean_symbol)
    frame["Action"] = frame["Action"].astype(str).str.strip().str.title()
    frame = frame[frame["Symbol"].notna() & frame["Action"].isin(["Inclusion", "Exclusion"])]
    return frame.sort_values(["Effective_Date", "Action", "Symbol"]).reset_index(drop=True)


def _load_aliases(path: Path) -> dict[str, str]:
    excel = pd.ExcelFile(path)
    if "Symbol_Aliases" not in excel.sheet_names:
        return {}
    frame = pd.read_excel(path, sheet_name="Symbol_Aliases", dtype=object)
    aliases: dict[str, str] = {}
    for row in frame.to_dict("records"):
        old_symbol = _clean_symbol(row.get("Old_Symbol"))
        new_symbol = _clean_symbol(row.get("New_Symbol"))
        if old_symbol and new_symbol:
            aliases[old_symbol] = new_symbol
    return aliases


def _infer_anchor_date(current_excel: Path, current_json: Path, end_date: date) -> date:
    if current_excel.exists():
        return datetime.fromtimestamp(current_excel.stat().st_mtime).date()
    if current_json.exists():
        return datetime.fromtimestamp(current_json.stat().st_mtime).date()
    return end_date


def _build_snapshots(
    current_symbols: set[str],
    changes: pd.DataFrame,
    start_date: date,
    end_date: date,
    anchor_date: date,
) -> dict[date, set[str]]:
    end_members = set(current_symbols)
    forward_changes = changes[(changes["Effective_Date"] > anchor_date) & (changes["Effective_Date"] <= end_date)]
    for row in forward_changes.sort_values(["Effective_Date", "Action"]).to_dict("records"):
        symbol = str(row["Symbol"])
        if row["Action"] == "Exclusion":
            end_members.discard(symbol)
        else:
            end_members.add(symbol)

    snapshot_dates = sorted(
        {start_date, end_date}
        | set(changes[(changes["Effective_Date"] >= start_date) & (changes["Effective_Date"] <= end_date)]["Effective_Date"])
    )
    snapshots: dict[date, set[str]] = {}
    members = set(end_members)
    cursor = end_date
    for snapshot_date in sorted(snapshot_dates, reverse=True):
        to_undo = changes[(changes["Effective_Date"] > snapshot_date) & (changes["Effective_Date"] <= cursor)]
        for row in to_undo.sort_values(["Effective_Date", "Action"], ascending=[False, True]).to_dict("records"):
            symbol = str(row["Symbol"])
            if row["Action"] == "Inclusion":
                members.discard(symbol)
            else:
                members.add(symbol)
        snapshots[snapshot_date] = set(members)
        cursor = snapshot_date
    return dict(sorted(snapshots.items()))


def _symbol_metadata(current_records: dict[str, dict[str, Any]], changes: pd.DataFrame) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for symbol, row in current_records.items():
        metadata[symbol] = {
            "company_name": row.get("company_name"),
            "sector": row.get("sector"),
            "industry": row.get("industry"),
            "isin": row.get("isin"),
            "source": "current_universe",
        }
    for row in changes.to_dict("records"):
        symbol = str(row["Symbol"])
        existing = metadata.setdefault(symbol, {})
        existing.setdefault("company_name", _none_if_na(row.get("Company_Name")))
        existing.setdefault("sector", None)
        existing.setdefault("industry", None)
        existing.setdefault("isin", None)
        existing.setdefault("source", "change_workbook")
    return metadata


def _snapshot_frame(snapshots: dict[date, set[str]], metadata: dict[str, dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for snapshot_date, symbols in snapshots.items():
        for number, symbol in enumerate(sorted(symbols), start=1):
            info = metadata.get(symbol, {})
            rows.append(
                {
                    "as_of_date": snapshot_date.isoformat(),
                    "symbol": symbol,
                    "snapshot_symbol_number": number,
                    "constituent_count": len(symbols),
                    "company_name": info.get("company_name"),
                    "sector": info.get("sector"),
                    "industry": info.get("industry"),
                    "isin": info.get("isin"),
                    "metadata_source": info.get("source"),
                }
            )
    return pd.DataFrame(rows)


def _required_symbol_frame(
    snapshots: dict[date, set[str]],
    metadata: dict[str, dict[str, Any]],
    aliases: dict[str, str],
    lookback_days: int,
) -> pd.DataFrame:
    first_seen: dict[str, date] = {}
    last_seen: dict[str, date] = {}
    for snapshot_date, symbols in snapshots.items():
        for symbol in symbols:
            first_seen[symbol] = min(first_seen.get(symbol, snapshot_date), snapshot_date)
            last_seen[symbol] = max(last_seen.get(symbol, snapshot_date), snapshot_date)
    rows: list[dict[str, Any]] = []
    for symbol in sorted(first_seen):
        info = metadata.get(symbol, {})
        alias_symbol = aliases.get(symbol)
        rows.append(
            {
                "symbol": symbol,
                "data_symbol": alias_symbol or symbol,
                "alias_applied": bool(alias_symbol),
                "first_membership_date": first_seen[symbol].isoformat(),
                "last_membership_date": last_seen[symbol].isoformat(),
                "required_price_start": (first_seen[symbol] - timedelta(days=lookback_days)).isoformat(),
                "required_price_end": last_seen[symbol].isoformat(),
                "company_name": info.get("company_name"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "metadata_source": info.get("source"),
            }
        )
    return pd.DataFrame(rows)


def _load_price_ranges(database_path: Path) -> dict[str, dict[str, Any]]:
    if not database_path.exists():
        return {}
    with sqlite3.connect(database_path) as connection:
        try:
            rows = connection.execute(
                """
                SELECT symbol, COUNT(*) AS row_count, MIN(price_date) AS first_date, MAX(price_date) AS last_date
                FROM market_prices
                GROUP BY symbol
                """
            ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return {}
            raise
    return {
        str(symbol).strip().upper(): {"row_count": row_count, "first_date": first_date, "last_date": last_date}
        for symbol, row_count, first_date, last_date in rows
    }


def _coverage_frame(required_symbols: pd.DataFrame, price_ranges: dict[str, dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in required_symbols.to_dict("records"):
        symbol = str(row["symbol"])
        data_symbol = str(row["data_symbol"])
        direct = price_ranges.get(symbol)
        alias = price_ranges.get(data_symbol) if data_symbol != symbol else None
        selected = direct or alias
        required_start = date.fromisoformat(str(row["required_price_start"]))
        required_end = date.fromisoformat(str(row["required_price_end"]))
        first_date = date.fromisoformat(selected["first_date"]) if selected and selected.get("first_date") else None
        last_date = date.fromisoformat(selected["last_date"]) if selected and selected.get("last_date") else None
        rows.append(
            {
                **row,
                "matched_price_symbol": symbol if direct else (data_symbol if alias else None),
                "has_any_price": selected is not None,
                "price_row_count": int(selected["row_count"]) if selected else 0,
                "price_first_date": first_date.isoformat() if first_date else None,
                "price_last_date": last_date.isoformat() if last_date else None,
                "covers_required_start": bool(first_date and first_date <= required_start),
                "covers_required_end": bool(last_date and last_date >= required_end),
                "coverage_status": _coverage_status(first_date, last_date, required_start, required_end),
            }
        )
    return pd.DataFrame(rows)


def _coverage_status(first_date: date | None, last_date: date | None, required_start: date, required_end: date) -> str:
    if first_date is None or last_date is None:
        return "missing_all_prices"
    if first_date <= required_start and last_date >= required_end:
        return "covered"
    if first_date > required_start and last_date < required_end:
        return "missing_start_and_end"
    if first_date > required_start:
        return "missing_start"
    return "missing_end"


def _summary_payload(
    workbook: Path,
    current_json: Path,
    database_path: Path,
    start_date: date,
    end_date: date,
    anchor_date: date,
    changes: pd.DataFrame,
    aliases: dict[str, str],
    snapshots: dict[date, set[str]],
    current_records: dict[str, dict[str, Any]],
    price_ranges: dict[str, dict[str, Any]],
    coverage: pd.DataFrame,
    lookback_days: int,
) -> dict[str, Any]:
    latest_effective = max(changes["Effective_Date"]) if not changes.empty else None
    latest_changes = changes[changes["Effective_Date"] == latest_effective] if latest_effective else pd.DataFrame()
    anchor_mismatches = []
    current_symbols = set(current_records)
    for row in latest_changes.to_dict("records"):
        symbol = str(row["Symbol"])
        action = row["Action"]
        if action == "Inclusion" and symbol not in current_symbols:
            anchor_mismatches.append({"symbol": symbol, "action": action, "issue": "included_in_workbook_missing_current"})
        if action == "Exclusion" and symbol in current_symbols:
            anchor_mismatches.append({"symbol": symbol, "action": action, "issue": "excluded_in_workbook_still_current"})

    coverage_counts = coverage["coverage_status"].value_counts().to_dict() if not coverage.empty else {}
    snapshot_counts = [len(symbols) for symbols in snapshots.values()]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "changes_workbook": str(workbook),
        "current_universe_json": str(current_json),
        "database_path": str(database_path),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "anchor_date": anchor_date.isoformat(),
        "lookback_days": lookback_days,
        "change_rows": int(len(changes)),
        "change_effective_min": min(changes["Effective_Date"]).isoformat() if not changes.empty else None,
        "change_effective_max": latest_effective.isoformat() if latest_effective else None,
        "alias_count": len(aliases),
        "snapshot_count": len(snapshots),
        "snapshot_constituent_count_min": min(snapshot_counts) if snapshot_counts else 0,
        "snapshot_constituent_count_max": max(snapshot_counts) if snapshot_counts else 0,
        "required_symbols": int(len(coverage)),
        "price_database_symbols": len(price_ranges),
        "coverage_status_counts": {str(key): int(value) for key, value in coverage_counts.items()},
        "anchor_mismatches_latest_effective_date": anchor_mismatches,
        "missing_price_symbols_sample": coverage.loc[
            coverage["coverage_status"].eq("missing_all_prices"), "symbol"
        ].head(50).tolist()
        if not coverage.empty
        else [],
    }


def _clean_symbol(value: Any) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip().upper()
    return text or None


def _none_if_na(value: Any) -> Any:
    return None if pd.isna(value) else value


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Nifty 500 point-in-time universe snapshots and price audit.")
    parser.add_argument("--changes-workbook", default=str(DEFAULT_CHANGE_WORKBOOK))
    parser.add_argument("--current-universe-json", default=config.UNIVERSE_JSON_PATH)
    parser.add_argument("--current-universe-excel", default=config.UNIVERSE_EXCEL_PATH)
    parser.add_argument("--database-path", default=config.DATABASE_PATH)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--start-date", type=_parse_date, default=date(2017, 9, 29))
    parser.add_argument("--end-date", type=_parse_date, default=date.today())
    parser.add_argument("--anchor-date", type=_parse_date)
    parser.add_argument("--lookback-days", type=int, default=450)
    args = parser.parse_args(argv)
    outputs = build_pit_universe_audit(
        changes_workbook=args.changes_workbook,
        current_universe_json=args.current_universe_json,
        current_universe_excel=args.current_universe_excel,
        database_path=args.database_path,
        output_dir=args.output_dir,
        start_date=args.start_date,
        end_date=args.end_date,
        anchor_date=args.anchor_date,
        lookback_days=args.lookback_days,
    )
    print(f"PIT membership snapshots written to {outputs.snapshots_path}")
    print(f"Required symbols written to {outputs.required_symbols_path}")
    print(f"Price coverage audit written to {outputs.coverage_audit_path}")
    print(f"Summary written to {outputs.summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
