from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from indicators import calculate_metrics, calculate_rsi, moving_average
from models import Config


def test_moving_average_uses_full_window() -> None:
    series = pd.Series([1, 2, 3, 4, 5], dtype=float)

    result = moving_average(series, 3)

    assert pd.isna(result.iloc[1])
    assert result.iloc[-1] == 4


def test_rsi_is_bounded_after_warmup() -> None:
    close = pd.Series([10, 9, 8, 9, 10, 11, 10, 12, 13, 12, 14, 15, 14, 16, 17, 18])

    result = calculate_rsi(close)

    assert 0 <= result.dropna().iloc[-1] <= 100


def test_calculate_metrics_detects_new_60d_low_and_volume_ratio() -> None:
    closes = [100.0] * 80 + [94.0, 93.0]
    volumes = [1000] * 81 + [2500]
    frame = _make_frame(closes, volumes)

    metrics = calculate_metrics(frame, Config(ma_short=5, ma_mid=10, ma_long=20))

    assert metrics.latest_close == 93.0
    assert metrics.previous_close == 94.0
    assert metrics.low_20d == 92.0
    assert metrics.distance_from_20d_low is not None
    assert metrics.is_new_60d_low is True
    assert metrics.is_new_20d_low is True
    assert metrics.volume_ratio is not None
    assert metrics.volume_ratio > 2


def _make_frame(closes: list[float], volumes: list[int]) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=len(closes), freq="B")
    return pd.DataFrame(
        {
            "Close": closes,
            "High": [value + 1 for value in closes],
            "Low": [value - 1 for value in closes],
            "Volume": volumes,
        },
        index=dates,
    )
