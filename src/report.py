from __future__ import annotations

from datetime import date

from models import Config, Signal, StockAnalysis
from state_store import is_release_to_no_signal


STATUS_EMOJI = {
    Signal.UNTRACKED: "▫️",
    Signal.DANGER: "🟥",
    Signal.WAIT: "🟨",
    Signal.BUY_CANDIDATE: "🟦",
    Signal.MOMENTUM: "🟩",
    Signal.OVERHEATED: "🟧",
    Signal.NO_SIGNAL: "⬜",
}


def render_report(
    analyses: list[StockAnalysis],
    failures: list[str],
    config: Config,
    report_date: date,
) -> str:
    displayable = [analysis for analysis in analyses if _should_display(analysis, config)]
    sorted_items = sorted(
        displayable,
        key=lambda item: (
            _change_sort_key(item),
            -item.judgement.priority,
            _sort_distance(item.metrics.nearest_support_distance),
            item.item.ticker,
        ),
    )
    selected = sorted_items[: config.max_discord_items]
    omitted_count = max(0, len(sorted_items) - len(selected))
    hidden_no_signal_count = sum(
        1
        for analysis in analyses
        if analysis.judgement.signal == Signal.NO_SIGNAL and not _should_display(analysis, config)
    )

    lines = [f"📉 Stock Bottom Watch - {report_date.isoformat()}", ""]

    if selected:
        for analysis in selected:
            lines.extend(_render_analysis(analysis))
            lines.append("")
    else:
        lines.append("表示対象のシグナルはありません。")
        lines.append("")

    if omitted_count:
        lines.append(f"表示上限により、ほか {omitted_count} 件は省略しました。")
        lines.append("")

    lines.append(f"非表示のNO_SIGNAL銘柄数: {hidden_no_signal_count}")
    lines.append("")

    if failures:
        lines.append("⚠️ 取得失敗銘柄")
        lines.extend(f"- {failure}" for failure in failures)
        lines.append("")

    lines.append("注意: この通知は投資助言ではなく、監視・分析補助のルール判定です。")
    return "\n".join(lines).strip()


def render_buy_candidate_summary(
    analyses: list[StockAnalysis],
    failures: list[str],
    report_date: date,
) -> str:
    candidates = sorted(
        [analysis for analysis in analyses if analysis.judgement.signal == Signal.BUY_CANDIDATE],
        key=lambda item: item.item.ticker,
    )

    lines = [
        f"🟦 Stock Bottom Watch - BUY_CANDIDATE一覧 - {report_date.isoformat()}",
        "",
        f"底値圏の深掘り候補: {len(candidates)}件",
        "",
    ]

    if candidates:
        lines.extend(
            f"{index}. {analysis.item.name} {analysis.item.ticker}"
            for index, analysis in enumerate(candidates, start=1)
        )
    else:
        lines.append("BUY_CANDIDATEはありません。")

    lines.append("")
    if failures:
        lines.append(f"取得失敗銘柄: {len(failures)}件")
        lines.append("")

    lines.append(
        "注意: BUY_CANDIDATEは買い指示ではなく、底値圏に来たため深掘り候補に入れるシグナルです。"
    )
    return "\n".join(lines).strip()


def _should_display(analysis: StockAnalysis, config: Config) -> bool:
    signal = analysis.judgement.signal
    if signal in {Signal.DANGER, Signal.WAIT, Signal.BUY_CANDIDATE}:
        return True
    if signal == Signal.NO_SIGNAL:
        return is_release_to_no_signal(analysis.previous_signal, signal)
    if signal == Signal.MOMENTUM:
        return config.show_momentum
    if signal == Signal.OVERHEATED:
        return config.show_overheated
    return False


def _render_analysis(analysis: StockAnalysis) -> list[str]:
    signal = analysis.judgement.signal
    metrics = analysis.metrics
    item = analysis.item
    reason_text = "、".join(analysis.judgement.reasons)

    return [
        _header(analysis),
        *_status_change_lines(analysis),
        f"previous_status: {_previous_status(analysis)}",
        f"テーマ: {item.theme or '-'}",
        f"株価: {_yen(metrics.latest_close)}",
        f"前日比: {_percent(metrics.daily_return)}",
        *_danger_rebound_lines(analysis),
        f"52週安値からの距離: {_percent(metrics.distance_from_52w_low)}",
        f"年初来安値からの距離: {_percent(metrics.distance_from_ytd_low)}",
        f"60日安値からの距離: {_percent(metrics.distance_from_60d_low)}",
        f"52週高値からの下落率: {_plain_percent(metrics.drawdown_from_52w_high)}",
        f"判定安値: {_support_types(analysis)}",
        f"最寄り安値: {_nearest_support(metrics.nearest_support_type, metrics.nearest_support_distance)}",
        f"RSI: {_number(metrics.rsi14, digits=1)}",
        f"25日線: {_yen(metrics.ma25)}",
        f"75日線: {_yen(metrics.ma75)}",
        f"出来高倍率: {_ratio(metrics.volume_ratio)}",
        f"判定理由: {reason_text}",
        f"アクション: {analysis.judgement.action}",
    ]


def _danger_rebound_lines(analysis: StockAnalysis) -> list[str]:
    metrics = analysis.metrics
    if analysis.judgement.signal != Signal.DANGER or metrics.daily_return < 0.03:
        return []

    if not metrics.above_ma25 and not metrics.above_ma75:
        context = "ただし25日線・75日線を回復していないためDANGER継続。"
    elif not metrics.above_ma25 or not metrics.above_ma75:
        context = "ただし25日線または75日線を回復していないためDANGER継続。"
    else:
        context = "ただし他のDANGER条件が残っているためDANGER継続。"

    return [f"補足: 前日比{_percent(metrics.daily_return)}で反発。{context}"]


def _header(analysis: StockAnalysis) -> str:
    signal = analysis.judgement.signal
    base = f"{STATUS_EMOJI[signal]} {signal.value} {analysis.item.name} {analysis.item.ticker}"
    if analysis.status_change_label is None:
        return base

    label = analysis.status_change_label
    if is_release_to_no_signal(analysis.previous_signal, signal):
        label = f"{label} / 解除"
    return f"🔔 **{label} {base}**"


def _status_change_lines(analysis: StockAnalysis) -> list[str]:
    if analysis.previous_signal is None or analysis.status_change_note is None:
        return []
    current_signal = analysis.judgement.signal
    return [
        (
            f"ステータス変化: **{_status_display(analysis.previous_signal)} → "
            f"{_status_display(current_signal)}**（{analysis.status_change_note}）"
        )
    ]


def _previous_status(analysis: StockAnalysis) -> str:
    if analysis.previous_signal is None:
        return "-"
    return analysis.previous_signal.value


def _status_display(signal: Signal) -> str:
    if signal == Signal.UNTRACKED:
        return "未記録"
    return signal.value


def _support_types(analysis: StockAnalysis) -> str:
    if not analysis.judgement.support_types:
        return "なし"
    return " / ".join(analysis.judgement.support_types)


def _nearest_support(support_type: str | None, distance: float | None) -> str:
    if support_type is None:
        return "-"
    return f"{support_type} ({_percent(distance)})"


def _yen(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:,.0f}円"


def _percent(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:+.2%}"


def _plain_percent(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2%}"


def _number(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}"


def _ratio(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.1f}x"


def _change_sort_key(analysis: StockAnalysis) -> int:
    return 0 if analysis.status_change_label is not None else 1


def _sort_distance(value: float | None) -> float:
    return value if value is not None else 999.0
