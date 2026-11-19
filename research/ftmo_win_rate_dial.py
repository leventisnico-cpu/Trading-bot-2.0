#!/usr/bin/env python3
"""What a win rate of 30 in 31 takes: a diagnostic, not a strategy.

For every FAST-4 signal in the study's data (close > SMA200 and RSI(2) < 10,
bought at the next open, each signal on its own, no position limit), scan
forward for which comes first: a target ``a`` x R above the entry or a
stop ``b`` x R below it, with R = 3 x ATR(14) as in the bot. A gap at the
open counts at the open's level; a bar that touches both counts as the
stop (pessimistic) or the target (optimistic).

The grid is printed whole. Nothing is chosen from it: a cell here is not a
tested rule (overlapping signals, no costs, no account, no FTMO lines).

    python -B -I research/ftmo_win_rate_dial.py --data-dir DIR [--report FILE]
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("ftmo_fast_pass", HERE / "ftmo_fast_pass.py")
base = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["ftmo_fast_pass"] = base
_spec.loader.exec_module(base)

R_ATR = 3.0
TARGETS = (0.1, 0.25, 0.5, 1.0)        # x R
STOPS = (1.0, 2.0, 3.0, 5.0)           # x R
CLAIM = 30 / 31


def first_passage(x: dict, i0: int, up: float, dn: float, stop_first: bool) -> Optional[bool]:
    """True if ``up`` trades before ``dn`` from the fill at session i0's
    open; None if neither by the end of the data."""
    o, h, l = x["o"], x["h"], x["l"]
    for j in range(i0, len(o)):
        if j > i0:
            if o[j] <= dn:
                return False
            if o[j] >= up:
                return True
        hit_up, hit_dn = h[j] >= up, l[j] <= dn
        if hit_up and hit_dn:
            return not stop_first
        if hit_up:
            return True
        if hit_dn:
            return False
    return None


def signals(inst: dict) -> list:
    out = []
    for name, x in inst.items():
        for i in range(base.WARMUP, len(x["c"]) - 1):
            if x["c"][i] > x["sma200"][i] and x["rsi"][i] < 10:
                out.append((name, i + 1, float(x["o"][i + 1]), R_ATR * float(x["atr"][i])))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--report", type=Path)
    a = ap.parse_args(argv)
    dates, inst = base.load_all(a.data_dir)
    sig = signals(inst)
    years = (dates[-1] - dates[base.WARMUP]) / np.timedelta64(1, "D") / 365.25
    first, last = pd.Timestamp(dates[base.WARMUP]).date(), pd.Timestamp(dates[-1]).date()
    out = [f"FAST-4 signals {first} → {last}: {len(sig)} over {years:.1f} years on the four "
           "indices (every signal counted, so they overlap). R = 3 × ATR(14).", "",
           "Each cell: win rate (pessimistic–optimistic), then the payoff per trade in R "
           "at the pessimistic rate, before costs. **Bold**: at least 30 wins in 31.", "",
           "| first target ↓ / stop → | " + " | ".join(f"−{b:g}R" for b in STOPS) + " |",
           "|---|" + "---|" * len(STOPS)]
    best = []
    for t in TARGETS:
        row = [f"+{t:g}R"]
        for b in STOPS:
            rates = []
            for stop_first in (True, False):
                res = [first_passage(inst[n], i0, e + t * r, e - b * r, stop_first)
                       for n, i0, e, r in sig]
                res = [x for x in res if x is not None]
                rates.append(sum(res) / len(res))
            p = rates[0]
            pay = p * t - (1 - p) * b
            cell = f"{rates[0]:.1%}–{rates[1]:.1%}, {pay:+.3f}R"
            if p >= CLAIM:
                cell = f"**{cell}**"
                best.append((t, b, p, pay))
            row.append(cell)
        out.append("| " + " | ".join(row) + " |")
    out.append("")
    if best:
        t, b, p, pay = min(best, key=lambda z: z[1] / z[0])
        out.append(f"The closest stop that gives 30 in 31 here: target +{t:g}R with the stop "
                   f"at −{b:g}R, {b / t:.0f} times further away. It wins {p:.1%} of the "
                   f"time; one loss takes back {b / t:.0f} wins; the payoff is {pay:+.3f}R "
                   "per trade before costs.")
    else:
        out.append("No cell reaches 30 wins in 31.")
    text = "\n".join(out) + "\n"
    if a.report:
        a.report.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
