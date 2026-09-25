#!/usr/bin/env python3
"""Expectancy gate: does a strategy beat holding the same lot?

    python scripts/expectancy.py --strategy adaptive_ema --symbol SPY \\
        --data data/prices_us.csv --folds 3

Replays daily adjusted closes through the *production* pipeline
(strategy -> RiskGuardrails -> OMS -> simulated broker, see
``mini_prop_os/sim.py``) and compares the strategy's final equity with
buy-and-hold of the same lot, bought at the first fillable open of the
same window and never touched. Costs on both sides: IBKR Pro fixed
commission ($0.005/share, $1.00 minimum per order) and one tick of
adverse slippage per fill.

GATE RULE (hard-coded, printed on every run):

    DEPLOYABLE only if the strategy's final equity beats buy-and-hold of
    the same lot in >= 2 of 3 walk-forward folds AND on the full sample.

Exit code 0 = deployable, 1 = not. ``--all`` runs every registered
strategy and exits 1 if any strategy whose module docstring says
``DEPLOYABLE: yes`` fails the gate (this is what CI runs), or if a
strategy module exists that the registry does not know.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from mini_prop_os.core.config import RiskConfig  # noqa: E402
from mini_prop_os.risk.guardrails import RiskGuardrails  # noqa: E402
from mini_prop_os.sim import (HistoricalSession, SimConfig,  # noqa: E402
                              bars_from_closes, run_session)
from mini_prop_os.strategy.registry import (  # noqa: E402
    get_spec, is_deployable, strategy_names, unregistered_strategy_modules)

GATE_RULE = ("DEPLOYABLE only if final equity beats buy-and-hold of the "
             "same lot in >= 2 of 3 walk-forward folds AND on the full "
             "sample.")
MIN_FOLD_WINS = 2
IBKR_PER_SHARE = 0.005
IBKR_MIN_PER_ORDER = 1.00
TICK = 0.01


# ------------------------------------------------------------------ data

def load_closes(path: Path, symbol: str) -> Tuple[List[datetime], List[float]]:
    dates: List[datetime] = []
    closes: List[float] = []
    with open(path) as fh:
        reader = csv.DictReader(fh)
        if symbol not in (reader.fieldnames or []):
            raise SystemExit(f"{symbol} not in {path}: {reader.fieldnames}")
        for row in reader:
            v = row.get(symbol, "")
            if not v:
                continue
            dates.append(datetime.strptime(row["Date"], "%Y-%m-%d")
                         .replace(tzinfo=timezone.utc))
            closes.append(float(v))
    if len(closes) < 300:
        raise SystemExit(f"only {len(closes)} rows for {symbol}")
    return dates, closes


def fold_slices(n: int, folds: int) -> List[Tuple[int, int]]:
    """Contiguous, equal, non-overlapping index ranges (walk-forward)."""
    edges = [round(i * n / folds) for i in range(folds + 1)]
    return [(edges[i], edges[i + 1]) for i in range(folds)]


# --------------------------------------------------------------- metrics

@dataclass
class Leg:
    label: str
    start: datetime
    end: datetime
    bars: int
    final: float
    cagr: float
    max_dd: float
    max_dd_pct: float
    trips: int
    win_rate: Optional[float]
    bh_final: float
    bh_cagr: float
    bh_max_dd_pct: float
    kill_tripped: bool

    @property
    def beats(self) -> bool:
        return self.final > self.bh_final


def cagr(initial: float, final: float, start: datetime, end: datetime) -> float:
    years = max((end - start).days / 365.25, 1e-9)
    if initial <= 0 or final <= 0:
        return float("nan")
    return (final / initial) ** (1 / years) - 1


def drawdown_pct(curve: Sequence[float]) -> float:
    peak, dd = -math.inf, 0.0
    for eq in curve:
        peak = max(peak, eq)
        if peak > 0:
            dd = max(dd, (peak - eq) / peak)
    return dd


def buy_and_hold(closes: Sequence[float], lot: int, cash: float,
                 commission_per_share: float) -> Tuple[float, List[float]]:
    """Buy ``lot`` at the first fillable open (= close[0], 1 tick adverse)
    and hold to the end. Returns (final equity, mark-to-market curve)."""
    fill = closes[0] + TICK
    cash_left = cash - lot * fill - lot * commission_per_share
    curve = [cash_left + lot * c for c in closes]
    return curve[-1], curve


def run_leg(label: str, strategy_name: str, symbol: str,
            dates: Sequence[datetime], closes: Sequence[float], lot: int,
            cash: float) -> Leg:
    commission = max(IBKR_PER_SHARE, IBKR_MIN_PER_ORDER / lot)
    sim_cfg = SimConfig(multiplier=1.0, tick_size=TICK, slippage_ticks=1,
                        commission_per_unit=commission, initial_cash=cash,
                        split_fills=False)
    # Measurement, not production: caps wide enough never to bind, so
    # the number reflects the strategy, not a risk setting. The per-order
    # cap still equals the lot (the strategy must not size above it).
    risk = RiskGuardrails(RiskConfig(
        max_position_shares=10_000_000, max_position_notional=1e12,
        max_order_quantity=lot, max_gross_notional=1e12,
        max_daily_loss=1e12, max_daily_loss_pct=0.999))
    strategy = get_spec(strategy_name).factory(symbol, lot, 1.0)
    session = HistoricalSession(strategy, risk, sim_cfg)
    bars = bars_from_closes(list(closes), symbol, timestamps=list(dates))
    res = run_session(session, bars)
    curve = [eq for _, eq in res.equity_curve]
    bh_final, bh_curve = buy_and_hold(closes, lot, cash, commission)
    return Leg(
        label=label, start=dates[0], end=dates[-1], bars=res.bars,
        final=res.final_equity,
        cagr=cagr(cash, res.final_equity, dates[0], dates[-1]),
        max_dd=res.max_drawdown, max_dd_pct=drawdown_pct(curve),
        trips=len(res.round_trips), win_rate=res.win_rate,
        bh_final=bh_final, bh_cagr=cagr(cash, bh_final, dates[0], dates[-1]),
        bh_max_dd_pct=drawdown_pct(bh_curve),
        kill_tripped=res.kill_switch_tripped)


@dataclass
class Verdict:
    strategy: str
    legs: List[Leg]           # folds..., then full sample last
    deployable: bool
    fold_wins: int
    full_beats: bool


def evaluate(strategy_name: str, symbol: str, dates: Sequence[datetime],
             closes: Sequence[float], folds: int, lot: int,
             cash: float) -> Verdict:
    legs: List[Leg] = []
    for k, (a, b) in enumerate(fold_slices(len(closes), folds), start=1):
        legs.append(run_leg(f"fold {k}/{folds}", strategy_name, symbol,
                            dates[a:b], closes[a:b], lot, cash))
    full = run_leg("full sample", strategy_name, symbol, dates, closes,
                   lot, cash)
    fold_wins = sum(1 for leg in legs if leg.beats)
    legs.append(full)
    needed = MIN_FOLD_WINS if folds == 3 else math.ceil(2 * folds / 3)
    return Verdict(strategy_name, legs, fold_wins >= needed and full.beats,
                   fold_wins, full.beats)


# -------------------------------------------------------------- reporting

def fmt_pct(x: Optional[float]) -> str:
    return "-" if x is None or (isinstance(x, float) and math.isnan(x)) \
        else f"{x:.1%}"


def table(v: Verdict) -> List[str]:
    lines = [
        "| window | dates | bars | final $ | CAGR | maxDD | trips | win% "
        "| B&H final $ | B&H CAGR | B&H maxDD | beats B&H |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for leg in v.legs:
        lines.append(
            f"| {leg.label} | {leg.start:%Y-%m-%d}–{leg.end:%Y-%m-%d} | "
            f"{leg.bars} | {leg.final:,.0f} | {fmt_pct(leg.cagr)} | "
            f"{leg.max_dd:,.0f} ({fmt_pct(leg.max_dd_pct)}) | {leg.trips} | "
            f"{fmt_pct(leg.win_rate)} | {leg.bh_final:,.0f} | "
            f"{fmt_pct(leg.bh_cagr)} | {fmt_pct(leg.bh_max_dd_pct)} | "
            f"{'YES' if leg.beats else 'no'}"
            f"{' (kill switch)' if leg.kill_tripped else ''} |")
    return lines


def render(v: Verdict, symbol: str, lot: int, cash: float,
           data: Path, marked: Optional[bool]) -> str:
    n_folds = len(v.legs) - 1
    out = [
        f"## {v.strategy} on {symbol} (lot {lot}, ${cash:,.0f} start)",
        "",
        f"Data: `{data.relative_to(REPO) if data.is_relative_to(REPO) else data}`"
        f" · {v.legs[-1].start:%Y-%m-%d} → {v.legs[-1].end:%Y-%m-%d} · "
        f"{n_folds} walk-forward folds · costs: IBKR ${IBKR_PER_SHARE}/share "
        f"(min ${IBKR_MIN_PER_ORDER:.2f}/order) + {TICK} adverse slippage "
        "per fill, both sides.",
        "",
        *table(v),
        "",
        f"Gate: {GATE_RULE}",
        f"Result: beats B&H in {v.fold_wins}/{n_folds} folds, full sample "
        f"{'YES' if v.full_beats else 'no'} → "
        f"**{'DEPLOYABLE' if v.deployable else 'NOT DEPLOYABLE'}**"
        + ("" if marked is None else
           f" (docstring marks it DEPLOYABLE: {'yes' if marked else 'no'}"
           f"{' — MISMATCH' if marked and not v.deployable else ''})"),
    ]
    return "\n".join(out)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--strategy", default=None,
                    help=f"one of {list(strategy_names())}")
    ap.add_argument("--all", action="store_true",
                    help="run every registered strategy; fail if one marked "
                         "DEPLOYABLE: yes does not pass (CI mode)")
    ap.add_argument("--symbol", default="SPY")
    ap.add_argument("--data", type=Path, default=REPO / "data/prices_us.csv")
    ap.add_argument("--folds", type=int, default=3)
    ap.add_argument("--lot", type=int, default=10, help="shares per lot")
    ap.add_argument("--cash", type=float, default=10_000.0)
    ap.add_argument("--report", type=Path, default=None,
                    help="write a markdown report here")
    args = ap.parse_args(argv)
    if args.folds < 2:
        ap.error("--folds must be >= 2")
    if not args.all and not args.strategy:
        ap.error("--strategy NAME or --all")

    dates, closes = load_closes(args.data, args.symbol)
    names = list(strategy_names()) if args.all else [args.strategy]
    print(f"GATE: {GATE_RULE}\n")
    sections: List[str] = []
    rc = 0
    for name in names:
        marked = is_deployable(name)
        v = evaluate(name, args.symbol, dates, closes, args.folds, args.lot,
                     args.cash)
        section = render(v, args.symbol, args.lot, args.cash, args.data,
                         marked)
        sections.append(section)
        print(section, "\n")
        if args.all:
            if marked and not v.deployable:
                print(f"FAIL: {name} is marked DEPLOYABLE: yes but does not "
                      f"pass the gate")
                rc = 1
        elif not v.deployable:
            rc = 1
    if args.all:
        stray = unregistered_strategy_modules()
        if stray:
            print(f"FAIL: strategy modules not in the registry (every "
                  f"strategy must face the gate): {list(stray)}")
            rc = 1
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            f"# Expectancy gate — {args.symbol}\n\n"
            f"Generated by `python scripts/expectancy.py "
            f"{'--all' if args.all else '--strategy ' + names[0]} "
            f"--symbol {args.symbol} --folds {args.folds} --lot {args.lot}` "
            f"on {datetime.now(timezone.utc):%Y-%m-%d}.\n\n"
            f"**Gate:** {GATE_RULE}\n\n"
            + "\n\n".join(sections) + "\n")
        print(f"report: {args.report}")
    print("exit", rc, "(0 = deployable / gate consistent, 1 = not)")
    return rc


if __name__ == "__main__":
    sys.exit(main())
