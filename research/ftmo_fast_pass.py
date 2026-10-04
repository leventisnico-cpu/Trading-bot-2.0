#!/usr/bin/env python3
"""FAST-4 under FTMO 2-Step rules, exactly as pre-registered in
``research/ftmo_fast_pass.md``.

    python research/ftmo_fast_pass.py --data-dir <dir with qqq_long.csv, spy_long.csv, dia_long.csv, iwm_long.csv>
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
NY = "America/New_York"
SYMS = {"US100 (QQQ)": "qqq_long.csv", "US500 (SPY)": "spy_long.csv",
        "US30 (DIA)": "dia_long.csv", "US2000 (IWM)": "iwm_long.csv"}
START = "2011-03-23"
SPLIT = np.datetime64("2019-01-01")
RISKS = (0.005, 0.010, 0.015, 0.020, 0.025, 0.030)
MAX_POS = 2
CAP = 5.0
SIDE_COST = 0.0002
FIN_RATE = 0.05
TARGETS = (0.10, 0.05)
MAX_LOSS = 0.10
DAILY = 0.05
MIN_DAYS = 4
INACTIVE = 30
KEEPALIVE = 25
SIX_MONTHS = 183
FUNDED_DAYS = 252
STEP = 5
WARMUP = 200


def load_all(data_dir: Path):
    frames = {}
    for name, fn in SYMS.items():
        df = pd.read_csv(data_dir / fn)
        df["date"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert(NY) \
            .dt.tz_localize(None).dt.normalize()
        df = df.drop_duplicates("date", keep="last").set_index("date").sort_index()
        frames[name] = df[df.index >= pd.Timestamp(START)]
    common = sorted(set.intersection(*(set(f.index) for f in frames.values())))
    dates = np.array(common, dtype="datetime64[ns]")
    inst = {}
    for name, df in frames.items():
        df = df.loc[common]
        c, h, l = df["close"], df["high"], df["low"]
        d = c.diff()
        g = d.clip(lower=0).ewm(alpha=0.5, adjust=False).mean()
        ls = (-d.clip(upper=0)).ewm(alpha=0.5, adjust=False).mean()
        rsi = (100 - 100 / (1 + g / ls.replace(0, np.nan))).fillna(100)
        tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()],
                       axis=1).max(axis=1)
        inst[name] = dict(o=df["open"].to_numpy(), h=h.to_numpy(), l=l.to_numpy(),
                          c=c.to_numpy(), sma200=c.rolling(200).mean().to_numpy(),
                          sma5=c.rolling(5).mean().to_numpy(), rsi=rsi.to_numpy(),
                          atr=tr.ewm(alpha=1 / 14, adjust=False).mean().to_numpy())
    return dates, inst


@dataclass
class Pos:
    units: float
    entry: float
    stop: float
    notional: float
    entry_bal: float
    held: int = 0
    fin: float = 0.0


@dataclass
class Acct:
    dates: np.ndarray
    inst: Dict[str, dict]
    risk: float
    cash: float = 1.0
    pos: Dict[str, Pos] = field(default_factory=dict)
    pend_in: List[tuple] = field(default_factory=list)
    pend_out: set = field(default_factory=set)
    last_fill: Optional[np.datetime64] = None
    fill_days: int = 0
    trades: List[tuple] = field(default_factory=list)   # (entry_date, pnl)
    entry_dates: Dict[str, np.datetime64] = field(default_factory=dict)

    def balance(self) -> float:
        return self.cash + sum(p.units * p.entry for p in self.pos.values())

    def _close(self, s: str, px: float, i: int) -> None:
        p = self.pos.pop(s)
        proceeds = p.units * px
        self.cash += proceeds - proceeds * SIDE_COST
        self.trades.append((self.entry_dates.pop(s),
                            (proceeds - p.units * p.entry - proceeds * SIDE_COST
                             - p.notional * SIDE_COST - p.fin) / p.entry_bal))
        self._filled(i)

    def _filled(self, i: int) -> None:
        if self.last_fill is None or self.last_fill != self.dates[i]:
            self.fill_days += 1
        self.last_fill = self.dates[i]

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
            notional = min(CAP * bal, self.risk * bal / dist)
            self.pos[s] = Pos(notional / entry, entry, stop, notional, bal)
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
        # stopped positions are in cash at their exit price; the rest at the low
        low_eq = self.cash + sum(p.units * self.inst[s]["l"][i] for s, p in self.pos.items())
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
        return low_eq, close_eq


def phase(dates, inst, risk, start, target):
    a = Acct(dates, inst, risk)
    t0 = dates[start]
    for i in range(start, len(dates)):
        bal0 = a.balance()
        low_eq, close_eq = a.step(i)
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
        if close_eq >= 1 + target and a.fill_days >= MIN_DAYS:
            return "pass", i
    return "unfinished", len(dates) - 1


def evaluation(dates, inst, risk, start):
    o1, e1 = phase(dates, inst, risk, start, TARGETS[0])
    if o1 != "pass":
        return "P1 " + o1, None
    if e1 + 1 >= len(dates):
        return "P2 unfinished", None
    o2, e2 = phase(dates, inst, risk, e1 + 1, TARGETS[1])
    if o2 != "pass":
        return "P2 " + o2, None
    return "pass", (dates[e2] - dates[start]) / np.timedelta64(1, "D")


def funded(dates, inst, risk, start):
    a = Acct(dates, inst, risk)
    for i in range(start, start + FUNDED_DAYS):
        bal0 = a.balance()
        low_eq, close_eq = a.step(i)
        if low_eq <= 1 - MAX_LOSS or low_eq <= bal0 - DAILY:
            return False
    return True


def stats(dates, inst, risk, starts_eval, starts_fund):
    ev = [evaluation(dates, inst, risk, s) for s in starts_eval]
    p6 = np.mean([e[0] == "pass" and e[1] <= SIX_MONTHS for e in ev]) if ev else 0
    p18 = np.mean([e[0] == "pass" and e[1] <= 548 for e in ev]) if ev else 0
    days = [e[1] for e in ev if e[0] == "pass"]
    fails = pd.Series([e[0] for e in ev if e[0] != "pass"]).value_counts()
    main_fail = f"{fails.index[0]} {fails.iloc[0] / len(ev):.0%}" if len(fails) else "-"
    fu = [funded(dates, inst, risk, s) for s in starts_fund]
    surv = np.mean(fu) if fu else 0
    return p6, p18, (np.median(days) if days else float("nan")), main_fail, surv


def trade_stats(trades):
    if not trades:
        return 0, 0.0, float("nan")
    p = np.array([t for _, t in trades])
    wins, losses = p[p > 0], p[p <= 0]
    pf = wins.sum() / -losses.sum() if losses.sum() < 0 else float("inf")
    return len(p), len(wins) / len(p), pf


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--report", type=Path,
                    default=REPO / "reports" / "ftmo_fast_pass.md")
    a = ap.parse_args(argv)
    dates, inst = load_all(a.data_dir)
    n = len(dates)
    six = np.timedelta64(SIX_MONTHS, "D")
    sel_eval = [s for s in range(WARMUP, n, STEP) if dates[s] < SPLIT
                and dates[s] + six <= dates[-1]]
    sel_fund = [s for s in range(WARMUP, n - FUNDED_DAYS, STEP) if dates[s] < SPLIT]
    tst_eval = [s for s in range(WARMUP, n, STEP) if dates[s] >= SPLIT
                and dates[s] + six <= dates[-1]]
    tst_fund = [s for s in range(WARMUP, n - FUNDED_DAYS, STEP) if dates[s] >= SPLIT]
    out = ["# FAST-4 under FTMO 2-Step rules", "",
           f"Rules: `research/ftmo_fast_pass.md` (pre-registered). Common "
           f"dates {pd.Timestamp(dates[0]).date()} → {pd.Timestamp(dates[-1]).date()}; "
           f"selection starts before {SPLIT}, test starts from it.", "",
           "| risk/trade | period | trades | win rate | profit factor | pass ≤6 mo | "
           "pass ≤18 mo | median days to pass | main failure | funded 1y survival |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    sel = {}
    for r in RISKS:
        full = Acct(dates, inst, r)
        for i in range(WARMUP, n):
            full.step(i)
        tr_sel = [t for t in full.trades if t[0] < SPLIT]
        tr_tst = [t for t in full.trades if t[0] >= SPLIT]
        for label, trs, se, sf in (("selection", tr_sel, sel_eval, sel_fund),
                                   ("test", tr_tst, tst_eval, tst_fund)):
            k, wr, pf = trade_stats(trs)
            p6, p18, md, mf, sv = stats(dates, inst, r, se, sf)
            out.append(f"| {r:.1%} | {label} | {k} | {wr:.0%} | {pf:.2f} | "
                       f"{p6:.0%} | {p18:.0%} | {md:.0f} | {mf} | {sv:.0%} |")
            if label == "selection":
                sel[r] = (p6, sv)
            else:
                sel[r] = sel[r] + (wr, p6, sv, pf)
    eligible = [r for r in RISKS if sel[r][1] >= 0.70]
    chosen = max(eligible, key=lambda r: (sel[r][0], -r)) if eligible else None
    out += [""]
    if chosen is None:
        out.append("No risk level kept funded survival ≥ 70% in the selection "
                   "period → **NO-GO** (nothing to carry to the test period).")
    else:
        _, _, wr, p6, sv, pf = sel[chosen]
        go = wr >= 0.70 and p6 >= 0.50 and sv >= 0.70 and pf > 1.2
        out += [f"Chosen in the selection period: **{chosen:.1%}** risk per "
                f"trade (highest pass ≤6 months with funded survival ≥70%).", "",
                f"Test period at {chosen:.1%}: win rate {wr:.0%} (bar ≥70%), "
                f"pass ≤6 months {p6:.0%} (bar ≥50%), funded survival "
                f"{sv:.0%} (bar ≥70%), profit factor {pf:.2f} (bar >1.2) → "
                f"**{'GO' if go else 'NO-GO'}**"]
    text = "\n".join(out) + "\n"
    a.report.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
