#!/usr/bin/env python3
"""Two safety rules for the 5-step exits, as pre-registered in
``research/ftmo_scale_out_v2.md``:

* W1: V1 + a time stop (TP1 not filled after 10 sessions: close at the
  next open);
* W2: V1 + the combined-risk cap 1.5% (not 0.2%) above the max-loss line;
* W3: both.

They are judged against V1 (the bot's exits since 2026-11-08) and,
for the record, against V0. Everything else is ``research/ftmo_scale_out.py``,
imported unchanged, through the same FTMO functions.

    python -B -I research/ftmo_scale_out_v2.py --data-dir DIR [--report FILE] [--jobs N]
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import importlib.util
import multiprocessing as mp
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("ftmo_scale_out", HERE / "ftmo_scale_out.py")
so = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["ftmo_scale_out"] = so
_spec.loader.exec_module(so)
policy, base = so.policy, so.base
COHORTS, BOUNDS, SPLIT = so.COHORTS, so.BOUNDS, so.SPLIT
WARMUP, STEP = so.WARMUP, so.STEP
SIX_MONTHS, FUNDED_DAYS = so.SIX_MONTHS, so.FUNDED_DAYS

TIME_STOP = 10        # sessions: FAST-4's own maximum hold
ML_BUFFER = 0.015     # a -1.5R loss at 3% risk


@dataclass(frozen=True)
class SafePolicy(so.ScalePolicy):
    time_stop: int = 0                   # 0: none
    ml_buffer: Optional[float] = None    # None: the cap's own buffer on both lines


class SafeAcct(so.ScaleAcct):
    """The scale-out account with the two rules. With neither it is
    ``ScaleAcct`` exactly (asserted in ``main``)."""

    def __init__(self, dates, inst, pol) -> None:
        super().__init__(dates, inst, pol)
        self.timed: set = set()          # flagged for the time stop at the next open

    def _signal_exits(self, i: int) -> None:
        super()._signal_exits(i)
        self.timed &= self.pend_out
        ts = getattr(self.pol, "time_stop", 0)
        if self.pol.exits == "scale" and ts:
            for s, p in self.pos.items():
                if not p.tp1 and p.held >= ts:
                    self.pend_out.add(s)
                    self.timed.add(s)

    def _close(self, s: str, px: float, i: int) -> None:
        timed = s in self.timed and s in self.pend_out
        self.timed.discard(s)
        super()._close(s, px, i)
        if timed:
            self.log[-1]["time_stop"] = True

    def step(self, i: int):
        """W2: ``ScaleAcct.step`` reads the max-loss line from its module
        only to size the cap's room; moving it there by (1.5% - 0.2%)
        keeps every open stop 1.5% above the line. FTMO's own max-loss
        check (``policy``'s constant) is untouched."""
        mb = getattr(self.pol, "ml_buffer", None)
        if mb is None or self.pol.cap_buffer is None:
            return super().step(i)
        saved = so.MAX_LOSS
        so.MAX_LOSS = saved - (mb - self.pol.cap_buffer)
        try:
            return super().step(i)
        finally:
            so.MAX_LOSS = saved


def safe_bounds(tag: str, **kw) -> Tuple[SafePolicy, SafePolicy]:
    return (SafePolicy(f"{tag}, pessimistic", stop_first=True, lock_on_close=True,
                       entry="fast4", r_atr=3.0, **kw),
            SafePolicy(f"{tag}, optimistic", stop_first=False, lock_on_close=False,
                       entry="fast4", r_atr=3.0, **kw))


V1 = safe_bounds("V1")
JUDGED = {
    "W1": safe_bounds("W1", time_stop=TIME_STOP),
    "W2": safe_bounds("W2", ml_buffer=ML_BUFFER),
    "W3": safe_bounds("W3", time_stop=TIME_STOP, ml_buffer=ML_BUFFER),
}
SENSITIVITY = {       # 2% risk: reported, never used to pick
    "V1 2%": safe_bounds("V1 2%", risk=0.02),
    "W3 2%": safe_bounds("W3 2%", risk=0.02, time_stop=TIME_STOP, ml_buffer=ML_BUFFER),
}
FTMO_POL = {"V0": (so.V0_PESS, so.V0_OPT), "V1": V1, **JUDGED, **SENSITIVITY}
CONT_POL = {k: tuple(dataclasses.replace(p, cap_on_day_start=True) for p in pols)
            for k, pols in {"V0": so.V0_RULE, "V1": V1, **JUDGED, **SENSITIVITY}.items()}
DESCRIBE = {
    "V0": "FAST-4 exits: close > SMA5 or 10 sessions",
    "V1": "the 5 steps (the bot since 2026-11-08)",
    "W1": "V1 + time stop: TP1 not filled after 10 sessions -> close at the next open",
    "W2": "V1 + the cap keeps open stops 1.5% (not 0.2%) above the max-loss line",
    "W3": "W1 + W2",
    "V1 2%": "V1 at 2% risk (sensitivity)",
    "W3 2%": "W3 at 2% risk (sensitivity)",
}


@contextlib.contextmanager
def harness():
    saved = policy.Acct
    policy.Acct = SafeAcct
    try:
        yield
    finally:
        policy.Acct = saved


def trade_metrics(dates, inst, acct, eq, stop_first: bool) -> dict:
    """``ftmo_scale_out.trade_metrics``, except that a trade closed by the
    time stop is exempt from its TP1-equals-the-scan check (it left before
    either level); every other scale-out trade is still checked."""
    log = sorted(acct.log, key=lambda t: (t["i0"], t["sym"]))
    pnl = np.array([t["pnl"] for t in log])
    rr = np.array([t["R"] for t in log])
    win = pnl > 0
    hit = np.array([t["tp1"] if t["scale"] else so.v0_reached(inst[t["sym"]], t, stop_first)
                    for t in log])
    touch = [so.first_touch(inst[t["sym"]], t["i0"], t["entry"], t["r"], stop_first)
             for t in log]
    for t, h, f in zip(log, hit, touch):
        assert not t["scale"] or t.get("time_stop") or bool(h) == f, ("TP1 vs scan", t)
    resolved = [f for f in touch if f is not None]
    longest = run = 0
    for w in win:
        run = 0 if w else run + 1
        longest = max(longest, run)
    curve = np.concatenate([[1.0], eq])
    years = (dates[-1] - dates[WARMUP]) / np.timedelta64(1, "D") / 365.25
    return dict(trades=len(log), webinar=hit.mean(), pnl_win=win.mean(),
                avg_win=rr[win].mean(), avg_loss=rr[~win].mean(), exp=rr.mean(),
                p1r=float(np.mean(resolved)), max_cl=longest,
                risk=float(np.mean([t["risk"] for t in log])),
                held=float(np.median([t["held"] for t in log])),
                timed=sum(1 for t in log if t.get("time_stop")),
                worst=float(rr.min()), final=curve[-1],
                cagr=curve[-1] ** (1 / years) - 1,
                mdd=float((1 - curve / np.maximum.accumulate(curve)).max()),
                trades_by=list(acct.trades))


DATA: Dict[str, object] = {}


def ftmo_job(job):
    key, b, cohort = job
    pol = FTMO_POL[key][b]
    se, sf = DATA["starts"][cohort]
    if isinstance(pol, so.ScalePolicy):
        with harness():
            return job, policy.stats(DATA["dates"], DATA["inst"], pol, se, sf)
    return job, policy.stats(DATA["dates"], DATA["inst"], pol, se, sf)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--report", type=Path, default=None)
    ap.add_argument("--jobs", type=int, default=max(1, (mp.cpu_count() or 1)))
    ap.add_argument("--fee", type=float, default=89.0)
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

    # the plumbing: with neither rule, the new account is ScaleAcct exactly
    for b in (0, 1):
        ref, _ = so.full_run(dates, inst, so.CONT_POL["V1"][b], so.ScaleAcct)
        mine, _ = so.full_run(dates, inst, CONT_POL["V1"][b], SafeAcct)
        assert len(ref.trades) == len(mine.trades) and all(
            x[0] == y[0] and abs(x[1] - y[1]) < 1e-12 for x, y in zip(ref.trades, mine.trades)), \
            "SafeAcct without the rules does not reproduce V1"
    say("plumbing check passed")

    metrics = {k: [trade_metrics(dates, inst, *so.full_run(dates, inst, p, SafeAcct),
                                 p.stop_first) for p in pols] for k, pols in CONT_POL.items()}
    say("continuous accounts done")
    jobs = [(k, b, c) for k in FTMO_POL for b in (0, 1) for c in COHORTS]
    jobs.sort(key=lambda j: j[0] == "V0")
    if a.jobs > 1:
        with mp.get_context("fork").Pool(a.jobs) as pool:
            ftmo = dict(pool.map(ftmo_job, jobs, chunksize=1))
    else:
        ftmo = dict(map(ftmo_job, jobs))
    say("FTMO runs done")

    first, last = pd.Timestamp(dates[WARMUP]).date(), pd.Timestamp(dates[-1]).date()
    m0, m1 = len(starts[COHORTS[0]][0]), len(starts[COHORTS[1]][0])
    out = [f"Common dates {pd.Timestamp(dates[0]).date()} → {last}; continuous account "
           f"{first} → {last}; start dates (2011–18 / 2019–26): {m0} / {m1} evaluations. "
           "Check passed: with neither rule the new account reproduces V1's trades in "
           "both bounds.", ""]
    out += [f"* **{k}**: {v}" for k, v in DESCRIBE.items()] + [""]
    out += ["**Per trade** (continuous account; trades open at the end left out):", "",
            "| variant | bound | trades | TP1 before stop | P&L win rate | avg win (R) | "
            "avg loss (R) | worst (R) | expectancy (R) | P(+1R before −1R) | max consecutive "
            "losses | time stops | avg initial risk | median sessions held | CAGR | max DD |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k in CONT_POL:
        for b, bound in enumerate(BOUNDS):
            m = metrics[k][b]
            out.append(f"| {k} | {bound} | {m['trades']} | {m['webinar']:.1%} | "
                       f"{m['pnl_win']:.1%} | {m['avg_win']:+.2f} | {m['avg_loss']:+.2f} | "
                       f"{m['worst']:+.2f} | {m['exp']:+.3f} | {m['p1r']:.1%} | {m['max_cl']} | "
                       f"{m['timed']} | {m['risk']:.2%} | {m['held']:.0f} | {m['cagr']:+.1%} | "
                       f"{m['mdd']:.1%} |")
    out += ["", "**FTMO** (cohorts by start date; trade columns from the continuous "
            "account):", "",
            "| policy | period | trades | win rate | profit factor | P1 passed | both ≤6 mo | "
            "both ≤18 mo | both, ever | breached | still running | days to pass (p25 / "
            "median / p75) | main failure | funded 1y survival | funded 1y return | "
            "attempts per pass |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k in FTMO_POL:
        for b, bound in enumerate(BOUNDS):
            trades = metrics[k][b]["trades_by"]
            for c, (lo, hi) in zip(COHORTS, ((None, SPLIT), (SPLIT, None))):
                trs = [t for t in trades if (lo is None or t[0] >= lo)
                       and (hi is None or t[0] < hi)]
                cnt, wr, pf = base.trade_stats(trs)
                r = ftmo[(k, b, c)]
                att = (r["pe"] + r["breach"]) / r["pe"] if r["pe"] > 0 else float("nan")
                out.append(f"| {k} {bound} | {c} | {cnt} | {wr:.0%} | {pf:.2f} | {r['p1']:.0%} | "
                           f"{r['p6']:.0%} | {r['p18']:.0%} | {r['pe']:.0%} | "
                           f"{r['breach']:.0%} | {r['running']:.0%} | {r['q1']:.0f} / "
                           f"{r['md']:.0f} / {r['q3']:.0f} | {r['main_fail']} | "
                           f"{r['surv']:.0%} | {r['fret']:+.1%} | {att:.2f} |")

    def cells(k, ref):
        rows = []
        for c in COHORTS:
            m = len(starts[c][0])
            for b in (0, 1):
                rv, r0 = ftmo[(k, b, c)], ftmo[(ref, b, c)]
                rows.append((c, BOUNDS[b], m, round(rv["breach"] * m), round(r0["breach"] * m),
                             round(rv["p18"] * m), round(r0["p18"] * m)))
        return rows

    out += ["", "### Verdict against V1, by the pre-registered rule", "",
            "| variant | cohort | bound | breached: variant vs V1 | both ≤18 mo: variant vs V1 |",
            "|---|---|---|---|---|"]
    winners = []
    for k in JUDGED:
        rows = cells(k, "V1")
        for c, bound, m, bv, b1, pv, p1 in rows:
            out.append(f"| {k} | {c} | {bound} | {bv}/{m} ({bv / m:.1%}) vs {b1}/{m} "
                       f"({b1 / m:.1%}) | {pv}/{m} ({pv / m:.1%}) vs {p1}/{m} ({p1 / m:.1%}) |")
        ab = all(bv <= b1 and pv >= p1 for _, _, _, bv, b1, pv, p1 in rows)
        strict = any(all(bv < b1 for cc, _, _, bv, b1, _, _ in rows if cc == c)
                     for c in COHORTS)
        if ab and strict:
            hb = max(bv / m for _, _, m, bv, _, _, _ in rows)
            lp = min(pv / m for _, _, m, _, _, pv, _ in rows)
            winners.append((hb, -lp, k))
    out.append("")
    if winners:
        best = min(winners)[2]
        out.append(f"**Beats V1:** {', '.join(w[2] for w in sorted(winners))}; preferred by "
                   f"the tie-break: **{best}**.")
    else:
        out.append("**No variant beats V1** by the rule; the bot keeps V1.")
    out += ["", "### For the record: against V0 (the first note's rule)", "",
            "| variant | all four cells: breached ≤ V0 and both ≤18 mo > V0 |", "|---|---|"]
    for k in ["V1", *JUDGED]:
        ok = all(bv <= b0 and pv > p0 for _, _, _, bv, b0, pv, p0 in cells(k, "V0"))
        out.append(f"| {k} | {'yes' if ok else 'no'} |")
    text = "\n".join(out) + "\n"
    if a.report is not None:
        a.report.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
