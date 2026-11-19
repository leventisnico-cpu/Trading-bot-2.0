"""The 5-step trade management (the operator's "Wall Street Income
Masterclass" deck), as tested pre-registered in research/ftmo_scale_out.md
(variant V1: FAST-4's entry, R = its 3 x ATR(14) stop):

1-2. size: 3% of the balance at risk from the entry to the first stop. The
     deck's "30% of the account with a 10% stop" is that same 3%; on index
     CFDs the bot sizes for the 3% directly, R = entry - first stop;
3.   at entry + 1R, close 1/2 of the first volume; the stop moves to the
     entry (break-even);
4.   at entry + 1.5R, close another 1/4; the stop moves to entry + 1R;
5.   the last 1/4 is never sold by hand: after each session's close its
     stop rises to max(entry + 1R, highest close since entry - 1R). A stop
     never moves down.

There is no SMA5 or time exit. Whether a trade loses is settled before
step 3: it loses when price falls 1R before it rises 1R, which depends on
the entry, not on these steps (the study measured 38-39% losers).

Pure functions; ``runner.Runner.manage`` applies them to live positions."""

from __future__ import annotations

import math
from typing import Optional

TP1_R = 1.0          # first target, in R
TP2_R = 1.5          # second target, in R (the deck's +12-15%; 1.5R as tested)
TRAIL_R = 1.0        # the last quarter trails this far under the highest close
#: share of the first volume closed once each stage is reached
CLOSED = {0: 0.0, 1: 0.5, 2: 0.75}
EPS = 1e-9

DESCRIPTION = ("5-step scale-out: 1/2 at +1R, stop to entry; 1/4 at +1.5R, stop to "
               "+1R; the last 1/4 trails 1R under the highest close (no SMA5 or "
               "time exit)")


def stage(price: float, entry: float, r: float, reached: int = 0) -> int:
    """The stage a position is in at ``price``: 0 before the first target,
    1 after +1R, 2 after +1.5R. A stage once reached is kept (``reached``):
    a target that filled stays filled when price falls back."""
    s = reached
    if price >= entry + TP2_R * r:
        s = max(s, 2)
    elif price >= entry + TP1_R * r:
        s = max(s, 1)
    return s


def stop_floor(st: int, entry: float, r: float,
               high_close: Optional[float] = None) -> Optional[float]:
    """The lowest the stop may sit at stage ``st`` (None: the first stop
    stands). ``high_close``: the highest session close since entry; the
    trail uses it from stage 2 on."""
    if st <= 0:
        return None
    if st == 1:
        return entry
    floor = entry + TP1_R * r
    if high_close is not None:
        floor = max(floor, high_close - TRAIL_R * r)
    return floor


def _steps(volume: float, step: float) -> int:
    return math.floor(volume / step + EPS)


def to_close(first_volume: float, volume: float, st: int,
             step: float, volume_min: float) -> float:
    """Lots to close now so that stage ``st``'s share of the first volume
    is closed (0.0 if none is due). The share is rounded to the volume step
    (half up). A slice under the minimum lot is not sent. A target never
    sells the last minimum lot (step 5: only a stop ends a trade), so a
    slice that would leave less than that open leaves the minimum lot; a
    single minimum lot is never split and keeps all of the stop moves."""
    if step <= 0 or st <= 0:
        return 0.0
    closed = math.floor(CLOSED[min(st, 2)] * first_volume / step + 0.5 + EPS) * step
    keep = max(0.0, first_volume - closed)
    x = _steps(volume - keep, step) * step
    if x < volume_min - EPS:
        return 0.0
    if volume - x < volume_min - EPS:                # keep the minimum lot open
        x = _steps(volume - volume_min, step) * step
        if x < volume_min - EPS:
            return 0.0
    return round(x, 8)
