"""FAST-4 signals, identical to research/ftmo_fast_pass.py: long when
close > SMA200 and RSI(2) < 10; stop entry - 3 x ATR(14); exit when
close > SMA5 or after 10 sessions; at most 2 positions, lowest RSI(2)
first. Pure functions over completed sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from .sessions import Session


@dataclass(frozen=True)
class Indicators:
    close: float
    sma200: Optional[float]
    sma5: Optional[float]
    rsi2: float
    atr14: float


def indicators(sessions: Sequence[Session]) -> Indicators:
    """Indicators on the last completed session (Wilder RSI(2) and
    ATR(14) as exponential averages from the first bar, like pandas
    ``ewm(alpha, adjust=False)``)."""
    closes = [s.close for s in sessions if s.complete]
    done = [s for s in sessions if s.complete]
    if len(closes) < 2:
        raise ValueError("need at least two completed sessions")
    gain = loss = None
    for a, b in zip(closes, closes[1:]):
        d = b - a
        g, lo = max(d, 0.0), max(-d, 0.0)
        gain = g if gain is None else gain + 0.5 * (g - gain)
        loss = lo if loss is None else loss + 0.5 * (lo - loss)
    rsi = 100.0 if not loss else 100 - 100 / (1 + gain / loss)
    atr = None
    for i, s in enumerate(done):
        tr = s.high - s.low if i == 0 else max(
            s.high - s.low, abs(s.high - done[i - 1].close),
            abs(s.low - done[i - 1].close))
        atr = tr if atr is None else atr + (tr - atr) / 14
    sma = lambda n: sum(closes[-n:]) / n if len(closes) >= n else None  # noqa: E731
    return Indicators(closes[-1], sma(200), sma(5), rsi, atr)


@dataclass(frozen=True)
class Plan:
    exits: List[str]
    entries: List[str]          # in priority order
    atr: Dict[str, float]       # ATR of the signal session, for the stop


def plan(ind: Dict[str, Indicators], held: Dict[str, int],
         max_positions: int = 2, max_hold: int = 10) -> Plan:
    """``held``: symbol -> sessions held so far (entry session counts 1)."""
    exits = [s for s, n in held.items()
             if s in ind and ind[s].sma5 is not None
             and (ind[s].close > ind[s].sma5 or n >= max_hold)]
    slots = max_positions - (len(held) - len(exits))
    cands = sorted((x.rsi2, s) for s, x in ind.items()
                   if s not in held and x.sma200 is not None
                   and x.close > x.sma200 and x.rsi2 < 10)
    entries = [s for _, s in cands[:max(0, slots)]]
    return Plan(exits, entries, {s: ind[s].atr14 for s in entries})
