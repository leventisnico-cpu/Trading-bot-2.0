"""DAY-70 backtest (rules fixed in research/day_futures.md before running).

    python research/day_futures.py --data-dir DIR [--report reports/day_futures.md]

DIR holds spy_5m.csv and qqq_5m.csv (Astral 5-minute exports, UTC bar
starts, regular session only).
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

COST = 0.0001                       # 1 bp of price per side
FUT = {"SPY": ("MES", 50.0), "QQQ": ("MNQ", 81.2)}   # $ per $1 of proxy
LAST_ENTRY = "15:00"
FLAT_AT = "15:55"


def load(path: Path) -> pd.DataFrame:
    d = pd.read_csv(path)
    t = pd.to_datetime(d.timestamp, utc=True).dt.tz_convert("America/New_York")
    d = d.assign(t=t, day=t.dt.date, hm=t.dt.strftime("%H:%M"))
    d = d[(d.hm >= "09:30") & (d.hm <= "15:55")].reset_index(drop=True)
    return d


def rsi2(close: pd.Series) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=0.5, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=0.5, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


@dataclass
class Trade:
    sym: str
    day: object
    side: int          # +1 long, -1 short
    entry: float
    exit: float
    why: str

    @property
    def ret(self) -> float:       # net of costs, fraction of entry
        return self.side * (self.exit - self.entry) / self.entry - 2 * COST

    @property
    def usd(self) -> float:       # 1 micro contract
        mult = FUT[self.sym][1]
        return mult * (self.side * (self.exit - self.entry)
                       - COST * (self.entry + self.exit))


def run_exit(day: pd.DataFrame, i: int, side: int, entry: float,
             target: float, stop: float):
    """Walk bars i.. of one session; return (exit price, reason, last i)."""
    for j in range(i, len(day)):
        o, h, l = day.open.iat[j], day.high.iat[j], day.low.iat[j]
        if j > i:                                   # gap through at the open
            if side > 0 and o <= stop or side < 0 and o >= stop:
                return o, "stop", j
            if side > 0 and o >= target or side < 0 and o <= target:
                return o, "target", j
        hit_stop = l <= stop if side > 0 else h >= stop
        hit_tgt = h >= target if side > 0 else l <= target
        if hit_stop:                                # both -> stop (conservative)
            return stop, "stop", j
        if hit_tgt:
            return target, "target", j
        if day.hm.iat[j] >= FLAT_AT:
            return day.close.iat[j], "time", j
    return day.close.iat[-1], "time", len(day) - 1


def gap_fade(sym: str, d: pd.DataFrame, g_min: float):
    out, prev_close = [], None
    for day, g in d.groupby("day", sort=True):
        g = g.reset_index(drop=True)
        if prev_close is not None and len(g) > 2 and g.hm.iat[0] == "09:30":
            gap = g.open.iat[0] / prev_close - 1
            if g_min <= abs(gap) <= 0.01:
                side = -1 if gap > 0 else 1
                entry = g.open.iat[1]                     # next bar's open
                target = prev_close
                stop = entry - side * abs(gap) * prev_close
                if (target - entry) * side > 0:           # not already filled
                    px, why, _ = run_exit(g, 1, side, entry, target, stop)
                    out.append(Trade(sym, day, side, entry, px, why))
        prev_close = g.close.iat[-1]
    return out


def rsi_pullback(sym: str, d: pd.DataFrame, t: float):
    r = rsi2(d.close).to_numpy()
    out = []
    for day, g in d.groupby("day", sort=True):
        idx = g.index.to_numpy()
        g = g.reset_index(drop=True)
        day_open = g.open.iat[0]
        i = 0
        while i < len(g) - 1:
            hm = g.hm.iat[i]
            if "09:45" <= hm <= LAST_ENTRY:
                rv, c = r[idx[i]], g.close.iat[i]
                side = 1 if (rv < 10 and c > day_open) else (
                    -1 if (rv > 90 and c < day_open) else 0)
                if side:
                    entry = g.open.iat[i + 1]
                    target = entry * (1 + side * t)
                    stop = entry * (1 - side * 3 * t)
                    px, why, j = run_exit(g, i + 1, side, entry, target, stop)
                    out.append(Trade(sym, day, side, entry, px, why))
                    i = j + 1
                    continue
            i += 1
    return out


def rsi_trend(sym: str, d: pd.DataFrame, t: float):
    """R2: R, but longs only above / shorts only below the 20-session
    average of daily closes (as of the previous session)."""
    closes = d.groupby("day", sort=True).close.last()
    ma = closes.rolling(20).mean()
    regime = (closes > ma).astype(int) - (closes < ma).astype(int)
    allowed = regime.shift(1).where(ma.shift(1).notna(), 0)   # yesterday's
    return [x for x in rsi_pullback(sym, d, t) if allowed.get(x.day, 0) == x.side]


def stats(trades, n_days):
    if not trades:
        return dict(n=0, win=0, pf=0, net=0, per_day=0, dd=0, months_pos="0/0")
    usd = np.array([x.usd for x in trades])
    wins = usd > 0
    gp, gl = usd[wins].sum(), -usd[~wins].sum()
    eq = np.cumsum(usd)
    dd = float(np.max(np.maximum.accumulate(eq) - eq)) if len(eq) else 0.0
    m = pd.Series(usd, index=pd.to_datetime([str(x.day) for x in trades])).resample("ME").sum()
    return dict(n=len(trades), win=wins.mean(), pf=gp / gl if gl else float("inf"),
                net=usd.sum(), per_day=len(trades) / n_days, dd=dd,
                months_pos=f"{int((m > 0).sum())}/{len(m)}",
                avg_win=usd[wins].mean() if wins.any() else 0,
                avg_loss=-usd[~wins].mean() if (~wins).any() else 0)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True, type=Path)
    ap.add_argument("--report", type=Path)
    ap.add_argument("--round", type=int, default=1, choices=[1, 2])
    a = ap.parse_args(argv)
    data, sha = {}, {}
    for s in ("SPY", "QQQ"):
        p = a.data_dir / f"{s.lower()}_5m.csv"
        sha[s] = hashlib.sha256(p.read_bytes()).hexdigest()[:8]
        data[s] = load(p)
    days = sorted(set(data["SPY"].day) & set(data["QQQ"].day))
    cut = days[int(len(days) * 0.6)]
    periods = {"selection": (days[0], cut), "test": (cut, days[-1])}
    n_days = {"selection": sum(1 for x in days if x < cut),
              "test": sum(1 for x in days if x >= cut)}

    if a.round == 1:
        systems = {"G": ("g_min", [0.001, 0.002, 0.003], gap_fade),
                   "R": ("t", [0.001, 0.0015, 0.002, 0.003], rsi_pullback)}
    else:
        systems = {"R2": ("t", [0.001, 0.0015, 0.002], rsi_trend)}
    rows, results = [], {}
    for name, (pname, values, fn) in systems.items():
        for v in values:
            trades = [x for s in data for x in fn(s, data[s], v)]
            for per, (lo, hi) in periods.items():
                sel = [x for x in trades if (lo <= x.day < hi if per == "selection"
                                             else x.day >= lo)]
                st = stats(sel, n_days[per])
                results[(name, v, per)] = (st, sel)
                rows.append((name, f"{pname}={v * 100:.2f}%", per, st))

    # selection rule (pre-registered)
    choice = {}
    for name, (_, values, _) in systems.items():
        ok = [(results[(name, v, "selection")][0]["pf"], -v, v) for v in values
              if results[(name, v, "selection")][0]["win"] >= 0.70]
        if ok:
            choice[name] = max(ok)[2]
    chosen = None
    if choice:
        chosen = max(choice, key=lambda n: results[(n, choice[n], "selection")][0]["pf"])

    lines = [f"# DAY-70 results (round {a.round})", "",
             f"Data: Astral 5m, {days[0]} to {days[-1]} ({len(days)} sessions); "
             f"selection {days[0]} to {cut} ({n_days['selection']}), test {cut} to "
             f"{days[-1]} ({n_days['test']}). sha256 SPY `{sha['SPY']}…`, QQQ `{sha['QQQ']}…`. "
             "Costs 1 bp/side. P&L in $ for 1 MES (SPY) + 1 MNQ (QQQ) per signal.", "",
             "| system | parameter | period | trades | per day | win rate | PF | net $ | "
             "avg win $ | avg loss $ | max DD $ | months + |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, p, per, st in rows:
        lines.append(f"| {name} | {p} | {per} | {st['n']} | {st['per_day']:.2f} | "
                     f"{st['win']:.0%} | {st['pf']:.2f} | {st['net']:,.0f} | "
                     f"{st.get('avg_win', 0):,.0f} | {st.get('avg_loss', 0):,.0f} | "
                     f"{st['dd']:,.0f} | {st['months_pos']} |")
    lines.append("")
    if chosen is None:
        lines.append("**Selection:** no parameter of either system reached a 70% "
                     "win rate in the selection period → NO-GO.")
        verdict = "NO-GO"
    else:
        v = choice[chosen]
        st = results[(chosen, v, "test")][0]
        pos, tot = (int(x) for x in st["months_pos"].split("/"))
        checks = [("win rate ≥ 70%", st["win"] >= 0.70),
                  ("PF ≥ 1.2 and net > 0", st["pf"] >= 1.2 and st["net"] > 0),
                  ("≥ 1 trade per session", st["per_day"] >= 1.0),
                  ("≥ 6 profitable months", pos >= 6),
                  ("max DD < half of net", st["dd"] < 0.5 * st["net"])]
        verdict = "GO" if all(ok for _, ok in checks) else "NO-GO"
        lines.append(f"**Chosen in selection:** system {chosen}, parameter "
                     f"{v * 100:.2f}% (selection choices: "
                     + ", ".join(f"{k}={choice[k] * 100:.2f}%" for k in choice) + ").")
        lines.append("")
        lines.append("Test-period GO bar:")
        for label, ok in checks:
            lines.append(f"* {label}: {'PASS' if ok else 'FAIL'}")
        lines.append("")
        lines.append(f"**Verdict: {verdict}**")
    text = "\n".join(lines) + "\n"
    print(text)
    if a.report:
        a.report.write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
