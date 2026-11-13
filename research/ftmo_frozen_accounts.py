#!/usr/bin/env python3
"""What "still running" hides: frozen accounts. A diagnostic of rules already
tested (V0, V1 and W2 of ``research/ftmo_scale_out.md`` and
``research/ftmo_scale_out_v2.md``), not a new rule.

The FTMO tables count an attempt that neither passed nor breached when the
data ended as "still running". This script splits those in two:

* **frozen**: flat at the end, with the combined-risk cap leaving a new
  entry less than 0.05% of the initial balance to risk. The max-loss line
  is static, so a flat account's room never comes back: the bot can open
  nothing more, and the attempt cannot pass;
* **still trading**: the rest.

It reruns the same evaluations through the same functions and reads the
last account of each unfinished attempt.

    python -B -I research/ftmo_frozen_accounts.py --data-dir DIR [--report FILE] [--jobs N]
"""

from __future__ import annotations

import argparse
import importlib.util
import multiprocessing as mp
import sys
from pathlib import Path
from typing import Dict

import numpy as np

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("ftmo_scale_out_v2", HERE / "ftmo_scale_out_v2.py")
v2 = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["ftmo_scale_out_v2"] = v2
_spec.loader.exec_module(v2)
so, policy, base = v2.so, v2.policy, v2.base

FROZEN_ROOM = 0.0005          # of the initial balance
VARIANTS = {"V0": so.V0_RULE, "V1": v2.V1, "W2": v2.JUDGED["W2"]}
DESCRIBE = {"V0": "FAST-4 exits, 0.2% buffer", "V1": "5 steps, 0.2% buffer",
            "W2": "5 steps, 1.5% max-loss buffer"}


class Probe(v2.SafeAcct):
    """The study's account, remembering the last one built and its last entry."""
    last = None

    def __init__(self, dates, inst, pol) -> None:
        super().__init__(dates, inst, pol)
        self.last_entry = None
        Probe.last = self

    def _filled(self, i: int) -> None:
        self.last_entry = i
        super()._filled(i)


def room(a) -> float:
    """What the cap leaves a new entry to risk, as ``ScaleAcct.step`` sizes it."""
    pol = a.pol
    ml = getattr(pol, "ml_buffer", None)
    ml = pol.cap_buffer if ml is None else ml
    worst = a.balance() - a.committed()
    return min(worst - (a.day_start - so.DAILY + pol.cap_buffer),
               worst - (1 - so.MAX_LOSS + ml))


DATA: Dict[str, object] = {}


def job(j):
    key, b, cohort = j
    dates, inst = DATA["dates"], DATA["inst"]
    pol, n = VARIANTS[key][b], len(dates)
    res = dict(n=0, passed=0, breached=0, frozen=0, trading=0, years=[])
    saved, policy.Acct = policy.Acct, Probe
    try:
        for s in DATA["starts"][cohort]:
            out, _ = policy.evaluation(dates, inst, pol, s)
            res["n"] += 1
            if out == "pass":
                res["passed"] += 1
            elif "unfinished" not in out:
                res["breached"] += 1
            else:
                a = Probe.last
                if not a.pos and room(a) <= FROZEN_ROOM:
                    res["frozen"] += 1
                    since = s if a.last_entry is None else a.last_entry
                    res["years"].append((n - 1 - since) / 252)
                else:
                    res["trading"] += 1
    finally:
        policy.Acct = saved
    return j, res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--report", type=Path)
    ap.add_argument("--jobs", type=int, default=max(1, (mp.cpu_count() or 1)))
    a = ap.parse_args(argv)
    dates, inst = base.load_all(a.data_dir)
    n = len(dates)
    six = np.timedelta64(so.SIX_MONTHS, "D")
    starts = {c: [s for s in range(so.WARMUP, n, so.STEP)
                  if (dates[s] < so.SPLIT) == (c == so.COHORTS[0]) and dates[s] + six <= dates[-1]]
              for c in so.COHORTS}
    DATA.update(dates=dates, inst=inst, starts=starts)
    jobs = [(k, b, c) for k in VARIANTS for b in (0, 1) for c in so.COHORTS]
    if a.jobs > 1:
        with mp.get_context("fork").Pool(a.jobs) as pool:
            got = dict(pool.map(job, jobs, chunksize=1))
    else:
        got = dict(map(job, jobs))
    out = ["Frozen: flat when the data ends, with under 0.05% of the initial balance left "
           "to risk. Attempts per pass counts a frozen attempt as lost, like a breach.", "",
           "| rule | bound | starts | attempts | passed | breached | frozen | still trading | "
           "median years since a frozen account's last entry | attempts per pass |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for k, b, c in jobs:
        r = got[(k, b, c)]
        m = r["n"]
        yrs = f"{np.median(r['years']):.1f}" if r["years"] else "–"
        per = (r["passed"] + r["breached"] + r["frozen"]) / r["passed"] if r["passed"] else float("nan")
        out.append(f"| {k} ({DESCRIBE[k]}) | {so.BOUNDS[b]} | {c} | {m} | {r['passed'] / m:.1%} | "
                   f"{r['breached'] / m:.1%} | {r['frozen'] / m:.1%} | {r['trading'] / m:.1%} | "
                   f"{yrs} | {per:.2f} |")
    text = "\n".join(out) + "\n"
    if a.report:
        a.report.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
