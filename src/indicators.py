from __future__ import annotations

import math

import pandas as pd

from models import Config, StockMetrics


REQUIRED_OHLCV_COLUMNS = {"Close", "High", "Low", "Volume"}
SUPPORT_LABELS = {
    "52w": "52週安値",
    "ytd": "年初来安値",
    "60d": "60日安値",
    "20d": "20日安値",
}


def moving_average(series: pd.Series, window: int) -> pd.Series:
    return series.astype(float).rolling(window=window, min_periods=window).mean()


def calculate_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    close = close.astype(float)
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.mask((avg_loss == 0) & (avg_gain > 0), 100)
    rsi = rsi.mask((avg_loss == 0) & (avg_gain == 0), 50)
    return rsi


def calculate_metrics(frame: pd.DataFrame, config: Config) -> StockMetrics:
    prepared = _prepare_ohlcv(frame)
    if len(prepared) < 2:
        raise ValueError("at least two daily rows are required")

    close = prepared["Close"].astype(float)
    high = prepared["High"].astype(float)
    low = prepared["Low"].astype(float)
    volume = prepared["Volume"].fillna(0).astype(float)

    ma_short = moving_average(close, config.ma_short)
    ma_mid = moving_average(close, config.ma_mid)
    ma_long = moving_average(close, config.ma_long)
    rsi = calculate_rsi(close, period=14)
    volume20 = moving_average(volume, 20)

    latest_close = float(close.iloc[-1])
    previous_close = float(close.iloc[-2])
    daily_return = _safe_rate(latest_close, previous_close)

    latest_volume = int(volume.iloc[-1])
    latest_volume20 = _last_float(volume20)
    volume_ratio = None
    if latest_volume20 is not None and latest_volume20 > 0:
        volume_ratio = latest_volume / latest_volume20

    lookback_window = max(1, min(config.lookback_days, len(prepared)))
    low_52w = _window_min(low.tail(lookback_window))
    previous_low_52w = _window_min(low.iloc[:-1].tail(lookback_window))
    high_52w = _window_max(high.tail(lookback_window))

    low_20d = _window_min(low.tail(min(20, len(prepared))))
    previous_low_20d = _window_min(low.iloc[:-1].tail(min(20, max(1, len(prepared) - 1))))
    low_60d = _window_min(low.tail(min(60, len(prepared))))
    previous_low_60d = _window_min(low.iloc[:-1].tail(min(60, max(1, len(prepared) - 1))))
    high_20d = _window_max(high.tail(min(20, len(prepared))))
    high_60d = _window_max(high.tail(min(60, len(prepared))))

    latest_date = prepared.index[-1]
    ytd_low = _calculate_ytd_low(low, latest_date)
    prior_5d_high = _window_max(high.iloc[:-1].tail(5))

    latest_ma25 = _last_float(ma_short)
    latest_ma75 = _last_float(ma_mid)
    latest_ma200 = _last_float(ma_long)
    distance_from_52w_low = _safe_rate(latest_close, low_52w)
    distance_from_ytd_low = _safe_rate(latest_close, ytd_low)
    distance_from_20d_low = _safe_rate(latest_close, low_20d)
    distance_from_60d_low = _safe_rate(latest_close, low_60d)
    nearest_support_type, nearest_support_distance = _nearest_support(
        {
            SUPPORT_LABELS["52w"]: distance_from_52w_low,
            SUPPORT_LABELS["ytd"]: distance_from_ytd_low,
            SUPPORT_LABELS["60d"]: distance_from_60d_low,
            SUPPORT_LABELS["20d"]: distance_from_20d_low,
        }
    )

    return StockMetrics(
        latest_close=latest_close,
        previous_close=previous_close,
        daily_return=daily_return,
        ma25=latest_ma25,
        ma75=latest_ma75,
        ma200=latest_ma200,
        previous_ma25=_previous_float(ma_short),
        rsi14=_last_float(rsi),
        previous_rsi14=_previous_float(rsi),
        volume=latest_volume,
        volume20=latest_volume20,
        volume_ratio=volume_ratio,
        low_52w=low_52w,
        distance_from_52w_low=distance_from_52w_low,
        high_52w=high_52w,
        distance_from_52w_high=_safe_rate(latest_close, high_52w),
        drawdown_from_52w_high=_drawdown(latest_close, high_52w),
        ytd_low=ytd_low,
        distance_from_ytd_low=distance_from_ytd_low,
        low_20d=low_20d,
        distance_from_20d_low=distance_from_20d_low,
        low_60d=low_60d,
        distance_from_60d_low=distance_from_60d_low,
        high_20d=high_20d,
        high_60d=high_60d,
        above_ma25=_at_or_above(latest_close, latest_ma25),
        above_ma75=_at_or_above(latest_close, latest_ma75),
        above_ma200=_at_or_above(latest_close, latest_ma200),
        near_52w_low=_near(distance_from_52w_low, config.near_low_threshold),
        near_ytd_low=_near(distance_from_ytd_low, config.near_low_threshold),
        near_60d_low=_near(distance_from_60d_low, config.near_low_threshold),
        near_20d_low=_near(distance_from_20d_low, config.near_low_threshold),
        nearest_support_type=nearest_support_type,
        nearest_support_distance=nearest_support_distance,
        is_new_52w_low=_is_close_below_reference(latest_close, previous_low_52w),
        is_new_20d_low=_is_close_below_reference(latest_close, previous_low_20d),
        is_new_60d_low=_is_close_below_reference(latest_close, previous_low_60d),
        is_break_above_5d_high=prior_5d_high is not None and latest_close > prior_5d_high,
    )


def _prepare_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        raise ValueError("price history is empty")

    prepared = frame.copy()
    if isinstance(prepared.columns, pd.MultiIndex):
        prepared.columns = prepared.columns.get_level_values(0)

    rename_map = {}
    for column in prepared.columns:
        normalized = str(column).strip().lower()
        if normalized == "close":
            rename_map[column] = "Close"
        elif normalized == "high":
            rename_map[column] = "High"
        elif normalized == "low":
            rename_map[column] = "Low"
        elif normalized == "volume":
            rename_map[column] = "Volume"

    prepared = prepared.rename(columns=rename_map)
    missing = REQUIRED_OHLCV_COLUMNS - set(prepared.columns)
    if missing:
        missing_columns = ", ".join(sorted(missing))
        raise ValueError(f"price history missing columns: {missing_columns}")

    prepared = prepared.sort_index()
    prepared = prepared.dropna(subset=["Close", "High", "Low"])
    return prepared[["Close", "High", "Low", "Volume"]]


def _last_float(series: pd.Series) -> float | None:
    if series.empty:
        return None
    value = series.iloc[-1]
    return _float_or_none(value)


def _previous_float(series: pd.Series) -> float | None:
    if len(series) < 2:
        return None
    value = series.iloc[-2]
    return _float_or_none(value)


def _float_or_none(value: object) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None

    if math.isnan(numeric) or math.isinf(numeric):
        return None
    return numeric


def _safe_rate(current: float, reference: float | None) -> float | None:
    if reference is None or reference == 0:
        return None
    return (current - reference) / reference


def _drawdown(current: float, high_value: float | None) -> float | None:
    if high_value is None or high_value == 0:
        return None
    return max(0.0, (high_value - current) / high_value)


def _window_min(series: pd.Series) -> float | None:
    if series.empty:
        return None
    return _float_or_none(series.min())


def _window_max(series: pd.Series) -> float | None:
    if series.empty:
        return None
    return _float_or_none(series.max())


def _is_close_below_reference(close: float, reference: float | None) -> bool:
    return reference is not None and close <= reference


def _calculate_ytd_low(low: pd.Series, latest_date: object) -> float | None:
    if not hasattr(latest_date, "year"):
        return _window_min(low)

    current_year = latest_date.year
    ytd = low[low.index.map(lambda value: getattr(value, "year", None) == current_year)]
    if ytd.empty:
        return _window_min(low)
    return _window_min(ytd)


def _at_or_above(value: float, reference: float | None) -> bool:
    return reference is not None and value >= reference


def _near(distance: float | None, threshold: float) -> bool:
    return distance is not None and 0 <= distance <= threshold


def _nearest_support(distances: dict[str, float | None]) -> tuple[str | None, float | None]:
    valid_distances = [
        (label, distance)
        for label, distance in distances.items()
        if distance is not None and distance >= 0
    ]
    if not valid_distances:
        return None, None
    return min(valid_distances, key=lambda item: item[1])
