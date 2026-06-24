from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from app_service import _render_stock_watch_report, filter_analyses, parse_status_filter, summarize_for_interaction
from models import Config, JudgeResult, Signal, StockAnalysis, StockMetrics, WatchItem


def test_filter_analyses_by_ticker_and_status() -> None:
    analyses = [
        _analysis("9503.T", Signal.DANGER),
        _analysis("7013.T", Signal.WAIT),
        _analysis("8035.T", Signal.MOMENTUM),
    ]

    filtered = filter_analyses(analyses, ticker="7013.t", status="WAIT")

    assert len(filtered) == 1
    assert filtered[0].item.ticker == "7013.T"
    assert filtered[0].judgement.signal == Signal.WAIT


def test_parse_status_filter_rejects_no_signal() -> None:
    try:
        parse_status_filter("NO_SIGNAL")
    except ValueError as exc:
        assert "unsupported status" in str(exc)
    else:
        raise AssertionError("NO_SIGNAL should not be accepted for slash command filtering")


def test_summarize_for_interaction_keeps_content_under_limit() -> None:
    report = "A" * 5000

    summary = summarize_for_interaction(report, detail_posted=True, limit=1900)

    assert len(summary) <= 1900
    assert summary.startswith("詳細レポートをWebhookで投稿しました。")
    assert "長文のため省略" in summary


def test_buy_candidate_summary_mode_is_used_without_filters() -> None:
    analyses = [_analysis("4116.T", Signal.BUY_CANDIDATE), _analysis("8057.T", Signal.MOMENTUM)]

    report = _render_stock_watch_report(
        analyses=analyses,
        failures=[],
        config=Config(discord_report_mode="buy_candidates_summary"),
        report_date=date(2026, 5, 17),
        ticker=None,
        status=None,
    )

    assert "BUY_CANDIDATE一覧" in report
    assert "4116.T" in report
    assert "8057.T" not in report


def _analysis(ticker: str, signal: Signal) -> StockAnalysis:
    return StockAnalysis(
        item=WatchItem(ticker=ticker, name=ticker, theme=""),
        metrics=_metrics(),
        judgement=JudgeResult(signal=signal, reasons=["test"], action="test", priority=0),
    )


def _metrics() -> StockMetrics:
    return StockMetrics(
        latest_close=100.0,
        previous_close=99.0,
        daily_return=0.0101,
        ma25=95.0,
        ma75=90.0,
        ma200=85.0,
        previous_ma25=94.0,
        rsi14=50.0,
        previous_rsi14=48.0,
        volume=1000,
        volume20=1000.0,
        volume_ratio=1.0,
        low_52w=80.0,
        distance_from_52w_low=0.25,
        high_52w=110.0,
        distance_from_52w_high=-0.0909,
        drawdown_from_52w_high=0.0909,
        ytd_low=90.0,
        distance_from_ytd_low=0.1111,
        low_20d=96.0,
        distance_from_20d_low=0.0417,
        low_60d=92.0,
        distance_from_60d_low=0.087,
        high_20d=105.0,
        high_60d=108.0,
        above_ma25=True,
        above_ma75=True,
        above_ma200=True,
        near_52w_low=False,
        near_ytd_low=False,
        near_60d_low=False,
        near_20d_low=False,
        nearest_support_type="20日安値",
        nearest_support_distance=0.0417,
        is_new_52w_low=False,
        is_new_20d_low=False,
        is_new_60d_low=False,
        is_break_above_5d_high=False,
    )
