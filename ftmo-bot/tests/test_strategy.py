"""Phase 3: Asian breakout strategy on synthetic bars."""

from __future__ import annotations

import ast
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import ftmo_bot
from ftmo_bot.config import StrategyParams, flatten_time_utc
from ftmo_bot.data.calendar import NewsEvent
from ftmo_bot.strategy.asian_breakout import AsianBreakout, atr, ema
from ftmo_bot.strategy.base import Bar, Signal

PRAGUE = ZoneInfo("Europe/Prague")
DAY = date(2026, 3, 4)  # Wednesday, CET (UTC+1)


def utc(day: date, hh: int, mm: int = 0) -> datetime:
    return datetime.combine(day, time(hh, mm), tzinfo=PRAGUE).astimezone(UTC)


def h4_trend(symbol: str, end: datetime, direction: float, n: int = 80) -> list[Bar]:
    """4H bars closing at or before ``end``; ``direction`` +1 up, -1 down, 0 flat."""
    bars = []
    start = end - timedelta(hours=4 * n)
    for i in range(n):
        c = 1.10 + direction * 0.0010 * i
        bars.append(Bar(symbol, start + timedelta(hours=4 * i), c, c + 0.0005, c - 0.0005, c, 240))
    return bars


def range_bars(
    symbol: str, day: date, start: tuple[int, int], end: tuple[int, int], hi: float, lo: float
) -> list[Bar]:
    """15m bars across the range window oscillating between ``lo`` and ``hi``."""
    out = []
    t = utc(day, *start)
    stop = utc(day, *end)
    while t < stop:
        out.append(Bar(symbol, t, (hi + lo) / 2, hi, lo, (hi + lo) / 2))
        t += timedelta(minutes=15)
    return out


def feed(strat: AsianBreakout, bars: Sequence[Bar], h4: Sequence[Bar]) -> list[Signal]:
    return [s for b in bars if (s := strat.on_bar(b, h4)) is not None]


def bo(symbol: str, day: date, hh: int, mm: int, close: float) -> Bar:
    """A breakout candle with a modest true range."""
    return Bar(
        symbol,
        utc(day, hh, mm),
        close - 0.0003,
        max(close, close - 0.0003) + 0.0001,
        min(close, close - 0.0003) - 0.0001,
        close,
    )


@pytest.fixture
def eur_day() -> list[Bar]:
    return range_bars("EURUSD", DAY, (0, 0), (8, 0), 1.1010, 1.0990)


def test_indicators() -> None:
    assert ema([1, 2, 3], 5) == []
    assert ema([2, 2, 2, 2], 2) == [2, 2, 2]
    assert atr([], 14) is None


def test_long_breakout_with_uptrend(params: StrategyParams, eur_day: list[Bar]) -> None:
    s = AsianBreakout(params)
    h4 = h4_trend("EURUSD", utc(DAY, 9), +1)
    sigs = feed(s, [*eur_day, bo("EURUSD", DAY, 9, 0, 1.1015)], h4)
    assert len(sigs) == 1
    sig = sigs[0]
    assert sig.side == "long" and sig.stop == pytest.approx(1.0990)
    assert sig.target == pytest.approx(1.1015 + 2 * (1.1015 - 1.0990))
    assert sig.session_id == "EURUSD:2026-03-04"


def test_short_breakout_with_downtrend(params: StrategyParams, eur_day: list[Bar]) -> None:
    s = AsianBreakout(params)
    h4 = h4_trend("EURUSD", utc(DAY, 9), -1)
    sigs = feed(s, [*eur_day, bo("EURUSD", DAY, 9, 15, 1.0985)], h4)
    assert len(sigs) == 1 and sigs[0].side == "short" and sigs[0].stop == pytest.approx(1.1010)


def test_no_trade_on_flat_ema_slope(params: StrategyParams, eur_day: list[Bar]) -> None:
    s = AsianBreakout(params)
    h4 = h4_trend("EURUSD", utc(DAY, 9), 0)
    assert feed(s, [*eur_day, bo("EURUSD", DAY, 9, 0, 1.1015)], h4) == []
    # Slope is flat when |slope| < 0.1 × ATR even if not exactly zero.
    tiny = [
        Bar(b.symbol, b.ts_utc, b.open, b.high + 0.01, b.low - 0.01, b.close + i * 1e-6, 240)
        for i, b in enumerate(h4)
    ]
    assert s.trend_slope(tiny, utc(DAY, 9, 15)) == 0.0


def test_no_trade_without_enough_h4_history(params: StrategyParams, eur_day: list[Bar]) -> None:
    s = AsianBreakout(params)
    h4 = h4_trend("EURUSD", utc(DAY, 9), +1, n=params.ema_period + params.slope_bars - 1)
    assert feed(s, [*eur_day, bo("EURUSD", DAY, 9, 0, 1.1015)], h4) == []


def test_h4_lookahead_ignored(params: StrategyParams, eur_day: list[Bar]) -> None:
    """4H bars that close after the signal bar must not influence it."""
    s = AsianBreakout(params)
    past_down = h4_trend("EURUSD", utc(DAY, 8), -1)
    future_up = h4_trend("EURUSD", utc(DAY, 8) + timedelta(hours=400), +1, n=100)
    sigs = feed(s, [*eur_day, bo("EURUSD", DAY, 9, 0, 1.1015)], past_down + future_up)
    assert sigs == []  # down trend → long breakout not in filtered direction


def test_breakout_against_trend_does_not_consume_session(
    params: StrategyParams, eur_day: list[Bar]
) -> None:
    s = AsianBreakout(params)
    h4 = h4_trend("EURUSD", utc(DAY, 9), +1)
    bars = [*eur_day, bo("EURUSD", DAY, 9, 0, 1.0985), bo("EURUSD", DAY, 9, 15, 1.1015)]
    sigs = feed(s, bars, h4)
    assert [x.side for x in sigs] == ["long"]


def test_skip_when_natural_stop_exceeds_atr_cap(params: StrategyParams) -> None:
    s = AsianBreakout(params)
    # Range 1.0950..1.1010 but each bar's true range is only 20 pips:
    # ATR ≈ 0.0020, cap 0.0030 < stop distance 1.1015 - 1.0950 = 0.0065.
    bars = range_bars("EURUSD", DAY, (0, 0), (7, 45), 1.1010, 1.0990)
    bars.append(Bar("EURUSD", utc(DAY, 7, 45), 1.0960, 1.0970, 1.0950, 1.0960))
    h4 = h4_trend("EURUSD", utc(DAY, 9), +1)
    late = bo("EURUSD", DAY, 9, 30, 1.1016)
    assert feed(s, [*bars, bo("EURUSD", DAY, 9, 0, 1.1015), late], h4) == []


def test_one_entry_per_instrument_per_session(params: StrategyParams, eur_day: list[Bar]) -> None:
    s = AsianBreakout(params)
    h4 = h4_trend("EURUSD", utc(DAY, 9), +1)
    bars = [*eur_day, bo("EURUSD", DAY, 9, 0, 1.1015), bo("EURUSD", DAY, 9, 15, 1.1020)]
    assert len(feed(s, bars, h4)) == 1
    # Next day is a new session.
    nxt = DAY + timedelta(days=1)
    bars2 = [
        *range_bars("EURUSD", nxt, (0, 0), (8, 0), 1.1030, 1.1010),
        bo("EURUSD", nxt, 9, 0, 1.1035),
    ]
    h4b = h4_trend("EURUSD", utc(nxt, 9), +1)
    assert len(feed(s, bars2, h4b)) == 1


def test_no_entry_outside_session_or_after_time_exit(
    params: StrategyParams, eur_day: list[Bar]
) -> None:
    s = AsianBreakout(params)
    h4 = h4_trend("EURUSD", utc(DAY, 12), +1)
    # 08:00-09:00 is neither range nor session; 11:30 bar closes at 11:45 = flatten time.
    bars = [*eur_day, bo("EURUSD", DAY, 8, 30, 1.1015), bo("EURUSD", DAY, 11, 30, 1.1015)]
    assert feed(s, bars, h4) == []
    assert flatten_time_utc(DAY, params.instruments["EURUSD"], params) == utc(DAY, 11, 45)


def test_news_window_suppression(params: StrategyParams, eur_day: list[Bar]) -> None:
    h4 = h4_trend("EURUSD", utc(DAY, 9), +1)
    breakout = bo("EURUSD", DAY, 9, 0, 1.1015)  # entry at 09:15 local
    event = NewsEvent(utc(DAY, 9, 40), "USD", "High", "CPI")  # 25 min after entry
    s = AsianBreakout(params, news=[event])
    later = bo("EURUSD", DAY, 10, 0, 1.1016)  # entry 10:15 = 35 min after → allowed
    sigs = feed(s, [*eur_day, breakout, later], h4)
    assert len(sigs) == 1 and sigs[0].entry == pytest.approx(1.1016)
    # Low-impact or unrelated-currency events do not block.
    for ev in (
        NewsEvent(utc(DAY, 9, 15), "USD", "Low", "x"),
        NewsEvent(utc(DAY, 9, 15), "JPY", "High", "x"),
    ):
        s2 = AsianBreakout(params, news=[ev])
        assert len(feed(s2, [*eur_day, breakout], h4)) == 1


def test_nas100_pre_cash_range(params: StrategyParams) -> None:
    s = AsianBreakout(params)
    sym = "NAS100"
    # A huge spike at 08:00-09:00 local must NOT be part of the range.
    spike = Bar(sym, utc(DAY, 8, 0), 18000, 18500, 17500, 18000)
    rng = range_bars(sym, DAY, (9, 0), (15, 15), 18050, 17950)
    # 15:15-15:30 bar is outside the range window too.
    gap_bar = Bar(sym, utc(DAY, 15, 15), 18000, 18400, 17600, 18000)
    h4 = [
        Bar(sym, b.ts_utc, b.open * 16000, b.high * 16000, b.low * 16000, b.close * 16000, 240)
        for b in h4_trend(sym, utc(DAY, 15, 30), +1)
    ]
    brk = Bar(sym, utc(DAY, 15, 30), 18040, 18062, 18035, 18060)
    sigs = feed(s, [spike, *rng, brk], h4)
    # Range is exactly the 09:00-15:15 bars.
    day_state = s._state[sym].day
    assert day_state is not None
    assert (day_state.range_high, day_state.range_low) == (18050, 17950)
    s.on_bar(gap_bar, h4)
    assert (day_state.range_high, day_state.range_low) == (18050, 17950)
    assert len(sigs) == 1 and sigs[0].side == "long" and sigs[0].stop == pytest.approx(17950)


def test_unknown_symbol_ignored(params: StrategyParams) -> None:
    assert AsianBreakout(params).on_bar(Bar("USDJPY", utc(DAY, 9), 1, 1, 1, 1), []) is None


# ---------------------------------------------------------------- module contract

FORBIDDEN = ("ftmo_bot.execution", "ftmo_bot.risk.guard")


def _imports(path: Path) -> set[str]:
    mods: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            mods |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
    return mods


def test_strategy_import_graph_excludes_execution_and_guard() -> None:
    """Static transitive closure over ftmo_bot imports from strategy/*."""
    pkg_root = Path(ftmo_bot.__file__).parent
    seen: set[str] = set()
    todo = [f"ftmo_bot.strategy.{p.stem}" for p in (pkg_root / "strategy").glob("*.py")]
    while todo:
        mod = todo.pop()
        if mod in seen or not mod.startswith("ftmo_bot"):
            continue
        seen.add(mod)
        rel = Path(*mod.split(".")[1:])
        path = pkg_root / rel.with_suffix(".py")
        if not path.exists():
            path = pkg_root / rel / "__init__.py"
        if path.exists():
            todo.extend(_imports(path))
    bad = sorted(m for m in seen if m.startswith(FORBIDDEN))
    assert bad == [], bad


def test_strategy_runtime_imports_exclude_execution_and_guard() -> None:
    code = (
        "import sys, ftmo_bot.strategy.asian_breakout, ftmo_bot.strategy.base;"
        f"print([m for m in sys.modules if m.startswith({FORBIDDEN!r})])"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"
