#!/usr/bin/env python3
"""The webinar's scale-out exits on FAST-4 under FTMO 2-Step rules, as
pre-registered in ``research/ftmo_scale_out.md``.

V0 is the bot's current policy. Its FTMO numbers come from
``research/ftmo_bot_policy.py`` itself (its two 3% rows). V1-V3 replace
the exits with the scale-out:

* TP1 at +1R closes half and moves the stop to the entry;
* TP2 at +1.5R closes a quarter and moves the stop to +1R;
* the last quarter trails at the highest close since entry - 1R;
* there is no SMA5 or time exit.

They run through the same FTMO functions (``phase``, ``evaluation``,
``funded`` and ``stats`` of that module), given the scale-out account in
place of the bot's.

Every variant runs twice:

* pessimistic: a daily bar that reaches a stop and a target is walked in
  the order that leaves the position worth less at the close, and the
  target lock decides on the close and flattens at the next open;
* optimistic: the bar is walked in the order that leaves the position
  worth more, and the intraday lock is used.

The per-trade figures and the CAGR come from one continuous account per
variant (V0's rule included) whose cap measures the loss lines from each
day-start balance; see the amendment in the note.

    python -B -I research/ftmo_scale_out.py --data-dir DIR [--report FILE] [--jobs N]

Prints the tables; ``--report`` also writes them to FILE.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import importlib.util
import math
import multiprocessing as mp
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("ftmo_bot_policy", HERE / "ftmo_bot_policy.py")
policy = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["ftmo_bot_policy"] = policy     # its dataclasses look themselves up here
_spec.loader.exec_module(policy)            # and it loads ftmo_fast_pass the same way
base = policy.base

MAX_POS, SIDE_COST, FIN_RATE = base.MAX_POS, base.SIDE_COST, base.FIN_RATE
MAX_LOSS, DAILY = base.MAX_LOSS, base.DAILY
WARMUP, STEP, SPLIT = base.WARMUP, base.STEP, base.SPLIT
SIX_MONTHS, FUNDED_DAYS = base.SIX_MONTHS, base.FUNDED_DAYS
WEBINAR_HITS, WEBINAR_TRADES, WEBINAR_GAIN = 42, 44, 5.17   # 42 of 44 winners, +517%
PLAUSIBLE = 0.01                                            # binomial tail bar
COHORTS = ("2011–18", "2019–26")
BOUNDS = ("pessimistic", "optimistic")
INF = float("inf")

# V0's FTMO rows: the bot policy's own 3% rows (cap 0.2%, lock at target + 0.3%)
V0_OPT, V0_PESS = policy.VARIANTS[1], policy.VARIANTS[2]
for _p, _on_close in ((V0_OPT, False), (V0_PESS, True)):
    assert (_p.risk, _p.cap_buffer, _p.lock_margin, _p.lock_on_close, _p.open_days_only,
            _p.notional_cap) == (0.03, 0.002, 0.003, _on_close, True, 3.0), _p


@dataclass(frozen=True)
class ScalePolicy(policy.Policy):
    """The bot's risk controls (3%, cap 0.2%, lock at target + 0.3%, 3x
    notional) with the exits chosen here. ``stop_first`` travels with
    ``lock_on_close``: both True is the pessimistic bound."""
    entry: str = "fast4"     # "fast4": RSI(2) < 10; "trend": a 20-session closing high
    exits: str = "scale"     # "scale": the scale-out; "fast4": V0's SMA5 / 10 sessions
    r_atr: float = 3.0       # R = r_atr x ATR(14) of the signal session
    tp1: float = 1.0         # targets, in R
    tp2: float = 1.5
    stop_first: bool = True
    cap_on_day_start: bool = False   # the continuous account: lines from the day-start balance


def bounds(tag: str, **kw) -> Tuple[ScalePolicy, ScalePolicy]:
    """(pessimistic, optimistic) runs of one variant."""
    return (ScalePolicy(f"{tag}, pessimistic", stop_first=True, lock_on_close=True, **kw),
            ScalePolicy(f"{tag}, optimistic", stop_first=False, lock_on_close=False, **kw))


SCALE = {
    "V1": bounds("V1", entry="fast4", r_atr=3.0),
    "V2": bounds("V2", entry="fast4", r_atr=1.5),
    "V3": bounds("V3", entry="trend", r_atr=3.0),
}
SENSITIVITY = {   # TP2 at +1.2R: reported, never used to pick a winner
    "V1 TP2 1.2R": bounds("V1 TP2 1.2R", entry="fast4", r_atr=3.0, tp2=1.2),
    "V2 TP2 1.2R": bounds("V2 TP2 1.2R", entry="fast4", r_atr=1.5, tp2=1.2),
    "V3 TP2 1.2R": bounds("V3 TP2 1.2R", entry="trend", r_atr=3.0, tp2=1.2),
}
V0_RULE = bounds("V0", entry="fast4", exits="fast4", r_atr=3.0)   # V0 in the scale-out account
FTMO_POL = {"V0": (V0_PESS, V0_OPT), **SCALE, **SENSITIVITY}
CONT_POL = {k: tuple(dataclasses.replace(p, cap_on_day_start=True) for p in pols)
            for k, pols in {"V0": V0_RULE, **SCALE, **SENSITIVITY}.items()}
CANONICAL = ["V0", *SCALE]
DESCRIBE = {
    "V0": "FAST-4 entry, stop 3×ATR, exit close > SMA5 or 10 sessions (the bot today)",
    "V1": "FAST-4 entry, R = 3×ATR, scale-out",
    "V2": "FAST-4 entry, R = 1.5×ATR, scale-out",
    "V3": "close > SMA200 and ≥ the prior 20 sessions' highest close, R = 3×ATR, scale-out",
}


@dataclass
class SPos:
    units: float             # still open
    entry: float
    stop: float              # in force
    notional: float          # of the initial units, at entry
    entry_bal: float
    r: float                 # initial stop distance, in price
    units0: float
    i0: int                  # entry session
    tp1: bool = False
    tp2: bool = False
    hc: float = 0.0          # highest close since entry
    cash_in: float = 0.0     # proceeds of the closes so far, net of costs
    held: int = 0
    fin: float = 0.0


class Walk(NamedTuple):
    cash: float              # taken this session, net of costs
    units: float             # still open after it
    stop: float
    tp1: bool
    tp2: bool
    closed: bool
    gap: bool                # closed at the open (it opened through the stop)
    low: float               # lowest value on the path: cash taken + units open x price
    high: float              # highest value on the path
    value: float             # value at the close


def walk(p: SPos, o: float, h: float, l: float, c: float, low_first: bool,
         tp1: float, tp2: float) -> Walk:
    """One session of ``p`` through its resting orders, with the bar's
    extremes in the order given: open, low, high, close if ``low_first``,
    else open, high, low, close. A level the open is through fills at the
    open. Pure: ``p`` is not changed."""
    units, stop, done1, done2 = p.units, p.stop, p.tp1, p.tp2
    t1, t2 = p.entry + tp1 * p.r, p.entry + tp2 * p.r
    q1, q2 = 0.5 * p.units0, 0.25 * p.units0
    cash, closed, gap = 0.0, False, False
    vals = [units * o]
    if o <= stop:                                    # opened through the stop
        cash += units * o - units * o * SIDE_COST
        units, closed, gap = 0.0, True, True
    else:
        if not done1 and o >= t1:                    # opened through TP1
            cash += q1 * o - q1 * o * SIDE_COST
            units, done1, stop = units - q1, True, max(stop, p.entry)
        if done1 and not done2 and o >= t2:          # and through TP2
            cash += q2 * o - q2 * o * SIDE_COST
            units, done2, stop = units - q2, True, max(stop, p.entry + p.r)
    vals.append(cash + units * o)
    prev = o
    for px in ((l, h, c) if low_first else (h, l, c)):
        if closed:
            break
        if px < prev and px <= stop:                 # falls through the stop
            fill = min(stop, prev)
            cash += units * fill - units * fill * SIDE_COST
            units, closed = 0.0, True
        elif px > prev:                              # rises through the targets
            if not done1 and px >= t1:
                cash += q1 * t1 - q1 * t1 * SIDE_COST
                units, done1, stop = units - q1, True, max(stop, p.entry)
                vals.append(cash + units * t1)
            if done1 and not done2 and px >= t2:
                cash += q2 * t2 - q2 * t2 * SIDE_COST
                units, done2, stop = units - q2, True, max(stop, p.entry + p.r)
                vals.append(cash + units * t2)
        vals.append(cash + units * px)
        prev = px
    return Walk(cash, units, stop, done1, done2, closed, gap, min(vals), max(vals),
                cash + units * c)


class ScaleAcct(policy.Acct):
    """The bot policy's account (the cap, trading days, the lock hooks)
    holding positions with a resting stop and targets. With the scale-out
    exits: partial closes, the trailing quarter, no SMA5 or time exit.
    With ``exits="fast4"``: V0's rule, for the continuous account."""

    def __init__(self, dates, inst, pol: ScalePolicy) -> None:
        super().__init__(dates, inst, pol)
        self.log: List[dict] = []

    def committed(self) -> float:
        """Open risk to the stops in force; zero once a stop is at the entry."""
        return sum(p.units * max(0.0, p.entry - p.stop) for p in self.pos.values())

    def _finish(self, s: str, i: int, at_open: bool) -> None:
        p = self.pos.pop(s)
        pnl = p.cash_in - p.notional - p.notional * SIDE_COST - p.fin
        self.trades.append((self.entry_dates.pop(s), pnl / p.entry_bal))
        self.log.append(dict(sym=s, i0=p.i0, i1=i, entry=p.entry, r=p.r, pnl=pnl,
                             R=pnl / (p.units0 * p.r), risk=p.units0 * p.r / p.entry_bal,
                             tp1=p.tp1, held=p.held, at_open=at_open,
                             scale=self.pol.exits == "scale"))
        if not self.pol.open_days_only:
            self._filled(i)

    def _close(self, s: str, px: float, i: int) -> None:
        """Close what is left at ``px``: V0's exits at the open, and the
        target lock's flattening."""
        p = self.pos[s]
        proceeds = p.units * px
        self.cash += proceeds - proceeds * SIDE_COST
        p.cash_in += proceeds - proceeds * SIDE_COST
        p.units = 0.0
        self._finish(s, i, bool(px == self.inst[s]["o"][i]))

    def _signal_exits(self, i: int) -> None:
        """Exits decided on the close for the next open: none in V1-V3."""
        if self.pol.exits == "fast4":
            for s, p in self.pos.items():
                x = self.inst[s]
                if x["c"][i] > x["sma5"][i] or p.held >= 10:
                    self.pend_out.add(s)

    def step(self, i: int):
        inst, pol = self.inst, self.pol
        tp1, tp2 = (pol.tp1, pol.tp2) if pol.exits == "scale" else (INF, INF)
        for s in list(self.pend_out):
            if s in self.pos:
                self._close(s, inst[s]["o"][i], i)
        self.pend_out.clear()
        for s, atr in self.pend_in:                  # entries at the open, sized as the bot does
            if s in self.pos or len(self.pos) >= MAX_POS:
                continue
            bal = self.balance()
            entry = inst[s]["o"][i]
            r = pol.r_atr * atr
            dist = r / entry
            if dist <= 0:
                continue
            risk_amt = pol.risk * bal
            if pol.cap_buffer is not None:
                size = self.day_start if pol.cap_on_day_start else 1.0
                worst = bal - self.committed()
                room = min(worst - (self.day_start - DAILY * size + pol.cap_buffer * size),
                           worst - ((1 - MAX_LOSS) * size + pol.cap_buffer * size))
                risk_amt = min(risk_amt, room)
                if risk_amt <= 0:
                    continue
            notional = min(pol.notional_cap * bal, risk_amt / dist)
            units = notional / entry
            self.pos[s] = SPos(units, entry, entry - r, notional, bal, r, units, i)
            self.cash -= notional + notional * SIDE_COST
            self.entry_dates[s] = self.dates[i]
            self._filled(i)
        self.pend_in = []
        low_eq = high_eq = self.cash                 # each position adds its path's extremes
        for s in list(self.pos):
            x, p = inst[s], self.pos[s]
            bar = (x["o"][i], x["h"][i], x["l"][i], x["c"][i])
            a = walk(p, *bar, True, tp1, tp2)
            b = walk(p, *bar, False, tp1, tp2)
            if (a.value, a.low) > (b.value, b.low):
                a, b = b, a                          # a: worth less at the close
            w = a if pol.stop_first else b
            low_eq += w.low
            high_eq += w.high
            self.cash += w.cash
            p.cash_in += w.cash
            p.units, p.stop, p.tp1, p.tp2 = w.units, w.stop, w.tp1, w.tp2
            if w.closed:
                self._finish(s, i, w.gap)
                continue
            p.hc = max(p.hc, bar[3])
            if p.tp2:                                # the last quarter trails on the close
                p.stop = max(p.stop, p.entry + p.r, p.hc - p.r)
        nxt = self.dates[i + 1] if i + 1 < len(self.dates) else self.dates[i]
        nights = max(1, int((nxt - self.dates[i]) / np.timedelta64(1, "D")))
        for p in self.pos.values():                  # financing on the notional still open
            charge = p.units * p.entry * FIN_RATE * nights / 365
            self.cash -= charge
            p.fin += charge
            p.held += 1
        close_eq = self.cash + sum(p.units * inst[s]["c"][i] for s, p in self.pos.items())
        self._signal_exits(i)
        slots = MAX_POS - (len(self.pos) - len(self.pend_out))
        cands = []
        for s, x in inst.items():
            if s in self.pos or np.isnan(x["sma200"][i]):
                continue
            c = x["c"][i]
            if pol.entry == "trend":
                ok = c > x["sma200"][i] and c >= x["hi20"][i]
            else:
                ok = c > x["sma200"][i] and x["rsi"][i] < 10
            if ok:
                cands.append((x["rsi"][i], s, x["atr"][i]))
        cands.sort()
        self.pend_in = [(s, a) for _, s, a in cands[:max(0, slots)]]
        return low_eq, close_eq, high_eq


@contextlib.contextmanager
def scale_harness():
    """The bot policy's FTMO functions build their accounts through the
    module name ``Acct``; point it at the scale-out account meanwhile."""
    saved = policy.Acct
    policy.Acct = ScaleAcct
    try:
        yield
    finally:
        policy.Acct = saved


def full_run(dates, inst, pol, cls):
    """One account from session WARMUP to the end, with no FTMO stop."""
    a = cls(dates, inst, pol)
    eq = []
    for i in range(WARMUP, len(dates)):
        a.day_start = a.balance()
        eq.append(a.step(i)[1])
    return a, np.array(eq)


def first_touch(x: dict, i0: int, entry: float, r: float, stop_first: bool) -> Optional[bool]:
    """True if entry + r trades before entry - r from the fill at session
    i0's open, regardless of any exit; None if neither by the end."""
    up, dn = entry + r, entry - r
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


def v0_reached(x: dict, t: dict, stop_first: bool) -> bool:
    """V0 has no TP1: did its price reach entry + 1R while it was open?"""
    up = t["entry"] + t["r"]
    if (x["h"][t["i0"]:t["i1"]] >= up).any():       # sessions held in full
        return True
    if t["at_open"]:                                 # left at the exit session's open
        return bool(x["o"][t["i1"]] >= up)
    return (not stop_first) and bool(x["h"][t["i1"]] >= up)   # stopped in the session


def trade_metrics(dates, inst, acct, eq, stop_first: bool) -> dict:
    log = sorted(acct.log, key=lambda t: (t["i0"], t["sym"]))
    pnl = np.array([t["pnl"] for t in log])
    rr = np.array([t["R"] for t in log])
    win = pnl > 0
    hit = np.array([t["tp1"] if t["scale"] else v0_reached(inst[t["sym"]], t, stop_first)
                    for t in log])
    touch = [first_touch(inst[t["sym"]], t["i0"], t["entry"], t["r"], stop_first) for t in log]
    for t, h, f in zip(log, hit, touch):             # V1-V3: TP1 before the stop is that event
        assert not t["scale"] or bool(h) == f, ("TP1 fill disagrees with the scan", t)
    resolved = [f for f in touch if f is not None]
    longest = run = 0
    for w in win:
        run = 0 if w else run + 1
        longest = max(longest, run)
    curve = np.concatenate([[1.0], eq])
    years = (dates[-1] - dates[WARMUP]) / np.timedelta64(1, "D") / 365.25
    return dict(trades=len(log), webinar=hit.mean(), pnl_win=win.mean(),
                avg_win=rr[win].mean(), avg_loss=rr[~win].mean(), exp=rr.mean(),
                p1r=float(np.mean(resolved)), unresolved=len(touch) - len(resolved),
                max_cl=longest, risk=float(np.mean([t["risk"] for t in log])),
                held=float(np.median([t["held"] for t in log])), final=curve[-1],
                cagr=curve[-1] ** (1 / years) - 1,
                mdd=float((1 - curve / np.maximum.accumulate(curve)).max()),
                trades_by=list(acct.trades), open_at_end=len(acct.pos))


def binom_tail(k: int, n: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p)."""
    return sum(math.comb(n, j) * p ** j * (1 - p) ** (n - j) for j in range(k, n + 1))


DATA: Dict[str, object] = {}     # set in main before the worker processes fork


def ftmo_job(job: Tuple[str, int, str]):
    key, b, cohort = job
    pol = FTMO_POL[key][b]
    se, sf = DATA["starts"][cohort]
    if isinstance(pol, ScalePolicy):
        with scale_harness():
            return job, policy.stats(DATA["dates"], DATA["inst"], pol, se, sf)
    return job, policy.stats(DATA["dates"], DATA["inst"], pol, se, sf)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--report", type=Path, default=None,
                    help="also write the tables here (default: print only)")
    ap.add_argument("--jobs", type=int, default=max(1, (mp.cpu_count() or 1)),
                    help="worker processes for the FTMO runs")
    ap.add_argument("--fee", type=float, default=89.0,
                    help="EUR per attempt (the $10k 2-Step fee) for the cost line")
    a = ap.parse_args(argv)
    dates, inst = base.load_all(a.data_dir)
    for x in inst.values():                          # V3: the prior 20 sessions' highest close
        x["hi20"] = pd.Series(x["c"]).shift(1).rolling(20).max().to_numpy()
    n = len(dates)
    six = np.timedelta64(SIX_MONTHS, "D")
    starts = {
        COHORTS[0]: ([s for s in range(WARMUP, n, STEP) if dates[s] < SPLIT
                      and dates[s] + six <= dates[-1]],
                     [s for s in range(WARMUP, n - FUNDED_DAYS, STEP) if dates[s] < SPLIT]),
        COHORTS[1]: ([s for s in range(WARMUP, n, STEP) if dates[s] >= SPLIT
                      and dates[s] + six <= dates[-1]],
                     [s for s in range(WARMUP, n - FUNDED_DAYS, STEP) if dates[s] >= SPLIT]),
    }
    DATA.update(dates=dates, inst=inst, starts=starts)
    say = lambda m: print(m, file=sys.stderr, flush=True)   # noqa: E731

    # V0's rule in the scale-out account, with the bot's cap, must be the bot policy's V0
    ref, _ = full_run(dates, inst, V0_PESS, policy.Acct)
    mine, _ = full_run(dates, inst, V0_RULE[0], ScaleAcct)
    assert len(ref.trades) == len(mine.trades) and all(
        x[0] == y[0] and abs(x[1] - y[1]) < 1e-12 for x, y in zip(ref.trades, mine.trades)), \
        "the scale-out account does not reproduce V0"

    # 1-2. per trade and at 3% risk: the continuous account, each variant and bound
    metrics = {k: [trade_metrics(dates, inst, *full_run(dates, inst, p, ScaleAcct), p.stop_first)
                   for p in pols] for k, pols in CONT_POL.items()}
    say("continuous accounts done")

    # 3. FTMO, through the bot policy's own functions
    jobs = [(k, b, c) for k in FTMO_POL for b in (0, 1) for c in COHORTS]
    jobs.sort(key=lambda j: j[0] == "V0")            # the slower scale-out runs first
    if a.jobs > 1:
        with mp.get_context("fork").Pool(a.jobs) as pool:
            ftmo = dict(pool.map(ftmo_job, jobs, chunksize=1))
    else:
        ftmo = dict(map(ftmo_job, jobs))
    say("FTMO runs done")

    first, last = pd.Timestamp(dates[WARMUP]).date(), pd.Timestamp(dates[-1]).date()
    out = [f"Common dates {pd.Timestamp(dates[0]).date()} → {last}. Continuous account "
           f"{first} → {last}. Start dates (2011–18 / 2019–26): "
           f"{len(starts[COHORTS[0]][0])} / {len(starts[COHORTS[1]][0])} evaluations, "
           f"{len(starts[COHORTS[0]][1])} / {len(starts[COHORTS[1]][1])} funded. Check "
           f"passed: V0's rule in the scale-out account with the bot's cap reproduces the "
           f"bot policy's {len(ref.trades)} V0 trades.", ""]
    out += [f"* **{k}**: {DESCRIBE[k]}" for k in CANONICAL] + [""]
    for title, keys in (("Canonical variants (TP2 = 1.5R)", CANONICAL),
                        ("Sensitivity only: TP2 = 1.2R (not used to pick a winner)",
                         list(SENSITIVITY))):
        out += [f"### {title}", "", "**Per trade** (continuous account at 3% risk; trades "
                "still open at the end are left out):", "",
                "| variant | bound | trades | webinar-style win rate | P&L win rate | "
                "avg win (R) | avg loss (R) | expectancy (R/trade) | P(+1R before −1R) | "
                "max consecutive losses | avg initial risk | median sessions held |",
                "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for k in keys:
            for b, bound in enumerate(BOUNDS):
                m = metrics[k][b]
                out.append(f"| {k} | {bound} | {m['trades']} | {m['webinar']:.1%} | "
                           f"{m['pnl_win']:.1%} | {m['avg_win']:+.2f} | {m['avg_loss']:+.2f} | "
                           f"{m['exp']:+.3f} | {m['p1r']:.1%} | {m['max_cl']} | "
                           f"{m['risk']:.2%} | {m['held']:.0f} |")
        unres = {f"{k} {BOUNDS[b]}": metrics[k][b]["unresolved"] for k in keys for b in (0, 1)
                 if metrics[k][b]["unresolved"]}
        opn = {f"{k} {BOUNDS[b]}": metrics[k][b]["open_at_end"] for k in keys for b in (0, 1)
               if metrics[k][b]["open_at_end"]}
        out += ["", f"Unresolved in the ±1R scan: {unres or 'none'}. Open at the end: "
                f"{opn or 'none'}.", "",
                f"**At 3% risk over the full sample** ({first} → {last}, daily closes):", "",
                "| variant | bound | final equity | CAGR | max drawdown |", "|---|---|---|---|---|"]
        for k in keys:
            for b, bound in enumerate(BOUNDS):
                m = metrics[k][b]
                out.append(f"| {k} | {bound} | {m['final']:.2f}× | {m['cagr']:+.1%} | "
                           f"{m['mdd']:.1%} |")
        out += ["", "**FTMO** (the layout of `reports/ftmo_bot_policy.md`; cohorts by start "
                "date; trade columns from the continuous account):", "",
                "| policy | period | trades | win rate | profit factor | P1 passed | "
                "both ≤6 mo | both ≤18 mo | both, ever | breached | still running | "
                "days to pass (p25 / median / p75) | main failure | funded 1y survival | "
                "funded 1y return (median, survivors) |",
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        fees = []
        for k in keys:
            for b, bound in enumerate(BOUNDS):
                trades = metrics[k][b]["trades_by"]
                for c, (lo, hi) in zip(COHORTS, ((None, SPLIT), (SPLIT, None))):
                    trs = [t for t in trades
                           if (lo is None or t[0] >= lo) and (hi is None or t[0] < hi)]
                    cnt, wr, pf = base.trade_stats(trs)
                    r = ftmo[(k, b, c)]
                    out.append(f"| {k} {bound} | {c} | {cnt} | {wr:.0%} | {pf:.2f} | "
                               f"{r['p1']:.0%} | {r['p6']:.0%} | {r['p18']:.0%} | "
                               f"{r['pe']:.0%} | {r['breach']:.0%} | {r['running']:.0%} | "
                               f"{r['q1']:.0f} / {r['md']:.0f} / {r['q3']:.0f} | "
                               f"{r['main_fail']} | {r['surv']:.0%} | {r['fret']:+.1%} |")
                    if r["pe"] > 0:
                        att = (r["pe"] + r["breach"]) / r["pe"]
                        fees.append(f"* {k} {bound}, {c} starts: {att:.2f} attempts per pass, "
                                    f"about EUR {a.fee * att:,.0f} of fees per pass.")
        out += ["", f"Fees per funded account at EUR {a.fee:.0f} per attempt (a breach "
                "costs a new fee):", ""] + fees + [""]

    # 4. the pre-registered verdict: canonical V1-V3 against V0, cell by cell
    out += ["### Verdict, by the pre-registered rule", "",
            "A variant beats V0 only if, in both cohorts and under both bounds (pessimistic "
            "against V0's next-open row, optimistic against V0's intraday row), it breached "
            "no more often AND passed both phases within 18 months more often, on the same "
            "start dates.", "",
            "| variant | cohort | bound | breached: variant vs V0 | both ≤18 mo: variant vs V0 "
            "| condition met |", "|---|---|---|---|---|---|"]
    winners = []
    for k in SCALE:
        cells = []
        for c in COHORTS:
            m = len(starts[c][0])
            for b, bound in enumerate(BOUNDS):
                rv, r0 = ftmo[(k, b, c)], ftmo[("V0", b, c)]
                bv, b0 = round(rv["breach"] * m), round(r0["breach"] * m)
                pv, p0 = round(rv["p18"] * m), round(r0["p18"] * m)
                ok = bv <= b0 and pv > p0
                cells.append((ok, rv["p18"], rv["breach"]))
                out.append(f"| {k} | {c} | {bound} | {bv}/{m} ({bv / m:.1%}) vs {b0}/{m} "
                           f"({b0 / m:.1%}) | {pv}/{m} ({pv / m:.1%}) vs {p0}/{m} "
                           f"({p0 / m:.1%}) | {'yes' if ok else 'no'} |")
        if all(ok for ok, _, _ in cells):
            winners.append((min(p for _, p, _ in cells), -max(br for _, _, br in cells), k))
    out.append("")
    if winners:
        best = max(winners)[2]
        out.append(f"**Beats V0:** {', '.join(w[2] for w in sorted(winners, reverse=True))}; "
                   f"preferred by the tie-break: **{best}**.")
    else:
        out.append("**No variant beats V0** in all four cells; by the rule the bot keeps V0.")

    # the webinar's hit rate against the measured P(+1R before -1R)
    p_best, k_best = max((metrics[k][1]["p1r"], k) for k in CONT_POL)
    tail = binom_tail(WEBINAR_HITS, WEBINAR_TRADES, p_best)
    need = ((1 + WEBINAR_GAIN) ** (1 / WEBINAR_TRADES) - 1) / 0.03
    out += ["", "### The webinar's hit rate", "",
            f"Highest measured P(+1R before −1R), optimistic bound: {p_best:.1%} ({k_best}). "
            f"At that rate, P(at least {WEBINAR_HITS} of {WEBINAR_TRADES}) = {tail:.2e} "
            f"(bar: below {PLAUSIBLE:.0%} = implausible) → "
            f"**{'implausible' if tail < PLAUSIBLE else 'not ruled out'}**. "
            f"+{WEBINAR_GAIN:.0%} over {WEBINAR_TRADES} trades at 3% risk needs a mean of "
            f"{need:+.2f}R per trade, compounded."]
    text = "\n".join(out) + "\n"
    if a.report is not None:
        a.report.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
