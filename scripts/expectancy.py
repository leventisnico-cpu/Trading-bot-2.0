#!/usr/bin/env python3
"""Expectancy gate: does a strategy earn its deployment against buy-and-hold?

    python scripts/expectancy.py --strategy air3_trend --symbol SMH \\
        --data data/prices_us.csv --folds 3

Replays daily closes through the *production* pipeline
(strategy -> RiskGuardrails -> OMS -> simulated broker, see
``mini_prop_os/sim.py``) and compares the strategy with buy-and-hold of
the same lot, bought at the first fillable open of the same window and
never touched. Buy-and-hold's lot is the **full-exposure lot**: as many
shares as 95% of the starting cash buys at the window's first close. The
strategy starts with the same lot and is re-sized before every entry to
95% of its *current* equity (``CompoundingLot``), so both sides are ~95%
invested whenever they are in the market. ``--lot N`` forces one fixed
lot on both sides instead. Costs on both sides: IBKR Pro fixed
commission ($0.005/share, $1.00 minimum per order) and one tick of
adverse slippage per fill.

GATE RULE (hard-coded, printed on every run):

    DEPLOYABLE only if, in >= 2 of 3 walk-forward folds AND on the full
    sample, the strategy either (1) ends with more equity than buy-and-hold
    of the same lot, or (2) earns more per dollar of maximum drawdown than
    buy-and-hold while keeping at least half of buy-and-hold's gain.

Rule (1) is the original law: beat the market. Rule (2) admits a rule
that deliberately gives up part of a bull market to be in cash through
bear markets, which can never pass (1) by construction; it must still
pay for that with a better return per unit of drawdown and must not
dilute the gain below half. A strategy that merely sits in cash earns a
negative ratio (costs, no gain) and fails both.

Exit code 0 = deployable, 1 = not. ``--all`` runs every registered
strategy on ``--symbol`` and exits 1 if any strategy whose module
docstring says ``DEPLOYABLE: yes`` fails the gate (this is what CI runs),
or if a strategy module exists that the registry does not know.
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

GATE_RULE = ("DEPLOYABLE only if, in >= 2 of 3 walk-forward folds AND on the "
             "full sample, the strategy either (1) ends with more equity "
             "than buy-and-hold of the same lot, or (2) earns more per "
             "dollar of maximum drawdown than buy-and-hold while keeping at "
             "least half of buy-and-hold's gain.")
MIN_FOLD_WINS = 2
IBKR_PER_SHARE = 0.005
IBKR_MIN_PER_ORDER = 1.00
TICK = 0.01
#: Fraction of starting cash the full-exposure lot commits.
EXPOSURE = 0.95
#: Rule (2): the strategy must keep at least this share of B&H's gain
#: (only binds in windows where buy-and-hold gained).
RISK_SHARE = 0.5
#: Rule (2): drawdown floor (fraction of cash) so a tiny drawdown cannot
#: turn a tiny gain into an infinite ratio.
DD_FLOOR = 0.001


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


def lot_for(lot: int, closes: Sequence[float], cash: float) -> int:
    """``lot`` if forced (> 0), else the full-exposure lot: the shares
    ``EXPOSURE * cash`` buys at the window's first fillable price."""
    if lot > 0:
        return lot
    return max(1, int((EXPOSURE * cash) // (closes[0] + TICK)))


def exposure_lot(equity: float, close: float) -> int:
    """Shares ``EXPOSURE`` of ``equity`` buys at ``close`` plus one tick."""
    return max(1, int((EXPOSURE * equity) // (close + TICK)))


#: Strategy attributes that hold the per-entry lot, in lookup order.
LOT_ATTRS = ("order_quantity", "base_quantity")


class CompoundingLot:
    """Per-entry re-sizing for the full-exposure measurement.

    Holding a lot fixed at the window's first close means a strategy that
    is in cash for a bear market re-enters with the same share count it
    left with, while buy-and-hold's dollar exposure has grown with the
    price. Both sides should be ~95% invested whenever they are in the
    market. So before every bar on which the strategy is flat, its lot is
    set to the shares ``EXPOSURE`` of the account's *current* equity buys
    at that bar's close. Once in, the lot is untouched until it is flat
    again. This is how the Astral deployment sizes (95% of equity per
    entry) and how the bot is meant to run live.

    Wraps the strategy for the session only: ``on_bar``, ``on_own_fill``
    and ``strategy_id`` are what ``HistoricalSession`` touches; everything
    else is delegated.
    """

    def __init__(self, inner, equity_at) -> None:
        attr = next((a for a in LOT_ATTRS if hasattr(inner, a)), None)
        if attr is None:
            raise ValueError(f"{type(inner).__name__} has no lot attribute "
                             f"({', '.join(LOT_ATTRS)})")
        self._inner = inner
        self._attr = attr
        self._equity_at = equity_at
        self.lots: List[int] = []

    def __getattr__(self, name):
        return getattr(self._inner, name)

    @property
    def strategy_id(self) -> str:
        return self._inner.strategy_id

    def on_own_fill(self, signed_quantity: int, price: float) -> None:
        self._inner.on_own_fill(signed_quantity, price)

    def on_bar(self, bar):
        if self._inner.position == 0 and bar.close > 0:
            lot = exposure_lot(self._equity_at(bar.close), bar.close)
            setattr(self._inner, self._attr, lot)
        intents = self._inner.on_bar(bar)
        if intents and self._inner.position == 0:
            self.lots.append(getattr(self._inner, self._attr))
        return intents


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
    cash: float = 0.0
    final_shares: int = 0
    lot: int = 0
    #: Rule (2) inputs: gain and max drawdown in currency, both sides.
    gain: Optional[float] = None
    bh_gain: Optional[float] = None
    bh_max_dd: Optional[float] = None

    @property
    def beats(self) -> bool:
        """Rule (1): more final equity than buy-and-hold."""
        return self.final > self.bh_final

    @property
    def ratio(self) -> Optional[float]:
        if self.gain is None:
            return None
        return self.gain / max(self.max_dd, DD_FLOOR * self.cash)

    @property
    def bh_ratio(self) -> Optional[float]:
        if self.bh_gain is None or self.bh_max_dd is None:
            return None
        return self.bh_gain / max(self.bh_max_dd, DD_FLOOR * self.cash)

    @property
    def beats_risk_adjusted(self) -> bool:
        """Rule (2): better gain per dollar of drawdown than buy-and-hold,
        keeping at least ``RISK_SHARE`` of buy-and-hold's gain when it
        gained."""
        if self.ratio is None or self.bh_ratio is None:
            return False
        assert self.gain is not None and self.bh_gain is not None
        keeps_share = self.bh_gain <= 0 or self.gain >= RISK_SHARE * self.bh_gain
        return self.ratio > self.bh_ratio and keeps_share

    @property
    def passes(self) -> bool:
        return self.beats or self.beats_risk_adjusted

    @property
    def verdict(self) -> str:
        if self.beats:
            return "YES (1)"
        if self.beats_risk_adjusted:
            return "YES (2)"
        return "no"


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


def drawdown_abs(curve: Sequence[float]) -> float:
    peak, dd = -math.inf, 0.0
    for eq in curve:
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return dd


def buy_and_hold(closes: Sequence[float], lot: int, cash: float,
                 commission_per_share: float) -> Tuple[float, List[float]]:
    """Buy ``lot`` at the first fillable open (= close[0], 1 tick adverse)
    and hold to the end. Returns (final equity, mark-to-market curve)."""
    fill = closes[0] + TICK
    cash_left = cash - lot * fill - lot * commission_per_share
    curve = [cash_left + lot * c for c in closes]
    return curve[-1], curve


def funding_for(strategy_name: str, closes: Sequence[float], lot: int,
                cash: float) -> float:
    """Starting cash for a leg. Lot-in/lot-out strategies get ``cash``.
    An accumulating strategy (never sells) is funded for one lot per
    week at the window's highest price, so no buy ever fails for lack
    of cash and the comparison is between exposures, not budgets."""
    if not get_spec(strategy_name).accumulates:
        return cash
    weeks = len(closes) / 5 + 1
    return max(cash, lot * max(closes) * weeks)


def run_leg(label: str, strategy_name: str, symbol: str,
            dates: Sequence[datetime], closes: Sequence[float], lot: int,
            cash: float) -> Leg:
    spec = get_spec(strategy_name)
    # Full-exposure mode re-sizes every entry to current equity; a forced
    # lot (--lot N) and accumulating strategies keep one fixed lot.
    compounding = lot <= 0 and not spec.accumulates
    lot = lot_for(lot, closes, cash)
    commission = max(IBKR_PER_SHARE, IBKR_MIN_PER_ORDER / lot)
    cash = funding_for(strategy_name, closes, lot, cash)
    sim_cfg = SimConfig(multiplier=1.0, tick_size=TICK, slippage_ticks=1,
                        commission_per_unit=commission, initial_cash=cash,
                        split_fills=False)
    # Measurement, not production: caps wide enough never to bind, so
    # the number reflects the strategy, not a risk setting. With a fixed
    # lot the per-order cap equals the lot (the strategy must not size
    # above it); when compounding the lot changes per entry, so the cap is
    # as wide as the position cap and the strategy's own sizing governs.
    order_cap = 10_000_000 if compounding else lot
    risk = RiskGuardrails(RiskConfig(
        max_position_shares=10_000_000, max_position_notional=1e12,
        max_order_quantity=order_cap, max_gross_notional=1e12,
        max_daily_loss=1e12, max_daily_loss_pct=0.999))
    strategy = spec.factory(symbol, lot, 1.0)
    session = HistoricalSession(strategy, risk, sim_cfg)
    if compounding:
        session.strategy = CompoundingLot(strategy, session._equity)
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
        kill_tripped=res.kill_switch_tripped, cash=cash,
        final_shares=res.final_position, lot=lot,
        gain=res.final_equity - cash, bh_gain=bh_final - cash,
        bh_max_dd=drawdown_abs(bh_curve))


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
    fold_wins = sum(1 for leg in legs if leg.passes)
    legs.append(full)
    needed = MIN_FOLD_WINS if folds == 3 else math.ceil(2 * folds / 3)
    return Verdict(strategy_name, legs, fold_wins >= needed and full.passes,
                   fold_wins, full.passes)


# -------------------------------------------------------------- reporting

def fmt_pct(x: Optional[float]) -> str:
    return "-" if x is None or (isinstance(x, float) and math.isnan(x)) \
        else f"{x:.1%}"


def fmt_ratio(x: Optional[float]) -> str:
    return "-" if x is None else f"{x:.2f}"


def table(v: Verdict) -> List[str]:
    lines = [
        "| window | dates | lot | final $ | CAGR | maxDD | gain/DD | trips "
        "| win% | B&H final $ | B&H CAGR | B&H maxDD | B&H gain/DD | passes |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for leg in v.legs:
        lines.append(
            f"| {leg.label} | {leg.start:%Y-%m-%d}–{leg.end:%Y-%m-%d} | "
            f"{leg.lot} | {leg.final:,.0f} | {fmt_pct(leg.cagr)} | "
            f"{leg.max_dd:,.0f} ({fmt_pct(leg.max_dd_pct)}) | "
            f"{fmt_ratio(leg.ratio)} | {leg.trips} | "
            f"{fmt_pct(leg.win_rate)} | {leg.bh_final:,.0f} | "
            f"{fmt_pct(leg.bh_cagr)} | "
            f"{leg.bh_max_dd or 0:,.0f} ({fmt_pct(leg.bh_max_dd_pct)}) | "
            f"{fmt_ratio(leg.bh_ratio)} | {leg.verdict}"
            f"{' (kill switch)' if leg.kill_tripped else ''} |")
    return lines


def exposure_note(v: Verdict) -> List[str]:
    """For accumulating strategies, say what the gate is measuring."""
    if not get_spec(v.strategy).accumulates:
        return []
    full = v.legs[-1]
    return [
        "",
        f"Note: {v.strategy} never sells, so the account was funded with "
        f"${full.cash:,.0f} (one lot per week at the window high) and "
        f"ended holding {full.final_shares:,} shares versus the benchmark's "
        f"one lot. Beating buy-and-hold here means accumulated exposure "
        f"outperformed idle cash — it is not evidence of timing skill, "
        f"and it loses in any window where the market ends lower than "
        f"the strategy's average cost.",
    ]


def render(v: Verdict, symbol: str, lot: int, cash: float,
           data: Path, marked: Optional[bool]) -> str:
    n_folds = len(v.legs) - 1
    lot_note = (f"{EXPOSURE:.0%} of equity per entry; lot column = B&H's "
                f"lot at the window's first close" if lot <= 0
                else f"fixed lot {lot}")
    out = [
        f"## {v.strategy} on {symbol} ({lot_note})",
        "",
        f"Data: `{data.relative_to(REPO) if data.is_relative_to(REPO) else data}`"
        f" · {v.legs[-1].start:%Y-%m-%d} → {v.legs[-1].end:%Y-%m-%d} · "
        f"{n_folds} walk-forward folds · costs: IBKR ${IBKR_PER_SHARE}/share "
        f"(min ${IBKR_MIN_PER_ORDER:.2f}/order) + {TICK} adverse slippage "
        "per fill, both sides. gain/DD = (final − start) / max drawdown in "
        "dollars; passes = YES (1) more equity than B&H, YES (2) better "
        f"gain/DD than B&H while keeping ≥ {RISK_SHARE:.0%} of B&H's gain.",
        "",
        *table(v),
        *exposure_note(v),
        "",
        f"Gate: {GATE_RULE}",
        f"Result: passes in {v.fold_wins}/{n_folds} folds, full sample "
        f"{v.legs[-1].verdict} → "
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
    ap.add_argument("--symbol", default="SPY",
                    help="instrument column in --data")
    ap.add_argument("--data", type=Path, default=REPO / "data/prices_us.csv")
    ap.add_argument("--folds", type=int, default=3)
    ap.add_argument("--lot", type=int, default=0,
                    help="shares per lot; 0 = full-exposure lot (default)")
    ap.add_argument("--cash", type=float, default=10_000.0)
    ap.add_argument("--report", type=Path, default=None,
                    help="write a markdown report here")
    args = ap.parse_args(argv)
    if args.folds < 2:
        ap.error("--folds must be >= 2")
    if not args.all and not args.strategy:
        ap.error("--strategy NAME or --all")

    names = list(strategy_names()) if args.all else [args.strategy]
    print(f"GATE: {GATE_RULE}\n")
    sections: List[str] = []
    rc = 0
    loaded: dict = {}
    for name in names:
        symbol = args.symbol
        if symbol not in loaded:
            loaded[symbol] = load_closes(args.data, symbol)
        dates, closes = loaded[symbol]
        marked = is_deployable(name)
        v = evaluate(name, symbol, dates, closes, args.folds, args.lot,
                     args.cash)
        section = render(v, symbol, args.lot, args.cash, args.data, marked)
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
        symbols = " / ".join(sorted(loaded))
        args.report.write_text(
            f"# Expectancy gate — {symbols}\n\n"
            f"Generated by `python scripts/expectancy.py "
            f"{'--all' if args.all else '--strategy ' + names[0]}"
            f"{' --symbol ' + args.symbol if args.symbol else ''} "
            f"--folds {args.folds} --lot {args.lot}` "
            f"on {datetime.now(timezone.utc):%Y-%m-%d}.\n\n"
            f"**Gate:** {GATE_RULE}\n\n"
            + "\n\n".join(sections) + "\n")
        print(f"report: {args.report}")
    print("exit", rc, "(0 = deployable / gate consistent, 1 = not)")
    return rc


if __name__ == "__main__":
    sys.exit(main())
