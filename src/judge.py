from __future__ import annotations

from models import Config, JudgeResult, Signal, StockMetrics


def judge_stock(metrics: StockMetrics, config: Config) -> JudgeResult:
    danger_reasons, danger_supports = _danger_reasons(metrics, config)
    if len(danger_reasons) >= 2:
        return JudgeResult(
            signal=Signal.DANGER,
            reasons=danger_reasons,
            action="底割れ危険。新規買いは抑え、材料・出来高・翌日以降の売り圧力を確認。",
            priority=50,
            support_types=danger_supports,
        )

    buy_reasons, buy_supports = _buy_candidate_reasons(metrics, config)
    if buy_reasons:
        return JudgeResult(
            signal=Signal.BUY_CANDIDATE,
            reasons=buy_reasons,
            action="初期底打ち候補。打診買い候補ですが、一括買いは避け、出来高と終値の継続を確認。",
            priority=40,
            support_types=buy_supports,
        )

    wait_reasons, wait_supports = _wait_reasons(metrics, config)
    if wait_reasons:
        return JudgeResult(
            signal=Signal.WAIT,
            reasons=wait_reasons,
            action="安いがまだ形が悪いです。反転確認待ちで、25日線回復を確認するまで待機。",
            priority=30,
            support_types=wait_supports,
        )

    overheated_reasons = _overheated_reasons(metrics, config)
    if overheated_reasons:
        return JudgeResult(
            signal=Signal.OVERHEATED,
            reasons=overheated_reasons,
            action="底値候補ではなく短期過熱。追いかけ買いは避け、25日線との乖離縮小を待つ。",
            priority=20,
        )

    momentum_reasons = _momentum_reasons(metrics)
    if momentum_reasons:
        return JudgeResult(
            signal=Signal.MOMENTUM,
            reasons=momentum_reasons,
            action="底値候補ではなく上昇トレンド監視。押し目は25日線との距離と出来高を確認。",
            priority=10,
        )

    return JudgeResult(
        signal=Signal.NO_SIGNAL,
        reasons=["底値候補、上昇トレンド、短期過熱のいずれにも該当しない"],
        action="通知対象外。",
        priority=0,
    )


def _danger_reasons(metrics: StockMetrics, config: Config) -> tuple[list[str], list[str]]:
    reasons: list[str] = []
    support_types: list[str] = []

    if metrics.is_new_20d_low:
        reasons.append("終値が20日安値を更新")
        support_types.append("20日安値")
    if metrics.is_new_60d_low:
        reasons.append("終値が60日安値を更新")
        support_types.append("60日安値")
    if not metrics.above_ma25 and not metrics.above_ma75 and metrics.ma25 is not None and metrics.ma75 is not None:
        reasons.append("25日線と75日線を両方下回る")
    if metrics.volume_ratio is not None and metrics.volume_ratio >= config.volume_spike_multiplier:
        reasons.append(f"出来高倍率が{metrics.volume_ratio:.1f}倍")
    if metrics.daily_return <= -0.03:
        reasons.append(f"前日比{metrics.daily_return:.2%}")
    if metrics.rsi14 is not None and metrics.rsi14 < 35:
        reasons.append(f"RSI {metrics.rsi14:.1f}で35未満")
    if metrics.drawdown_from_52w_high is not None and metrics.drawdown_from_52w_high >= 0.20:
        reasons.append(f"52週高値からの下落率{metrics.drawdown_from_52w_high:.2%}")

    return reasons, _unique(support_types)


def _buy_candidate_reasons(metrics: StockMetrics, config: Config) -> tuple[list[str], list[str]]:
    support_types = _near_short_support_types(metrics, config.near_low_threshold * 2)
    rebounding_from_short_low = bool(support_types) and metrics.daily_return > 0
    rsi_improved = _rsi_recovered_or_improved(metrics, config)
    ma25_recovered = _recovered_ma25(metrics)
    price_confirmation = metrics.is_break_above_5d_high or ma25_recovered
    volume_confirmation = metrics.volume_ratio is not None and metrics.volume_ratio >= 1.0

    if not (rebounding_from_short_low and rsi_improved and price_confirmation and volume_confirmation):
        return [], []

    reasons = [f"{'・'.join(support_types)}から反発"]
    if metrics.previous_rsi14 is not None and metrics.rsi14 is not None:
        reasons.append(f"RSIが{metrics.previous_rsi14:.1f}から{metrics.rsi14:.1f}へ改善")
    if metrics.is_break_above_5d_high:
        reasons.append("終値が5日高値を上抜け")
    if ma25_recovered:
        reasons.append("終値が25日線を回復")
    reasons.append("出来高が20日平均以上")
    return reasons, support_types


def _wait_reasons(metrics: StockMetrics, config: Config) -> tuple[list[str], list[str]]:
    support_types = _near_wait_support_types(metrics, config.near_low_threshold)
    below_ma25 = metrics.ma25 is not None and not metrics.above_ma25
    low_rsi = metrics.rsi14 is not None and metrics.rsi14 < 45

    if not (support_types and below_ma25 and low_rsi):
        return [], []

    reasons = [_distance_reason(metrics, support_type) for support_type in support_types]
    if not metrics.near_52w_low and any(item in support_types for item in ("60日安値", "20日安値", "年初来安値")):
        reasons.append("52週安値ではなく、短期安値への接近")
    reasons.append("25日線をまだ回復していない")
    reasons.append(f"RSI {metrics.rsi14:.1f}で45未満")
    return reasons, support_types


def _overheated_reasons(metrics: StockMetrics, config: Config) -> list[str]:
    if metrics.rsi14 is None or metrics.rsi14 < 70:
        return []

    reasons = [f"RSI {metrics.rsi14:.1f}で70以上"]
    ma25_distance = _distance_from_ma(metrics.latest_close, metrics.ma25)
    if ma25_distance is not None and ma25_distance >= config.ma25_overheat_threshold:
        reasons.append(f"25日線から{ma25_distance:+.2%}乖離")
    elif metrics.above_ma25:
        reasons.append("25日線を上回る")
    return reasons


def _momentum_reasons(metrics: StockMetrics) -> list[str]:
    if not (metrics.above_ma25 and metrics.above_ma75):
        return []
    if metrics.rsi14 is None or not (45 <= metrics.rsi14 < 70):
        return []
    if metrics.drawdown_from_52w_high is None or metrics.drawdown_from_52w_high > 0.15:
        return []

    return [
        "25日線と75日線の上にいる",
        f"RSI {metrics.rsi14:.1f}で45から70の範囲",
        f"52週高値からの下落率{metrics.drawdown_from_52w_high:.2%}",
    ]


def _near_wait_support_types(metrics: StockMetrics, threshold: float) -> list[str]:
    supports: list[str] = []
    if _near(metrics.distance_from_ytd_low, threshold):
        supports.append("年初来安値")
    if _near(metrics.distance_from_60d_low, threshold):
        supports.append("60日安値")
    if _near(metrics.distance_from_20d_low, threshold):
        supports.append("20日安値")
    return supports


def _near_short_support_types(metrics: StockMetrics, threshold: float) -> list[str]:
    supports: list[str] = []
    if _near(metrics.distance_from_60d_low, threshold):
        supports.append("60日安値")
    if _near(metrics.distance_from_20d_low, threshold):
        supports.append("20日安値")
    return supports


def _distance_reason(metrics: StockMetrics, support_type: str) -> str:
    distance_by_type = {
        "年初来安値": metrics.distance_from_ytd_low,
        "60日安値": metrics.distance_from_60d_low,
        "20日安値": metrics.distance_from_20d_low,
    }
    distance = distance_by_type.get(support_type)
    if distance is None:
        return f"{support_type}に接近"
    return f"{support_type}から{distance:+.2%}"


def _near(distance: float | None, threshold: float) -> bool:
    return distance is not None and 0 <= distance <= threshold


def _rsi_recovered_or_improved(metrics: StockMetrics, config: Config) -> bool:
    if metrics.rsi14 is None:
        return False
    if metrics.previous_rsi14 is None:
        return metrics.rsi14 >= 40
    recovered_from_oversold = metrics.previous_rsi14 < config.rsi_oversold and metrics.rsi14 >= config.rsi_recover
    improved_to_40 = metrics.rsi14 >= 40 and metrics.rsi14 > metrics.previous_rsi14
    return recovered_from_oversold or improved_to_40


def _recovered_ma25(metrics: StockMetrics) -> bool:
    if metrics.ma25 is None or metrics.latest_close < metrics.ma25:
        return False
    if metrics.previous_ma25 is None:
        return True
    return metrics.previous_close < metrics.previous_ma25


def _distance_from_ma(close: float, ma_value: float | None) -> float | None:
    if ma_value is None or ma_value == 0:
        return None
    return (close - ma_value) / ma_value


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
