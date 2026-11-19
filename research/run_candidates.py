#!/usr/bin/env python3
"""Run the pre-registered Order 5 candidates and write research/<name>.md.

    python research/run_candidates.py

Every candidate is a *monthly-decision* overlay on one instrument, tested
against buy-and-hold of that instrument with identical costs, on three
contiguous walk-forward folds plus the full sample. The pass/fail rule is
fixed in this file and printed in every note (same rule as
scripts/expectancy.py). Parameters are the canonical literature values;
this script has no grid and no tuning knob on purpose.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Sequence, Tuple

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "research"

START_CASH = 10_000.0
#: IBKR Pro fixed ($0.005/share, $1 min) plus one cent of slippage on a
#: ~$100-$700 ETF comes to roughly 0.02%-0.03% of traded value per side;
#: 0.03% is applied to every unit of turnover on both candidate and
#: benchmark (the benchmark pays it once, on the initial buy).
COST_PER_SIDE = 0.0003
FOLDS = 3
PASS_RULE = ("PASS only if final wealth beats buy-and-hold of the same "
             "instrument in >= 2 of 3 walk-forward folds AND on the full "
             "sample (identical costs, identical starting capital).")

UNIVERSE: Dict[str, Tuple[str, str]] = {
    # column -> (file, label)
    "SPY": ("prices_us.csv", "US large cap (SPY), 1999-2026"),
    "XUU.TO": ("prices_cad.csv", "CAD-listed US total market (XUU.TO), 2015-2026"),
    "XIC.TO": ("prices_cad.csv", "CAD-listed Canadian equity (XIC.TO), 2001-2026"),
}


def load(column: str) -> pd.Series:
    file, _ = UNIVERSE[column]
    df = pd.read_csv(REPO / "data" / file, index_col=0, parse_dates=True)
    s = df[column].dropna().astype(float)
    s.index = pd.DatetimeIndex(s.index)
    return s


# ------------------------------------------------------------ candidates

#: A candidate maps a daily close series to a daily *target weight* in
#: [0, 1], decided at month end from information available at that
#: close, applied from the next trading day (t+1, no lookahead).
Candidate = Callable[[pd.Series], pd.Series]


def month_end_flags(idx: pd.DatetimeIndex) -> pd.Series:
    """True on the last trading day of each month."""
    return pd.Series(idx.to_period("M"), index=idx).ne(
        pd.Series(idx.to_period("M"), index=idx).shift(-1)).fillna(True)


def hold_monthly(daily_signal: pd.Series) -> pd.Series:
    """Sample a daily decision at month ends and hold it until the next."""
    flags = month_end_flags(daily_signal.index)
    w = daily_signal.where(flags).ffill().fillna(0.0)
    return w.shift(1).fillna(0.0)  # decided at close, applied next day


def sma200_filter(close: pd.Series) -> pd.Series:
    sma = close.rolling(200).mean()
    signal = (close > sma).astype(float).where(sma.notna(), 0.0)
    return hold_monthly(signal)


def momentum_12_1(close: pd.Series) -> pd.Series:
    """12-1 month momentum: at the last trading day of month M, invested
    for month M+1 iff close(M-1) / close(M-12) - 1 > 0 — the return over
    the eleven months ending one month ago, skipping the most recent
    month (T-bill proxy: 0% cash; see the note)."""
    me_days = close.index[month_end_flags(close.index).values]
    monthly = close.loc[me_days]
    mom = monthly.shift(1) / monthly.shift(12) - 1.0
    signal_m = (mom > 0).astype(float).where(mom.notna(), 0.0)
    signal = signal_m.reindex(close.index, method="ffill").fillna(0.0)
    return hold_monthly(signal)


def vol_target(close: pd.Series, target: float = 0.10,
               window: int = 60) -> pd.Series:
    rets = close.pct_change()
    realized = rets.rolling(window).std() * np.sqrt(252)
    w = (target / realized).clip(upper=1.0).where(realized.notna(), 0.0)
    return hold_monthly(w)


CANDIDATES: Dict[str, Tuple[str, Candidate, str]] = {
    "sma200_trend_filter": (
        "200-day SMA trend filter, monthly",
        sma200_filter,
        "At each month end, hold the instrument if its close is above its "
        "200-day simple moving average, otherwise cash at 0%; no other "
        "parameter. Claim under test: the filter's crash avoidance is worth "
        "more than the whipsaws and the time out of the market."),
    "momentum_12_1_vs_tbills": (
        "12-1 month time-series momentum vs T-bills, monthly",
        momentum_12_1,
        "At each month end, hold the instrument if its return from 12 "
        "months ago to 1 month ago is positive, else cash. T-bills are "
        "proxied by 0% (no T-bill series in the repo); this *favors* the "
        "candidate relative to the benchmark by nothing and understates "
        "its cash return by ~1-2%/yr on average, so a PASS here is "
        "conservative and a FAIL is decisive only if the gap exceeds that. "
        "The engine/ dual-momentum result already said no on CAD; this "
        "confirms on US."),
    "vol_target_buy_and_hold": (
        "Volatility-target sizing of buy-and-hold (10% target, no timing)",
        vol_target,
        "At each month end, set exposure = min(1, 10% / realized 60-day "
        "annualized vol); never above 100% (TFSA: no margin), the rest in "
        "cash at 0%. Constant-vol, no directional view. Claim under test: "
        "cutting exposure in high-vol regimes raises terminal wealth net of "
        "costs, not just smooths the path."),
}


#: Appended to a note after the candidate went through Order 3's gate
#: (scripts/expectancy.py), so regenerating the note keeps the outcome.
FOLLOW_UP: Dict[str, str] = {
    "momentum_12_1_vs_tbills": """## Order 3 follow-up (the gate that counts)

The SPY PASS above earned the candidate an implementation as
`mini_prop_os/strategy/tsmom_12_1.py` and a run through the production
gate: `python scripts/expectancy.py --strategy tsmom_12_1` (real risk
gate + OMS + simulated broker, a 10-share lot, IBKR $1 minimum commission,
one tick of slippage, entry on the bar after the month-boundary decision).
Result (`reports/minipropos_expectancy_spy.md`): beats buy-and-hold of
the same lot in **1/3 folds, full sample no → NOT DEPLOYABLE**.

Why the two disagree: the research model is constant-dollar (a 100%
weight that compounds), the gate is constant-share (one lot in or out),
and the gate pays per-order costs and enters one bar later. The research
edge is ~4% of terminal wealth over 27 years; those differences are of
the same order, so the sign flips. An edge that thin is not robust to the
modelling choice, let alone to live execution. Marked `DEPLOYABLE: no`.
The engine/ verdict on CAD (dual momentum loses to DCA) stands, and this
note adds: on US data the 12-1 filter is at best a coin toss net of
costs, not a deployable improvement over holding.
""",
}


# --------------------------------------------------------------- engine

@dataclass
class Leg:
    label: str
    start: pd.Timestamp
    end: pd.Timestamp
    final: float
    cagr: float
    max_dd: float
    bh_final: float
    bh_cagr: float
    bh_max_dd: float
    turnover: float
    time_invested: float

    @property
    def beats(self) -> bool:
        return self.final > self.bh_final


def simulate(close: pd.Series, weight: pd.Series) -> Tuple[pd.Series, float]:
    """Daily equity of a weight path with turnover costs; returns (equity,
    total turnover). Weight applies to the day's return; costs are charged
    on |Δw| at each change."""
    rets = close.pct_change().fillna(0.0)
    w = weight.reindex(close.index).fillna(0.0).clip(0.0, 1.0)
    dw = w.diff().abs().fillna(w.iloc[0])
    growth = 1.0 + w * rets - dw * COST_PER_SIDE
    equity = START_CASH * growth.cumprod()
    return equity, float(dw.sum())


def cagr(final: float, start: pd.Timestamp, end: pd.Timestamp) -> float:
    years = max((end - start).days / 365.25, 1e-9)
    return (final / START_CASH) ** (1 / years) - 1


def max_drawdown(eq: pd.Series) -> float:
    return float(((eq.cummax() - eq) / eq.cummax()).max())


def run_leg(label: str, close: pd.Series, cand: Candidate) -> Leg:
    w = cand(close)
    eq, turnover = simulate(close, w)
    bh = pd.Series(1.0, index=close.index)
    bh_eq, _ = simulate(close, bh)
    return Leg(label, close.index[0], close.index[-1],
               float(eq.iloc[-1]), cagr(float(eq.iloc[-1]), close.index[0],
                                         close.index[-1]),
               max_drawdown(eq), float(bh_eq.iloc[-1]),
               cagr(float(bh_eq.iloc[-1]), close.index[0], close.index[-1]),
               max_drawdown(bh_eq), turnover,
               float((w.reindex(close.index).fillna(0.0) > 0).mean()))


def evaluate(close: pd.Series, cand: Candidate) -> Tuple[List[Leg], bool, int]:
    """Walk-forward: each fold re-computes indicators inside the fold
    (a real deployment starts with no history it has not yet seen)."""
    n = len(close)
    edges = [round(i * n / FOLDS) for i in range(FOLDS + 1)]
    legs = [run_leg(f"fold {k + 1}/{FOLDS}", close.iloc[edges[k]:edges[k + 1]],
                    cand) for k in range(FOLDS)]
    full = run_leg("full sample", close, cand)
    wins = sum(1 for leg in legs if leg.beats)
    passed = wins >= 2 and full.beats
    return legs + [full], passed, wins


# ------------------------------------------------------------- reporting

def table(legs: Sequence[Leg]) -> List[str]:
    out = ["| window | dates | final $ | CAGR | maxDD | time invested | "
           "turnover | B&H final $ | B&H CAGR | B&H maxDD | beats B&H |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    for leg in legs:
        out.append(
            f"| {leg.label} | {leg.start:%Y-%m-%d}–{leg.end:%Y-%m-%d} | "
            f"{leg.final:,.0f} | {leg.cagr:.1%} | {leg.max_dd:.1%} | "
            f"{leg.time_invested:.0%} | {leg.turnover:.1f}x | "
            f"{leg.bh_final:,.0f} | {leg.bh_cagr:.1%} | {leg.bh_max_dd:.1%} | "
            f"{'YES' if leg.beats else 'no'} |")
    return out


def write_note(key: str, title: str, cand: Candidate, hypothesis: str) -> bool:
    sections: List[str] = []
    overall: List[str] = []
    any_pass = False
    for column, (file, label) in UNIVERSE.items():
        close = load(column)
        legs, passed, wins = evaluate(close, cand)
        any_pass = any_pass or passed
        overall.append(f"- **{column}** ({label}): beats B&H in {wins}/{FOLDS} "
                       f"folds, full sample {'YES' if legs[-1].beats else 'no'} "
                       f"→ **{'PASS' if passed else 'FAIL'}**")
        sections += [f"### {column} — {label}", "", *table(legs), ""]
    note = f"""# Research note — {title}

Generated by `python research/run_candidates.py` on
{datetime.now(timezone.utc):%Y-%m-%d}. Pre-registered before the numbers
were seen; parameters are the canonical literature values and there is
no grid. **This note is kept whether it passes or fails.**

## Hypothesis
{hypothesis}

## Universe
{chr(10).join(f"- `{c}`: {UNIVERSE[c][1]} (`data/{UNIVERSE[c][0]}`)" for c in UNIVERSE)}

## Data source
Yahoo Finance adjusted daily closes (total-return approximation) as
shipped in `data/`; fetched {pd.read_json(REPO / 'data' / 'meta.json', typ='series')['fetched']}.
Decisions use the month-end close and apply from the next trading day
(t+1); indicators are recomputed inside each fold from that fold's own
history, so a fold starts un-invested until its lookback fills.

## Cost model
{COST_PER_SIDE:.2%} of traded value per side on every unit of turnover
(IBKR Pro fixed $0.005/share, $1 minimum, plus one cent of slippage on a
$100–$700 ETF), charged identically to the candidate and the benchmark.
Cash earns 0%.

## Walk-forward folds
{FOLDS} contiguous, non-overlapping, equal-length folds of each
instrument's history, plus the full sample.

## Benchmark
Buy-and-hold of the same instrument, same ${START_CASH:,.0f}, same costs
(paid once on the initial buy).

## Pre-registered pass/fail
{PASS_RULE}

## Result
{chr(10).join(overall)}

{chr(10).join(sections)}
Verdict: **{'PASS on at least one instrument — eligible for Order 3' if any_pass else 'FAIL on every instrument — not eligible for Order 3'}**.

{FOLLOW_UP.get(key, "")}"""
    (OUT / f"{key}.md").write_text(note)
    print(f"{key}: {'PASS' if any_pass else 'FAIL'}")
    for line in overall:
        print("   ", line)
    return any_pass


def main() -> int:
    OUT.mkdir(exist_ok=True)
    print(f"RULE: {PASS_RULE}\n")
    for key, (title, cand, hyp) in CANDIDATES.items():
        write_note(key, title, cand, hyp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
