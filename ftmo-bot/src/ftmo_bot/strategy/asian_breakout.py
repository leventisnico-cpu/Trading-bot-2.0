"""Asian-range breakout with 4H trend filter (SPEC "Strategy spec" steps 1–7).

Per instrument per CE(S)T day:
1. Range = high/low of 15m bars whose local open time is in the range window
   (00:00–08:00; NAS100 09:00–15:15 pre-cash).
2. Trend = slope of the 4H EMA(50) over the last 6 completed 4H bars. Longs only
   if slope > 0, shorts only if slope < 0, no trade if |slope| < 0.1 × ATR(14, 4H).
3. Entry = the first 15m bar in the session window that CLOSES beyond the range
   in the trend direction; entry at the next bar's open (the engine/runner fills
   on the next tick). One entry per instrument per session.
4. Stop = opposite side of the range. If that is wider than 1.5 × ATR(14, 15m)
   the trade is skipped — and the session is done (the stop is never shrunk).
5. Target = 2.0 R from the reference entry. Breakeven at 1.0 R is executed by
   the engine/runner, not here.
6. Time exit 15 min before session end: no entry whose next-bar open is at or
   after that time; flattening is done by the engine/runner.
7. News: no entry within ±30 min of a high-impact event for the instrument's
   currencies. A news-blocked candle does not consume the session; a later
   qualifying candle (after the window) may still enter.

Candles that close beyond the range AGAINST the trend, or while the slope is
flat, are "not in the filtered direction" and do not consume the session.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from ftmo_bot.config import InstrumentParams, StrategyParams, flatten_time_utc
from ftmo_bot.data.calendar import NewsEvent, blocked
from ftmo_bot.strategy.base import Bar, Side, Signal, Strategy


def ema(values: Sequence[float], period: int) -> list[float]:
    """EMA seeded with the SMA of the first ``period`` values (len - period + 1 outputs)."""
    if len(values) < period:
        return []
    alpha = 2.0 / (period + 1)
    out = [sum(values[:period]) / period]
    for v in values[period:]:
        out.append(out[-1] + alpha * (v - out[-1]))
    return out


def atr(bars: Sequence[Bar], period: int) -> float | None:
    """Simple average of the last ``period`` true ranges (needs ``period + 1`` bars)."""
    if len(bars) < period + 1:
        return None
    trs = []
    for prev, cur in zip(bars[-period - 1 : -1], bars[-period:], strict=True):
        trs.append(max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close)))
    return sum(trs) / period


@dataclass
class _Day:
    day: date
    range_high: float = float("-inf")
    range_low: float = float("inf")
    done: bool = False

    @property
    def has_range(self) -> bool:
        return self.range_high > self.range_low


@dataclass
class _SymbolState:
    history: deque[Bar] = field(default_factory=lambda: deque(maxlen=64))
    day: _Day | None = None


class AsianBreakout(Strategy):
    def __init__(self, params: StrategyParams, news: Sequence[NewsEvent] = ()) -> None:
        self.p = params
        self.news = [e for e in news if e.impact == params.news_impact]
        self._news_window = timedelta(minutes=params.news_window_minutes)
        self._state: dict[str, _SymbolState] = {}

    # ------------------------------------------------------------ trend

    def trend_slope(self, h4: Sequence[Bar], asof: datetime) -> float | None:
        """Signed slope, 0.0 if flat, None if not enough completed 4H bars."""
        done = [b for b in h4 if b.close_ts <= asof]
        p = self.p
        if len(done) < p.ema_period + p.slope_bars:
            return None
        series = ema([b.close for b in done], p.ema_period)
        slope = series[-1] - series[-1 - p.slope_bars]
        a = atr(done, p.trend_atr_period)
        if a is None or abs(slope) < p.flat_atr_mult * a:
            return 0.0
        return slope

    # ------------------------------------------------------------ bars

    def on_bar(self, bar: Bar, h4: Sequence[Bar]) -> Signal | None:
        inst = self.p.instruments.get(bar.symbol)
        if inst is None:
            return None
        st = self._state.setdefault(bar.symbol, _SymbolState())
        st.history.append(bar)

        local_open = bar.ts_utc.astimezone(ZoneInfo(self.p.timezone))
        today = local_open.date()
        if st.day is None or st.day.day != today:
            st.day = _Day(today)
        day = st.day
        t = local_open.time()

        if inst.range.contains(t):
            day.range_high = max(day.range_high, bar.high)
            day.range_low = min(day.range_low, bar.low)
            return None
        if day.done or not day.has_range or not self._entry_allowed(bar, inst):
            return None

        if bar.close > day.range_high:
            side: Side = "long"
        elif bar.close < day.range_low:
            side = "short"
        else:
            return None

        slope = self.trend_slope(h4, bar.close_ts)
        if not slope or (side == "long") != (slope > 0):
            return None  # flat / unknown trend, or breakout against it

        if blocked(self.news, inst.currencies, bar.close_ts, self._news_window):
            return None

        a15 = atr(list(st.history), self.p.stop_atr_period)
        if a15 is None:
            return None
        entry = bar.close
        stop = day.range_low if side == "long" else day.range_high
        dist = abs(entry - stop)
        day.done = True  # the first qualifying breakout decides the session
        if dist > self.p.atr_cap_mult * a15:
            return None
        target = (
            entry + self.p.target_r * dist if side == "long" else entry - self.p.target_r * dist
        )
        return Signal(
            symbol=bar.symbol,
            side=side,
            entry=entry,
            stop=stop,
            target=target,
            session_id=f"{bar.symbol}:{today.isoformat()}",
        )

    def _entry_allowed(self, bar: Bar, inst: InstrumentParams) -> bool:
        """Bar opened in the session and the next bar opens before the time exit."""
        z = ZoneInfo(self.p.timezone)
        local_open = bar.ts_utc.astimezone(z)
        if not inst.session.contains(local_open.time()):
            return False
        flatten = flatten_time_utc(local_open.date(), inst, self.p)
        return bar.close_ts < flatten
