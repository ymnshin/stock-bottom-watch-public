from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from models import Config, JudgeResult, Signal, StockAnalysis, StockMetrics, WatchItem
from report import render_buy_candidate_summary, render_report


def test_report_does_not_contradict_ihi_style_wait_reason() -> None:
    analysis = StockAnalysis(
        item=WatchItem("7013.T", "IHI", "重工・原子力"),
        metrics=_metrics(distance_from_52w_low=1.21, distance_from_60d_low=0.02),
        judgement=JudgeResult(
            signal=Signal.WAIT,
            reasons=["60日安値から+2.00%", "52週安値ではなく、短期安値への接近", "25日線をまだ回復していない"],
            action="安いがまだ形が悪いです。",
            priority=30,
            support_types=["60日安値"],
        ),
    )

    report = render_report([analysis], [], Config(), date(2026, 5, 6))

    assert "52週安値からの距離: +121.00%" in report
    assert "判定安値: 60日安値" in report
    assert "60日安値から+2.00%" in report
    assert "52週安値または年初来安値から3%以内" not in report


def test_no_signal_is_not_rendered_in_discord_report() -> None:
    no_signal = StockAnalysis(
        item=WatchItem("8035.T", "東京エレクトロン", "半導体装置"),
        metrics=_metrics(),
        judgement=JudgeResult(
            signal=Signal.NO_SIGNAL,
            reasons=["通知対象外"],
            action="通知対象外。",
            priority=0,
        ),
    )

    report = render_report([no_signal], [], Config(), date(2026, 5, 6))

    assert "東京エレクトロン" not in report
    assert "非表示のNO_SIGNAL銘柄数: 1" in report


def test_buy_candidate_summary_lists_only_buy_candidates() -> None:
    analyses = [
        _analysis("4116.T", "Dainichiseika", Signal.BUY_CANDIDATE),
        _analysis("1518.T", "Mitsui Matsushima", Signal.BUY_CANDIDATE),
        _analysis("8057.T", "Uchida Yoko", Signal.MOMENTUM),
        _analysis("4324.T", "Dentsu", Signal.DANGER),
    ]

    report = render_buy_candidate_summary(analyses, [], date(2026, 5, 17))

    assert "底値圏の深掘り候補: 2件" in report
    assert "Dainichiseika 4116.T" in report
    assert "Mitsui Matsushima 1518.T" in report
    assert "Uchida Yoko" not in report
    assert "Dentsu" not in report
    assert "買い指示ではなく" in report


def test_new_status_change_is_emphasized_with_previous_status() -> None:
    analysis = StockAnalysis(
        item=WatchItem("9503.T", "関西電力", "電力・原子力"),
        metrics=_metrics(),
        judgement=JudgeResult(
            signal=Signal.DANGER,
            reasons=["終値が60日安値を更新", "RSI 32.0で35未満"],
            action="底割れ危険。",
            priority=50,
            support_types=["60日安値"],
        ),
        previous_signal=Signal.NO_SIGNAL,
        status_change_label="NEW",
        status_change_note="新規DANGER",
    )

    report = render_report([analysis], [], Config(), date(2026, 5, 6))

    assert "🔔 **NEW 🟥 DANGER 関西電力 9503.T**" in report
    assert "ステータス変化: **NO_SIGNAL → DANGER**（新規DANGER）" in report
    assert "previous_status: NO_SIGNAL" in report


def test_same_status_renders_previous_status_without_emphasis() -> None:
    analysis = StockAnalysis(
        item=WatchItem("9503.T", "Kansai Electric", "Power"),
        metrics=_metrics(),
        judgement=JudgeResult(
            signal=Signal.WAIT,
            reasons=["test"],
            action="test",
            priority=30,
            support_types=["20d low"],
        ),
        previous_signal=Signal.WAIT,
    )

    report = render_report([analysis], [], Config(), date(2026, 5, 6))

    assert "WAIT Kansai Electric 9503.T" in report
    assert "previous_status: WAIT" in report
    assert "**NEW" not in report
    assert "**CHANGED" not in report


def test_danger_with_positive_three_percent_return_adds_rebound_note() -> None:
    analysis = StockAnalysis(
        item=WatchItem("7013.T", "IHI", "Heavy Industry"),
        metrics=_metrics(daily_return=0.0573, above_ma25=False, above_ma75=False),
        judgement=JudgeResult(
            signal=Signal.DANGER,
            reasons=["test"],
            action="test",
            priority=50,
            support_types=["60d low"],
        ),
    )

    report = render_report([analysis], [], Config(), date(2026, 5, 6))

    assert "補足: 前日比+5.73%で反発。" in report
    assert "ただし25日線・75日線を回復していないためDANGER継続。" in report
    assert "DANGER IHI 7013.T" in report


def test_non_danger_with_positive_three_percent_return_has_no_rebound_note() -> None:
    analysis = StockAnalysis(
        item=WatchItem("7013.T", "IHI", "Heavy Industry"),
        metrics=_metrics(daily_return=0.0573, above_ma25=False, above_ma75=False),
        judgement=JudgeResult(
            signal=Signal.WAIT,
            reasons=["test"],
            action="test",
            priority=30,
            support_types=["60d low"],
        ),
    )

    report = render_report([analysis], [], Config(), date(2026, 5, 6))

    assert "補足:" not in report


def test_untracked_status_change_uses_unrecorded_display() -> None:
    analysis = StockAnalysis(
        item=WatchItem("9503.T", "関西電力", "電力・原子力"),
        metrics=_metrics(),
        judgement=JudgeResult(
            signal=Signal.WAIT,
            reasons=["60日安値から+2.00%"],
            action="反転確認待ち。",
            priority=30,
            support_types=["60日安値"],
        ),
        previous_signal=Signal.UNTRACKED,
        status_change_label="NEW",
        status_change_note="新規WAIT",
    )

    report = render_report([analysis], [], Config(), date(2026, 5, 6))

    assert "🔔 **NEW 🟨 WAIT 関西電力 9503.T**" in report
    assert "ステータス変化: **未記録 → WAIT**（新規WAIT）" in report
    assert "previous_status: UNTRACKED" in report


def test_untracked_to_no_signal_is_not_rendered() -> None:
    analysis = StockAnalysis(
        item=WatchItem("9503.T", "関西電力", "電力・原子力"),
        metrics=_metrics(),
        judgement=JudgeResult(
            signal=Signal.NO_SIGNAL,
            reasons=["通知対象外"],
            action="通知対象外。",
            priority=0,
        ),
        previous_signal=Signal.UNTRACKED,
    )

    report = render_report([analysis], [], Config(), date(2026, 5, 6))

    assert "関西電力" not in report
    assert "非表示のNO_SIGNAL銘柄数: 1" in report


def test_release_to_no_signal_is_rendered() -> None:
    analysis = StockAnalysis(
        item=WatchItem("9503.T", "関西電力", "電力・原子力"),
        metrics=_metrics(),
        judgement=JudgeResult(
            signal=Signal.NO_SIGNAL,
            reasons=["底値候補、上昇トレンド、短期過熱のいずれにも該当しない"],
            action="通知対象外。",
            priority=0,
        ),
        previous_signal=Signal.DANGER,
        status_change_label="CHANGED",
        status_change_note="解除",
    )

    report = render_report([analysis], [], Config(), date(2026, 5, 6))

    assert "🔔 **CHANGED / 解除 ⬜ NO_SIGNAL 関西電力 9503.T**" in report
    assert "ステータス変化: **DANGER → NO_SIGNAL**（解除）" in report
    assert "非表示のNO_SIGNAL銘柄数: 0" in report


def _analysis(ticker: str, name: str, signal: Signal) -> StockAnalysis:
    return StockAnalysis(
        item=WatchItem(ticker=ticker, name=name, theme=""),
        metrics=_metrics(),
        judgement=JudgeResult(
            signal=signal,
            reasons=["test"],
            action="test",
            priority=0,
        ),
    )


def _metrics(
    distance_from_52w_low: float = 0.50,
    distance_from_60d_low: float = 0.10,
    daily_return: float = -0.0178,
    above_ma25: bool = False,
    above_ma75: bool = False,
) -> StockMetrics:
    return StockMetrics(
        latest_close=221.0,
        previous_close=225.0,
        daily_return=daily_return,
        ma25=240.0,
        ma75=230.0,
        ma200=200.0,
        previous_ma25=238.0,
        rsi14=42.0,
        previous_rsi14=44.0,
        volume=1000,
        volume20=1000.0,
        volume_ratio=1.0,
        low_52w=100.0,
        distance_from_52w_low=distance_from_52w_low,
        high_52w=300.0,
        distance_from_52w_high=-0.2633,
        drawdown_from_52w_high=0.2633,
        ytd_low=216.0,
        distance_from_ytd_low=0.0231,
        low_20d=218.0,
        distance_from_20d_low=0.0138,
        low_60d=216.0,
        distance_from_60d_low=distance_from_60d_low,
        high_20d=250.0,
        high_60d=270.0,
        above_ma25=above_ma25,
        above_ma75=above_ma75,
        above_ma200=True,
        near_52w_low=False,
        near_ytd_low=True,
        near_60d_low=distance_from_60d_low <= 0.03,
        near_20d_low=True,
        nearest_support_type="20日安値",
        nearest_support_distance=0.0138,
        is_new_52w_low=False,
        is_new_20d_low=False,
        is_new_60d_low=False,
        is_break_above_5d_high=False,
    )
