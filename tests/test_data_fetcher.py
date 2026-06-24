from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import data_fetcher
from data_fetcher import fetch_daily_histories


def test_fetch_daily_histories_batches_and_writes_cache() -> None:
    calls: list[tuple[list[str], object, object, bool]] = []
    original_download = data_fetcher._download_daily_histories
    original_single = data_fetcher.fetch_daily_history
    cache_files: tuple[bool, bool] = (False, False)

    def fake_download(tickers, start_date, end_date, threads):
        calls.append((list(tickers), start_date, end_date, threads))
        return _download_frame(list(tickers), "2026-01-01")

    def fail_single(ticker: str, lookback_days: int) -> pd.DataFrame:
        raise AssertionError(f"single fetch should not run for {ticker}")

    try:
        data_fetcher._download_daily_histories = fake_download
        data_fetcher.fetch_daily_history = fail_single
        with TemporaryDirectory() as tmp_dir:
            cache_dir = Path(tmp_dir)
            first = fetch_daily_histories(
                ["1301.T", "1332.T"],
                lookback_days=260,
                batch_size=100,
                threads=True,
                cache_dir=cache_dir,
            )
            second = fetch_daily_histories(
                ["1301.T", "1332.T"],
                lookback_days=260,
                batch_size=100,
                threads=True,
                cache_dir=cache_dir,
            )
            cache_files = ((cache_dir / "1301.T.csv").exists(), (cache_dir / "1332.T.csv").exists())
    finally:
        data_fetcher._download_daily_histories = original_download
        data_fetcher.fetch_daily_history = original_single

    assert set(first.histories) == {"1301.T", "1332.T"}
    assert first.failures == {}
    assert second.failures == {}
    assert cache_files == (True, True)
    assert len(calls) == 2
    assert calls[0][0] == ["1301.T", "1332.T"]
    assert calls[0][3] is True
    assert calls[1][0] == ["1301.T", "1332.T"]
    assert calls[1][1] > calls[0][1]


def test_fetch_daily_histories_falls_back_to_single_for_missing_uncached_ticker() -> None:
    single_calls: list[str] = []
    original_download = data_fetcher._download_daily_histories
    original_single = data_fetcher.fetch_daily_history

    def fake_download(tickers, start_date, end_date, threads):
        return _download_frame(["1301.T"], "2026-01-01")

    def fake_single(ticker: str, lookback_days: int) -> pd.DataFrame:
        single_calls.append(ticker)
        return _single_frame("2026-01-01")

    try:
        data_fetcher._download_daily_histories = fake_download
        data_fetcher.fetch_daily_history = fake_single
        with TemporaryDirectory() as tmp_dir:
            result = fetch_daily_histories(
                ["1301.T", "9999.T"],
                lookback_days=260,
                batch_size=100,
                threads=True,
                cache_dir=Path(tmp_dir),
            )
    finally:
        data_fetcher._download_daily_histories = original_download
        data_fetcher.fetch_daily_history = original_single

    assert set(result.histories) == {"1301.T", "9999.T"}
    assert result.failures == {}
    assert single_calls == ["9999.T"]


def test_fetch_daily_histories_can_skip_cache_writes_for_dry_run() -> None:
    original_download = data_fetcher._download_daily_histories

    def fake_download(tickers, start_date, end_date, threads):
        return _download_frame(list(tickers), "2026-01-01")

    try:
        data_fetcher._download_daily_histories = fake_download
        with TemporaryDirectory() as tmp_dir:
            cache_dir = Path(tmp_dir)
            result = fetch_daily_histories(
                ["1301.T"],
                lookback_days=260,
                cache_dir=cache_dir,
                write_cache=False,
            )
            cache_file_exists = (cache_dir / "1301.T.csv").exists()
    finally:
        data_fetcher._download_daily_histories = original_download

    assert set(result.histories) == {"1301.T"}
    assert cache_file_exists is False


def _download_frame(tickers: list[str], start: str) -> pd.DataFrame:
    frames = {ticker: _single_frame(start, offset=index) for index, ticker in enumerate(tickers)}
    return pd.concat(frames, axis=1)


def _single_frame(start: str, offset: int = 0) -> pd.DataFrame:
    dates = pd.date_range(start, periods=6, freq="B")
    closes = [100.0 + offset + index for index in range(len(dates))]
    return pd.DataFrame(
        {
            "Open": [value - 0.5 for value in closes],
            "High": [value + 1.0 for value in closes],
            "Low": [value - 1.0 for value in closes],
            "Close": closes,
            "Volume": [1000 + offset] * len(dates),
        },
        index=dates,
    )
