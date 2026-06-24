from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from data_fetcher import fetch_daily_histories, fetch_daily_history, load_watchlist
from indicators import calculate_metrics
from judge import judge_stock
from models import Config, Signal, StockAnalysis, WatchItem
from report import render_buy_candidate_summary, render_report
from state_store import StatusState, apply_status_changes, load_status_state, reset_status_state, save_status_state


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INTERACTION_RESPONSE_LIMIT = 1900
SLASH_STATUS_CHOICES = {
    Signal.DANGER,
    Signal.WAIT,
    Signal.BUY_CANDIDATE,
    Signal.MOMENTUM,
    Signal.OVERHEATED,
}


@dataclass(frozen=True)
class StockWatchResult:
    analyses: list[StockAnalysis]
    failures: list[str]
    report: str
    config: Config
    previous_state: StatusState
    watchlist_tickers: list[str]
    run_at: datetime


def run_stock_watch(
    config_path: Path = PROJECT_ROOT / "config.yaml",
    watchlist_path: Path = PROJECT_ROOT / "watchlist.csv",
    state_path: Path = PROJECT_ROOT / "data" / "state.json",
    ticker: str | None = None,
    status: str | None = None,
    reset_state: bool = False,
    write_history_cache: bool = True,
) -> StockWatchResult:
    config = load_config(config_path)
    watchlist = load_watchlist(watchlist_path)
    watchlist_tickers = [item.ticker for item in watchlist]
    if status:
        parse_status_filter(status)

    if reset_state:
        removed = reset_status_state(state_path)
        if removed:
            logging.info("Reset state: %s", state_path)
        else:
            logging.info("State file did not exist: %s", state_path)

    previous_state = load_status_state(state_path)
    target_items = _filter_watchlist_items(watchlist, ticker)

    history_result = fetch_daily_histories(
        [item.ticker for item in target_items],
        lookback_days=config.lookback_days,
        batch_size=config.fetch_batch_size,
        threads=config.fetch_threads,
        cache_dir=_history_cache_dir(config),
        write_cache=write_history_cache,
    )

    analyses: list[StockAnalysis] = []
    failures: list[str] = []
    for item in target_items:
        history = history_result.histories.get(item.ticker)
        if history is None:
            warning = f"{item.name} {item.ticker}: {history_result.failures.get(item.ticker, 'no daily data returned')}"
            logging.warning(warning)
            failures.append(warning)
            continue

        try:
            analyses.append(analyze_history(item, history, config))
        except Exception as exc:
            warning = f"{item.name} {item.ticker}: unexpected error: {exc}"
            logging.exception(warning)
            failures.append(warning)

    analyses = apply_status_changes(analyses, previous_state)
    analyses_for_report = filter_analyses(analyses, ticker=ticker, status=status)
    report_config = _report_config_for_filter(config, status)
    run_at = datetime.now(ZoneInfo("Asia/Tokyo"))
    report = _render_stock_watch_report(
        analyses=analyses_for_report,
        failures=failures,
        config=report_config,
        report_date=run_at.date(),
        ticker=ticker,
        status=status,
    )

    return StockWatchResult(
        analyses=analyses,
        failures=failures,
        report=report,
        config=config,
        previous_state=previous_state,
        watchlist_tickers=watchlist_tickers,
        run_at=run_at,
    )


def save_stock_watch_state(result: StockWatchResult, state_path: Path) -> None:
    save_status_state(
        state_path,
        result.analyses,
        result.previous_state,
        result.watchlist_tickers,
        result.run_at,
    )


def analyze_item(item: WatchItem, config: Config) -> StockAnalysis:
    history = fetch_daily_history(item.ticker, config.lookback_days)
    return analyze_history(item, history, config)


def analyze_history(item: WatchItem, history: pd.DataFrame, config: Config) -> StockAnalysis:
    metrics = calculate_metrics(history, config)
    judgement = judge_stock(metrics, config)
    return StockAnalysis(item=item, metrics=metrics, judgement=judgement)


def load_config(path: Path) -> Config:
    if not path.exists():
        raise FileNotFoundError(f"config not found: {path}")

    import yaml

    with path.open("r", encoding="utf-8") as file:
        raw_config = yaml.safe_load(file) or {}
    if not isinstance(raw_config, dict):
        raise ValueError("config.yaml must be a mapping")

    return Config.from_mapping(raw_config)


def filter_analyses(
    analyses: list[StockAnalysis],
    ticker: str | None = None,
    status: str | None = None,
) -> list[StockAnalysis]:
    result = analyses
    if ticker:
        ticker_upper = ticker.strip().upper()
        result = [analysis for analysis in result if analysis.item.ticker.upper() == ticker_upper]

    if status:
        signal = parse_status_filter(status)
        result = [analysis for analysis in result if analysis.judgement.signal == signal]

    return result


def parse_status_filter(status: str) -> Signal:
    normalized = status.strip().upper().replace(" ", "_")
    try:
        signal = Signal(normalized)
    except ValueError as exc:
        allowed = ", ".join(sorted(signal.value for signal in SLASH_STATUS_CHOICES))
        raise ValueError(f"unsupported status: {status}. allowed: {allowed}") from exc

    if signal not in SLASH_STATUS_CHOICES:
        allowed = ", ".join(sorted(signal.value for signal in SLASH_STATUS_CHOICES))
        raise ValueError(f"unsupported status: {status}. allowed: {allowed}")
    return signal


def summarize_for_interaction(
    report: str,
    detail_posted: bool = False,
    limit: int = INTERACTION_RESPONSE_LIMIT,
) -> str:
    prefix = "詳細レポートをWebhookで投稿しました。\n\n" if detail_posted else ""
    if len(prefix + report) <= limit:
        return prefix + report

    suffix = "\n\n...（長文のため省略）"
    available = max(0, limit - len(prefix) - len(suffix))
    return f"{prefix}{report[:available].rstrip()}{suffix}"


def _filter_watchlist_items(watchlist: list[WatchItem], ticker: str | None) -> list[WatchItem]:
    if not ticker:
        return watchlist

    ticker_upper = ticker.strip().upper()
    return [item for item in watchlist if item.ticker.upper() == ticker_upper]


def _report_config_for_filter(config: Config, status: str | None) -> Config:
    if not status:
        return config

    signal = parse_status_filter(status)
    if signal == Signal.MOMENTUM:
        return replace(config, show_momentum=True)
    if signal == Signal.OVERHEATED:
        return replace(config, show_overheated=True)
    return config


def _history_cache_dir(config: Config) -> Path | None:
    if not config.use_history_cache:
        return None

    cache_dir = Path(config.history_cache_dir)
    if not cache_dir.is_absolute():
        cache_dir = PROJECT_ROOT / cache_dir
    return cache_dir


def _render_stock_watch_report(
    analyses: list[StockAnalysis],
    failures: list[str],
    config: Config,
    report_date: date,
    ticker: str | None,
    status: str | None,
) -> str:
    if not ticker and not status and config.discord_report_mode == "buy_candidates_summary":
        return render_buy_candidate_summary(analyses, failures, report_date)
    return render_report(analyses, failures, config, report_date)
