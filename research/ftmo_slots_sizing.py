#!/usr/bin/env python3
"""Slots and sizing around the 5 steps, as pre-registered in
``research/ftmo_slots_sizing.md``:

* S1: an entry risks at most one third of the room over the max-loss line
  (V1 lets it use all of that room);
* S2: a position whose stop is at or above its entry takes no slot;
* S3: both.

Each runs at both buffers over the max-loss line and is judged against
the rule it would replace: V1 at 0.2%, W2 at 1.5%. Everything else is
``research/ftmo_scale_out_v2.py`` (and through it
``research/ftmo_scale_out.py``), imported unchanged, through the same FTMO
functions.

    python -B -I research/ftmo_slots_sizing.py --data-dir DIR [--report FILE] [--jobs N]
        [--check-only]

``--check-only`` runs the plumbing checks alone (V1 and W2 reproduced, the
pre-registered signal counts) and computes nothing for S1-S3.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import importlib.util
import multiprocessing as mp
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("ftmo_scale_out_v2", HERE / "ftmo_scale_out_v2.py")
v2 = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["ftmo_scale_out_v2"] = v2
_spec.loader.exec_module(v2)
so, policy, base = v2.so, v2.policy, v2.base
COHORTS, BOUNDS, SPLIT = so.COHORTS, so.BOUNDS, so.SPLIT
WARMUP, STEP = so.WARMUP, so.STEP
SIX_MONTHS, FUNDED_DAYS = so.SIX_MONTHS, so.FUNDED_DAYS

THIRD, HALF = 1 / 3, 0.5
EIGHTEEN_MONTHS, THREE_YEARS = policy.EIGHTEEN_MONTHS, 1096
FROZEN_ROOM = 0.0005      # of the initial balance (research/ftmo_frozen_accounts.py)
STUCK_RISK = 0.005        # a new entry may risk less than this: stuck
# V1's signal counts, pessimistic bound, as written in the note before the run
PREREG_SIGNALS = dict(signals=990, planned=153, held=408, held_free=179, no_slot=429,
                      no_slot_free=250, no_slot_all_free=161, days=3725, days_full=2341,
                      days_full_free=1706, pos_days=5295, free_days=2990)
# frozen shares already published (research/ftmo_scale_out_v2.md, the correction)
PUBLISHED_FROZEN = {("V1", 0, 0): "16.8%", ("V1", 1, 0): "16.5%", ("V1", 0, 1): "29.9%",
                    ("V1", 1, 1): "30.2%", ("W2", 0, 0): "46.9%", ("W2", 1, 0): "41.8%",
                    ("W2", 0, 1): "41.6%", ("W2", 1, 1): "41.6%"}


@dataclass(frozen=True)
class SlotPolicy(v2.SafePolicy):
    room_share: float = 1.0      # of the room over the max-loss line an entry may risk
    free_slots: bool = False     # a position with its stop at or over its entry takes no slot


class SlotAcct(v2.SafeAcct):
    """The scale-out account with the two rules. With the share at one and
    free slots off it is ``SafeAcct`` exactly (asserted in ``main``)."""

    def __init__(self, dates, inst, pol) -> None:
        super().__init__(dates, inst, pol)
        self.sig: Counter = Counter()
        self.max_open = 0
        self.entered = 0

    def in_slots(self) -> int:
        """Positions that take one of the two slots."""
        if getattr(self.pol, "free_slots", False):
            return sum(1 for p in self.pos.values() if p.stop < p.entry)
        return len(self.pos)

    def rooms(self, bal: float) -> Tuple[float, float]:
        """(room over the daily line, room over the max-loss line), as
        ``ScaleAcct.step`` and ``SafeAcct.step`` compute them."""
        pol = self.pol
        size = self.day_start if pol.cap_on_day_start else 1.0
        mb = getattr(pol, "ml_buffer", None)
        max_loss = so.MAX_LOSS if mb is None else so.MAX_LOSS - (mb - pol.cap_buffer)
        worst = bal - self.committed()
        return (worst - (self.day_start - so.DAILY * size + pol.cap_buffer * size),
                worst - ((1 - max_loss) * size + pol.cap_buffer * size))

    def allowed(self, bal: float) -> float:
        """What a new entry may risk now."""
        pol = self.pol
        risk_amt = pol.risk * bal
        if pol.cap_buffer is not None:
            daily, total = self.rooms(bal)
            risk_amt = min(risk_amt, daily, getattr(pol, "room_share", 1.0) * total)
        return risk_amt

    def step(self, i: int):
        """``ScaleAcct.step`` with the two rules: the slot count where it
        counted positions, and ``allowed`` where it sized the cap's room."""
        inst, pol = self.inst, self.pol
        tp1, tp2 = (pol.tp1, pol.tp2) if pol.exits == "scale" else (so.INF, so.INF)
        for s in list(self.pend_out):
            if s in self.pos:
                self._close(s, inst[s]["o"][i], i)
        self.pend_out.clear()
        for s, atr in self.pend_in:                  # entries at the open
            if s in self.pos or self.in_slots() >= so.MAX_POS:
                continue
            bal = self.balance()
            entry = inst[s]["o"][i]
            r = pol.r_atr * atr
            dist = r / entry
            if dist <= 0:
                continue
            risk_amt = self.allowed(bal)
            if pol.cap_buffer is not None and risk_amt <= 0:
                continue
            notional = min(pol.notional_cap * bal, risk_amt / dist)
            units = notional / entry
            self.pos[s] = so.SPos(units, entry, entry - r, notional, bal, r, units, i)
            self.cash -= notional + notional * so.SIDE_COST
            self.entry_dates[s] = self.dates[i]
            self._filled(i)
            self.entered += 1
            assert self.in_slots() <= so.MAX_POS, "more than two positions at risk"
            assert units * r <= risk_amt * (1 + 1e-12) + 1e-15, "entry over its risk limit"
        self.pend_in = []
        self.max_open = max(self.max_open, len(self.pos))
        low_eq = high_eq = self.cash                 # each position adds its path's extremes
        for s in list(self.pos):
            x, p = inst[s], self.pos[s]
            bar = (x["o"][i], x["h"][i], x["l"][i], x["c"][i])
            a = so.walk(p, *bar, True, tp1, tp2)
            b = so.walk(p, *bar, False, tp1, tp2)
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
            charge = p.units * p.entry * so.FIN_RATE * nights / 365
            self.cash -= charge
            p.fin += charge
            p.held += 1
        close_eq = self.cash + sum(p.units * inst[s]["c"][i] for s, p in self.pos.items())
        self._signal_exits(i)
        # pend_out is empty under the 5 steps without a time stop (every variant
        # here); with free slots AND pending exits a leaving free position would
        # be subtracted twice, and only the entry-time check would hold the limit
        slots = so.MAX_POS - (self.in_slots() - len(self.pend_out))
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
        self._count_signals(i)
        return low_eq, close_eq, high_eq

    def _count_signals(self, i: int) -> None:
        """What happened to each FAST-4 signal of this close (a diagnostic;
        it changes nothing)."""
        sig = self.sig
        free = {s for s, p in self.pos.items() if p.stop >= p.entry}
        sig["days"] += 1
        sig["pos_days"] += len(self.pos)
        sig["free_days"] += len(free)
        if len(self.pos) >= so.MAX_POS:
            sig["days_full"] += 1
            sig["days_full_free"] += bool(free)
        planned = {s for s, _ in self.pend_in}
        staying = set(self.pos) - self.pend_out
        for s, x in self.inst.items():
            if np.isnan(x["sma200"][i]) or not (x["c"][i] > x["sma200"][i]
                                                and x["rsi"][i] < 10):
                continue
            sig["signals"] += 1
            if s in planned:
                sig["planned"] += 1
            elif s in self.pos:
                sig["held"] += 1
                sig["held_free"] += s in free
            else:
                sig["no_slot"] += 1
                sig["no_slot_free"] += bool(staying & free)
                sig["no_slot_all_free"] += bool(staying) and staying <= free


def bounds(tag: str, **kw) -> Tuple[SlotPolicy, SlotPolicy]:
    return (SlotPolicy(f"{tag}, pessimistic", stop_first=True, lock_on_close=True,
                       entry="fast4", r_atr=3.0, **kw),
            SlotPolicy(f"{tag}, optimistic", stop_first=False, lock_on_close=False,
                       entry="fast4", r_atr=3.0, **kw))


W = v2.ML_BUFFER
BASE = {"V1": bounds("V1"), "W2": bounds("W2", ml_buffer=W)}
JUDGED = {                                   # judged against the baseline named
    "S1": ("V1", bounds("S1", room_share=THIRD)),
    "S2": ("V1", bounds("S2", free_slots=True)),
    "S3": ("V1", bounds("S3", room_share=THIRD, free_slots=True)),
    "W2+S1": ("W2", bounds("W2+S1", ml_buffer=W, room_share=THIRD)),
    "W2+S2": ("W2", bounds("W2+S2", ml_buffer=W, free_slots=True)),
    "W2+S3": ("W2", bounds("W2+S3", ml_buffer=W, room_share=THIRD, free_slots=True)),
}
SENSITIVITY = {                              # reported, never used to pick
    "S1 at 1/2": bounds("S1 at 1/2", room_share=HALF),
    "S3 at 1/2": bounds("S3 at 1/2", room_share=HALF, free_slots=True),
}
FTMO_POL = {**BASE, **{k: p for k, (_, p) in JUDGED.items()}, **SENSITIVITY}
CONT_POL = {k: tuple(dataclasses.replace(p, cap_on_day_start=True) for p in pols)
            for k, pols in FTMO_POL.items()}
REF_POL = {"V1": v2.V1, "W2": v2.JUDGED["W2"]}          # the published accounts
DESCRIBE = {
    "V1": "the 5 steps, 0.2% buffer (the last note's verdict)",
    "W2": "the 5 steps, 1.5% buffer over the max-loss line (the bot today, by order)",
    "S1": "V1 + an entry risks at most 1/3 of the room over the max-loss line",
    "S2": "V1 + a position with its stop at or above its entry takes no slot",
    "S3": "S1 + S2",
    "W2+S1": "W2 + the 1/3 share",
    "W2+S2": "W2 + free slots",
    "W2+S3": "W2 + both",
    "S1 at 1/2": "S1 with 1/2 (sensitivity)",
    "S3 at 1/2": "S3 with 1/2 (sensitivity)",
}


@contextlib.contextmanager
def harness(cls):
    saved = policy.Acct
    policy.Acct = cls
    try:
        yield
    finally:
        policy.Acct = saved


class Probe(SlotAcct):
    """Remembers the last account built: the one an unfinished attempt ends in."""
    last = None

    def __init__(self, dates, inst, pol) -> None:
        super().__init__(dates, inst, pol)
        Probe.last = self


DATA: Dict[str, object] = {}


def job(j):
    kind, key, b, cohort = j
    dates, inst = DATA["dates"], DATA["inst"]
    se, sf = DATA["starts"][cohort]
    if kind == "ref":                                # the published account, untouched
        with v2.harness():
            return j, policy.stats(dates, inst, REF_POL[key][b], se, sf)
    pol = FTMO_POL[key][b]
    if kind == "stats":
        with harness(SlotAcct):
            return j, policy.stats(dates, inst, pol, se, sf)
    res = dict(n=0, frozen=0, stuck=0, p18=0, p36=0, pe=0)   # kind == "probe"
    with harness(Probe):
        for s in se:
            out, days = policy.evaluation(dates, inst, pol, s)
            res["n"] += 1
            if out == "pass":
                res["pe"] += 1
                res["p18"] += days <= EIGHTEEN_MONTHS
                res["p36"] += days <= THREE_YEARS
            if "unfinished" not in out:
                continue
            a = Probe.last
            if a.pos:
                continue
            bal = a.balance()
            res["frozen"] += min(a.rooms(bal)) <= FROZEN_ROOM
            res["stuck"] += a.allowed(bal) < STUCK_RISK
    return j, res


def same(x: dict, y: dict) -> bool:
    for k in x:
        a, b = x[k], y[k]
        if isinstance(a, str) or isinstance(b, str):
            if a != b:
                return False
        elif not (a == b or (np.isnan(a) and np.isnan(b))):
            return False
    return x.keys() == y.keys()


def judge(rs) -> Tuple[bool, bool]:
    """The pre-registered rule on a variant's cells against its baseline's:
    (no worse anywhere, better somewhere). A row is (cohort, bound, start
    dates, breached, the baseline's, both phases within 18 months, the
    baseline's, both phases within the data, the baseline's), in counts."""
    no_worse = all(bv <= b0 and pv >= p0 and ev >= e0
                   for _, _, _, bv, b0, pv, p0, ev, e0 in rs)
    better = any(all(pv > p0 or ev > e0
                     for c, _, _, _, _, pv, p0, ev, e0 in rs if c == cohort)
                 for cohort in {r[0] for r in rs})
    return no_worse, better


def continuous(dates, inst, pol):
    acct, eq = so.full_run(dates, inst, pol, SlotAcct)
    m = v2.trade_metrics(dates, inst, acct, eq, pol.stop_first)
    m.update(sig=dict(acct.sig), max_open=acct.max_open, entered=acct.entered)
    return m


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--report", type=Path, default=None)
    ap.add_argument("--jobs", type=int, default=max(1, (mp.cpu_count() or 1)))
    ap.add_argument("--check-only", action="store_true",
                    help="the plumbing checks alone; nothing is computed for S1-S3")
    a = ap.parse_args(argv)
    dates, inst = base.load_all(a.data_dir)
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
    cells = [(b, c) for b in (0, 1) for c in COHORTS]

    def run(jobs):
        if a.jobs > 1:
            with mp.get_context("fork").Pool(a.jobs) as pool:
                return dict(pool.map(job, jobs, chunksize=1))
        return dict(map(job, jobs))

    # 1. plumbing: with neither rule the new account is the published one, trade by trade
    base_metrics = {}
    for key in BASE:
        for b in (0, 1):
            ref, _ = so.full_run(dates, inst, v2.CONT_POL[key][b], v2.SafeAcct)
            mine, _ = so.full_run(dates, inst, CONT_POL[key][b], SlotAcct)
            assert len(ref.trades) == len(mine.trades) and all(
                x[0] == y[0] and x[1] == y[1] for x, y in zip(ref.trades, mine.trades)), \
                f"SlotAcct without the rules does not reproduce {key}'s trades"
            base_metrics[(key, b)] = continuous(dates, inst, CONT_POL[key][b])
    got = base_metrics[("V1", 0)]["sig"]
    assert all(got.get(k, 0) == v for k, v in PREREG_SIGNALS.items()), \
        ("V1's signal counts differ from the note's", got)
    say("plumbing: trades and the pre-registered signal counts reproduced")

    # 2. ... and in every FTMO figure of every cell; the frozen shares as published
    ftmo = run([(kind, k, b, c) for kind in ("ref", "stats", "probe")
                for k in BASE for b, c in cells])
    for k in BASE:
        for b, c in cells:
            assert same(ftmo[("ref", k, b, c)], ftmo[("stats", k, b, c)]), \
                (f"SlotAcct without the rules does not reproduce {k}'s FTMO figures", b, c)
            pr = ftmo[("probe", k, b, c)]
            share = f"{pr['frozen'] / pr['n']:.1%}"
            assert share == PUBLISHED_FROZEN[(k, b, COHORTS.index(c))], \
                (f"{k}'s frozen share differs from the published one", b, c, share)
    say("plumbing: V1's and W2's FTMO figures and frozen shares reproduced")
    if a.check_only:
        print("checks passed; nothing was computed for S1-S3")
        return 0

    # 3. the variants: continuous accounts, then FTMO
    others = [k for k in FTMO_POL if k not in BASE]
    metrics = {k: [base_metrics[(k, b)] if k in BASE else continuous(dates, inst, CONT_POL[k][b])
                   for b in (0, 1)] for k in FTMO_POL}
    say("continuous accounts done")
    ftmo.update(run([(kind, k, b, c) for kind in ("stats", "probe")
                     for k in others for b, c in cells]))
    for k in FTMO_POL:                               # the two passes over the attempts agree
        for b, c in cells:
            r, pr = ftmo[("stats", k, b, c)], ftmo[("probe", k, b, c)]
            assert (round(r["pe"] * pr["n"]), round(r["p18"] * pr["n"])) == (pr["pe"], pr["p18"]), \
                ("the probe and the statistics disagree", k, b, c)
    say("FTMO runs done")

    first, last = pd.Timestamp(dates[WARMUP]).date(), pd.Timestamp(dates[-1]).date()
    years = (dates[-1] - dates[WARMUP]) / np.timedelta64(1, "D") / 365.25
    m0, m1 = len(starts[COHORTS[0]][0]), len(starts[COHORTS[1]][0])
    out = [f"Common dates {pd.Timestamp(dates[0]).date()} → {last}; continuous account "
           f"{first} → {last}; start dates (2011–18 / 2019–26): {m0} / {m1} evaluations. "
           "Checks passed: with the share at one and free slots off, the new account "
           "reproduces V1 and W2 trade by trade and in every FTMO figure; V1's signal "
           "counts are the note's; V1's and W2's frozen shares are the published ones.", ""]
    out += [f"* **{k}**: {v}" for k, v in DESCRIBE.items()] + [""]

    out += ["**Per trade** (continuous account; trades open at the end left out):", "",
            "| variant | bound | trades | trades per year | TP1 before stop | P&L win rate | "
            "avg win (R) | avg loss (R) | payoff (R/trade) | avg first risk | median "
            "sessions held | most open at once | CAGR | max DD |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k in FTMO_POL:
        for b, bound in enumerate(BOUNDS):
            m = metrics[k][b]
            out.append(f"| {k} | {bound} | {m['trades']} | {m['trades'] / years:.1f} | "
                       f"{m['webinar']:.1%} | {m['pnl_win']:.1%} | {m['avg_win']:+.2f} | "
                       f"{m['avg_loss']:+.2f} | {m['exp']:+.3f} | {m['risk']:.2%} | "
                       f"{m['held']:.0f} | {m['max_open']} | {m['cagr']:+.1%} | "
                       f"{m['mdd']:.1%} |")

    out += ["", "**Signals** (continuous account, pessimistic bound; 'free': a position "
            "whose stop is at or above its entry):", "",
            "| variant | signals | planned for the next open | entered | not taken: index "
            "already held | … by a free position | not taken: slots full | … while a free "
            "position was open | … while every open position was free | sessions with two "
            "or more positions open |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    for k in FTMO_POL:
        m = metrics[k][0]
        g = Counter(m["sig"])
        out.append(f"| {k} | {g['signals']} | {g['planned']} | {m['entered']} | {g['held']} | "
                   f"{g['held_free']} | {g['no_slot']} | {g['no_slot_free']} | "
                   f"{g['no_slot_all_free']} | {g['days_full']} of {g['days']} |")

    out += ["", "**FTMO** (cohorts by start date). Frozen: flat at the end with under 0.05% "
            "of room. Stuck: flat at the end and a new entry may risk under 0.5% (every "
            "frozen attempt is stuck). Attempts per pass counts a stuck attempt as lost.", "",
            "| policy | period | P1 passed | both ≤6 mo | both ≤18 mo | both ≤36 mo | both, "
            "ever | breached | frozen | stuck | still trading | days to pass (p25 / median / "
            "p75) | main failure | funded 1y survival | funded 1y return | attempts per pass |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k in FTMO_POL:
        for b, bound in enumerate(BOUNDS):
            for c in COHORTS:
                r, pr = ftmo[("stats", k, b, c)], ftmo[("probe", k, b, c)]
                fz, st = pr["frozen"] / pr["n"], pr["stuck"] / pr["n"]
                att = (r["pe"] + r["breach"] + st) / r["pe"] if r["pe"] > 0 else float("nan")
                out.append(f"| {k} {bound} | {c} | {r['p1']:.0%} | {r['p6']:.0%} | "
                           f"{r['p18']:.1%} | {pr['p36'] / pr['n']:.1%} | {r['pe']:.1%} | "
                           f"{r['breach']:.1%} | {fz:.1%} | "
                           f"{st:.1%} | {r['running'] - st:.1%} | {r['q1']:.0f} / "
                           f"{r['md']:.0f} / {r['q3']:.0f} | {r['main_fail']} | "
                           f"{r['surv']:.0%} | {r['fret']:+.1%} | {att:.2f} |")

    def rows(k, ref):
        got = []
        for c in COHORTS:
            m = len(starts[c][0])
            for b in (0, 1):
                rv, r0 = ftmo[("stats", k, b, c)], ftmo[("stats", ref, b, c)]
                got.append((c, b, m, *(round(x[f] * m) for f in ("breach", "p18", "pe")
                                       for x in (rv, r0))))
        return got

    for ref in BASE:
        out += ["", f"### Verdict against {ref}, by the pre-registered rule", "",
                f"| variant | cohort | bound | breached: variant vs {ref} | both ≤18 mo | "
                "both, ever | no worse |", "|---|---|---|---|---|---|---|"]
        winners = []
        for k, (base_key, _) in JUDGED.items():
            if base_key != ref:
                continue
            rs = rows(k, ref)
            for c, b, m, bv, b0, pv, p0, ev, e0 in rs:
                ok = bv <= b0 and pv >= p0 and ev >= e0
                out.append(f"| {k} | {c} | {BOUNDS[b]} | {bv}/{m} ({bv / m:.1%}) vs {b0}/{m} "
                           f"({b0 / m:.1%}) | {pv}/{m} ({pv / m:.1%}) vs {p0}/{m} "
                           f"({p0 / m:.1%}) | {ev}/{m} ({ev / m:.1%}) vs {e0}/{m} "
                           f"({e0 / m:.1%}) | {'yes' if ok else 'no'} |")
            no_worse, better = judge(rs)
            out.append(f"| **{k}** | | | | | | no worse anywhere: {'yes' if no_worse else 'no'}; "
                       f"better somewhere: {'yes' if better else 'no'} |")
            if no_worse and better:
                pol = JUDGED[k][1][0]
                winners.append((-min(ev / m for _, _, m, _, _, _, _, ev, _ in rs),
                                max(bv / m for _, _, m, bv, _, _, _, _, _ in rs),
                                (pol.room_share != 1.0) + pol.free_slots, k))
        out.append("")
        if winners:
            out.append(f"**Beats {ref}:** {', '.join(w[-1] for w in sorted(winners))}; "
                       f"preferred by the tie-break: **{min(winners)[-1]}**.")
        else:
            out.append(f"**No variant beats {ref}** by the rule.")
    text = "\n".join(out) + "\n"
    if a.report is not None:
        a.report.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
