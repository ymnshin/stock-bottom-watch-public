from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from judge import judge_stock
from models import Config, Signal, StockMetrics


def test_judge_danger_when_multiple_breakdown_conditions_match() -> None:
    metrics = replace(
        _base_metrics(),
        daily_return=-0.045,
        rsi14=24.0,
        volume_ratio=2.4,
        latest_close=88.0,
        ma25=100.0,
        ma75=105.0,
        above_ma25=False,
        above_ma75=False,
        is_new_20d_low=True,
        is_new_60d_low=True,
        drawdown_from_52w_high=0.40,
    )

    result = judge_stock(metrics, Config())

    assert result.signal == Signal.DANGER
    assert "終値が20日安値を更新" in result.reasons
    assert "安値を守るまで" not in result.action


def test_wait_reason_names_60d_low_when_52w_low_is_far() -> None:
    metrics = replace(
        _base_metrics(),
        latest_close=221.0,
        ma25=240.0,
        above_ma25=False,
        rsi14=42.0,
        low_52w=100.0,
        distance_from_52w_low=1.21,
        drawdown_from_52w_high=0.10,
        low_60d=216.0,
        distance_from_60d_low=0.023148,
        near_52w_low=False,
        near_60d_low=True,
        nearest_support_type="60日安値",
        nearest_support_distance=0.023148,
    )

    result = judge_stock(metrics, Config())

    assert result.signal == Signal.WAIT
    assert any("60日安値" in reason for reason in result.reasons)
    assert "52週安値ではなく、短期安値への接近" in result.reasons
    assert not any("52週安値" in reason and "3%" in reason for reason in result.reasons)


def test_rsi_over_70_becomes_overheated() -> None:
    metrics = replace(
        _base_metrics(),
        latest_close=120.0,
        ma25=105.0,
        above_ma25=True,
        rsi14=72.0,
    )

    result = judge_stock(metrics, Config())

    assert result.signal == Signal.OVERHEATED
    assert any("70以上" in reason for reason in result.reasons)


def test_above_ma25_ma75_with_rsi_50_becomes_momentum() -> None:
    metrics = replace(
        _base_metrics(),
        latest_close=120.0,
        ma25=110.0,
        ma75=105.0,
        above_ma25=True,
        above_ma75=True,
        rsi14=50.0,
        drawdown_from_52w_high=0.08,
    )

    result = judge_stock(metrics, Config())

    assert result.signal == Signal.MOMENTUM
    assert "底値候補ではなく上昇トレンド監視" in result.action


def test_buy_candidate_after_rsi_and_price_recovery() -> None:
    metrics = replace(
        _base_metrics(),
        latest_close=103.0,
        previous_close=100.0,
        daily_return=0.03,
        ma25=102.0,
        previous_ma25=101.0,
        above_ma25=True,
        previous_rsi14=28.0,
        rsi14=36.0,
        volume_ratio=1.2,
        distance_from_60d_low=0.03,
        distance_from_20d_low=0.03,
        near_60d_low=True,
        near_20d_low=True,
        is_break_above_5d_high=True,
    )

    result = judge_stock(metrics, Config())

    assert result.signal == Signal.BUY_CANDIDATE
    assert "60日安値" in result.support_types


def _base_metrics() -> StockMetrics:
    return StockMetrics(
        latest_close=100.0,
        previous_close=101.0,
        daily_return=-0.01,
        ma25=105.0,
        ma75=110.0,
        ma200=120.0,
        previous_ma25=104.0,
        rsi14=40.0,
        previous_rsi14=35.0,
        volume=1000,
        volume20=1000.0,
        volume_ratio=1.0,
        low_52w=90.0,
        distance_from_52w_low=0.11,
        high_52w=150.0,
        distance_from_52w_high=-0.33,
        drawdown_from_52w_high=0.33,
        ytd_low=90.0,
        distance_from_ytd_low=0.11,
        low_20d=95.0,
        distance_from_20d_low=0.0526,
        low_60d=92.0,
        distance_from_60d_low=0.087,
        high_20d=112.0,
        high_60d=125.0,
        above_ma25=False,
        above_ma75=False,
        above_ma200=False,
        near_52w_low=False,
        near_ytd_low=False,
        near_60d_low=False,
        near_20d_low=False,
        nearest_support_type="20日安値",
        nearest_support_distance=0.0526,
        is_new_52w_low=False,
        is_new_20d_low=False,
        is_new_60d_low=False,
        is_break_above_5d_high=False,
    )
