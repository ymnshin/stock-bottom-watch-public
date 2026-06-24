from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Sequence
from zoneinfo import ZoneInfo

import pandas as pd

from models import WatchItem


class DataFetchError(RuntimeError):
    """Raised when daily price data cannot be fetched for one ticker."""


@dataclass(frozen=True)
class HistoryFetchResult:
    histories: dict[str, pd.DataFrame]
    failures: dict[str, str]


REQUIRED_WATCHLIST_COLUMNS = {"ticker", "name", "theme", "avg_price", "memo"}
OHLCV_CACHE_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


def load_watchlist(path: Path) -> list[WatchItem]:
    if not path.exists():
        raise FileNotFoundError(f"watchlist not found: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None:
            raise ValueError("watchlist.csv is empty")

        missing = REQUIRED_WATCHLIST_COLUMNS - set(reader.fieldnames)
        if missing:
            missing_columns = ", ".join(sorted(missing))
            raise ValueError(f"watchlist.csv missing columns: {missing_columns}")

        items: list[WatchItem] = []
        for row_number, row in enumerate(reader, start=2):
            ticker = (row.get("ticker") or "").strip()
            if not ticker:
                continue

            items.append(
                WatchItem(
                    ticker=ticker,
                    name=(row.get("name") or ticker).strip(),
                    theme=(row.get("theme") or "").strip(),
                    avg_price=_parse_optional_float(row.get("avg_price"), row_number),
                    memo=(row.get("memo") or "").strip(),
                )
            )

    return items


def fetch_daily_history(ticker: str, lookback_days: int) -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise DataFetchError("yfinance is not installed. Run: pip install -r requirements.txt") from exc

    end_date = datetime.now(ZoneInfo("Asia/Tokyo")).date() + timedelta(days=1)
    calendar_days = max(int(lookback_days * 1.7), lookback_days + 120)
    start_date = end_date - timedelta(days=calendar_days)

    try:
        frame = yf.Ticker(ticker).history(
            start=start_date.isoformat(),
            end=end_date.isoformat(),
            interval="1d",
            auto_adjust=False,
            actions=False,
        )
    except Exception as exc:  # yfinance raises several transport/parser exceptions.
        raise DataFetchError(f"failed to fetch {ticker}: {exc}") from exc

    if frame.empty:
        raise DataFetchError(f"no daily data returned for {ticker}")

    return frame


def fetch_daily_histories(
    tickers: Sequence[str],
    lookback_days: int,
    batch_size: int = 100,
    threads: bool = True,
    cache_dir: Path | None = None,
    write_cache: bool = True,
) -> HistoryFetchResult:
    normalized_tickers = _unique_tickers(tickers)
    if not normalized_tickers:
        return HistoryFetchResult(histories={}, failures={})

    cached_histories = _load_cached_histories(normalized_tickers, cache_dir)
    histories: dict[str, pd.DataFrame] = dict(cached_histories)
    failures: dict[str, str] = {}
    end_date = _end_date()
    full_start_date = _full_start_date(end_date, lookback_days)
    safe_batch_size = max(1, int(batch_size))

    for batch in _chunks(normalized_tickers, safe_batch_size):
        full_tickers = [ticker for ticker in batch if ticker not in cached_histories]
        cached_tickers = [ticker for ticker in batch if ticker in cached_histories]

        _fetch_batch_into(
            tickers=full_tickers,
            start_date=full_start_date,
            end_date=end_date,
            lookback_days=lookback_days,
            threads=threads,
            cached_histories=cached_histories,
            histories=histories,
            failures=failures,
            cache_dir=cache_dir,
            write_cache=write_cache,
        )
        _fetch_batch_into(
            tickers=cached_tickers,
            start_date=_incremental_start_date(cached_tickers, cached_histories, full_start_date),
            end_date=end_date,
            lookback_days=lookback_days,
            threads=threads,
            cached_histories=cached_histories,
            histories=histories,
            failures=failures,
            cache_dir=cache_dir,
            write_cache=write_cache,
        )

    return HistoryFetchResult(histories=histories, failures=failures)


def _parse_optional_float(raw_value: str | None, row_number: int) -> float | None:
    value = (raw_value or "").strip()
    if not value:
        return None

    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"invalid avg_price at row {row_number}: {raw_value}") from exc


def _fetch_batch_into(
    tickers: Sequence[str],
    start_date: date,
    end_date: date,
    lookback_days: int,
    threads: bool,
    cached_histories: dict[str, pd.DataFrame],
    histories: dict[str, pd.DataFrame],
    failures: dict[str, str],
    cache_dir: Path | None,
    write_cache: bool,
) -> None:
    if not tickers:
        return

    try:
        downloaded = _download_daily_histories(tickers, start_date, end_date, threads)
    except DataFetchError as exc:
        logging.warning("batch fetch failed for %d tickers: %s", len(tickers), exc)
        downloaded = pd.DataFrame()

    missing_tickers: list[str] = []
    for ticker in tickers:
        frame = _extract_ticker_frame(downloaded, ticker, len(tickers))
        if frame.empty:
            missing_tickers.append(ticker)
            continue

        merged = _merge_histories(cached_histories.get(ticker), frame, lookback_days)
        histories[ticker] = merged
        if write_cache:
            _save_cached_history(cache_dir, ticker, merged, lookback_days)

    for ticker in missing_tickers:
        if ticker in cached_histories:
            histories[ticker] = cached_histories[ticker]
            continue

        try:
            frame = fetch_daily_history(ticker, lookback_days)
        except DataFetchError as exc:
            failures[ticker] = str(exc)
            continue

        normalized = _normalize_history_frame(frame)
        if normalized.empty:
            failures[ticker] = f"no usable daily data returned for {ticker}"
            continue

        merged = _merge_histories(None, normalized, lookback_days)
        histories[ticker] = merged
        if write_cache:
            _save_cached_history(cache_dir, ticker, merged, lookback_days)


def _download_daily_histories(
    tickers: Sequence[str],
    start_date: date,
    end_date: date,
    threads: bool,
) -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise DataFetchError("yfinance is not installed. Run: pip install -r requirements.txt") from exc

    try:
        return yf.download(
            tickers=list(tickers),
            start=start_date.isoformat(),
            end=end_date.isoformat(),
            interval="1d",
            group_by="ticker",
            auto_adjust=False,
            actions=False,
            threads=threads,
            progress=False,
        )
    except Exception as exc:  # yfinance raises several transport/parser exceptions.
        raise DataFetchError(f"failed to batch fetch: {exc}") from exc


def _extract_ticker_frame(downloaded: pd.DataFrame, ticker: str, ticker_count: int) -> pd.DataFrame:
    if downloaded.empty:
        return pd.DataFrame()

    frame = downloaded
    if isinstance(downloaded.columns, pd.MultiIndex):
        if ticker in downloaded.columns.get_level_values(0):
            frame = downloaded.xs(ticker, axis=1, level=0)
        elif ticker in downloaded.columns.get_level_values(1):
            frame = downloaded.xs(ticker, axis=1, level=1)
        elif ticker_count == 1:
            frame = downloaded.droplevel(0, axis=1)
        else:
            return pd.DataFrame()

    return _normalize_history_frame(frame)


def _normalize_history_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()

    prepared = frame.copy()
    if isinstance(prepared.columns, pd.MultiIndex):
        prepared.columns = prepared.columns.get_level_values(-1)

    rename_map = {}
    for column in prepared.columns:
        normalized = str(column).strip().lower()
        if normalized == "open":
            rename_map[column] = "Open"
        elif normalized == "high":
            rename_map[column] = "High"
        elif normalized == "low":
            rename_map[column] = "Low"
        elif normalized == "close":
            rename_map[column] = "Close"
        elif normalized == "volume":
            rename_map[column] = "Volume"

    prepared = prepared.rename(columns=rename_map)
    required_columns = {"Close", "High", "Low", "Volume"}
    if required_columns - set(prepared.columns):
        return pd.DataFrame()

    prepared = prepared[[column for column in OHLCV_CACHE_COLUMNS if column in prepared.columns]]
    prepared.index = pd.to_datetime(prepared.index)
    if getattr(prepared.index, "tz", None) is not None:
        prepared.index = prepared.index.tz_convert(None)
    prepared.index = prepared.index.normalize()
    prepared = prepared.sort_index()
    prepared = prepared.dropna(subset=["Close", "High", "Low"])
    prepared["Volume"] = prepared["Volume"].fillna(0)
    prepared = prepared[~prepared.index.duplicated(keep="last")]
    return prepared


def _load_cached_histories(tickers: Sequence[str], cache_dir: Path | None) -> dict[str, pd.DataFrame]:
    if cache_dir is None:
        return {}

    histories: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        frame = _load_cached_history(_cache_path(cache_dir, ticker))
        if frame is not None and len(frame) >= 2:
            histories[ticker] = frame
    return histories


def _load_cached_history(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None

    try:
        frame = pd.read_csv(path, index_col=0, parse_dates=True)
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        logging.warning("failed to read history cache %s: %s", path, exc)
        return None

    normalized = _normalize_history_frame(frame)
    if normalized.empty:
        return None
    return normalized


def _save_cached_history(
    cache_dir: Path | None,
    ticker: str,
    frame: pd.DataFrame,
    lookback_days: int,
) -> None:
    if cache_dir is None or frame.empty:
        return

    cache_dir.mkdir(parents=True, exist_ok=True)
    frame.tail(_cache_row_limit(lookback_days)).to_csv(_cache_path(cache_dir, ticker), index_label="Date")


def _merge_histories(
    cached: pd.DataFrame | None,
    fresh: pd.DataFrame,
    lookback_days: int,
) -> pd.DataFrame:
    frames = [frame for frame in (cached, fresh) if frame is not None and not frame.empty]
    if not frames:
        return pd.DataFrame()

    merged = _normalize_history_frame(pd.concat(frames, axis=0))
    return merged.tail(_cache_row_limit(lookback_days))


def _cache_path(cache_dir: Path, ticker: str) -> Path:
    safe_name = ticker.replace("/", "_").replace("\\", "_").replace(":", "_")
    return cache_dir / f"{safe_name}.csv"


def _cache_row_limit(lookback_days: int) -> int:
    return max(int(lookback_days * 1.5), lookback_days + 120, 320)


def _unique_tickers(tickers: Sequence[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for ticker in tickers:
        normalized = ticker.strip()
        if normalized and normalized not in seen:
            unique.append(normalized)
            seen.add(normalized)
    return unique


def _chunks(items: Sequence[str], size: int) -> list[list[str]]:
    return [list(items[index : index + size]) for index in range(0, len(items), size)]


def _end_date() -> date:
    return datetime.now(ZoneInfo("Asia/Tokyo")).date() + timedelta(days=1)


def _full_start_date(end_date: date, lookback_days: int) -> date:
    calendar_days = max(int(lookback_days * 1.7), lookback_days + 120)
    return end_date - timedelta(days=calendar_days)


def _incremental_start_date(
    tickers: Sequence[str],
    cached_histories: dict[str, pd.DataFrame],
    full_start_date: datetime.date,
) -> date:
    last_dates = [
        cached_histories[ticker].index[-1].date()
        for ticker in tickers
        if ticker in cached_histories and not cached_histories[ticker].empty
    ]
    if not last_dates:
        return full_start_date
    return max(full_start_date, min(last_dates) - timedelta(days=7))
