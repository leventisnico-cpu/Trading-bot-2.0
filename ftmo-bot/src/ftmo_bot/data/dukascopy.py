"""Dukascopy tick download and .bi5 decode.

Each hour of ticks lives at
``{BASE_URL}/{INSTRUMENT}/{YYYY}/{MM-1:02d}/{DD:02d}/{HH:02d}h_ticks.bi5`` (month
is ZERO-based). A .bi5 file is LZMA ("alone" format) wrapping 20-byte
big-endian records: ``uint32 ms_since_hour, uint32 ask, uint32 bid,
float32 ask_volume, float32 bid_volume``; prices are integers scaled by a
per-instrument divisor (1e5 for EURUSD, 1e3 for XAUUSD and USA100IDXUSD).

Output: one parquet per symbol-day at ``{raw_dir}/{symbol}/{YYYY-MM-DD}.parquet``
with columns ``ts_utc`` (datetime64[ns, UTC]), ``bid``, ``ask``. Days already on
disk are skipped (resumable); a day is written atomically only once all 24
hours are fetched, so an interrupted download never leaves a partial day.
"""

from __future__ import annotations

import logging
import lzma
import time as _time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

BASE_URL = "https://datafeed.dukascopy.com/datafeed"
RECORD = np.dtype(
    [("ms", ">u4"), ("ask", ">u4"), ("bid", ">u4"), ("ask_vol", ">f4"), ("bid_vol", ">f4")]
)
Fetcher = Callable[[str], bytes]


def hour_url(instrument: str, hour_utc: datetime) -> str:
    return (
        f"{BASE_URL}/{instrument}/{hour_utc.year:04d}/{hour_utc.month - 1:02d}/"
        f"{hour_utc.day:02d}/{hour_utc.hour:02d}h_ticks.bi5"
    )


def decode_bi5(payload: bytes, hour_utc: datetime, divisor: float) -> pd.DataFrame:
    """Decode one hour file into ``ts_utc, bid, ask``. Empty payload → empty frame."""
    if not payload:
        return empty_ticks()
    raw = lzma.decompress(payload)
    if len(raw) % RECORD.itemsize:
        raise ValueError(f"corrupt bi5: {len(raw)} bytes is not a multiple of {RECORD.itemsize}")
    rec = np.frombuffer(raw, dtype=RECORD)
    base = (
        pd.Timestamp(hour_utc).tz_convert("UTC")
        if hour_utc.tzinfo
        else pd.Timestamp(hour_utc, tz="UTC")
    )
    ts = (base + pd.to_timedelta(rec["ms"].astype(np.int64), unit="ms")).astype(
        "datetime64[ns, UTC]"
    )
    return pd.DataFrame(
        {
            "ts_utc": ts,
            "bid": rec["bid"].astype(np.float64) / divisor,
            "ask": rec["ask"].astype(np.float64) / divisor,
        }
    )


def encode_bi5(ticks: pd.DataFrame, hour_utc: datetime, divisor: float) -> bytes:
    """Inverse of ``decode_bi5`` (test fixtures)."""
    base = pd.Timestamp(hour_utc)
    rec = np.zeros(len(ticks), dtype=RECORD)
    rec["ms"] = ((ticks["ts_utc"] - base).dt.total_seconds() * 1000).round().astype(np.int64)
    rec["ask"] = np.round(ticks["ask"].to_numpy() * divisor).astype(np.int64)
    rec["bid"] = np.round(ticks["bid"].to_numpy() * divisor).astype(np.int64)
    rec["ask_vol"] = 1.0
    rec["bid_vol"] = 1.0
    return lzma.compress(rec.tobytes(), format=lzma.FORMAT_ALONE)


def empty_ticks() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts_utc": pd.Series([], dtype="datetime64[ns, UTC]"),
            "bid": pd.Series([], dtype=np.float64),
            "ask": pd.Series([], dtype=np.float64),
        }
    )


class HttpFetcher:
    """Rate-limited HTTP GET with retries. 404 means "no ticks that hour"."""

    def __init__(
        self,
        min_interval_s: float = 0.25,
        retries: int = 4,
        backoff_s: float = 2.0,
        timeout_s: float = 30.0,
        sleep: Callable[[float], None] = _time.sleep,
        clock: Callable[[], float] = _time.monotonic,
        opener: Callable[..., object] = urllib.request.urlopen,
    ) -> None:
        self.min_interval_s = min_interval_s
        self.retries = retries
        self.backoff_s = backoff_s
        self.timeout_s = timeout_s
        self._sleep = sleep
        self._clock = clock
        self._open = opener
        self._last = -float("inf")

    def __call__(self, url: str) -> bytes:
        for attempt in range(self.retries + 1):
            wait = self.min_interval_s - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
            self._last = self._clock()
            try:
                with self._open(url, timeout=self.timeout_s) as resp:  # type: ignore[attr-defined]
                    data: bytes = resp.read()
                    return data
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    return b""
                err: Exception = exc
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                err = exc
            if attempt == self.retries:
                raise RuntimeError(f"giving up on {url}: {err}") from err
            delay = self.backoff_s * (2**attempt)
            log.warning("fetch failed (%s), retry %d in %.1fs: %s", err, attempt + 1, delay, url)
            self._sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover


def day_path(raw_dir: Path, symbol: str, day: date) -> Path:
    return raw_dir / symbol / f"{day.isoformat()}.parquet"


def download_day(
    symbol: str,
    instrument: str,
    divisor: float,
    day: date,
    raw_dir: Path,
    fetch: Fetcher,
) -> Path:
    """Fetch the 24 UTC hours of ``day`` and write one parquet. Skips if present."""
    out = day_path(raw_dir, symbol, day)
    if out.exists():
        return out
    frames = []
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    for h in range(24):
        hour = start + timedelta(hours=h)
        frames.append(decode_bi5(fetch(hour_url(instrument, hour)), hour, divisor))
    non_empty = [f for f in frames if len(f)]
    df = pd.concat(non_empty, ignore_index=True) if non_empty else empty_ticks()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(out)
    return out


def download_range(
    symbol: str,
    instrument: str,
    divisor: float,
    start: date,
    end: date,
    raw_dir: Path,
    fetch: Fetcher | None = None,
    today_utc: date | None = None,
) -> list[Path]:
    """Download ``[start, end]`` inclusive. Weekends are fetched too (Sunday open).

    Never fetches the current UTC day or later: an incomplete day written now
    would be skipped forever by the resume logic.
    """
    fetch = fetch or HttpFetcher()
    today_utc = today_utc or datetime.now(UTC).date()
    end = min(end, today_utc - timedelta(days=1))
    paths = []
    day = start
    while day <= end:
        paths.append(download_day(symbol, instrument, divisor, day, raw_dir, fetch))
        log.info("downloaded %s %s", symbol, day)
        day += timedelta(days=1)
    return paths
