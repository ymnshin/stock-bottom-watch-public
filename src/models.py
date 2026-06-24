from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Signal(str, Enum):
    UNTRACKED = "UNTRACKED"
    DANGER = "DANGER"
    WAIT = "WAIT"
    BUY_CANDIDATE = "BUY_CANDIDATE"
    MOMENTUM = "MOMENTUM"
    OVERHEATED = "OVERHEATED"
    NO_SIGNAL = "NO_SIGNAL"


@dataclass(frozen=True)
class Config:
    lookback_days: int = 260
    near_low_threshold: float = 0.03
    rsi_oversold: float = 30.0
    rsi_recover: float = 35.0
    volume_spike_multiplier: float = 2.0
    ma_short: int = 25
    ma_mid: int = 75
    ma_long: int = 200
    max_discord_items: int = 10
    show_momentum: bool = False
    show_overheated: bool = False
    ma25_overheat_threshold: float = 0.08
    fetch_batch_size: int = 100
    fetch_threads: bool = True
    use_history_cache: bool = True
    history_cache_dir: str = "data/history"
    discord_report_mode: str = "full"

    @classmethod
    def from_mapping(cls, values: dict[str, Any] | None) -> "Config":
        if not values:
            return cls()

        allowed = {item.name for item in cls.__dataclass_fields__.values()}
        filtered = {key: value for key, value in values.items() if key in allowed}
        return cls(**filtered)


@dataclass(frozen=True)
class WatchItem:
    ticker: str
    name: str
    theme: str
    avg_price: float | None = None
    memo: str = ""


@dataclass(frozen=True)
class StockMetrics:
    latest_close: float
    previous_close: float
    daily_return: float
    ma25: float | None
    ma75: float | None
    ma200: float | None
    previous_ma25: float | None
    rsi14: float | None
    previous_rsi14: float | None
    volume: int
    volume20: float | None
    volume_ratio: float | None
    low_52w: float | None
    distance_from_52w_low: float | None
    high_52w: float | None
    distance_from_52w_high: float | None
    drawdown_from_52w_high: float | None
    ytd_low: float | None
    distance_from_ytd_low: float | None
    low_20d: float | None
    distance_from_20d_low: float | None
    low_60d: float | None
    distance_from_60d_low: float | None
    high_20d: float | None
    high_60d: float | None
    above_ma25: bool
    above_ma75: bool
    above_ma200: bool
    near_52w_low: bool
    near_ytd_low: bool
    near_60d_low: bool
    near_20d_low: bool
    nearest_support_type: str | None
    nearest_support_distance: float | None
    is_new_52w_low: bool
    is_new_20d_low: bool
    is_new_60d_low: bool
    is_break_above_5d_high: bool


@dataclass(frozen=True)
class JudgeResult:
    signal: Signal
    reasons: list[str]
    action: str
    priority: int
    support_types: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class StockAnalysis:
    item: WatchItem
    metrics: StockMetrics
    judgement: JudgeResult
    previous_signal: Signal | None = None
    status_change_label: str | None = None
    status_change_note: str | None = None
    notes: list[str] = field(default_factory=list)
