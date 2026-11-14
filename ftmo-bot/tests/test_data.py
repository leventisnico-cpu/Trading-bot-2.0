"""Phase 2: Dukascopy decode/download, resample (incl. DST), calendar, integrity."""

from __future__ import annotations

import io
import json
import urllib.error
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from ftmo_bot.config import StrategyParams
from ftmo_bot.data import calendar as cal
from ftmo_bot.data import dukascopy as dk
from ftmo_bot.data.integrity import check_day, load_excluded, run_integrity
from ftmo_bot.data.resample import bars_path, resample_symbol, tag_sessions, ticks_to_bars

from .conftest import make_ticks

PRAGUE = ZoneInfo("Europe/Prague")


# ---------------------------------------------------------------- dukascopy


def test_hour_url_month_is_zero_based() -> None:
    url = dk.hour_url("EURUSD", datetime(2024, 1, 2, 7, tzinfo=UTC))
    assert url.endswith("/EURUSD/2024/00/02/07h_ticks.bi5")


def test_bi5_roundtrip() -> None:
    hour = datetime(2024, 1, 2, 7, tzinfo=UTC)
    ticks = make_ticks(hour, hour + timedelta(minutes=2), timedelta(seconds=1), 1.10123)
    payload = dk.encode_bi5(ticks, hour, 100_000)
    out = dk.decode_bi5(payload, hour, 100_000)
    assert len(out) == 120
    assert out["ts_utc"].iloc[0] == pd.Timestamp(hour)
    assert out["bid"].iloc[0] == pytest.approx(1.10123)
    assert out["ask"].iloc[0] == pytest.approx(1.10133)
    assert str(out["ts_utc"].dtype) == "datetime64[ns, UTC]"


def test_bi5_empty_and_corrupt() -> None:
    hour = datetime(2024, 1, 2, 7, tzinfo=UTC)
    assert dk.decode_bi5(b"", hour, 1e5).empty
    import lzma

    with pytest.raises(ValueError):
        dk.decode_bi5(lzma.compress(b"x" * 7, format=lzma.FORMAT_ALONE), hour, 1e5)


class FakeFetch:
    """Serves synthetic hours; records calls; can fail after N calls."""

    def __init__(self, fail_after: int | None = None) -> None:
        self.calls: list[str] = []
        self.fail_after = fail_after

    def __call__(self, url: str) -> bytes:
        if self.fail_after is not None and len(self.calls) >= self.fail_after:
            raise RuntimeError("network down")
        self.calls.append(url)
        y, m, d, hh = url.split("/")[-4:]
        hour = datetime(int(y), int(m) + 1, int(d), int(hh[:2]), tzinfo=UTC)
        if hour.hour % 6 == 5:
            return b""  # some empty hours
        ticks = make_ticks(hour, hour + timedelta(minutes=1), timedelta(seconds=10), 1.1)
        return dk.encode_bi5(ticks, hour, 100_000)


def test_download_day_and_resume(tmp_path: Path) -> None:
    f = FakeFetch()
    p = dk.download_day("EURUSD", "EURUSD", 1e5, date(2024, 1, 2), tmp_path, f)
    df = pd.read_parquet(p)
    assert len(f.calls) == 24
    assert len(df) == 20 * 6 and list(df.columns) == ["ts_utc", "bid", "ask"]
    dk.download_day("EURUSD", "EURUSD", 1e5, date(2024, 1, 2), tmp_path, f)
    assert len(f.calls) == 24  # resumed: not refetched


def test_interrupted_download_leaves_no_partial_day(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        dk.download_day("EURUSD", "EURUSD", 1e5, date(2024, 1, 2), tmp_path, FakeFetch(10))
    assert not dk.day_path(tmp_path, "EURUSD", date(2024, 1, 2)).exists()


def test_download_range_never_fetches_today(tmp_path: Path) -> None:
    f = FakeFetch()
    paths = dk.download_range(
        "EURUSD",
        "EURUSD",
        1e5,
        date(2024, 1, 1),
        date(2024, 1, 5),
        tmp_path,
        f,
        today_utc=date(2024, 1, 3),
    )
    assert [p.stem for p in paths] == ["2024-01-01", "2024-01-02"]


def test_http_fetcher_rate_limit_and_retry() -> None:
    sleeps: list[float] = []
    clock = iter(float(x) for x in range(100))
    attempts = {"n": 0}

    class Resp(io.BytesIO):
        def __enter__(self) -> Resp:
            return self

        def __exit__(self, *a: object) -> None:
            pass

    def opener(url: str, timeout: float) -> Resp:
        attempts["n"] += 1
        if url.endswith("404"):
            raise urllib.error.HTTPError(url, 404, "nf", None, None)  # type: ignore[arg-type]
        if attempts["n"] == 1:
            raise urllib.error.URLError("reset")
        return Resp(b"ok")

    f = dk.HttpFetcher(
        min_interval_s=5.0,
        retries=2,
        backoff_s=1.0,
        sleep=sleeps.append,
        clock=lambda: next(clock),
        opener=opener,
    )
    assert f("http://x/a") == b"ok"
    assert 1.0 in sleeps  # backoff after first failure
    assert any(s > 1.0 for s in sleeps)  # rate-limit wait
    assert f("http://x/404") == b""

    def always_fail(url: str, timeout: float) -> Resp:
        raise urllib.error.HTTPError(url, 500, "boom", None, None)  # type: ignore[arg-type]

    g = dk.HttpFetcher(min_interval_s=0, retries=1, sleep=lambda s: None, opener=always_fail)
    with pytest.raises(RuntimeError):
        g("http://x/b")


# ---------------------------------------------------------------- resample


def test_ticks_to_bars_ohlc() -> None:
    start = datetime(2024, 1, 2, 8, 0, tzinfo=UTC)
    prices = [1.0, 1.2, 0.9, 1.1, 1.0, 1.0, 1.0, 1.15, 1.3]  # 9th tick opens bar 2
    ticks = make_ticks(
        start, start + timedelta(minutes=18), timedelta(minutes=2), prices, spread=0.1
    )
    bars = ticks_to_bars(ticks, 15)
    assert len(bars) == 2
    b = bars.iloc[0]
    assert (b.open, b.high, b.low, b.close) == (1.0, 1.2, 0.9, 1.15)
    assert b.ticks == 8
    assert b.spread_mean == pytest.approx(0.1)
    assert bars.iloc[1].ts_utc == pd.Timestamp(start + timedelta(minutes=15))
    assert ticks_to_bars(ticks.iloc[:0], 15).empty


def test_session_tagging_across_spring_dst(params: StrategyParams) -> None:
    """2026-03-29: CET→CEST. Range 00:00–08:00 local spans 7h of UTC that night."""
    inst = params.instruments["EURUSD"]
    start = datetime(2026, 3, 28, 22, 0, tzinfo=UTC)  # 23:00 CET on the 28th
    ticks = make_ticks(start, start + timedelta(hours=12), timedelta(minutes=1), 1.1)
    bars = tag_sessions(ticks_to_bars(ticks, 15), inst, "Europe/Prague")
    day = bars[bars["date_cest"] == date(2026, 3, 29)]
    rng = day[day["session"] == "range"]
    # 00:00 CET (23:00Z) to 08:00 CEST (06:00Z) = 7 hours = 28 bars.
    assert len(rng) == 28
    assert rng["ts_utc"].min() == pd.Timestamp("2026-03-28 23:00", tz="UTC")
    assert rng["ts_utc"].max() == pd.Timestamp("2026-03-29 05:45", tz="UTC")
    sess = day[day["session"] == "session"]
    assert sess["ts_utc"].min() == pd.Timestamp("2026-03-29 07:00", tz="UTC")  # 09:00 CEST
    assert len(sess) == 12
    # 22:00Z..23:00Z on the 28th is 23:00 CET on the 28th, not the 29th.
    assert set(bars[bars["ts_utc"] < pd.Timestamp("2026-03-28 23:00", tz="UTC")]["date_cest"]) == {
        date(2026, 3, 28)
    }


def test_session_tagging_across_fall_dst(params: StrategyParams) -> None:
    """2026-10-25: CEST→CET. Range night is 9h long in UTC."""
    inst = params.instruments["EURUSD"]
    start = datetime(2026, 10, 24, 21, 0, tzinfo=UTC)
    ticks = make_ticks(start, start + timedelta(hours=14), timedelta(minutes=1), 1.1)
    bars = tag_sessions(ticks_to_bars(ticks, 15), inst, "Europe/Prague")
    rng = bars[(bars["date_cest"] == date(2026, 10, 25)) & (bars["session"] == "range")]
    assert len(rng) == 36  # 22:00Z..07:00Z
    assert rng["ts_utc"].min() == pd.Timestamp("2026-10-24 22:00", tz="UTC")


def test_resample_symbol_writes_15m_and_4h(tmp_path: Path, params: StrategyParams) -> None:
    raw = tmp_path / "raw"
    for d in (date(2024, 1, 2), date(2024, 1, 3)):
        start = datetime.combine(d, time(0), tzinfo=UTC)
        t = make_ticks(start, start + timedelta(hours=24), timedelta(minutes=5), 1.1)
        (raw / "EURUSD").mkdir(parents=True, exist_ok=True)
        t.to_parquet(dk.day_path(raw, "EURUSD", d), index=False)
    dk.empty_ticks().to_parquet(dk.day_path(raw, "EURUSD", date(2024, 1, 6)), index=False)
    out = resample_symbol(raw, tmp_path / "bars", params.instruments["EURUSD"], "Europe/Prague")
    b15 = pd.read_parquet(out[15])
    b4 = pd.read_parquet(out[240])
    assert len(b15) == 2 * 96 and len(b4) == 2 * 6
    assert {"date_cest", "session"} <= set(b15.columns)
    assert out[15] == bars_path(tmp_path / "bars", "EURUSD", 15)
    assert out[15].name == "EURUSD_15m.parquet" and out[240].name == "EURUSD_4h.parquet"


# ---------------------------------------------------------------- calendar

FF = json.dumps(
    [
        {
            "title": "CPI m/m",
            "country": "USD",
            "date": "2024-01-11T08:30:00-05:00",
            "impact": "High",
            "forecast": "0.2%",
            "previous": "0.1%",
        },
        {
            "title": "Bank Holiday",
            "country": "GBP",
            "date": "2024-01-12T03:00:00-05:00",
            "impact": "Holiday",
        },
        {
            "title": "German ZEW",
            "country": "EUR",
            "date": "2024-01-16T05:00:00-05:00",
            "impact": "Medium",
        },
        {"title": "No date", "country": "USD", "impact": "High"},
        {"title": "Naive", "country": "USD", "date": "2024-01-16T05:00:00", "impact": "High"},
    ]
)


def test_parse_ff_and_filter() -> None:
    ev = cal.parse_ff_json(FF)
    assert len(ev) == 3
    assert ev[0].ts_utc == datetime(2024, 1, 11, 13, 30, tzinfo=UTC)
    hi = cal.high_impact(ev)
    assert [e.title for e in hi] == ["CPI m/m"]
    at = datetime(2024, 1, 11, 13, 0, tzinfo=UTC)
    assert cal.blocked(hi, ["EUR", "USD"], at, timedelta(minutes=30)) is not None
    assert cal.blocked(hi, ["EUR", "USD"], at - timedelta(minutes=1), timedelta(minutes=30)) is None
    assert cal.blocked(hi, ["GBP"], at, timedelta(minutes=30)) is None


def test_fetch_week_caches_and_survives_outage(tmp_path: Path) -> None:
    now = datetime(2024, 1, 10, tzinfo=UTC)
    p = cal.fetch_week(tmp_path, now, fetch=lambda url: FF)
    assert p.name == "ff_2024-W02.json"
    assert len(cal.load_cache(tmp_path)) == 3

    def down(url: str) -> str:
        raise OSError("down")

    assert cal.fetch_week(tmp_path, now, fetch=down) == p  # keeps good cache
    with pytest.raises(OSError):
        cal.fetch_week(tmp_path / "empty", now, fetch=down)


def test_load_csv(tmp_path: Path) -> None:
    p = tmp_path / "ev.csv"
    p.write_text(
        "ts_utc,currency,impact,title\n2024-01-11T13:30:00Z,usd,High,CPI\n"
        "2024-01-11T13:30:00Z,usd,High,CPI\n"
    )
    ev = cal.load_csv(p)
    assert len(ev) == 1 and ev[0].currency == "USD"


# ---------------------------------------------------------------- integrity


def _session_ticks(day: date, every: timedelta = timedelta(seconds=30)) -> pd.DataFrame:
    s = datetime.combine(day, time(9), tzinfo=PRAGUE).astimezone(UTC)
    e = datetime.combine(day, time(12), tzinfo=PRAGUE).astimezone(UTC)
    return make_ticks(s, e, every, 1.1)


def test_check_day_clean_and_failures(params: StrategyParams) -> None:
    inst = params.instruments["EURUSD"]
    d = date(2024, 1, 3)
    clean = _session_ticks(d)
    assert check_day(clean, d, inst, "Europe/Prague").problems == []

    gap = clean[(clean.ts_utc < clean.ts_utc.iloc[100]) | (clean.ts_utc > clean.ts_utc.iloc[115])]
    assert any("gap" in p for p in check_day(gap, d, inst, "Europe/Prague").problems)

    neg = clean.copy()
    neg.loc[5, "ask"] = neg.loc[5, "bid"] - 0.0001
    assert any("negative spread" in p for p in check_day(neg, d, inst, "Europe/Prague").problems)

    zero = clean.copy()
    zero.loc[5, ["bid", "ask"]] = 0.0
    assert any("non-positive" in p for p in check_day(zero, d, inst, "Europe/Prague").problems)

    assert not check_day(clean.iloc[:0], d, inst, "Europe/Prague").has_session


def test_run_integrity_excludes_failing_days(tmp_path: Path, params: StrategyParams) -> None:
    inst = params.instruments["EURUSD"]
    raw = tmp_path / "raw"
    (raw / "EURUSD").mkdir(parents=True)
    days = [date(2024, 1, d) for d in range(1, 26)]
    rng = np.random.default_rng(0)
    for d in days:
        every = timedelta(seconds=int(rng.integers(28, 33)))
        t = _session_ticks(d, every)
        if d == date(2024, 1, 10):
            t = _session_ticks(d, timedelta(seconds=3))  # 10x tick rate -> anomaly
        if d == date(2024, 1, 11):
            t = t.iloc[: len(t) // 2]  # data stops mid-session -> gap
        if d == date(2024, 1, 13):
            t = t.iloc[:0]  # weekend-like: no session ticks
        t.to_parquet(dk.day_path(raw, "EURUSD", d), index=False)
    rep = run_integrity(raw, inst, "Europe/Prague", tmp_path / "integ")
    assert set(rep["failed"]) == {"2024-01-10", "2024-01-11"}
    assert rep["no_session"] == ["2024-01-13"]
    ex = load_excluded(tmp_path / "integ", "EURUSD")
    assert ex == {date(2024, 1, 10), date(2024, 1, 11), date(2024, 1, 13)}
    with pytest.raises(FileNotFoundError):
        load_excluded(tmp_path / "integ", "GBPUSD")
