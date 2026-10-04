#!/usr/bin/env python3
"""Mechanical test of the TJR NY-session sweep + break-of-structure method.

Implements exactly the rules pre-registered in
``research/tjr_ny_sweep_bos.md`` (committed before this script ran) and
scores every window with the repo gate's own ``Leg`` logic from
``scripts/expectancy.py``.

    python research/tjr_backtest.py --data-dir <dir with spy.csv, spy_1d.csv ...>

The 5-minute and daily files come from Astral (canonical OHLCV); they
are not committed (about 8 MB). Their sha256 values are in the note.
"""

from __future__ import annotations

import argparse
import bisect
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import expectancy as gate  # noqa: E402

NY = "America/New_York"
PER_SHARE = 0.005
MIN_ORDER = 1.00
SLIP = 0.01
RISK = 0.01
TARGET_R = 2.0
EXPOSURE = 0.95
SWEEP_START, SWEEP_END = 9 * 60 + 30, 11 * 60 + 30     # bar start in [.,.)
SETUP_DEADLINE = 12 * 60                                # bar end <= 12:00


def commission(shares: int) -> float:
    return max(MIN_ORDER, PER_SHARE * shares)


# ------------------------------------------------------------------ bars

@dataclass
class Bars:
    """Chronological OHLC with bar end times (minutes since epoch)."""
    o: List[float]
    h: List[float]
    l: List[float]
    c: List[float]
    end: List[pd.Timestamp]
    day: List[object] = field(default_factory=list)


def load_5m(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    ts = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert(NY)
    df["start"] = ts
    df["end"] = ts + pd.Timedelta(minutes=5)
    df["date"] = ts.dt.date
    df["mod"] = ts.dt.hour * 60 + ts.dt.minute
    return df.sort_values("start").reset_index(drop=True)


def resample(df: pd.DataFrame, edges: Sequence[int]) -> Bars:
    """Aggregate 5m RTH bars into buckets whose start minutes are
    ``edges`` (e.g. 570, 630, ... for 1h). A bucket ends at the next edge
    or at the day's last bar."""
    o, h, l, c, end, day = [], [], [], [], [], []
    for d, g in df.groupby("date", sort=True):
        b = [bisect.bisect_right(edges, m) - 1 for m in g["mod"]]
        g = g.assign(bucket=b)
        for _, gb in g.groupby("bucket", sort=True):
            o.append(gb["open"].iloc[0]); h.append(gb["high"].max())
            l.append(gb["low"].min()); c.append(gb["close"].iloc[-1])
            end.append(gb["end"].iloc[-1]); day.append(d)
    return Bars(o, h, l, c, end, day)


@dataclass
class Swings:
    """Swing points with the time each became known (2 bars later)."""
    hi_known: List[pd.Timestamp]
    hi_px: List[float]
    hi_idx: List[int]
    lo_known: List[pd.Timestamp]
    lo_px: List[float]
    lo_idx: List[int]


def swings(b: Bars, k: int = 2) -> Swings:
    hk, hp, hi, lk, lp, li = [], [], [], [], [], []
    n = len(b.h)
    for j in range(k, n - k):
        if all(b.h[j] > b.h[j - s] and b.h[j] > b.h[j + s]
               for s in range(1, k + 1)):
            hk.append(b.end[j + k]); hp.append(b.h[j]); hi.append(j)
        if all(b.l[j] < b.l[j - s] and b.l[j] < b.l[j + s]
               for s in range(1, k + 1)):
            lk.append(b.end[j + k]); lp.append(b.l[j]); li.append(j)
    # known times are increasing because j is
    return Swings(hk, hp, hi, lk, lp, li)


def bias(sw: Swings, t: pd.Timestamp) -> int:
    """+1 bullish (HH and HL), -1 bearish (LH and LL), 0 otherwise, using
    swings known at or before ``t``."""
    nh = bisect.bisect_right(sw.hi_known, t)
    nl = bisect.bisect_right(sw.lo_known, t)
    if nh < 2 or nl < 2:
        return 0
    up = sw.hi_px[nh - 1] > sw.hi_px[nh - 2] and sw.lo_px[nl - 1] > sw.lo_px[nl - 2]
    dn = sw.hi_px[nh - 1] < sw.hi_px[nh - 2] and sw.lo_px[nl - 1] < sw.lo_px[nl - 2]
    return 1 if up else (-1 if dn else 0)


def last_known(known: List[pd.Timestamp], px: List[float],
               t: pd.Timestamp) -> Optional[float]:
    n = bisect.bisect_right(known, t)
    return px[n - 1] if n else None


def last_swing_before(sw_known, sw_px, sw_idx, before_idx: int,
                      t: pd.Timestamp) -> Optional[float]:
    """Most recent swing formed at index < before_idx and known by t."""
    n = bisect.bisect_right(sw_known, t)
    for m in range(n - 1, -1, -1):
        if sw_idx[m] < before_idx:
            return sw_px[m]
    return None


# --------------------------------------------------------------- strategy

@dataclass
class Trade:
    day: object
    side: int
    entry: float
    stop: float
    target: float
    shares: int
    exit: float
    pnl: float
    r: float
    reason: str


class Market:
    def __init__(self, df5: pd.DataFrame) -> None:
        self.df = df5
        self.b5 = Bars(list(df5.open), list(df5.high), list(df5.low),
                       list(df5.close), list(df5.end), list(df5.date))
        self.start = list(df5.start)
        self.mod = list(df5["mod"])
        self.sw5 = swings(self.b5)
        e15 = list(range(570, 960, 15))
        e60 = [570, 630, 690, 750, 810, 870, 930]
        e240 = [570, 810]
        self.sw15 = swings(resample(df5, e15))
        self.sw60 = swings(resample(df5, e60))
        self.sw240 = swings(resample(df5, e240))
        self.days = sorted(df5.date.unique())
        idx = df5.groupby("date").indices
        self.day_idx = {d: sorted(idx[d]) for d in self.days}
        self.day_hi = {d: df5.high.iloc[self.day_idx[d]].max() for d in self.days}
        self.day_lo = {d: df5.low.iloc[self.day_idx[d]].min() for d in self.days}

    def htf_bias(self, t) -> int:
        a, b = bias(self.sw60, t), bias(self.sw240, t)
        return a if a == b else 0


def find_setup(m: Market, d, prev_d, side: int):
    """Scan one day for the first break of structure on ``side``
    (+1 long, -1 short). Returns (bos_index, extreme, extreme_index) or
    None."""
    ix = m.day_idx[d]
    b = m.b5
    pd_level = m.day_lo[prev_d] if side > 0 else m.day_hi[prev_d]
    state = None
    ext = e = None
    for g in ix:
        if state is None:
            if not (SWEEP_START <= m.mod[g] < SWEEP_END):
                continue
            t0 = m.start[g]
            if side > 0:
                sw = last_known(m.sw15.lo_known, m.sw15.lo_px, t0)
                levels = [x for x in (pd_level, sw) if x is not None]
                swept = any(b.l[g] < x for x in levels)
            else:
                sw = last_known(m.sw15.hi_known, m.sw15.hi_px, t0)
                levels = [x for x in (pd_level, sw) if x is not None]
                swept = any(b.h[g] > x for x in levels)
            if swept and m.htf_bias(b.end[g]) == side:
                state, ext, e = "swept", (b.l[g] if side > 0 else b.h[g]), g
            continue
        end_mod = m.mod[g] + 5
        if end_mod > SETUP_DEADLINE:
            return None
        if side > 0 and b.l[g] < ext:
            ext, e = b.l[g], g
        if side < 0 and b.h[g] > ext:
            ext, e = b.h[g], g
        if side > 0:
            ref = last_swing_before(m.sw5.hi_known, m.sw5.hi_px,
                                    m.sw5.hi_idx, e, b.end[g])
            if ref is not None and b.c[g] > ref:
                return g, ext, e
        else:
            ref = last_swing_before(m.sw5.lo_known, m.sw5.lo_px,
                                    m.sw5.lo_idx, e, b.end[g])
            if ref is not None and b.c[g] < ref:
                return g, ext, e
    return None


def entry_level(m: Market, side: int, e: int, k: int, ext: float) -> float:
    b = m.b5
    for i in range(k, e + 1, -1):           # most recent gap first
        if side > 0 and b.h[i - 2] < b.l[i]:
            return (b.h[i - 2] + b.l[i]) / 2
        if side < 0 and b.l[i - 2] > b.h[i]:
            return (b.l[i - 2] + b.h[i]) / 2
    if side > 0:
        return (ext + max(b.h[e:k + 1])) / 2
    return (ext + min(b.l[e:k + 1])) / 2


def trade_day(m: Market, d, prev_d, equity: float,
              sides: Tuple[int, ...]) -> Optional[Trade]:
    setups = []
    for s in sides:
        r = find_setup(m, d, prev_d, s)
        if r is not None:
            setups.append((r[0], s, r[1], r[2]))
    if not setups:
        return None
    k, side, ext, e = min(setups)            # first break of the day
    entry = entry_level(m, side, e, k, ext)
    stop = ext - 0.01 if side > 0 else ext + 0.01
    risk = (entry - stop) * side
    if risk <= 0:
        return None
    shares = min(int(RISK * equity // risk), int(equity // entry))
    if shares < 1:
        return None
    target = entry + side * TARGET_R * risk
    b = m.b5
    ix = [g for g in m.day_idx[d] if g > k]
    filled = None
    for pos, g in enumerate(ix):
        if m.mod[g] + 5 > SETUP_DEADLINE:
            return None
        # cancelled if price trades through the sweep extreme first
        if (side > 0 and b.o[g] <= stop) or (side < 0 and b.o[g] >= stop):
            return None
        if side > 0 and b.o[g] <= entry:
            filled = (pos, b.o[g])
        elif side < 0 and b.o[g] >= entry:
            filled = (pos, b.o[g])
        elif side > 0 and b.l[g] <= entry:
            filled = (pos, entry)
        elif side < 0 and b.h[g] >= entry:
            filled = (pos, entry)
        if filled:
            break
    if not filled:
        return None
    pos, px = filled
    exit_px, reason = None, "time"
    for g in ix[pos:]:
        hit_stop = b.l[g] <= stop if side > 0 else b.h[g] >= stop
        hit_tgt = b.h[g] >= target if side > 0 else b.l[g] <= target
        if hit_stop:
            exit_px, reason = stop - side * SLIP, "stop"
            break
        if hit_tgt:
            exit_px, reason = target, "target"
            break
    if exit_px is None:
        exit_px = b.c[ix[-1]] - side * SLIP
    gross = side * shares * (exit_px - px)
    pnl = gross - commission(shares) * 2
    return Trade(d, side, px, stop, target, shares, exit_px, pnl,
                 side * (exit_px - px) / risk, reason)


def run_tjr(m: Market, days: Sequence, cash: float,
            sides: Tuple[int, ...]) -> Tuple[List[float], List[Trade]]:
    eq, curve, trades = cash, [], []
    all_days = m.days
    for d in days:
        i = all_days.index(d)
        if i > 0:
            t = trade_day(m, d, all_days[i - 1], eq, sides)
            if t is not None:
                eq += t.pnl
                trades.append(t)
        curve.append(eq)
    return curve, trades


# -------------------------------------------------------------- benchmarks

def run_bh(m: Market, days: Sequence, cash: float) -> List[float]:
    first = m.day_idx[days[0]][0]
    px = m.b5.o[first]
    sh = int(EXPOSURE * cash // px)
    left = cash - sh * px - commission(sh)
    return [left + sh * m.b5.c[m.day_idx[d][-1]] for d in days]


def run_air3(m: Market, daily: pd.DataFrame, days: Sequence,
             cash: float) -> Tuple[List[float], int]:
    c = daily.set_index("date")["close"]
    s200, s50 = c.rolling(200).mean(), c.rolling(50).mean()
    eq_cash, sh, curve, trips = cash, 0, [], 0
    pending = 0     # +1 buy / -1 sell at next open
    for d in days:
        o = m.b5.o[m.day_idx[d][0]]
        if pending > 0 and sh == 0:
            sh = int(EXPOSURE * eq_cash // o)
            eq_cash -= sh * o + commission(sh)
        elif pending < 0 and sh > 0:
            eq_cash += sh * o - commission(sh)
            sh, trips = 0, trips + 1
        pending = 0
        close = m.b5.c[m.day_idx[d][-1]]
        if d in c.index and not math.isnan(s200.get(d, float("nan"))):
            cl, a, f = c[d], s200[d], s50[d]
            if sh == 0 and cl > 1.05 * a and f > a:
                pending = 1
            elif sh > 0 and cl < 0.95 * a:
                pending = -1
        curve.append(eq_cash + sh * close)
    return curve, trips


# ------------------------------------------------------------------ gate

def leg(label: str, days, curve: List[float], bh: List[float], cash: float,
        trades: Optional[List[Trade]] = None, trips: int = 0) -> gate.Leg:
    start = pd.Timestamp(days[0]).to_pydatetime()
    end = pd.Timestamp(days[-1]).to_pydatetime()
    wins = None
    if trades:
        wins = sum(1 for t in trades if t.pnl > 0) / len(trades)
    return gate.Leg(
        label=label, start=start, end=end, bars=len(days), final=curve[-1],
        cagr=gate.cagr(cash, curve[-1], start, end),
        max_dd=gate.drawdown_abs(curve), max_dd_pct=gate.drawdown_pct(curve),
        trips=len(trades) if trades is not None else trips, win_rate=wins,
        bh_final=bh[-1], bh_cagr=gate.cagr(cash, bh[-1], start, end),
        bh_max_dd_pct=gate.drawdown_pct(bh), kill_tripped=False, cash=cash,
        gain=curve[-1] - cash, bh_gain=bh[-1] - cash,
        bh_max_dd=gate.drawdown_abs(bh))


def windows(days: Sequence) -> List[Tuple[str, Sequence]]:
    out = [(f"fold {k}/3", days[a:b])
           for k, (a, b) in enumerate(gate.fold_slices(len(days), 3), 1)]
    return out + [("full sample", days)]


def verdict(legs: List[gate.Leg]) -> Tuple[int, bool, bool]:
    wins = sum(1 for x in legs[:-1] if x.passes)
    return wins, legs[-1].passes, wins >= 2 and legs[-1].passes


def row(x: gate.Leg) -> str:
    return (f"| {x.label} | {x.final:,.0f} | {x.gain / x.cash:+.1%} | "
            f"{x.max_dd_pct:.1%} | {gate.fmt_ratio(x.ratio)} | {x.trips} | "
            f"{gate.fmt_pct(x.win_rate)} | {x.bh_final:,.0f} | "
            f"{x.bh_gain / x.cash:+.1%} | {x.bh_max_dd_pct:.1%} | "
            f"{gate.fmt_ratio(x.bh_ratio)} | {x.verdict} |")


HEAD = ("| window | final $ | return | maxDD | gain/DD | trades | win% | "
        "B&H final $ | B&H return | B&H maxDD | B&H gain/DD | passes |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|---|")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--symbols", default="SPY,QQQ,SMH")
    ap.add_argument("--report", type=Path,
                    default=REPO / "reports" / "tjr_ny_sweep_bos.md")
    a = ap.parse_args(argv)
    out = ["# TJR NY-session sweep + BOS — gate results", "",
           "Rules: `research/tjr_ny_sweep_bos.md` (pre-registered). "
           "Costs: IBKR $0.005/share, $1.00 min per order, 1 cent "
           "slippage on stop/time exits. 5-minute regular-hours bars "
           "from Astral. Scored with `scripts/expectancy.py`'s rule.", ""]
    summary = []
    for sym in a.symbols.split(","):
        df5 = load_5m(a.data_dir / f"{sym.lower()}.csv")
        daily = pd.read_csv(a.data_dir / f"{sym.lower()}_1d.csv")
        daily["date"] = pd.to_datetime(daily["timestamp"], utc=True) \
            .dt.tz_convert(NY).dt.date
        daily = daily.drop_duplicates("date", keep="last").sort_values("date")
        m = Market(df5)
        for cash in (10_000.0, 870.0):
            for name, sides in (("A two-sided", (1, -1)),
                                ("B long-only (TFSA)", (1,))):
                legs, all_tr = [], []
                for lab, ds in windows(m.days):
                    curve, tr = run_tjr(m, ds, cash, sides)
                    legs.append(leg(lab, ds, curve, run_bh(m, ds, cash),
                                    cash, tr))
                    if lab == "full sample":
                        all_tr = tr
                w, full, ok = verdict(legs)
                out += [f"## {sym} — {name}, ${cash:,.0f}", "", HEAD,
                        *[row(x) for x in legs], ""]
                if all_tr:
                    rs = [t.r for t in all_tr]
                    gp = sum(t.pnl for t in all_tr if t.pnl > 0)
                    gl = -sum(t.pnl for t in all_tr if t.pnl < 0)
                    fees = sum(2 * commission(t.shares) for t in all_tr)
                    out.append(
                        f"Full sample: {len(all_tr)} trades on "
                        f"{len(m.days)} days, avg {sum(rs)/len(rs):+.2f}R, "
                        f"profit factor {gp / gl if gl else float('inf'):.2f}, "
                        f"commissions ${fees:,.0f}, exits: "
                        + ", ".join(f"{k} {sum(1 for t in all_tr if t.reason == k)}"
                                    for k in ("target", "stop", "time")) + ".")
                out += ["", f"Gate: passes {w}/3 folds, full sample "
                        f"{legs[-1].verdict} → **"
                        f"{'PASS' if ok else 'FAIL'}**", ""]
                summary.append((sym, name, cash, w, legs[-1], ok))
            # AIR3 comparison (same windows)
            legs = []
            for lab, ds in windows(m.days):
                curve, trips = run_air3(m, daily, ds, cash)
                legs.append(leg(lab, ds, curve, run_bh(m, ds, cash), cash,
                                None, trips))
            w, full, ok = verdict(legs)
            out += [f"## {sym} — AIR3 (comparison), ${cash:,.0f}", "", HEAD,
                    *[row(x) for x in legs], "",
                    f"Gate on this 2-year window: passes {w}/3 folds, full "
                    f"sample {legs[-1].verdict} → "
                    f"**{'PASS' if ok else 'FAIL'}**", ""]
            summary.append((sym, "AIR3", cash, w, legs[-1], ok))
    out += ["## Summary", "",
            "| symbol | strategy | start $ | folds passed | full-sample "
            "return | B&H return | maxDD | B&H maxDD | gate |",
            "|---|---|---|---|---|---|---|---|---|"]
    for sym, name, cash, w, x, ok in summary:
        out.append(f"| {sym} | {name} | {cash:,.0f} | {w}/3 | "
                   f"{x.gain / x.cash:+.1%} | {x.bh_gain / x.cash:+.1%} | "
                   f"{x.max_dd_pct:.1%} | {x.bh_max_dd_pct:.1%} | "
                   f"{'PASS' if ok else 'FAIL'} |")
    text = "\n".join(out) + "\n"
    a.report.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
