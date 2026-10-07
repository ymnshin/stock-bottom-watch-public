from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import data_fetcher
import main
from data_fetcher import DataFetchError
from models import Signal


def test_dry_run_reads_restored_state_and_history_without_writing_or_posting(tmp_path, monkeypatch, capsys):
    data = tmp_path / "data"
    history = data / "history"
    history.mkdir(parents=True)
    dates = pd.date_range("2025-09-01", periods=260, freq="B")
    frame = pd.DataFrame({
        "Open": 99.0, "High": 101.0, "Low": 98.0, "Close": 100.0, "Volume": 1000.0,
    }, index=dates)
    frame.to_csv(history / "9503.T.csv", index_label="Date")
    state = data / "state.json"
    state.write_text(json.dumps({
        "version": 1, "updated_at": "2026-08-24T15:45:00+09:00",
        "tickers": {"9503.T": {"status": "WAIT", "updated_at": "2026-08-24T15:45:00+09:00"}},
    }))
    config = tmp_path / "config.yaml"
    config.write_text(f"history_cache_dir: {history}\ndiscord_report_mode: buy_candidates_summary\n")
    watchlist = tmp_path / "watchlist.csv"
    watchlist.write_text("ticker,name,theme,avg_price,memo\n9503.T,関西電力,電力,,\n")
    before = {p: p.read_bytes() for p in data.rglob("*") if p.is_file()}
    starts = []

    def download(tickers, start_date, end_date, threads):
        starts.append(start_date)
        return pd.concat({"9503.T": frame.tail(5)}, axis=1)

    def reject_post(*args, **kwargs):
        raise AssertionError("dry run must never post to Discord")

    results = []
    original_run = main.run_stock_watch

    def capture_result(**kwargs):
        result = original_run(**kwargs)
        results.append(result)
        return result

    monkeypatch.setattr(data_fetcher, "_download_daily_histories", download)
    monkeypatch.setattr(main, "run_stock_watch", capture_result)
    monkeypatch.setattr(main, "_load_dotenv", lambda path: None)
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://example.invalid/webhook")
    import requests
    monkeypatch.setattr(requests, "post", reject_post)
    monkeypatch.setattr(sys, "argv", ["main.py", "--dry-run", "--config", str(config),
                                      "--watchlist", str(watchlist), "--state-path", str(state)])

    assert main.main() == 0
    assert "BUY_CANDIDATE一覧" in capsys.readouterr().out
    assert results[0].previous_state.records["9503.T"].status == Signal.WAIT
    assert starts[0] > data_fetcher._full_start_date(data_fetcher._end_date(), 260)
    assert {p: p.read_bytes() for p in data.rglob("*") if p.is_file()} == before


def test_no_price_data_fails_without_posting_or_creating_state(tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.write_text("use_history_cache: false\n")
    watchlist = tmp_path / "watchlist.csv"
    watchlist.write_text("ticker,name,theme,avg_price,memo\n9503.T,関西電力,電力,,\n")
    state = tmp_path / "state.json"

    def no_history(ticker, lookback_days):
        raise DataFetchError("no data")

    def reject_report(*args, **kwargs):
        raise AssertionError("an empty analysis must not be notified")

    monkeypatch.setattr(data_fetcher, "_download_daily_histories", lambda *args: pd.DataFrame())
    monkeypatch.setattr(data_fetcher, "fetch_daily_history", no_history)
    monkeypatch.setattr(main, "post_or_print", reject_report)
    monkeypatch.setattr(main, "_load_dotenv", lambda path: None)
    monkeypatch.setattr(sys, "argv", ["main.py", "--config", str(config),
                                      "--watchlist", str(watchlist), "--state-path", str(state)])

    with pytest.raises(RuntimeError, match="No stocks could be analyzed"):
        main.main()
    assert not state.exists()
