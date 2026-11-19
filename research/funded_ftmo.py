#!/usr/bin/env python3
"""AIR3 and DIP2 under FTMO 2-Step Swing rules, as pre-registered in
``research/funded_ftmo_swing.md``. Reuses the account model of
``research/funded_backtest.py`` (same strategies, costs, fills).

    python research/funded_ftmo.py --data-dir <dir with smh_long.csv, qqq_long.csv>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import funded_backtest as fb  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
TARGETS = (0.10, 0.05)
MAX_LOSS = 0.10
DAILY = 0.05
MIN_DAYS = 4
INACTIVE = 30
KEEPALIVE = 25
WITHIN = 548          # 18 months, calendar days
ACCOUNT_CAD = 15_000
SPLIT = 0.80


def day_start_balance(acc: fb.Account) -> float:
    """FTMO balance: closed P&L only, open position at entry value."""
    return acc.cash + acc.units * acc.entry_px


def phase(name, d, start, f, target, keepalive):
    acc = fb.Account(name, d, f)
    t0 = d.date[start]
    for i in range(start, len(d.c)):
        bal0 = day_start_balance(acc)
        low_eq, close_eq = acc.step(i)
        ref = acc.last_fill if acc.last_fill is not None else t0
        idle = (d.date[i] - ref) / np.timedelta64(1, "D")
        if keepalive and idle >= KEEPALIVE:
            acc.fill_days += 1
            acc.last_fill = d.date[i]
            idle = 0
        if low_eq <= 1 - MAX_LOSS:
            return "max_loss", i
        if low_eq <= bal0 - DAILY:
            return "daily_loss", i
        if idle >= INACTIVE:
            return "inactive", i
        if close_eq >= 1 + target and acc.fill_days >= MIN_DAYS:
            return "pass", i
    return "unfinished", len(d.c) - 1


def evaluation(name, d, start, f, keepalive):
    o1, e1 = phase(name, d, start, f, TARGETS[0], keepalive)
    if o1 != "pass":
        return "P1 " + o1, None
    if e1 + 1 >= len(d.c):
        return "P2 unfinished", None
    o2, e2 = phase(name, d, e1 + 1, f, TARGETS[1], keepalive)
    if o2 != "pass":
        return "P2 " + o2, None
    return "pass", (d.date[e2] - d.date[start]) / np.timedelta64(1, "D")


def funded(name, d, start, f):
    acc = fb.Account(name, d, f)
    if start + fb.FUNDED_DAYS >= len(d.c):
        return None
    for i in range(start, start + fb.FUNDED_DAYS):
        bal0 = day_start_balance(acc)
        low_eq, close_eq = acc.step(i)
        if low_eq <= 1 - MAX_LOSS or low_eq <= bal0 - DAILY:
            return False, low_eq - 1
    return True, close_eq - 1


def pct(x):
    return f"{x:.0%}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--report", type=Path,
                    default=REPO / "reports" / "funded_ftmo_swing.md")
    a = ap.parse_args(argv)
    sets = [("QQQ (US100 proxy)", fb.load(a.data_dir / "qqq_long.csv",
                                          start="2011-03-23")),
            ("SMH (semis proxy)", fb.load(a.data_dir / "smh_long.csv"))]
    out = ["# AIR3 and DIP2 under FTMO 2-Step Swing rules", "",
           "Rules: `research/funded_ftmo_swing.md` (pre-registered). "
           f"Account CAD {ACCOUNT_CAD:,}, reward {SPLIT:.0%} of profit.", "",
           "| symbol | strategy | sizing | keep-alive | pass both phases | "
           "…within 18 months | median days to pass | main failure | "
           "funded survives 1y | median funded 1y profit | reward on that "
           "(CAD) |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    verdicts = []
    for sym, d in sets:
        starts = list(range(fb.WARMUP, len(d.c) - 30, fb.STEP))
        for name in ("AIR3", "DIP2"):
            for f in (1.0, 2.0):
                fu = [x for x in (funded(name, d, s, f) for s in starts)
                      if x is not None]
                surv = [x for x in fu if x[0]]
                p_surv = len(surv) / len(fu)
                med_profit = np.median([x[1] for x in surv]) if surv else 0.0
                for ka in (False, True):
                    ev = [evaluation(name, d, s, f, ka) for s in starts]
                    outc = pd.Series([e[0] for e in ev])
                    days = [e[1] for e in ev if e[0] == "pass"]
                    p_pass = (outc == "pass").mean()
                    p_18 = sum(1 for x in days if x <= WITHIN) / len(ev)
                    fails = outc[outc != "pass"].value_counts()
                    main_fail = (f"{fails.index[0]} {pct(fails.iloc[0] / len(ev))}"
                                 if len(fails) else "-")
                    reward = max(0.0, med_profit) * ACCOUNT_CAD * SPLIT
                    out.append(
                        f"| {sym} | {name} | {f:.1f}× | {'yes' if ka else 'no'} | "
                        f"{pct(p_pass)} | {pct(p_18)} | "
                        f"{np.median(days) if days else float('nan'):.0f} | "
                        f"{main_fail} | {pct(p_surv)} | {med_profit:+.1%} | "
                        f"{reward:,.0f} |")
                    if f == 1.0 and ka:
                        go = p_18 >= 0.60 and p_surv >= 0.70
                        verdicts.append((sym, name, p_18, p_surv, go))
    out += ["", "## Pre-registered go/no-go (1.0×, keep-alive)", "",
            "| symbol | strategy | pass within 18 months | funded 1y survival | "
            "verdict |", "|---|---|---|---|---|"]
    for sym, name, p18, ps, go in verdicts:
        out.append(f"| {sym} | {name} | {pct(p18)} | {pct(ps)} | "
                   f"**{'GO' if go else 'NO-GO'}** |")
    text = "\n".join(out) + "\n"
    a.report.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
