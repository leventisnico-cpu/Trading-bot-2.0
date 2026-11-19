#!/usr/bin/env python3
"""More markets for the 5 steps, as pre-registered in
``research/ftmo_breadth.md``.

The bot's rule as it runs today (W2+S2 of
``research/ftmo_slots_sizing.md``: the 5 steps, 3% risk, the 1.5% buffer
over the max-loss line, free slots) on four lists of markets:

* B0: the four US indices (the bot today);
* B1: B0 + gold;
* B2: B0 + Germany, the United Kingdom, Japan and Australia;
* B3: all nine.

Only the list differs. The account, the FTMO functions, the costs and
the start dates are ``research/ftmo_slots_sizing.py`` and the modules it
imports, unchanged. B1-B3 are judged against B0 with that note's rule
(its ``judge``).

    python -B -I research/ftmo_breadth.py --data-dir DIR --extra-dir DIR
        [--div-dir DIR] [--report FILE] [--jobs N] [--check-only]

``--data-dir`` holds the four index files of the earlier notes,
``--extra-dir`` the five new ones, ``--div-dir`` (optional) the country
funds' distribution histories for the sensitivity rows. ``--check-only``
runs the plumbing checks (B0 reproduces the published W2+S2 figures) and
prints what the data alone shows (correlations, signal counts, the
distributions if given); no account is run on a new market.

Every run first checks that the nine files are the note's (sha256), that
each new file has exactly the four indices' sessions, and that B0 comes
out as published. A failed check stops the run.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import multiprocessing as mp
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("ftmo_slots_sizing", HERE / "ftmo_slots_sizing.py")
ss = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["ftmo_slots_sizing"] = ss
_spec.loader.exec_module(ss)
v2, so, policy, base = ss.v2, ss.so, ss.policy, ss.base
COHORTS, BOUNDS, SPLIT = ss.COHORTS, ss.BOUNDS, ss.SPLIT
WARMUP, STEP = ss.WARMUP, ss.STEP
SIX_MONTHS, FUNDED_DAYS = ss.SIX_MONTHS, ss.FUNDED_DAYS

KEY = "W2+S2"                # the bot as it runs (research/ftmo_slots_sizing.md)
US = tuple(base.SYMS)
GOLD = "XAUUSD (GLD)"
EXTRA = {GOLD: "gld_long.csv", "GER40 (EWG)": "ewg_long.csv", "UK100 (EWU)": "ewu_long.csv",
         "JP225 (EWJ)": "ewj_long.csv", "AUS200 (EWA)": "ewa_long.csv"}
COUNTRIES = tuple(k for k in EXTRA if k != GOLD)
UNIVERSES = {"B0": US, "B1": US + (GOLD,), "B2": US + COUNTRIES, "B3": US + tuple(EXTRA)}
JUDGED = ("B1", "B2", "B3")
ADJ = " adj"                 # the same list, its country funds adjusted for distributions
SENSITIVITY = ("B2" + ADJ, "B3" + ADJ)
DESCRIBE = {
    "B0": "US100, US500, US30, US2000 (the bot today)",
    "B1": "B0 + XAUUSD",
    "B2": "B0 + GER40, UK100, JP225, AUS200",
    "B3": "B0 + all five",
    "B2" + ADJ: "B2 with the four country funds' prices adjusted for distributions "
                "(sensitivity)",
    "B3" + ADJ: "B3 with the same adjustment (sensitivity)",
}

# The nine files the note was written on (research/ftmo_breadth.md, "Data").
SHA256 = {
    "qqq_long.csv": "cfab2078c1777e4cf39fab62909d53d2a316fc92b1cfb27dab0719db9ad2e123",
    "spy_long.csv": "66043ca34d7aa4e6b191bf3607a004674f8027f5cb98aa84d0c23e39c07be6ce",
    "dia_long.csv": "be0494ef6804e96889c320e3be4858217c6eada743d80665d01df07a90681f3b",
    "iwm_long.csv": "44cc382e05c8da6fdf47fa6b761676cd18867f22ec258d6f02cc47b9533ebdd2",
    "gld_long.csv": "9d62e4f2811e4cebd6075f8043867e2055b20fcb00cb20dc466f5d38b9993bd6",
    "ewg_long.csv": "5bd6e2e38d3968897974f59a832b12011cd4efbff3f26cc629058d81321f5163",
    "ewu_long.csv": "0c468b3ed7fb47af10191bdea785c3366e44bf4d83072a8d49d777c151d4f77c",
    "ewj_long.csv": "75e0ef01aba3ee17522e68141014600db6a0f7daf1e95471bc977c39589a9a4d",
    "ewa_long.csv": "7f919003205372d456c9de8428add2df2b575c11055f81beee293db8282cc621",
}

# B0 is W2+S2 on the four indices. Its rows as published in
# research/ftmo_slots_sizing.md (results of 2026-11-09), cell for cell; keys
# are the bound (0 pessimistic, 1 optimistic) and the cohort's position.
PUBLISHED = dict(
    starts=(352, 368),
    trades={0: "214 | 14.4 | 58.9% | 58.9% | +0.92 | -1.13 | +0.079 | 2.45% | 22 | 4 | "
               "+1.4% | 37.3%",
            1: "214 | 14.4 | 58.9% | 58.9% | +0.92 | -1.13 | +0.079 | 2.45% | 22 | 4 | "
               "+1.4% | 37.3%"},
    signals="990 | 216 | 216 | 550 | 191 | 224 | 45 | 5 | 2428 of 3725",
    ftmo={(0, 0): "45% | 5% | 33.8% | 35.2% | 35.2% | 21.0% | 43.8% | 43.8% | 0.0% | "
                  "209 / 260 / 322 | P1 unfinished 35% | 77% | -6.7% | 2.84",
          (0, 1): "52% | 9% | 30.4% | 42.4% | 42.4% | 8.4% | 38.3% | 38.3% | 10.9% | "
                  "214 / 360 / 602 | P1 unfinished 41% | 92% | +1.7% | 2.10",
          (1, 0): "48% | 8% | 34.1% | 35.5% | 35.5% | 19.3% | 45.2% | 45.2% | 0.0% | "
                  "188 / 237 / 302 | P1 unfinished 34% | 77% | -6.4% | 2.82",
          (1, 1): "58% | 12% | 39.4% | 51.9% | 51.9% | 7.3% | 31.8% | 31.8% | 9.0% | "
                  "192 / 309 / 519 | P1 unfinished 34% | 92% | +1.7% | 1.75"},
    counts={(0, 0): (74, 119, 124), (0, 1): (31, 112, 156),      # breached, both within
            (1, 0): (68, 120, 125), (1, 1): (27, 145, 191)},     # 18 months, both ever
)


# --------------------------------------------------------------------- data

def must(ok, *what) -> None:
    """A check that stops the run, also under ``python -O``."""
    if not ok:
        raise SystemExit("check failed: " + "; ".join(str(w) for w in what))


def verify_files(data_dir: Path, extra_dir: Path) -> None:
    """The nine files are the note's, byte for byte."""
    for folder, files in ((data_dir, base.SYMS.values()), (extra_dir, EXTRA.values())):
        for fn in files:
            got = hashlib.sha256((folder / fn).read_bytes()).hexdigest()
            must(got == SHA256[fn], f"{fn} is not the note's file (sha256 {got})",
                 "nothing was run")


def load_extra(folder: Path) -> Tuple[np.ndarray, Dict[str, dict]]:
    """The five new markets through the earlier notes' own loader."""
    saved = base.SYMS
    base.SYMS = EXTRA
    try:
        return base.load_all(folder)
    finally:
        base.SYMS = saved


def load(data_dir: Path, extra_dir: Path):
    """(sessions, the four indices exactly as every earlier note loads them,
    the five new markets). Each new file must have the four's sessions
    from the first one on, all of them and no others: nothing is
    re-aligned, so B0 runs on the published data."""
    dates, four = base.load_all(data_dir)
    for name, fn in EXTRA.items():
        days = ny_days(pd.read_csv(extra_dir / fn)["timestamp"])
        own = np.array(sorted(set(days[days >= pd.Timestamp(base.START)])),
                       dtype="datetime64[ns]")
        if not np.array_equal(own, dates):
            raise SystemExit(f"{name}: its sessions differ from the four indices' "
                             f"({len(own)} against {len(dates)}); nothing was run")
    dates_x, five = load_extra(extra_dir)
    must(np.array_equal(dates, dates_x), "the new markets loaded on other sessions")
    return dates, four, five


def universe(name: str, four: Dict[str, dict], five: Dict[str, dict],
             adjusted: Optional[Dict[str, dict]] = None) -> Dict[str, dict]:
    """The markets of one list, the four indices first."""
    if name.endswith(ADJ):
        must(adjusted is not None, "the adjusted prices were not loaded")
        name, five = name[:-len(ADJ)], {**five, **adjusted}
    both = {**four, **five}
    return {k: both[k] for k in UNIVERSES[name]}


def ny_days(stamps: pd.Series) -> pd.Series:
    """Session dates, as ``base.load_all`` reads them."""
    return (pd.to_datetime(stamps, utc=True).dt.tz_convert(base.NY)
            .dt.tz_localize(None).dt.normalize())


def adjust(df: pd.DataFrame, div: pd.DataFrame) -> Tuple[pd.DataFrame, List[tuple]]:
    """A price file with every price before an ex-date multiplied by
    1 - amount / (the close of the session before it): the usual
    back-adjustment, which takes the distribution's drop out of the
    series. Returns the frame and, per distribution applied, (the first
    session on or after the ex-date, amount / that earlier close)."""
    df = df.assign(_day=ny_days(df["timestamp"])).drop_duplicates("_day", keep="last") \
        .sort_values("_day").reset_index(drop=True)
    factor = np.ones(len(df))
    applied = []
    for ex, amount in zip(pd.to_datetime(div["ex_date"]), div["amount"].astype(float)):
        k = int(df["_day"].searchsorted(ex))         # the first session on or after it
        if k == 0 or k >= len(df):                   # outside the data: nothing to adjust
            continue
        share = amount / float(df["close"].iloc[k - 1])
        if not 0 < share < 0.1:
            raise SystemExit(f"distribution of {ex.date()}: {amount} is {share:.1%} of the "
                             "price before it; check the amounts and their split basis")
        factor[:k] *= 1 - share
        applied.append((df["_day"].iloc[k], share))
    for col in ("open", "high", "low", "close"):
        df[col] = df[col] * factor
    return df.drop(columns="_day"), applied


def load_adjusted(extra_dir: Path, div_dir: Path):
    """The four country funds adjusted for their distributions, loaded like
    the others, and what was applied per fund. Gold pays nothing."""
    applied = {}
    with tempfile.TemporaryDirectory() as tmp:
        for name, fn in EXTRA.items():
            df = pd.read_csv(extra_dir / fn)
            if name != GOLD:
                df, applied[name] = adjust(
                    df, pd.read_csv(div_dir / fn.replace("_long.csv", "_div.csv")))
            df.to_csv(Path(tmp) / fn, index=False)
        dates, five = load_extra(Path(tmp))
    return dates, {k: five[k] for k in COUNTRIES}, applied


def fast4(x: dict) -> np.ndarray:
    """Sessions whose close gives a FAST-4 signal, as the account reads it."""
    with np.errstate(invalid="ignore"):
        return ~np.isnan(x["sma200"]) & (x["c"] > x["sma200"]) & (x["rsi"] < 10)


def data_view(inst: Dict[str, dict]) -> dict:
    """What the prices alone show from session WARMUP on: no account, no
    trade. Correlations of daily close-to-close returns, and where the
    signals fall."""
    names = list(inst)
    rets = np.array([np.diff(np.log(inst[k]["c"][WARMUP - 1:])) for k in names])
    corr = np.corrcoef(rets)
    sig = {k: fast4(inst[k])[WARMUP:] for k in names}
    us = [names.index(k) for k in US]
    us_any = np.any([sig[k] for k in US], axis=0)
    rows = {}
    for j, k in enumerate(names):
        others = [i for i in us if i != j]
        rows[k] = dict(signals=int(sig[k].sum()),
                       alone=int((sig[k] & ~us_any).sum()),
                       corr_us=float(np.mean([corr[j, i] for i in others])))
    return dict(rows=rows, sessions=len(us_any),
                any={u: int(np.any([sig[k] for k in ks if k in sig], axis=0).sum())
                     for u, ks in UNIVERSES.items() if all(k in sig for k in ks)})


def drop_view(raw: pd.DataFrame, adj: pd.DataFrame, applied: List[tuple]) -> dict:
    """Do the ex-dates sit on real drops? The mean return from the close
    before each ex-date to that session's open, before and after the
    adjustment (it should go from about minus the distribution to about
    zero), and the distributions' sum."""
    def gaps(df):
        df = df.assign(_day=ny_days(df["timestamp"])).drop_duplicates("_day", keep="last") \
            .sort_values("_day").set_index("_day")
        gap = df["open"] / df["close"].shift() - 1
        return [float(gap.loc[d]) for d, _ in applied]
    shares = [s for _, s in applied]
    return dict(n=len(applied), total=float(np.sum(shares)), mean=float(np.mean(shares)),
                gap_raw=float(np.mean(gaps(raw))), gap_adj=float(np.mean(gaps(adj))))


# ------------------------------------------------------------------ accounts

class Wide(ss.SlotAcct):
    """``SlotAcct`` that also remembers the largest total position at a
    close (open units at their entry prices, as a multiple of the
    balance). A diagnostic: it changes nothing (asserted in ``main``)."""

    def __init__(self, dates, inst, pol) -> None:
        super().__init__(dates, inst, pol)
        self.max_notional = 0.0

    def step(self, i: int):
        out = super().step(i)
        if self.pos:
            held = sum(p.units * p.entry for p in self.pos.values())
            self.max_notional = max(self.max_notional, held / self.balance())
        return out


def spread(trades: List[dict]) -> dict:
    """Trades, the share that reached +1R first, the payoff per trade in R
    with its standard error, and the sum of R."""
    rr = np.array([t["R"] for t in trades], dtype=float)
    n = len(rr)
    return dict(n=n, tp1=float(np.mean([t["tp1"] for t in trades])) if n else float("nan"),
                exp=float(rr.mean()) if n else float("nan"),
                se=float(rr.std(ddof=1) / np.sqrt(n)) if n > 1 else float("nan"),
                total=float(rr.sum()))


def continuous(dates, inst, pol) -> dict:
    """One continuous account on a list of markets: the slots note's
    figures, plus the same per market."""
    acct, eq = so.full_run(dates, inst, pol, Wide)
    m = v2.trade_metrics(dates, inst, acct, eq, pol.stop_first)
    m.update(sig=dict(acct.sig), max_open=acct.max_open, entered=acct.entered,
             max_notional=acct.max_notional, all=spread(acct.log),
             markets={k: spread([t for t in acct.log if t["sym"] == k]) for k in inst})
    return m


def alone(dates, name: str, x: dict, pol) -> dict:
    """One market traded by itself with the same rule."""
    acct, _ = so.full_run(dates, {name: x}, pol, ss.SlotAcct)
    return spread(acct.log)


def make_starts(dates) -> dict:
    """The start dates of the earlier notes (``ss.main`` builds the same;
    ``check_b0`` holds this to the published counts)."""
    n, six = len(dates), np.timedelta64(SIX_MONTHS, "D")

    def pick(inside):
        return ([s for s in range(WARMUP, n, STEP)
                 if inside(dates[s]) and dates[s] + six <= dates[-1]],
                [s for s in range(WARMUP, n - FUNDED_DAYS, STEP) if inside(dates[s])])
    return {COHORTS[0]: pick(lambda d: d < SPLIT), COHORTS[1]: pick(lambda d: d >= SPLIT)}


DATA: Dict[str, object] = {}


def job(j):
    """One cell of ``ss.job`` (kind "stats" or "probe") on one list of
    markets. Each worker process sets the slots module's data for the
    call."""
    kind, uni, b, cohort = j
    ss.DATA.update(dates=DATA["dates"], inst=DATA["inst"][uni], starts=DATA["starts"])
    return j, ss.job((kind, KEY, b, cohort))[1]


# -------------------------------------------------------------------- tables

def trade_cells(m: dict, years: float) -> str:
    return (f"{m['trades']} | {m['trades'] / years:.1f} | {m['webinar']:.1%} | "
            f"{m['pnl_win']:.1%} | {m['avg_win']:+.2f} | {m['avg_loss']:+.2f} | "
            f"{m['exp']:+.3f} | {m['risk']:.2%} | {m['held']:.0f} | {m['max_open']} | "
            f"{m['cagr']:+.1%} | {m['mdd']:.1%}")


def signal_cells(m: dict) -> str:
    g = Counter(m["sig"])
    return (f"{g['signals']} | {g['planned']} | {m['entered']} | {g['held']} | "
            f"{g['held_free']} | {g['no_slot']} | {g['no_slot_free']} | "
            f"{g['no_slot_all_free']} | {g['days_full']} of {g['days']}")


def ftmo_cells(r: dict, pr: dict) -> str:
    n = pr["n"] or 1
    fz, st = pr["frozen"] / n, pr["stuck"] / n
    att = (r["pe"] + r["breach"] + st) / r["pe"] if r["pe"] > 0 else float("nan")
    return (f"{r['p1']:.0%} | {r['p6']:.0%} | {r['p18']:.1%} | {pr['p36'] / n:.1%} | "
            f"{r['pe']:.1%} | {r['breach']:.1%} | {fz:.1%} | {st:.1%} | "
            f"{r['running'] - st:.1%} | {r['q1']:.0f} / {r['md']:.0f} / {r['q3']:.0f} | "
            f"{r['main_fail']} | {r['surv']:.0%} | {r['fret']:+.1%} | {att:.2f}")


def counts(r: dict, m: int) -> Tuple[int, int, int]:
    """(breached, both phases within 18 months, both within the data), of m."""
    return tuple(round(r[f] * m) for f in ("breach", "p18", "pe"))


def check_b0(years: float, metrics, ftmo: dict, starts: dict, view: dict) -> None:
    """B0 through this script is the published W2+S2: every cell of its
    rows in ``research/ftmo_slots_sizing.md``, as printed there. And the
    signals ``data_view`` counts are the ones the account counts."""
    got = tuple(len(starts[c][0]) for c in COHORTS)
    must(got == PUBLISHED["starts"], "the start dates are not the published run's", got)
    seen = sum(view["rows"][k]["signals"] for k in US)
    must(seen == metrics[0]["sig"].get("signals", 0),
         "the signals counted from the prices are not the account's", seen)
    for b in (0, 1):
        cells = trade_cells(metrics[b], years)
        must(cells == PUBLISHED["trades"][b], "B0's trades differ from W2+S2's", b, cells)
    cells = signal_cells(metrics[0])
    must(cells == PUBLISHED["signals"], "B0's signals differ from W2+S2's", cells)
    for b in (0, 1):
        for ci, c in enumerate(COHORTS):
            r, pr = ftmo[("stats", "B0", b, c)], ftmo[("probe", "B0", b, c)]
            cells = ftmo_cells(r, pr)
            must(cells == PUBLISHED["ftmo"][(b, ci)],
                 "B0's FTMO figures differ from W2+S2's", b, c, cells)
            must(counts(r, got[ci]) == PUBLISHED["counts"][(b, ci)],
                 "B0's counts differ from W2+S2's", b, c, counts(r, got[ci]))


def rows(ftmo: dict, starts: dict, uni: str, ref: str = "B0") -> List[tuple]:
    """The verdict rule's rows for one list against the reference:
    (cohort, bound, start dates, then breached, both within 18 months and
    both within the data, each as the list's count and the reference's)."""
    got = []
    for c in COHORTS:
        m = len(starts[c][0])
        for b in (0, 1):
            rv, r0 = ftmo[("stats", uni, b, c)], ftmo[("stats", ref, b, c)]
            got.append((c, b, m, *(round(x[f] * m) for f in ("breach", "p18", "pe")
                                   for x in (rv, r0))))
    return got


def prefer(winners: Dict[str, List[tuple]]) -> str:
    """Among lists that beat B0: the higher lowest share passing within the
    data across the four cells, then the lower highest breach share, then
    the fewer markets."""
    def key(k):
        rs = winners[k]
        return (-min(ev / m for _, _, m, _, _, _, _, ev, _ in rs),
                max(bv / m for _, _, m, bv, _, _, _, _, _ in rs), len(UNIVERSES[k]), k)
    return min(winners, key=key)


def verdict_lines(ftmo: dict, starts: dict, names, judged: bool) -> List[str]:
    out = ["| list | cohort | bound | breached: list vs B0 | both ≤18 mo | both, ever | "
           "no worse |", "|---|---|---|---|---|---|---|"]
    winners = {}
    for k in names:
        rs = rows(ftmo, starts, k)
        for c, b, m, bv, b0, pv, p0, ev, e0 in rs:
            ok = bv <= b0 and pv >= p0 and ev >= e0
            out.append(f"| {k} | {c} | {BOUNDS[b]} | {bv}/{m} ({bv / m:.1%}) vs {b0}/{m} "
                       f"({b0 / m:.1%}) | {pv}/{m} ({pv / m:.1%}) vs {p0}/{m} "
                       f"({p0 / m:.1%}) | {ev}/{m} ({ev / m:.1%}) vs {e0}/{m} "
                       f"({e0 / m:.1%}) | {'yes' if ok else 'no'} |")
        no_worse, better = ss.judge(rs)
        out.append(f"| **{k}** | | | | | | no worse anywhere: {'yes' if no_worse else 'no'}; "
                   f"better somewhere: {'yes' if better else 'no'} |")
        if no_worse and better:
            winners[k] = rs
    out.append("")
    if not judged:
        out.append("These rows are a sensitivity: reported, not judged, and nothing is "
                   "adopted on them.")
    elif winners:
        out.append(f"**Beats B0:** {', '.join(winners)}; preferred by the tie-break: "
                   f"**{prefer(winners)}**.")
    else:
        out.append("**No list beats B0** by the rule.")
    return out


def view_lines(view: dict, drops: Optional[dict]) -> List[str]:
    out = ["**What the prices alone show** (sessions from the first trading day on; no "
           "account is involved). A signal: close over the 200-day average and RSI(2) "
           "under 10.", "",
           "| market | signals | … on sessions with no signal in any US index | average "
           "correlation of daily returns with the (other) US indices |", "|---|---|---|---|"]
    for k, r in view["rows"].items():
        alone_cell = "" if k in US else str(r["alone"])
        out.append(f"| {k} | {r['signals']} | {alone_cell} | {r['corr_us']:+.2f} |")
    out += ["", "Sessions with at least one signal, of " + str(view["sessions"]) + ": "
            + ", ".join(f"{u} {n}" for u, n in view["any"].items()) + "."]
    if drops:
        out += ["", "**The distributions** behind the sensitivity rows (the mean move from "
                "the close before an ex-date to that session's open should go from about "
                "minus the distribution to about zero):", "",
                "| fund | distributions | their sum, of the price | mean | mean move into "
                "the ex-date, as downloaded | … adjusted |", "|---|---|---|---|---|---|"]
        for k, d in drops.items():
            out.append(f"| {k} | {d['n']} | {d['total']:.1%} | {d['mean']:.2%} | "
                       f"{d['gap_raw']:+.2%} | {d['gap_adj']:+.2%} |")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--extra-dir", type=Path, required=True)
    ap.add_argument("--div-dir", type=Path, default=None,
                    help="the country funds' distributions: adds the sensitivity rows")
    ap.add_argument("--report", type=Path, default=None)
    ap.add_argument("--jobs", type=int, default=max(1, (mp.cpu_count() or 1)))
    ap.add_argument("--check-only", action="store_true",
                    help="the plumbing checks and the data's own figures; no account "
                         "runs on a new market")
    a = ap.parse_args(argv)
    if not __debug__:                                # the imported accounts check with assert
        raise SystemExit("run without -O: the accounts' own checks are assertions")
    verify_files(a.data_dir, a.extra_dir)
    dates, four, five = load(a.data_dir, a.extra_dir)
    adjusted, drops = None, None
    if a.div_dir is not None:
        dates_a, adjusted, applied = load_adjusted(a.extra_dir, a.div_dir)
        must(np.array_equal(dates, dates_a), "the adjusted files changed the sessions")
        drops = {}
        for k in COUNTRIES:
            raw = pd.read_csv(a.extra_dir / EXTRA[k])
            adj, _ = adjust(raw, pd.read_csv(a.div_dir / EXTRA[k].replace("_long.csv",
                                                                         "_div.csv")))
            drops[k] = drop_view(raw, adj, applied[k])
    names = list(UNIVERSES) + (list(SENSITIVITY) if adjusted is not None else [])
    inst = {k: universe(k, four, five, adjusted) for k in names}
    must(all(inst["B0"][k] is four[k] for k in US) and list(inst["B0"]) == list(US),
         "B0 is not the four indices as loaded")
    starts = make_starts(dates)
    DATA.update(dates=dates, inst=inst, starts=starts)
    say = lambda m: print(m, file=sys.stderr, flush=True)   # noqa: E731
    cells = [(b, c) for b in (0, 1) for c in COHORTS]
    years = (dates[-1] - dates[WARMUP]) / np.timedelta64(1, "D") / 365.25
    cont = ss.CONT_POL[KEY]

    def run(jobs):
        if a.jobs > 1:
            with mp.get_context("fork").Pool(a.jobs) as pool:
                return dict(pool.map(job, jobs, chunksize=1))
        return dict(map(job, jobs))

    # 1. plumbing: B0 here is the published W2+S2, and the diagnostics change nothing
    metrics = {"B0": [continuous(dates, inst["B0"], cont[b]) for b in (0, 1)]}
    for b in (0, 1):
        ref, _ = so.full_run(dates, four, cont[b], ss.SlotAcct)
        must(metrics["B0"][b]["trades_by"] == list(ref.trades),
             "the account with the diagnostics does not reproduce W2+S2's trades")
    view = data_view({**four, **five})
    ftmo = run([(kind, "B0", b, c) for kind in ("stats", "probe") for b, c in cells])
    check_b0(years, metrics["B0"], ftmo, starts, view)
    say("plumbing: B0 reproduces the published W2+S2 rows, cell for cell")

    first, last = pd.Timestamp(dates[WARMUP]).date(), pd.Timestamp(dates[-1]).date()
    m0, m1 = (len(starts[c][0]) for c in COHORTS)
    out = [f"Common dates {pd.Timestamp(dates[0]).date()} → {last}; continuous account "
           f"{first} → {last}; start dates (2011–18 / 2019–26): {m0} / {m1} evaluations. "
           "Checks passed: the nine files are the note's (sha256); each new file has "
           "exactly the four indices' sessions; B0 through this script reproduces every "
           "published cell of W2+S2 (per trade, signals, FTMO, the verdict counts).", ""]
    out += [f"* **{k}**: {DESCRIBE[k]}" for k in names] + [""]
    out += view_lines(view, drops)
    if a.check_only:
        text = "\n".join(out) + "\n"
        print(text)
        print("checks passed; no account was run on a new market")
        return 0

    # 2. the lists: continuous accounts, each market alone, then FTMO
    for k in names[1:]:
        metrics[k] = [continuous(dates, inst[k], cont[b]) for b in (0, 1)]
    solo = {(k, b): alone(dates, k, x, cont[b])
            for k, x in {**four, **five}.items() for b in (0, 1)}
    if adjusted is not None:
        solo.update({(k + ADJ, b): alone(dates, k, x, cont[b])
                     for k, x in adjusted.items() for b in (0, 1)})
    say("continuous accounts done")
    ftmo.update(run([(kind, k, b, c) for kind in ("stats", "probe")
                     for k in names[1:] for b, c in cells]))
    for k in names:                                  # the two passes over the attempts agree
        for b, c in cells:
            r, pr = ftmo[("stats", k, b, c)], ftmo[("probe", k, b, c)]
            must((round(r["pe"] * pr["n"]), round(r["p18"] * pr["n"])) ==
                 (pr["pe"], pr["p18"]), "the probe and the statistics disagree", k, b, c)
    say("FTMO runs done")

    out += ["", "**Per trade** (continuous account; trades open at the end left out):", "",
            "| list | bound | trades | trades per year | TP1 before stop | P&L win rate | "
            "avg win (R) | avg loss (R) | payoff (R/trade) | avg first risk | median "
            "sessions held | most open at once | CAGR | max DD | payoff's standard error | "
            "largest total position (× balance) |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k in names:
        for b, bound in enumerate(BOUNDS):
            m = metrics[k][b]
            out.append(f"| {k} | {bound} | {trade_cells(m, years)} | ±{m['all']['se']:.3f} | "
                       f"{m['max_notional']:.2f} |")

    out += ["", "**Signals** (continuous account, pessimistic bound; 'free': a position "
            "whose stop is at or above its entry):", "",
            "| list | signals | planned for the next open | entered | not taken: market "
            "already held | … by a free position | not taken: slots full | … while a free "
            "position was open | … while every open position was free | sessions with two "
            "or more positions open |", "|---|---|---|---|---|---|---|---|---|---|"]
    out += [f"| {k} | {signal_cells(metrics[k][0])} |" for k in names]

    out += ["", "**Per market, inside each list** (continuous account, pessimistic bound; "
            "payoff ± its standard error):", "",
            "| list | market | trades | TP1 before stop | payoff (R/trade) | sum of R |",
            "|---|---|---|---|---|---|"]
    for k in names:
        for s, g in metrics[k][0]["markets"].items():
            cell = (f"{g['tp1']:.0%} | {g['exp']:+.3f} ± {g['se']:.3f}" if g["n"] > 1
                    else "– | –")
            out.append(f"| {k} | {s} | {g['n']} | {cell} | {g['total']:+.1f} |")

    out += ["", "**Each market alone** (the same rule and account with that one market; "
            "reported, not judged):", "",
            "| market | bound | trades | TP1 before stop | payoff (R/trade) | sum of R |",
            "|---|---|---|---|---|---|"]
    for (s, b), g in solo.items():
        cell = f"{g['tp1']:.0%} | {g['exp']:+.3f} ± {g['se']:.3f}" if g["n"] > 1 else "– | –"
        out.append(f"| {s} | {BOUNDS[b]} | {g['n']} | {cell} | {g['total']:+.1f} |")

    out += ["", "**FTMO** (cohorts by start date; columns as in "
            "`research/ftmo_slots_sizing.md`). Frozen: flat at the end with under 0.05% of "
            "room. Stuck: flat at the end and a new entry may risk under 0.5%. Attempts "
            "per pass counts a stuck attempt as lost.", "",
            "| list | period | P1 passed | both ≤6 mo | both ≤18 mo | both ≤36 mo | both, "
            "ever | breached | frozen | stuck | still trading | days to pass (p25 / median / "
            "p75) | main failure | funded 1y survival | funded 1y return | attempts per pass |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k in names:
        for b, bound in enumerate(BOUNDS):
            for c in COHORTS:
                out.append(f"| {k} {bound} | {c} | "
                           f"{ftmo_cells(ftmo[('stats', k, b, c)], ftmo[('probe', k, b, c)])} |")

    out += ["", "### Verdict against B0, by the pre-registered rule", ""]
    out += verdict_lines(ftmo, starts, JUDGED, judged=True)
    if adjusted is not None:
        out += ["", "### Sensitivity: the country funds adjusted for distributions", ""]
        out += verdict_lines(ftmo, starts, SENSITIVITY, judged=False)
    text = "\n".join(out) + "\n"
    if a.report is not None:
        a.report.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
