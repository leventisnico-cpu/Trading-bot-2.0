#!/usr/bin/env python3
"""Win rate and prop-firm evaluation test for AIR3 and DIP2 on SMH / QQQ.

Implements exactly ``research/funded_ai_70pct.md`` (pre-registered and
committed before this script ran).

    python research/funded_backtest.py --data-dir <dir with smh_long.csv, qqq_long.csv>
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
NY = "America/New_York"

SIDE_COST = 0.0002          # 0.02% of notional per side
FIN_RATE = 0.05             # financing per year on notional, per night held
TARGETS = (0.10, 0.05)      # phase 1, phase 2
MAX_LOSS = 0.10
DAILY_LOSS = 0.05
MIN_FILL_DAYS = 4
INACTIVE_DAYS = 30
FUNDED_DAYS = 252
STEP = 10
WARMUP = 200


@dataclass
class Data:
    date: np.ndarray
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    sma200: np.ndarray
    sma50: np.ndarray
    sma5: np.ndarray
    rsi2: np.ndarray


def load(path: Path, start: Optional[str] = None) -> Data:
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert(NY) \
        .dt.tz_localize(None).dt.normalize()
    df = df.drop_duplicates("date", keep="last").sort_values("date")
    if start:
        df = df[df["date"] >= pd.Timestamp(start)]
    c = df["close"]
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 2, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 2, adjust=False).mean()
    rsi = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    rsi = rsi.fillna(100)
    return Data(df["date"].to_numpy(), df["open"].to_numpy(),
                df["high"].to_numpy(), df["low"].to_numpy(), c.to_numpy(),
                c.rolling(200).mean().to_numpy(), c.rolling(50).mean().to_numpy(),
                c.rolling(5).mean().to_numpy(), rsi.to_numpy())


# --------------------------------------------------------------- strategies

def wants_entry(name: str, d: Data, i: int) -> bool:
    if np.isnan(d.sma200[i]):
        return False
    if name == "AIR3":
        return d.c[i] > 1.05 * d.sma200[i] and d.sma50[i] > d.sma200[i]
    return d.c[i] > d.sma200[i] and d.rsi2[i] < 10           # DIP2


def wants_exit(name: str, d: Data, i: int, held: int) -> bool:
    if name == "AIR3":
        return d.c[i] < 0.95 * d.sma200[i]
    return d.c[i] > d.sma5[i] or held >= 10                  # DIP2


@dataclass
class Account:
    """One account run from flat at index ``start``; stepping returns
    the day's low and close equity."""
    name: str
    d: Data
    f: float
    cash: float = 1.0
    units: float = 0.0
    notional: float = 0.0
    entry_px: float = 0.0
    entry_cost: float = 0.0
    held: int = 0
    pending: int = 0            # +1 buy / -1 sell at the next open
    last_fill: Optional[np.datetime64] = None
    fill_days: int = 0
    trades: Optional[List[float]] = None
    trade_dates: Optional[List[np.datetime64]] = None

    def equity(self, px: float) -> float:
        return self.cash + self.units * px

    def step(self, i: int) -> Tuple[float, float]:
        d = self.d
        filled = False
        if self.pending > 0 and self.units == 0:
            bal = self.cash
            self.notional = self.f * bal
            self.entry_px = d.o[i]
            self.units = self.notional / self.entry_px
            self.entry_cost = self.notional * SIDE_COST
            self.cash = bal - self.notional - self.entry_cost
            self.held = 0
            filled = True
            self.entry_cash = bal
        elif self.pending < 0 and self.units > 0:
            proceeds = self.units * d.o[i]
            cost = abs(proceeds) * SIDE_COST
            self.cash += proceeds - cost
            if self.trades is not None:
                self.trades.append(self.cash - self.entry_cash)
                self.trade_dates.append(d.date[i])
            self.units = 0.0
            filled = True
        self.pending = 0
        if filled:
            self.fill_days += 1
            self.last_fill = d.date[i]
        low_eq = self.equity(d.l[i])
        # financing for the night ahead, charged at the close
        if self.units > 0:
            nxt = d.date[i + 1] if i + 1 < len(d.date) else d.date[i]
            nights = max(1, int((nxt - d.date[i]) / np.timedelta64(1, "D")))
            self.cash -= self.notional * FIN_RATE * nights / 365
            self.held += 1
        close_eq = self.equity(d.c[i])
        if self.units == 0 and wants_entry(self.name, d, i):
            self.pending = 1
        elif self.units > 0 and wants_exit(self.name, d, i, self.held):
            self.pending = -1
        return low_eq, close_eq

    def close_out(self, i: int) -> None:
        if self.units > 0:
            proceeds = self.units * self.d.c[i]
            self.cash += proceeds - abs(proceeds) * SIDE_COST
            self.units = 0.0
        self.pending = 0


# ------------------------------------------------------------- evaluation

def run_phase(name: str, d: Data, start: int, f: float, target: float):
    """Returns (outcome, end_index). outcome: pass / max_loss / daily_loss /
    inactive / unfinished."""
    acc = Account(name, d, f)
    prev_close = 1.0
    phase_start_day = d.date[start]
    for i in range(start, len(d.c)):
        low_eq, close_eq = acc.step(i)
        if low_eq <= 1.0 - MAX_LOSS:
            return "max_loss", i
        if low_eq <= prev_close * (1 - DAILY_LOSS):
            return "daily_loss", i
        ref = acc.last_fill if acc.last_fill is not None else phase_start_day
        if (d.date[i] - ref) / np.timedelta64(1, "D") >= INACTIVE_DAYS:
            return "inactive", i
        if close_eq >= 1.0 + target and acc.fill_days >= MIN_FILL_DAYS:
            return "pass", i
        prev_close = close_eq
    return "unfinished", len(d.c) - 1


def evaluation(name: str, d: Data, start: int, f: float):
    out1, end1 = run_phase(name, d, start, f, TARGETS[0])
    if out1 != "pass":
        return "P1 " + out1, end1 - start
    if end1 + 1 >= len(d.c):
        return "P2 unfinished", end1 - start
    out2, end2 = run_phase(name, d, end1 + 1, f, TARGETS[1])
    return ("pass" if out2 == "pass" else "P2 " + out2), end2 - start


def funded(name: str, d: Data, start: int, f: float):
    acc = Account(name, d, f)
    prev = 1.0
    end = start + FUNDED_DAYS
    if end >= len(d.c):
        return None
    for i in range(start, end):
        low_eq, close_eq = acc.step(i)
        if low_eq <= 1 - MAX_LOSS or low_eq <= prev * (1 - DAILY_LOSS):
            return False, low_eq - 1
        prev = close_eq
    return True, prev - 1


def full_sample_trades(name: str, d: Data, f: float):
    acc = Account(name, d, f, trades=[], trade_dates=[])
    for i in range(WARMUP, len(d.c)):
        acc.step(i)
    return acc.trades, acc.trade_dates, acc.equity(d.c[-1])


# ------------------------------------------------------------------- main

def pct(x: float) -> str:
    return f"{x:.0%}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--report", type=Path,
                    default=REPO / "reports" / "funded_ai_70pct.md")
    a = ap.parse_args(argv)
    sets = [("SMH", load(a.data_dir / "smh_long.csv")),
            ("QQQ", load(a.data_dir / "qqq_long.csv", start="2011-03-23"))]
    out = ["# AI-trade strategies vs a two-phase prop evaluation", "",
           "Rules: `research/funded_ai_70pct.md` (pre-registered). Next-day "
           "open fills, 0.02% per side, 5%/yr financing on notional.", ""]
    summary = []
    for sym, d in sets:
        span = f"{pd.Timestamp(d.date[0]).date()} → {pd.Timestamp(d.date[-1]).date()}"
        for name in ("AIR3", "DIP2"):
            trades, tdates, final = full_sample_trades(name, d, 1.0)
            n = len(trades)
            wins = sum(1 for t in trades if t > 0)
            wr = wins / n if n else 0.0
            t0, t1 = d.date[WARMUP], d.date[-1]
            edges = [t0 + (t1 - t0) * k / 3 for k in range(4)]
            fold_wr = []
            for k in range(3):
                ts = [t for t, dt in zip(trades, tdates)
                      if edges[k] <= dt < edges[k + 1] or (k == 2 and dt == t1)]
                fold_wr.append((sum(1 for t in ts if t > 0) / len(ts)) if ts else None)
            avg_w = np.mean([t for t in trades if t > 0]) if wins else 0
            avg_l = np.mean([t for t in trades if t <= 0]) if n - wins else 0
            out += [f"## {sym} — {name} ({span})", "",
                    f"Full sample at 1.0×: {n} trades, win rate {pct(wr)}, "
                    f"folds " + ", ".join("-" if w is None else pct(w) for w in fold_wr)
                    + f"; average win {avg_w:+.2%}, average loss {avg_l:+.2%} "
                    f"of the balance at entry; ending balance {final:.2f}× "
                    f"the start.", ""]
            rows = ["| sizing | eval pass | median days to pass | P1 max loss | "
                    "P1 daily loss | inactive (either phase) | other | "
                    "funded survives 1y | median funded 1y return |",
                    "|---|---|---|---|---|---|---|---|---|"]
            res = {}
            for f in (1.0, 2.0):
                starts = list(range(WARMUP, len(d.c) - 30, STEP))
                ev = [evaluation(name, d, s, f) for s in starts]
                outc = pd.Series([e[0] for e in ev])
                passed = [e[1] for e in ev if e[0] == "pass"]
                fu = [funded(name, d, s, f) for s in starts]
                fu = [x for x in fu if x is not None]
                surv = [x for x in fu if x[0]]
                p_pass = (outc == "pass").mean()
                p_surv = len(surv) / len(fu) if fu else 0.0
                inactive = outc.str.contains("inactive").mean()
                other = 1 - p_pass - (outc == "P1 max_loss").mean() \
                    - (outc == "P1 daily_loss").mean() - inactive
                rows.append(
                    f"| {f:.1f}× | {pct(p_pass)} | "
                    f"{np.median(passed) if passed else float('nan'):.0f} | "
                    f"{pct((outc == 'P1 max_loss').mean())} | "
                    f"{pct((outc == 'P1 daily_loss').mean())} | {pct(inactive)} | "
                    f"{pct(other)} | {pct(p_surv)} | "
                    f"{np.median([x[1] for x in surv]) if surv else float('nan'):+.1%} |")
                res[f] = (p_pass, p_surv)
            out += rows + [""]
            ok_wr = wr >= 0.70 and all(w is not None and w >= 0.70 for w in fold_wr)
            p_pass, p_surv = res[1.0]
            ok = ok_wr and p_pass >= 0.60 and p_surv >= 0.70
            out += [f"Bars at 1.0×: win rate ≥70% everywhere "
                    f"{'YES' if ok_wr else 'no'}; eval pass ≥60% "
                    f"{'YES' if p_pass >= 0.60 else 'no'} ({pct(p_pass)}); "
                    f"funded survival ≥70% {'YES' if p_surv >= 0.70 else 'no'} "
                    f"({pct(p_surv)}) → **{'PROP CANDIDATE' if ok else 'FAIL'}**", ""]
            summary.append((sym, name, n, wr, fold_wr, p_pass, p_surv, ok))
    out += ["## Summary (1.0× sizing)", "",
            "| symbol | strategy | trades | win rate | fold win rates | eval pass | "
            "funded 1y survival | verdict |", "|---|---|---|---|---|---|---|---|"]
    for sym, name, n, wr, fw, pp, ps, ok in summary:
        out.append(f"| {sym} | {name} | {n} | {pct(wr)} | "
                   + " / ".join("-" if w is None else pct(w) for w in fw)
                   + f" | {pct(pp)} | {pct(ps)} | "
                   f"{'PROP CANDIDATE' if ok else 'FAIL'} |")
    text = "\n".join(out) + "\n"
    a.report.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
