#!/usr/bin/env python3
"""PROP-A and PROP-B under FTMO 2-Step Swing rules, exactly as
pre-registered in ``research/prop_native.md``.

    python research/prop_native.py --data-dir <dir with qqq_long.csv, smh_long.csv>
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
NY = "America/New_York"

RISK = 0.015
CAP = 5.0
SIDE_COST = 0.0002
FIN_RATE = 0.05
TARGETS = (0.10, 0.05)
MAX_LOSS = 0.10
DAILY = 0.05
MIN_DAYS = 4
INACTIVE = 30
KEEPALIVE = 25
WITHIN = 548
FUNDED_DAYS = 252
ACCOUNT_CAD = 15_000
SPLIT = 0.80
WARMUP = 200
STEP = 10


@dataclass
class D:
    date: np.ndarray
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    sma200: np.ndarray
    sma50: np.ndarray
    sma5: np.ndarray
    rsi2: np.ndarray
    atr: np.ndarray
    hi20: np.ndarray


def load(path: Path, start: Optional[str] = None) -> D:
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert(NY) \
        .dt.tz_localize(None).dt.normalize()
    df = df.drop_duplicates("date", keep="last").sort_values("date")
    if start:
        df = df[df["date"] >= pd.Timestamp(start)]
    c, h, l = df["close"], df["high"], df["low"]
    delta = c.diff()
    g = delta.clip(lower=0).ewm(alpha=0.5, adjust=False).mean()
    ls = (-delta.clip(upper=0)).ewm(alpha=0.5, adjust=False).mean()
    rsi = (100 - 100 / (1 + g / ls.replace(0, np.nan))).fillna(100)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()],
                   axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
    return D(df["date"].to_numpy(), df["open"].to_numpy(), h.to_numpy(),
             l.to_numpy(), c.to_numpy(), c.rolling(200).mean().to_numpy(),
             c.rolling(50).mean().to_numpy(), c.rolling(5).mean().to_numpy(),
             rsi.to_numpy(), atr.to_numpy(),
             c.rolling(20).max().to_numpy())


def entry_signal(name: str, d: D, i: int) -> bool:
    if np.isnan(d.sma200[i]) or np.isnan(d.atr[i]):
        return False
    if name == "PROP-A":
        return d.c[i] > d.sma200[i] and d.rsi2[i] < 10
    return (d.c[i] > d.sma200[i] and d.sma50[i] > d.sma200[i]
            and d.c[i] >= d.hi20[i])


@dataclass
class Acct:
    name: str
    d: D
    cash: float = 1.0
    units: float = 0.0
    notional: float = 0.0
    entry: float = 0.0
    stop: float = 0.0
    hi_close: float = 0.0
    held: int = 0
    pend_in: Optional[float] = None     # ATR of the signal day
    pend_out: bool = False
    last_fill: Optional[np.datetime64] = None
    fill_days: int = 0
    trades: List[float] = field(default_factory=list)
    entry_bal: float = 0.0

    def balance(self) -> float:
        return self.cash + self.units * self.entry

    def _exit(self, px: float, i: int) -> None:
        proceeds = self.units * px
        self.cash += proceeds - proceeds * SIDE_COST
        self.trades.append(self.cash - self.entry_bal)
        self.units = 0.0
        self.fill_days += 1
        self.last_fill = self.d.date[i]

    def step(self, i: int):
        d = self.d
        if self.pend_out and self.units > 0:
            self._exit(d.o[i], i)
        self.pend_out = False
        if self.pend_in is not None and self.units == 0:
            bal = self.cash
            entry = d.o[i]
            stop = entry - 2 * self.pend_in
            dist = (entry - stop) / entry
            if dist > 0:
                notional = min(CAP * bal, RISK * bal / dist)
                self.units = notional / entry
                self.notional = notional
                self.entry, self.stop, self.hi_close = entry, stop, entry
                self.entry_bal = bal
                self.cash = bal - notional - notional * SIDE_COST
                self.held = 0
                self.fill_days += 1
                self.last_fill = d.date[i]
        self.pend_in = None
        low_eq = self.cash + self.units * d.l[i]
        if self.units > 0:
            if d.o[i] <= self.stop:
                px = d.o[i]
            elif d.l[i] <= self.stop:
                px = self.stop
            else:
                px = None
            if px is not None:
                low_eq = self.cash + self.units * px
                self._exit(px, i)
        if self.units > 0:
            nxt = d.date[i + 1] if i + 1 < len(d.date) else d.date[i]
            nights = max(1, int((nxt - d.date[i]) / np.timedelta64(1, "D")))
            self.cash -= self.notional * FIN_RATE * nights / 365
            self.held += 1
        close_eq = self.cash + self.units * d.c[i]
        # signals on the close
        if self.units > 0:
            if self.name == "PROP-A":
                if d.c[i] > d.sma5[i] or self.held >= 10:
                    self.pend_out = True
            else:
                self.hi_close = max(self.hi_close, d.c[i])
                self.stop = max(self.stop, self.hi_close - 3 * d.atr[i])
                if d.c[i] < d.sma200[i]:
                    self.pend_out = True
        elif entry_signal(self.name, d, i):
            self.pend_in = d.atr[i]
        return low_eq, close_eq


def phase(name, d, start, target):
    a = Acct(name, d)
    t0 = d.date[start]
    for i in range(start, len(d.c)):
        bal0 = a.balance()
        low_eq, close_eq = a.step(i)
        ref = a.last_fill if a.last_fill is not None else t0
        idle = (d.date[i] - ref) / np.timedelta64(1, "D")
        if idle >= KEEPALIVE:
            a.fill_days += 1
            a.last_fill = d.date[i]
            idle = 0
        if low_eq <= 1 - MAX_LOSS:
            return "max_loss", i
        if low_eq <= bal0 - DAILY:
            return "daily_loss", i
        if idle >= INACTIVE:
            return "inactive", i
        if close_eq >= 1 + target and a.fill_days >= MIN_DAYS:
            return "pass", i
    return "unfinished", len(d.c) - 1


def evaluation(name, d, start):
    o1, e1 = phase(name, d, start, TARGETS[0])
    if o1 != "pass":
        return "P1 " + o1, None
    if e1 + 1 >= len(d.c):
        return "P2 unfinished", None
    o2, e2 = phase(name, d, e1 + 1, TARGETS[1])
    if o2 != "pass":
        return "P2 " + o2, None
    return "pass", (d.date[e2] - d.date[start]) / np.timedelta64(1, "D")


def funded(name, d, start):
    a = Acct(name, d)
    for i in range(start, start + FUNDED_DAYS):
        bal0 = a.balance()
        low_eq, close_eq = a.step(i)
        if low_eq <= 1 - MAX_LOSS or low_eq <= bal0 - DAILY:
            return False, low_eq - 1
    return True, close_eq - 1


def pct(x):
    return f"{x:.0%}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--report", type=Path,
                    default=REPO / "reports" / "prop_native.md")
    a = ap.parse_args(argv)
    sets = [("QQQ", load(a.data_dir / "qqq_long.csv", start="2011-03-23")),
            ("SMH", load(a.data_dir / "smh_long.csv"))]
    out = ["# Prop-native strategies under FTMO 2-Step Swing rules", "",
           "Rules: `research/prop_native.md` (pre-registered). Risk 1.5% "
           "per trade, stop 2×ATR, notional cap 5×, CAD 15,000 account.", "",
           "| symbol | strategy | trades | win rate | profit factor | avg win | "
           "avg loss | pass ≤18 mo | by third | median days to pass | main "
           "failure | funded survives 1y | median funded 1y | reward (CAD) | "
           "GO bar |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for sym, d in sets:
        last_eval = np.searchsorted(d.date, d.date[-1] - np.timedelta64(WITHIN, "D"))
        ev_starts = list(range(WARMUP, last_eval, STEP))
        fu_starts = list(range(WARMUP, len(d.c) - FUNDED_DAYS, STEP))
        for name in ("PROP-A", "PROP-B"):
            full = Acct(name, d)
            for i in range(WARMUP, len(d.c)):
                full.step(i)
            tr = full.trades
            wins = [t for t in tr if t > 0]
            losses = [t for t in tr if t <= 0]
            pf = sum(wins) / -sum(losses) if losses and sum(losses) < 0 else float("inf")
            wr = len(wins) / len(tr) if tr else 0
            ev = [evaluation(name, d, s) for s in ev_starts]
            ok18 = [e[0] == "pass" and e[1] <= WITHIN for e in ev]
            p18 = np.mean(ok18)
            thirds = [np.mean(part) for part in np.array_split(np.array(ok18), 3)]
            days = [e[1] for e in ev if e[0] == "pass"]
            fails = pd.Series([e[0] for e in ev if e[0] != "pass"]).value_counts()
            main_fail = (f"{fails.index[0]} {pct(fails.iloc[0] / len(ev))}"
                         if len(fails) else "-")
            fu = [funded(name, d, s) for s in fu_starts]
            surv = [x for x in fu if x[0]]
            ps = len(surv) / len(fu)
            mp = np.median([x[1] for x in surv]) if surv else 0.0
            go = (p18 >= 0.60 and min(thirds) >= 0.50 and ps >= 0.70 and pf > 1.2)
            bar = ("GO" if go else "NO-GO") if sym == "QQQ" else "info only"
            out.append(
                f"| {sym} | {name} | {len(tr)} | {pct(wr)} | {pf:.2f} | "
                f"{np.mean(wins) if wins else 0:+.2%} | "
                f"{np.mean(losses) if losses else 0:+.2%} | {pct(p18)} | "
                + " / ".join(pct(t) for t in thirds)
                + f" | {np.median(days) if days else float('nan'):.0f} | "
                f"{main_fail} | {pct(ps)} | {mp:+.1%} | "
                f"{max(0.0, mp) * ACCOUNT_CAD * SPLIT:,.0f} | **{bar}** |")
    out += ["", "Trade P&L is in fractions of the balance at entry. Evaluation "
            "starts need 18 months of data after them; funded starts 252 "
            "trading days."]
    text = "\n".join(out) + "\n"
    a.report.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
