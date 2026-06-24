from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from models import Signal, StockAnalysis


CORE_BOTTOM_SIGNALS = {Signal.DANGER, Signal.WAIT, Signal.BUY_CANDIDATE}


@dataclass(frozen=True)
class StateRecord:
    status: Signal
    name: str = ""
    theme: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class StatusState:
    exists: bool
    records: dict[str, StateRecord]

    def statuses(self) -> dict[str, Signal]:
        return {ticker: record.status for ticker, record in self.records.items()}


def load_status_state(path: Path) -> StatusState:
    if not path.exists():
        return StatusState(exists=False, records={})

    with path.open("r", encoding="utf-8") as file:
        raw_state = json.load(file)

    records = _parse_records(raw_state)
    return StatusState(exists=True, records=records)


def apply_status_changes(analyses: list[StockAnalysis], state: StatusState) -> list[StockAnalysis]:
    previous_statuses = state.statuses()
    updated: list[StockAnalysis] = []
    for analysis in analyses:
        current_signal = analysis.judgement.signal
        previous_signal = previous_statuses.get(analysis.item.ticker, Signal.UNTRACKED)
        if previous_signal == current_signal:
            updated.append(replace(analysis, previous_signal=previous_signal))
            continue

        if previous_signal == Signal.UNTRACKED and current_signal == Signal.NO_SIGNAL:
            updated.append(replace(analysis, previous_signal=previous_signal))
            continue

        updated.append(
            replace(
                analysis,
                previous_signal=previous_signal,
                status_change_label=_change_label(previous_signal, current_signal),
                status_change_note=_change_note(previous_signal, current_signal),
            )
        )
    return updated


def reset_status_state(path: Path) -> bool:
    if not path.exists():
        return False
    path.unlink()
    return True


def save_status_state(
    path: Path,
    analyses: list[StockAnalysis],
    previous_state: StatusState,
    watchlist_tickers: list[str],
    run_at: datetime,
) -> None:
    analysis_by_ticker = {analysis.item.ticker: analysis for analysis in analyses}
    updated_at = run_at.isoformat()
    records: dict[str, StateRecord] = {}

    for ticker in watchlist_tickers:
        analysis = analysis_by_ticker.get(ticker)
        if analysis is not None:
            records[ticker] = StateRecord(
                status=analysis.judgement.signal,
                name=analysis.item.name,
                theme=analysis.item.theme,
                updated_at=updated_at,
            )
            continue

        previous_record = previous_state.records.get(ticker)
        if previous_record is not None:
            records[ticker] = previous_record

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "updated_at": updated_at,
        "tickers": {
            ticker: {
                "status": record.status.value,
                "name": record.name,
                "theme": record.theme,
                "updated_at": record.updated_at,
            }
            for ticker, record in sorted(records.items())
        },
    }
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")


def is_release_to_no_signal(previous_signal: Signal | None, current_signal: Signal) -> bool:
    return current_signal == Signal.NO_SIGNAL and previous_signal in CORE_BOTTOM_SIGNALS


def is_untracked_new_signal(previous_signal: Signal | None, current_signal: Signal) -> bool:
    return previous_signal == Signal.UNTRACKED and current_signal != Signal.NO_SIGNAL


def _parse_records(raw_state: Any) -> dict[str, StateRecord]:
    if not isinstance(raw_state, dict):
        raise ValueError("state.json must be a JSON object")

    raw_tickers = raw_state.get("tickers", raw_state)
    if not isinstance(raw_tickers, dict):
        raise ValueError("state.json tickers must be a JSON object")

    records: dict[str, StateRecord] = {}
    for ticker, raw_record in raw_tickers.items():
        if not isinstance(ticker, str):
            continue

        record = _parse_record(raw_record)
        if record is not None:
            records[ticker] = record

    return records


def _parse_record(raw_record: Any) -> StateRecord | None:
    if isinstance(raw_record, str):
        return _record_from_status(raw_record)

    if not isinstance(raw_record, dict):
        return None

    raw_status = raw_record.get("status")
    if not isinstance(raw_status, str):
        return None

    return _record_from_status(
        raw_status,
        name=str(raw_record.get("name") or ""),
        theme=str(raw_record.get("theme") or ""),
        updated_at=str(raw_record.get("updated_at") or ""),
    )


def _record_from_status(
    raw_status: str,
    name: str = "",
    theme: str = "",
    updated_at: str = "",
) -> StateRecord | None:
    try:
        status = Signal(raw_status)
    except ValueError:
        return None
    return StateRecord(status=status, name=name, theme=theme, updated_at=updated_at)


def _change_label(previous_signal: Signal, current_signal: Signal) -> str:
    if previous_signal in {Signal.UNTRACKED, Signal.NO_SIGNAL} and current_signal != Signal.NO_SIGNAL:
        return "NEW"
    return "CHANGED"


def _change_note(previous_signal: Signal, current_signal: Signal) -> str:
    explicit_notes = {
        (Signal.UNTRACKED, Signal.DANGER): "新規DANGER",
        (Signal.UNTRACKED, Signal.WAIT): "新規WAIT",
        (Signal.UNTRACKED, Signal.BUY_CANDIDATE): "新規BUY_CANDIDATE",
        (Signal.NO_SIGNAL, Signal.DANGER): "新規DANGER",
        (Signal.NO_SIGNAL, Signal.WAIT): "新規WAIT",
        (Signal.WAIT, Signal.BUY_CANDIDATE): "反転候補として強調",
        (Signal.MOMENTUM, Signal.DANGER): "トレンド崩れ警戒",
        (Signal.DANGER, Signal.WAIT): "下落加速が一服",
    }
    note = explicit_notes.get((previous_signal, current_signal))
    if note is not None:
        return note

    if is_release_to_no_signal(previous_signal, current_signal):
        return "解除"
    if current_signal == Signal.DANGER:
        return "危険シグナルへ変化"
    if current_signal == Signal.WAIT:
        return "待機シグナルへ変化"
    if current_signal == Signal.BUY_CANDIDATE:
        return "反転候補へ変化"
    if current_signal == Signal.MOMENTUM:
        return "上昇トレンド監視へ変化"
    if current_signal == Signal.OVERHEATED:
        return "短期過熱へ変化"
    return "シグナル解除"
