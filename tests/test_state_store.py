from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from models import JudgeResult, Signal, StockAnalysis, StockMetrics, WatchItem
from state_store import (
    apply_status_changes,
    load_status_state,
    reset_status_state,
    save_status_state,
)


def test_first_run_signal_is_untracked_and_new() -> None:
    state = load_status_state(_state_path())

    updated = apply_status_changes([_analysis("9503.T", Signal.DANGER)], state)

    assert updated[0].previous_signal == Signal.UNTRACKED
    assert updated[0].status_change_label == "NEW"
    assert updated[0].status_change_note == "新規DANGER"


def test_first_run_no_signal_is_untracked_without_change_label() -> None:
    state = load_status_state(_state_path())

    updated = apply_status_changes([_analysis("9503.T", Signal.NO_SIGNAL)], state)

    assert updated[0].previous_signal == Signal.UNTRACKED
    assert updated[0].status_change_label is None
    assert updated[0].status_change_note is None


def test_existing_no_signal_to_danger_keeps_no_signal_previous_status() -> None:
    state_path = _state_path()
    try:
        save_status_state(
            state_path,
            [_analysis("9503.T", Signal.NO_SIGNAL)],
            load_status_state(state_path),
            ["9503.T"],
            datetime(2026, 5, 6, 15, 45),
        )
        loaded_state = load_status_state(state_path)
        updated = apply_status_changes([_analysis("9503.T", Signal.DANGER)], loaded_state)
    finally:
        _cleanup(state_path)

    assert updated[0].previous_signal == Signal.NO_SIGNAL
    assert updated[0].status_change_label == "NEW"
    assert updated[0].status_change_note == "新規DANGER"


def test_same_status_keeps_previous_status_without_change_label() -> None:
    updated = _changed_analysis(Signal.WAIT, Signal.WAIT)

    assert updated.previous_signal == Signal.WAIT
    assert updated.status_change_label is None
    assert updated.status_change_note is None


def test_new_ticker_in_existing_state_is_untracked() -> None:
    state_path = _state_path()
    try:
        save_status_state(
            state_path,
            [_analysis("9503.T", Signal.NO_SIGNAL)],
            load_status_state(state_path),
            ["9503.T"],
            datetime(2026, 5, 6, 15, 45),
        )
        loaded_state = load_status_state(state_path)
        updated = apply_status_changes([_analysis("7013.T", Signal.WAIT)], loaded_state)
    finally:
        _cleanup(state_path)

    assert updated[0].previous_signal == Signal.UNTRACKED
    assert updated[0].status_change_label == "NEW"
    assert updated[0].status_change_note == "新規WAIT"


def test_untracked_to_buy_candidate_is_new() -> None:
    state = load_status_state(_state_path())

    updated = apply_status_changes([_analysis("7013.T", Signal.BUY_CANDIDATE)], state)

    assert updated[0].previous_signal == Signal.UNTRACKED
    assert updated[0].status_change_label == "NEW"
    assert updated[0].status_change_note == "新規BUY_CANDIDATE"


def test_named_status_change_notes_are_changed() -> None:
    cases = [
        (Signal.WAIT, Signal.BUY_CANDIDATE, "反転候補として強調"),
        (Signal.MOMENTUM, Signal.DANGER, "トレンド崩れ警戒"),
        (Signal.DANGER, Signal.WAIT, "下落加速が一服"),
    ]

    for previous_signal, current_signal, expected_note in cases:
        updated = _changed_analysis(previous_signal, current_signal)

        assert updated.previous_signal == previous_signal
        assert updated.status_change_label == "CHANGED"
        assert updated.status_change_note == expected_note


def test_core_signal_to_no_signal_is_release_change() -> None:
    updated = _changed_analysis(Signal.BUY_CANDIDATE, Signal.NO_SIGNAL)

    assert updated.previous_signal == Signal.BUY_CANDIDATE
    assert updated.status_change_label == "CHANGED"
    assert updated.status_change_note == "解除"


def test_failed_ticker_keeps_previous_state_record() -> None:
    state_path = _state_path()
    try:
        initial_state = load_status_state(state_path)
        save_status_state(
            state_path,
            [_analysis("9503.T", Signal.WAIT), _analysis("7013.T", Signal.DANGER)],
            initial_state,
            ["9503.T", "7013.T"],
            datetime(2026, 5, 6, 15, 45),
        )
        previous_state = load_status_state(state_path)
        save_status_state(
            state_path,
            [_analysis("9503.T", Signal.BUY_CANDIDATE)],
            previous_state,
            ["9503.T", "7013.T"],
            datetime(2026, 5, 7, 15, 45),
        )
        loaded_state = load_status_state(state_path)
    finally:
        _cleanup(state_path)

    assert loaded_state.records["9503.T"].status == Signal.BUY_CANDIDATE
    assert loaded_state.records["7013.T"].status == Signal.DANGER


def test_reset_status_state_deletes_file() -> None:
    state_path = _state_path()
    try:
        save_status_state(
            state_path,
            [_analysis("9503.T", Signal.WAIT)],
            load_status_state(state_path),
            ["9503.T"],
            datetime(2026, 5, 6, 15, 45),
        )

        removed = reset_status_state(state_path)
        state = load_status_state(state_path)
    finally:
        _cleanup(state_path)

    assert removed is True
    assert state.exists is False


def _changed_analysis(previous_signal: Signal, current_signal: Signal) -> StockAnalysis:
    state_path = _state_path()
    try:
        save_status_state(
            state_path,
            [_analysis("9503.T", previous_signal)],
            load_status_state(state_path),
            ["9503.T"],
            datetime(2026, 5, 6, 15, 45),
        )
        loaded_state = load_status_state(state_path)
        updated = apply_status_changes([_analysis("9503.T", current_signal)], loaded_state)
    finally:
        _cleanup(state_path)
    return updated[0]


def _state_path() -> Path:
    return ROOT / "data" / f"test-state-{uuid4().hex}.json"


def _cleanup(path: Path) -> None:
    if path.exists():
        path.unlink()


def _analysis(ticker: str, signal: Signal) -> StockAnalysis:
    return StockAnalysis(
        item=WatchItem(ticker=ticker, name=ticker, theme=""),
        metrics=_metrics(),
        judgement=JudgeResult(
            signal=signal,
            reasons=["test"],
            action="test",
            priority=0,
        ),
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
