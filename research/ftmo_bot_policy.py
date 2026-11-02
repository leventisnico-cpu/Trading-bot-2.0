#!/usr/bin/env python3
"""FAST-4 under FTMO 2-Step rules with the bot's actual risk controls.

A companion to the pre-registered study ``research/ftmo_fast_pass.py``:
same data, same FTMO model, same start dates, same trade rule. The rows
differ only in what ``ftmo_bot`` does on top of the rule:

* the combined-risk cap: every open stop together stays ``cap_buffer``
  (share of initial) above the daily and the max-loss line, so a second
  position gets only the room the first one leaves
  (``ftmo_bot.rules.risk_room``);
* trading days are days with an opened position, FTMO's definition;
* the target lock: once equity touches target + ``lock_margin`` the bot
  flattens and, if trading days are short, adds them with minimum-lot
  round trips, so a reached target cannot be given back.

The first row switches all three off and must reproduce the
pre-registered table on the same data.

    python -I research/ftmo_bot_policy.py --data-dir DIR [--report FILE]
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("ftmo_fast_pass", HERE / "ftmo_fast_pass.py")
base = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["ftmo_fast_pass"] = base        # its dataclasses look themselves up here
_spec.loader.exec_module(base)

MAX_POS, SIDE_COST, FIN_RATE = base.MAX_POS, base.SIDE_COST, base.FIN_RATE
TARGETS, MAX_LOSS, DAILY, MIN_DAYS = base.TARGETS, base.MAX_LOSS, base.DAILY, base.MIN_DAYS
INACTIVE, KEEPALIVE = base.INACTIVE, base.KEEPALIVE
SIX_MONTHS, FUNDED_DAYS, STEP, WARMUP, SPLIT = (base.SIX_MONTHS, base.FUNDED_DAYS,
                                               base.STEP, base.WARMUP, base.SPLIT)
EIGHTEEN_MONTHS = 548


@dataclass(frozen=True)
class Policy:
    name: str
    risk: float = 0.03
    cap_buffer: Optional[float] = 0.002    # None: no combined-risk cap
    lock_margin: Optional[float] = 0.003   # None: no target lock
    open_days_only: bool = True            # False: any fill counts a trading day
    notional_cap: float = 3.0


PRE_REGISTERED = Policy("pre-registered 3% (no cap, no lock)", cap_buffer=None,
                        lock_margin=None, open_days_only=False, notional_cap=5.0)
VARIANTS = [
    PRE_REGISTERED,
    Policy("bot 3%: cap 0.2%, lock"),
    Policy("bot 3%: cap 1.0%, lock", cap_buffer=0.01),
    Policy("bot 2%: cap 0.2%, lock", risk=0.02),
]


class Acct(base.Acct):
    def __init__(self, dates, inst, pol: Policy) -> None:
        super().__init__(dates, inst, pol.risk)
        self.pol = pol
        self.day_start = 1.0

    def _close(self, s: str, px: float, i: int) -> None:
        p = self.pos.pop(s)
        proceeds = p.units * px
        self.cash += proceeds - proceeds * SIDE_COST
        self.trades.append((self.entry_dates.pop(s),
                            (proceeds - p.units * p.entry - proceeds * SIDE_COST
                             - p.notional * SIDE_COST - p.fin) / p.entry_bal))
        if not self.pol.open_days_only:
            self._filled(i)

    def flatten_at(self, level: float, i: int) -> None:
        """Close everything the moment equity touches ``level``: every
        position at the same fraction of its entry price."""
        basis = sum(p.units * p.entry for p in self.pos.values())
        if basis <= 0:
            return
        k = (level - self.cash) / basis
        for s in list(self.pos):
            self._close(s, k * self.pos[s].entry, i)

    def step(self, i: int):
        for s in list(self.pend_out):
            if s in self.pos:
                self._close(s, self.inst[s]["o"][i], i)
        self.pend_out.clear()
        for s, atr in self.pend_in:
            if s in self.pos or len(self.pos) >= MAX_POS:
                continue
            x = self.inst[s]
            bal = self.balance()
            entry = x["o"][i]
            stop = entry - 3 * atr
            dist = (entry - stop) / entry
            if dist <= 0:
                continue
            risk_amt = self.pol.risk * bal
            if self.pol.cap_buffer is not None:
                committed = sum(p.units * (p.entry - p.stop) for p in self.pos.values())
                worst = bal - committed
                room = min(worst - (self.day_start - DAILY + self.pol.cap_buffer),
                           worst - (1 - MAX_LOSS + self.pol.cap_buffer))
                risk_amt = min(risk_amt, room)
                if risk_amt <= 0:
                    continue
            notional = min(self.pol.notional_cap * bal, risk_amt / dist)
            self.pos[s] = base.Pos(notional / entry, entry, stop, notional, bal)
            self.cash -= notional + notional * SIDE_COST
            self.entry_dates[s] = self.dates[i]
            self._filled(i)
        self.pend_in = []
        for s in list(self.pos):
            x, p = self.inst[s], self.pos[s]
            if x["o"][i] <= p.stop:
                self._close(s, x["o"][i], i)
            elif x["l"][i] <= p.stop:
                self._close(s, p.stop, i)
        low_eq = self.cash + sum(p.units * self.inst[s]["l"][i] for s, p in self.pos.items())
        high_eq = self.cash + sum(p.units * self.inst[s]["h"][i] for s, p in self.pos.items())
        nxt = self.dates[i + 1] if i + 1 < len(self.dates) else self.dates[i]
        nights = max(1, int((nxt - self.dates[i]) / np.timedelta64(1, "D")))
        for p in self.pos.values():
            charge = p.notional * FIN_RATE * nights / 365
            self.cash -= charge
            p.fin += charge
            p.held += 1
        close_eq = self.cash + sum(p.units * self.inst[s]["c"][i]
                                   for s, p in self.pos.items())
        for s, p in self.pos.items():
            x = self.inst[s]
            if x["c"][i] > x["sma5"][i] or p.held >= 10:
                self.pend_out.add(s)
        slots = MAX_POS - (len(self.pos) - len(self.pend_out))
        cands = []
        for s, x in self.inst.items():
            if s in self.pos or np.isnan(x["sma200"][i]):
                continue
            if x["c"][i] > x["sma200"][i] and x["rsi"][i] < 10:
                cands.append((x["rsi"][i], s, x["atr"][i]))
        cands.sort()
        self.pend_in = [(s, a) for _, s, a in cands[:max(0, slots)]]
        return low_eq, close_eq, high_eq


def phase(dates, inst, pol: Policy, start: int, target: float):
    a = Acct(dates, inst, pol)
    t0 = dates[start]
    locked = False
    for i in range(start, len(dates)):
        bal0 = a.balance()
        a.day_start = bal0
        if locked:                        # flat; one min-lot round trip per session
            a.fill_days += 1
            if a.fill_days >= MIN_DAYS:
                return "pass", i
            continue
        low_eq, close_eq, high_eq = a.step(i)
        ref = a.last_fill if a.last_fill is not None else t0
        idle = (dates[i] - ref) / np.timedelta64(1, "D")
        if idle >= KEEPALIVE:
            a.fill_days += 1
            a.last_fill = dates[i]
            idle = 0
        if low_eq <= 1 - MAX_LOSS:
            return "max_loss", i
        if low_eq <= bal0 - DAILY:
            return "daily_loss", i
        if idle >= INACTIVE:
            return "inactive", i
        if pol.lock_margin is None:
            if close_eq >= 1 + target and a.fill_days >= MIN_DAYS:
                return "pass", i
        elif high_eq >= 1 + target + pol.lock_margin:
            a.flatten_at(1 + target + pol.lock_margin, i)
            if a.fill_days >= MIN_DAYS:
                return "pass", i
            locked = True
    return "unfinished", len(dates) - 1


def evaluation(dates, inst, pol: Policy, start: int):
    o1, e1 = phase(dates, inst, pol, start, TARGETS[0])
    if o1 != "pass":
        return "P1 " + o1, None
    if e1 + 1 >= len(dates):
        return "P2 unfinished", None
    o2, e2 = phase(dates, inst, pol, e1 + 1, TARGETS[1])
    if o2 != "pass":
        return "P2 " + o2, None
    return "pass", (dates[e2] - dates[start]) / np.timedelta64(1, "D")


def funded(dates, inst, pol: Policy, start: int):
    """(survived 252 sessions, balance at the end or at the breach)."""
    a = Acct(dates, inst, pol)
    for i in range(start, start + FUNDED_DAYS):
        bal0 = a.balance()
        a.day_start = bal0
        low_eq, close_eq, _ = a.step(i)
        if low_eq <= 1 - MAX_LOSS or low_eq <= bal0 - DAILY:
            return False, low_eq
    return True, a.balance()


def stats(dates, inst, pol: Policy, starts_eval: List[int], starts_fund: List[int]):
    ev = [evaluation(dates, inst, pol, s) for s in starts_eval]
    n = len(ev) or 1
    p1 = sum(not e[0].startswith("P1") for e in ev) / n
    p6 = sum(e[0] == "pass" and e[1] <= SIX_MONTHS for e in ev) / n
    p18 = sum(e[0] == "pass" and e[1] <= EIGHTEEN_MONTHS for e in ev) / n
    pe = sum(e[0] == "pass" for e in ev) / n            # within the data, however long
    breach = sum(any(w in e[0] for w in ("daily_loss", "max_loss", "inactive"))
                 for e in ev) / n                       # the account (and its fee) lost
    running = sum("unfinished" in e[0] for e in ev) / n  # no breach when the data ends
    days = [e[1] for e in ev if e[0] == "pass"]
    fails = pd.Series([e[0] for e in ev if e[0] != "pass"]).value_counts()
    main_fail = f"{fails.index[0]} {fails.iloc[0] / n:.0%}" if len(fails) else "-"
    fu = [funded(dates, inst, pol, s) for s in starts_fund]
    surv = np.mean([f[0] for f in fu]) if fu else float("nan")
    rets = [f[1] - 1 for f in fu if f[0]]
    return dict(p1=p1, p6=p6, p18=p18, pe=pe, breach=breach, running=running,
                md=np.median(days) if days else float("nan"),
                q1=np.percentile(days, 25) if days else float("nan"),
                q3=np.percentile(days, 75) if days else float("nan"),
                main_fail=main_fail, surv=surv,
                fret=np.median(rets) if rets else float("nan"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--report", type=Path,
                    default=HERE.parent / "reports" / "ftmo_bot_policy.md")
    ap.add_argument("--fee", type=float, default=89.0,
                    help="EUR per attempt (the $10k 2-Step fee) for the cost line")
    a = ap.parse_args(argv)
    dates, inst = base.load_all(a.data_dir)
    n = len(dates)
    six = np.timedelta64(SIX_MONTHS, "D")
    sel_eval = [s for s in range(WARMUP, n, STEP) if dates[s] < SPLIT
                and dates[s] + six <= dates[-1]]
    sel_fund = [s for s in range(WARMUP, n - FUNDED_DAYS, STEP) if dates[s] < SPLIT]
    tst_eval = [s for s in range(WARMUP, n, STEP) if dates[s] >= SPLIT
                and dates[s] + six <= dates[-1]]
    tst_fund = [s for s in range(WARMUP, n - FUNDED_DAYS, STEP) if dates[s] >= SPLIT]
    out = ["# FAST-4 under FTMO 2-Step rules: the bot's risk controls", "",
           f"Companion to `reports/ftmo_fast_pass.md` (`research/ftmo_bot_policy.py`). "
           f"Common dates {pd.Timestamp(dates[0]).date()} → "
           f"{pd.Timestamp(dates[-1]).date()}; selection starts before "
           f"{pd.Timestamp(SPLIT).date()}, test starts from it; {len(tst_eval)} test "
           "start dates. Cap: every open stop together stays the buffer above both "
           "loss lines. Lock: flatten at target + 0.3%, add missing trading days "
           "with minimum-lot round trips. 'Both, ever' counts passes within the "
           "data, however long they took; late start dates have less room. "
           "'Breached': a daily-loss, max-loss or inactivity breach ended the "
           "attempt. 'Still running': no pass and no breach when the data ends.", "",
           "| policy | period | trades | win rate | profit factor | P1 passed | "
           "both ≤6 mo | both ≤18 mo | both, ever | breached | still running | "
           "days to pass (p25 / median / p75) | "
           "main failure | funded 1y survival | funded 1y return (median, survivors) |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    cost = []
    for pol in VARIANTS:
        full = Acct(dates, inst, pol)
        for i in range(WARMUP, n):
            full.day_start = full.balance()
            full.step(i)
        for label, se, sf, lo, hi in (("selection", sel_eval, sel_fund, None, SPLIT),
                                      ("test", tst_eval, tst_fund, SPLIT, None)):
            trs = [t for t in full.trades
                   if (lo is None or t[0] >= lo) and (hi is None or t[0] < hi)]
            k, wr, pf = base.trade_stats(trs)
            r = stats(dates, inst, pol, se, sf)
            out.append(f"| {pol.name} | {label} | {k} | {wr:.0%} | {pf:.2f} | "
                       f"{r['p1']:.0%} | {r['p6']:.0%} | {r['p18']:.0%} | {r['pe']:.0%} | "
                       f"{r['breach']:.0%} | {r['running']:.0%} | "
                       f"{r['q1']:.0f} / {r['md']:.0f} / {r['q3']:.0f} | "
                       f"{r['main_fail']} | {r['surv']:.0%} | {r['fret']:+.1%} |")
            if r["pe"] > 0:
                k = (r["pe"] + r["breach"]) / r["pe"]
                cost.append(f"* {pol.name}, {label} period: {k:.2f} attempts per pass, "
                            f"about EUR {a.fee * k:,.0f} of fees per pass.")
    out += ["", f"**Fees per funded account** at EUR {a.fee:.0f} per attempt: a breach "
            "costs a new fee; a slow attempt keeps running, since FTMO has no time "
            "limit. The passing attempt's fee comes back with the first payout.",
            ""] + cost + [
        "", "The pre-registered row must match `reports/ftmo_fast_pass.md` run on the "
        "same data; the other rows are the same rule with the bot's risk controls, "
        "not a new strategy choice. 3% risk per trade is the operator's order; the "
        "2% row is shown for the trade-off only."]
    text = "\n".join(out) + "\n"
    a.report.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
