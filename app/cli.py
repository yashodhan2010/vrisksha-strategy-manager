from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta

from app import config
from app.automation.kite_selenium import capture_request_token
from app.automation.schedule import is_rebalance_day, parse_target_days, rebalance_dates_for_month
from app.backtest.engine import BacktestEngine
from app.data.trading_calendar import WeekdayTradingCalendar
from app.data.price_ingestion import fetch_and_store_history
from app.data.universe_sync import UniverseSyncError, sync_universe
from app.execution.kite_session import exchange_request_token, get_login_url, save_access_token_to_env, validate_saved_access_token
from app.logging_config import get_logger
from app.storage.database import initialize_database
from app.storage.repositories import (
    add_audit_event,
    complete_strategy_run,
    create_backtest_run,
    create_strategy_run,
)
from app.strategy.rebalance import RebalanceEngine
from app.strategy.models import RunMode, RunStatus, RunType


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def cmd_init_db(_args: argparse.Namespace) -> int:
    initialize_database()
    print(f"Initialized SQLite database at {config.DATABASE_PATH}")
    return 0


def cmd_show_config(_args: argparse.Namespace) -> int:
    print(json.dumps(config.public_config(), indent=2))
    return 0


def cmd_sync_universe(_args: argparse.Namespace) -> int:
    logger = get_logger("app.universe")
    try:
        report = sync_universe()
    except (FileNotFoundError, UniverseSyncError) as exc:
        logger.error("Universe sync failed: %s", exc)
        print(f"Universe sync failed: {exc}")
        return 1
    initialize_database()
    add_audit_event(None, "UNIVERSE_SYNC", "INFO", "Universe synchronized", report)
    logger.info("Universe sync completed: %s active rows", report["active_rows"])
    print(
        "Universe sync completed: "
        f"{report['active_rows']} active, {report['inactive_rows']} inactive, "
        f"report={config.UNIVERSE_VALIDATION_REPORT_PATH}"
    )
    return 0


def cmd_manual_run(_args: argparse.Namespace) -> int:
    initialize_database()
    logger = get_logger("app.manual")
    run_id = create_strategy_run(
        RunType.MANUAL,
        RunMode.RANK_ONLY,
        message="Manual placeholder run started.",
    )
    message = "Strategy engine is not implemented yet; no orders were placed."
    add_audit_event(run_id, "MANUAL_RUN", "INFO", message)
    complete_strategy_run(run_id, RunStatus.COMPLETED, message)
    logger.info("Manual placeholder run %s completed safely", run_id)
    print(f"Manual run {run_id} completed. {message}")
    return 0


def cmd_monthly_run(_args: argparse.Namespace) -> int:
    initialize_database()
    logger = get_logger("scheduler.monthly")
    try:
        mode = RunMode(config.DEFAULT_MODE)
    except ValueError:
        print(f"Unsupported DEFAULT_MODE: {config.DEFAULT_MODE}")
        return 2
    run_id = create_strategy_run(
        RunType.MONTHLY,
        mode,
        message="Scheduled rebalance run started.",
        config_payload={
            "target_portfolio_value": config.TARGET_PORTFOLIO_VALUE,
            "available_purchase_funds": config.AVAILABLE_PURCHASE_FUNDS,
            "strategy_allocation_mode": config.STRATEGY_ALLOCATION_MODE,
            "strategy_top_n": config.STRATEGY_TOP_N,
            "strategy_ranking_method": config.STRATEGY_RANKING_METHOD,
            "ranking_momentum_weight": config.RANKING_MOMENTUM_WEIGHT,
            "ranking_beta_weight": config.RANKING_BETA_WEIGHT,
            "ranking_volatility_weight": config.RANKING_VOLATILITY_WEIGHT,
            "dynamic_min_weight": config.DYNAMIC_MIN_WEIGHT,
            "dynamic_max_weight": config.DYNAMIC_MAX_WEIGHT,
            "max_stock_weight": config.MAX_STOCK_WEIGHT,
            "high_52w_threshold": config.HIGH_52W_THRESHOLD,
            "beta_lookback_days": config.BETA_LOOKBACK_DAYS,
            "mode": mode.value,
        },
    )
    today = date.today()
    calendar = WeekdayTradingCalendar()
    if not calendar.is_trading_day(today):
        message = f"Skipped: {today.isoformat()} is a weekend under the provisional weekday calendar."
        status = RunStatus.SKIPPED
    else:
        try:
            result = RebalanceEngine(run_id=run_id, run_date=today).run()
        except ValueError as exc:
            message = f"Scheduled rebalance failed: {exc}"
            status = RunStatus.FAILED
            add_audit_event(run_id, "MONTHLY_REBALANCE", "ERROR", message)
            complete_strategy_run(run_id, status, message)
            logger.error("Monthly rebalance %s failed: %s", run_id, exc)
            print(f"Monthly run {run_id}: {status.value}. {message}")
            return 1
        message = (
            f"Scheduled rebalance completed for {result.run_date.isoformat()}: "
            f"{result.selected_count} selected stocks, {result.proposal_count} proposed orders, "
            f"{result.liquidbees_weight:.2%} LIQUIDBEES/cash, "
            f"{result.buy_scaling_ratio:.2%} buy scaling."
        )
        status = RunStatus.COMPLETED
        if result.warnings:
            add_audit_event(
                run_id,
                "MONTHLY_REBALANCE_WARNINGS",
                "WARNING",
                "Rebalance completed with warnings.",
                {"warnings": result.warnings},
            )
    add_audit_event(run_id, "MONTHLY_RUN", "INFO", message)
    complete_strategy_run(run_id, status, message)
    logger.info("Monthly rebalance run %s ended with %s", run_id, status.value)
    print(f"Monthly run {run_id}: {status.value}. {message}")
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    initialize_database()
    logger = get_logger("backtest.cli")
    if args.years and (args.start_date or args.end_date):
        print("Use either --years or --start-date/--end-date, not both.")
        return 2
    if bool(args.start_date) != bool(args.end_date):
        print("Both --start-date and --end-date are required when using explicit dates.")
        return 2

    start_date = _parse_date(args.start_date) if args.start_date else None
    end_date = _parse_date(args.end_date) if args.end_date else None
    if start_date and end_date and start_date > end_date:
        print("--start-date must be on or before --end-date.")
        return 2
    if args.years is not None and args.years <= 0:
        print("--years must be greater than zero.")
        return 2
    if args.initial_capital <= 0:
        print("--initial-capital must be greater than zero.")
        return 2
    if args.years is None and start_date is None and end_date is None:
        print("Provide either --years or --start-date/--end-date.")
        return 2

    if args.years:
        end_date = date.today()
        start_date = end_date - timedelta(days=round(args.years * 365.25))

    payload = {
        "years": args.years,
        "requested_at": datetime.now().isoformat(),
        "initial_capital": args.initial_capital,
        "rebalances_per_month": config.BACKTEST_REBALANCES_PER_MONTH,
        "strategy_allocation_mode": config.STRATEGY_ALLOCATION_MODE,
        "strategy_top_n": config.STRATEGY_TOP_N,
        "strategy_ranking_method": config.STRATEGY_RANKING_METHOD,
        "ranking_momentum_weight": config.RANKING_MOMENTUM_WEIGHT,
        "ranking_beta_weight": config.RANKING_BETA_WEIGHT,
        "ranking_volatility_weight": config.RANKING_VOLATILITY_WEIGHT,
        "dynamic_min_weight": config.DYNAMIC_MIN_WEIGHT,
        "dynamic_max_weight": config.DYNAMIC_MAX_WEIGHT,
    }
    run_id = create_backtest_run(
        start_date,
        end_date,
        config.DEFAULT_BENCHMARK_SYMBOL,
        payload,
        status=RunStatus.STARTED,
    )
    try:
        result = BacktestEngine(
            backtest_run_id=run_id,
            start_date=start_date,
            end_date=end_date,
            initial_capital=args.initial_capital,
        ).run()
    except ValueError as exc:
        from app.storage.repositories import update_backtest_run_result

        update_backtest_run_result(run_id, RunStatus.FAILED, None, None, args.initial_capital, None, {}, [str(exc)])
        add_audit_event(None, "BACKTEST", "ERROR", str(exc), {"backtest_run_id": run_id})
        print(f"Backtest run {run_id} failed: {exc}")
        return 1

    message = (
        f"Backtest run {run_id} completed: final value {result.final_value:,.2f}, "
        f"total return {result.total_return:.2%}, rebalances {result.rebalance_count}."
    )
    add_audit_event(None, "BACKTEST", "INFO", message, {"backtest_run_id": run_id})
    logger.info(message)
    print(message)
    if result.warnings:
        print("Warnings:")
        for warning in result.warnings[:10]:
            print(f"- {warning}")
    return 0


def cmd_run_backtest(args: argparse.Namespace) -> int:
    initialize_database()
    logger = get_logger("app.run_backtest")
    start_date = _parse_date(args.start_date)
    end_date = _parse_date(args.end_date)
    if start_date > end_date:
        print("--start-date must be on or before --end-date.")
        return 2
    if args.initial_capital <= 0:
        print("--initial-capital must be greater than zero.")
        return 2

    # Fetch extra history before the requested simulation window so 12M momentum,
    # 52-week highs, and beta lookbacks are available on the first rebalance date.
    history_start_date = start_date - timedelta(days=args.lookback_days)
    try:
        if args.request_token:
            access_token = exchange_request_token(args.request_token)
            save_access_token_to_env(access_token)
            print("Kite access token saved for today.")

        print("Step 1/4: syncing universe...")
        report = sync_universe()
        print(f"Universe ready: {report['active_rows']} active symbols.")

        print(f"Step 2/4: fetching Kite history from {history_start_date} to {end_date}...")
        fetch_result = fetch_and_store_history(
            start_date=history_start_date,
            end_date=end_date,
            symbols=args.symbols if args.symbols else None,
            include_benchmark=not args.no_benchmark,
        )
        print(
            f"Historical data ready: {fetch_result.stored_rows} rows stored "
            f"for {fetch_result.requested_symbols} requested symbols."
        )
        if fetch_result.missing_symbols:
            print(f"Missing symbols: {', '.join(fetch_result.missing_symbols[:20])}")
            if len(fetch_result.missing_symbols) > 20:
                print(f"...and {len(fetch_result.missing_symbols) - 20} more.")

        print("Step 3/4: running backtest simulation...")
        payload = {
            "orchestrated": True,
            "requested_at": datetime.now().isoformat(),
            "initial_capital": args.initial_capital,
            "rebalances_per_month": config.BACKTEST_REBALANCES_PER_MONTH,
            "strategy_allocation_mode": config.STRATEGY_ALLOCATION_MODE,
            "strategy_top_n": config.STRATEGY_TOP_N,
            "strategy_ranking_method": config.STRATEGY_RANKING_METHOD,
            "ranking_momentum_weight": config.RANKING_MOMENTUM_WEIGHT,
            "ranking_beta_weight": config.RANKING_BETA_WEIGHT,
            "ranking_volatility_weight": config.RANKING_VOLATILITY_WEIGHT,
            "dynamic_min_weight": config.DYNAMIC_MIN_WEIGHT,
            "dynamic_max_weight": config.DYNAMIC_MAX_WEIGHT,
            "history_start_date": history_start_date.isoformat(),
            "requested_start_date": start_date.isoformat(),
            "requested_end_date": end_date.isoformat(),
        }
        run_id = create_backtest_run(
            start_date,
            end_date,
            config.DEFAULT_BENCHMARK_SYMBOL,
            payload,
            status=RunStatus.STARTED,
        )
        result = BacktestEngine(
            backtest_run_id=run_id,
            start_date=start_date,
            end_date=end_date,
            initial_capital=args.initial_capital,
        ).run()
    except (FileNotFoundError, ImportError, UniverseSyncError, ValueError) as exc:
        logger.error("Run-backtest failed: %s", exc)
        print(f"Run failed: {exc}")
        return 1

    print("Step 4/4: complete.")
    print(
        f"Backtest run {result.backtest_run_id} completed: final value {result.final_value:,.2f}, "
        f"total return {result.total_return:.2%}, rebalances {result.rebalance_count}."
    )
    if result.warnings:
        print("Warnings:")
        for warning in result.warnings[:10]:
            print(f"- {warning}")
    add_audit_event(
        None,
        "RUN_BACKTEST",
        "INFO",
        "End-to-end backtest run completed.",
        {
            "backtest_run_id": result.backtest_run_id,
            "final_value": result.final_value,
            "total_return": result.total_return,
        },
    )
    return 0


def cmd_fetch_history(args: argparse.Namespace) -> int:
    initialize_database()
    logger = get_logger("app.market_data")
    start_date = _parse_date(args.start_date)
    end_date = _parse_date(args.end_date)
    symbols = args.symbols if args.symbols else None
    try:
        if args.request_token:
            access_token = exchange_request_token(args.request_token)
            save_access_token_to_env(access_token)
            print("Kite access token saved for today. Continuing with historical data fetch.")
        result = fetch_and_store_history(
            start_date=start_date,
            end_date=end_date,
            symbols=symbols,
            include_benchmark=not args.no_benchmark,
        )
    except (FileNotFoundError, ImportError, ValueError) as exc:
        logger.error("Historical data fetch failed: %s", exc)
        print(f"Historical data fetch failed: {exc}")
        return 1
    add_audit_event(
        None,
        "FETCH_HISTORY",
        "INFO",
        "Historical market data fetch completed.",
        {
            "requested_symbols": result.requested_symbols,
            "stored_rows": result.stored_rows,
            "missing_symbols": result.missing_symbols,
        },
    )
    logger.info("Historical data fetch stored %s rows", result.stored_rows)
    print(
        f"Historical data fetch completed: {result.stored_rows} rows stored "
        f"for {result.requested_symbols} requested symbols."
    )
    if result.missing_symbols:
        print(f"Missing symbols: {', '.join(result.missing_symbols[:20])}")
        if len(result.missing_symbols) > 20:
            print(f"...and {len(result.missing_symbols) - 20} more.")
    return 0 if result.stored_rows else 1


def cmd_kite_login_url(_args: argparse.Namespace) -> int:
    try:
        print(get_login_url())
        token_valid, token_message = validate_saved_access_token()
        print(f"Saved token valid: {'yes' if token_valid else 'no'}")
        print(token_message)
    except (ImportError, ValueError) as exc:
        print(f"Kite login URL failed: {exc}")
        return 1
    return 0


def cmd_kite_token_status(_args: argparse.Namespace) -> int:
    try:
        token_valid, token_message = validate_saved_access_token()
    except (ImportError, ValueError) as exc:
        print(f"Kite token status failed: {exc}")
        return 1
    print(f"Saved token valid: {'yes' if token_valid else 'no'}")
    print(token_message)
    return 0 if token_valid else 1


def cmd_kite_save_token(args: argparse.Namespace) -> int:
    try:
        access_token = exchange_request_token(args.request_token)
        save_access_token_to_env(access_token)
    except (ImportError, ValueError) as exc:
        print(f"Kite token exchange failed: {exc}")
        return 1
    print("Kite access token saved to .env.")
    return 0


def cmd_kite_selenium_token(args: argparse.Namespace) -> int:
    try:
        request_token = capture_request_token(args.timeout_seconds)
        access_token = exchange_request_token(request_token)
        save_access_token_to_env(access_token)
    except (ImportError, ValueError) as exc:
        print(f"Kite Selenium token flow failed: {exc}")
        return 1
    print("Kite access token saved to .env via Selenium login.")
    return 0


def cmd_auto_daily_run(args: argparse.Namespace) -> int:
    initialize_database()
    if args.history_lookback_days <= 0:
        print("--history-lookback-days must be greater than zero.")
        return 2
    today = date.today()
    calendar = WeekdayTradingCalendar()
    target_days = parse_target_days(config.AUTO_REBALANCE_TARGET_DAYS)
    rebalance_dates = rebalance_dates_for_month(today.year, today.month, target_days, calendar)
    print(f"Automation date: {today.isoformat()}")
    print(f"This month's rebalance dates: {', '.join(item.isoformat() for item in rebalance_dates)}")

    if not calendar.is_trading_day(today):
        print("Skipped: today is not a trading day under the provisional weekday calendar.")
        return 0

    try:
        token_valid, token_message = validate_saved_access_token()
        print(token_message)
        if args.selenium_token and not token_valid:
            print("Opening Selenium login to refresh Kite token...")
            request_token = capture_request_token(args.timeout_seconds)
            access_token = exchange_request_token(request_token)
            save_access_token_to_env(access_token)
            print("Kite access token saved for today.")

        print("Syncing universe...")
        report = sync_universe()
        print(f"Universe ready: {report['active_rows']} active symbols.")

        history_start_date = today - timedelta(days=args.history_lookback_days)
        print(f"Fetching recent Kite history from {history_start_date} to {today}...")
        fetch_result = fetch_and_store_history(
            start_date=history_start_date,
            end_date=today,
            symbols=args.symbols if args.symbols else None,
            include_benchmark=not args.no_benchmark,
        )
        print(
            f"Historical data refreshed: {fetch_result.stored_rows} rows stored "
            f"for {fetch_result.requested_symbols} requested symbols."
        )
    except (FileNotFoundError, ImportError, UniverseSyncError, ValueError) as exc:
        print(f"Daily automation failed: {exc}")
        return 1

    if is_rebalance_day(today, target_days, calendar):
        print("Today is a configured rebalance day. Running scheduled rebalance workflow...")
        return cmd_monthly_run(argparse.Namespace())

    print("Today is not a configured rebalance day. Data refresh complete; no rebalance run started.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dual-momentum")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db").set_defaults(func=cmd_init_db)
    subparsers.add_parser("show-config").set_defaults(func=cmd_show_config)
    subparsers.add_parser("sync-universe").set_defaults(func=cmd_sync_universe)
    subparsers.add_parser("manual-run").set_defaults(func=cmd_manual_run)
    subparsers.add_parser("monthly-run").set_defaults(func=cmd_monthly_run)

    backtest = subparsers.add_parser("backtest")
    backtest.add_argument("--years", type=int)
    backtest.add_argument("--start-date")
    backtest.add_argument("--end-date")
    backtest.add_argument("--initial-capital", type=float, default=1_000_000.0)
    backtest.set_defaults(func=cmd_backtest)

    run_backtest = subparsers.add_parser("run-backtest")
    run_backtest.add_argument("--start-date", required=True)
    run_backtest.add_argument("--end-date", required=True)
    run_backtest.add_argument("--initial-capital", type=float, default=1_000_000.0)
    run_backtest.add_argument("--lookback-days", type=int, default=450)
    run_backtest.add_argument("--symbols", nargs="*")
    run_backtest.add_argument("--no-benchmark", action="store_true")
    run_backtest.add_argument("--request-token")
    run_backtest.set_defaults(func=cmd_run_backtest)

    fetch_history = subparsers.add_parser("fetch-history")
    fetch_history.add_argument("--start-date", required=True)
    fetch_history.add_argument("--end-date", required=True)
    fetch_history.add_argument("--symbols", nargs="*")
    fetch_history.add_argument("--no-benchmark", action="store_true")
    fetch_history.add_argument("--request-token")
    fetch_history.set_defaults(func=cmd_fetch_history)

    subparsers.add_parser("kite-login-url").set_defaults(func=cmd_kite_login_url)
    subparsers.add_parser("kite-token-status").set_defaults(func=cmd_kite_token_status)

    kite_save_token = subparsers.add_parser("kite-save-token")
    kite_save_token.add_argument("--request-token", required=True)
    kite_save_token.set_defaults(func=cmd_kite_save_token)

    kite_selenium = subparsers.add_parser("kite-selenium-token")
    kite_selenium.add_argument("--timeout-seconds", type=int, default=config.SELENIUM_LOGIN_TIMEOUT_SECONDS)
    kite_selenium.set_defaults(func=cmd_kite_selenium_token)

    auto_daily = subparsers.add_parser("auto-daily-run")
    auto_daily.add_argument("--selenium-token", action="store_true")
    auto_daily.add_argument("--timeout-seconds", type=int, default=config.SELENIUM_LOGIN_TIMEOUT_SECONDS)
    auto_daily.add_argument("--history-lookback-days", type=int, default=config.AUTOMATION_HISTORY_LOOKBACK_DAYS)
    auto_daily.add_argument("--symbols", nargs="*")
    auto_daily.add_argument("--no-benchmark", action="store_true")
    auto_daily.set_defaults(func=cmd_auto_daily_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))
