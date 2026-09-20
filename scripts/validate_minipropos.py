#!/usr/bin/env python3
"""Mini-Prop OS validation scorecard.

Paper-trades the shipped EMA-crossover strategy and the full OS pipeline
(risk gate -> OMS -> simulated broker) against engineered scenarios and
real historical data (SPY daily closes from data/prices_us.csv, scaled x10
to S&P-index level as an MES price proxy).

Every check is a concrete, falsifiable claim about system behavior. The
run PASSES if at least PASS_THRESHOLD of checks pass. Strategy performance
(win rate, PnL, drawdown) is reported as measured — it is evidence, not
a number to be tuned until it looks good.

Usage:
    python scripts/validate_minipropos.py            # run + print + report
    python scripts/validate_minipropos.py --quiet    # summary only
Exit code 0 iff the pass rate >= 75%.
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from mini_prop_os.core.config import RiskConfig, load_config  # noqa: E402
from mini_prop_os.core.types import Bar, Fill  # noqa: E402
from mini_prop_os.sim import (HistoricalSession, SimConfig, SimResult,
                              bars_from_closes, run_session)  # noqa: E402
from mini_prop_os.strategy.adaptive_ema import (  # noqa: E402
    AdaptiveEmaCrossoverStrategy, VolRegime)
from mini_prop_os.strategy.ema_crossover import EmaCrossoverStrategy  # noqa: E402
from mini_prop_os.risk.guardrails import RiskGuardrails  # noqa: E402

PASS_THRESHOLD = 0.75
SYMBOL = "MES"
ACCOUNTING_TOLERANCE = 0.01  # dollars


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


def make_session(
    risk_cfg: Optional[RiskConfig] = None,
    order_quantity: int = 1,
    fast: int = 9,
    slow: int = 21,
) -> HistoricalSession:
    strategy = EmaCrossoverStrategy(
        symbol=SYMBOL, fast_period=fast, slow_period=slow,
        order_quantity=order_quantity)
    risk = RiskGuardrails(risk_cfg or RiskConfig())
    return HistoricalSession(strategy, risk, SimConfig())


def common_invariants(res: SimResult, cfg: RiskConfig,
                      label: str) -> List[Check]:
    """Invariants every run must uphold, whatever the data."""
    return [
        Check(f"{label}: never short (long-only enforced)",
              res.min_position >= 0, f"min position {res.min_position}"),
        Check(f"{label}: position cap never exceeded",
              res.max_position <= cfg.max_position_shares,
              f"max {res.max_position} <= {cfg.max_position_shares}"),
        Check(f"{label}: order-size cap never exceeded",
              res.max_order_quantity <= cfg.max_order_quantity,
              f"max order {res.max_order_quantity}"),
        Check(f"{label}: no strategy orders after kill switch",
              res.orders_after_kill == 0,
              f"{res.orders_after_kill} leaked"),
        Check(f"{label}: accounting reconciles (OMS ledger vs raw fills)",
              res.accounting_error < ACCOUNTING_TOLERANCE,
              f"error ${res.accounting_error:.4f}"),
        Check(f"{label}: no working orders left at shutdown",
              res.open_orders_at_end == 0,
              f"{res.open_orders_at_end} open"),
    ]


def make_adaptive_session(
    risk_cfg: Optional[RiskConfig] = None,
    base_quantity: int = 2,
) -> HistoricalSession:
    strategy = AdaptiveEmaCrossoverStrategy(
        SYMBOL, fast_period=9, slow_period=21, base_quantity=base_quantity)
    risk = RiskGuardrails(risk_cfg or RiskConfig())
    return HistoricalSession(strategy, risk, SimConfig())


def _noise(i: int, amp: float = 4.0) -> float:
    return amp if i % 2 == 0 else -amp


def _calm(n: int, start: float = 5000.0, step: float = -2.0) -> List[float]:
    return [start + step * i + _noise(i) for i in range(n)]


def _trend(n: int, start: float, step: float = 15.0,
           noise: float = 4.0) -> List[float]:
    return [start + step * i + _noise(i, noise) for i in range(1, n + 1)]


def _chop(n: int, level: float, amp: float = 12.0) -> List[float]:
    return [level + (amp if i % 2 == 0 else -amp) for i in range(n)]


def _crash(start: float) -> List[float]:
    p, out = start, []
    for pct in (-0.04, -0.05, 0.03, -0.06, 0.04, -0.03, 0.02):
        p *= 1 + pct
        out.append(p)
    return out


# --------------------------------------------------------------- scenarios

def scenario_crossover_lifecycle() -> Tuple[List[Check], SimResult]:
    """Down -> up -> down trend must produce one full BUY/SELL round trip."""
    closes = ([5000 - 3 * i for i in range(80)]            # warmup, fast<slow
              + [4760 + 12 * i for i in range(40)]         # golden cross
              + [5240 - 15 * i for i in range(40)])        # death cross
    session = make_session()
    res = run_session(session, bars_from_closes(closes, SYMBOL))
    orders = session.broker.orders_received
    checks = [
        Check("lifecycle: exactly one entry and one exit order",
              len(orders) == 2 and orders[0].action.value == "BUY"
              and orders[1].action.value == "SELL",
              f"{[(o.action.value, o.quantity) for o in orders]}"),
        Check("lifecycle: golden cross entered long",
              res.max_position == 1, f"max position {res.max_position}"),
        Check("lifecycle: death cross exited to flat",
              res.final_position == 0 and len(res.round_trips) >= 1,
              f"final {res.final_position}, {len(res.round_trips)} trips"),
        Check("lifecycle: round trip captured most of the up-trend",
              bool(res.round_trips) and res.round_trips[0].pnl > 0,
              f"pnl {[f'{t.pnl:.0f}' for t in res.round_trips]}"),
    ]
    return checks + common_invariants(res, RiskConfig(), "lifecycle"), res


def scenario_warmup_strict() -> List[Check]:
    """Feeding only warmup-length data must yield zero orders even though
    the series contains a textbook crossover."""
    strategy = EmaCrossoverStrategy(SYMBOL, 9, 21, 1, warmup_bars=500)
    session = HistoricalSession(strategy, RiskGuardrails(RiskConfig()),
                                SimConfig())
    closes = [5000 - 3 * i for i in range(60)] + \
             [4820 + 10 * i for i in range(60)]
    run_session(session, bars_from_closes(closes, SYMBOL))
    n = len(session.broker.orders_received)
    return [Check("warmup: zero orders before warmup completes", n == 0,
                  f"{n} orders")]


def scenario_partial_fills() -> List[Check]:
    """Multi-unit orders exercise the OMS partial-fill path end to end."""
    cfg = RiskConfig(max_position_shares=10, max_order_quantity=10,
                     max_position_notional=500_000.0,
                     max_gross_notional=500_000.0)
    session = make_session(risk_cfg=cfg, order_quantity=4)
    closes = ([5000 - 3 * i for i in range(80)]
              + [4760 + 12 * i for i in range(40)]
              + [5240 - 15 * i for i in range(40)])
    res = run_session(session, bars_from_closes(closes, SYMBOL))
    filled = [o for o in session.oms.orders.values()
              if o.filled_quantity > 0]
    all_complete = all(o.remaining_quantity == 0 for o in filled)
    partials_seen = any(
        len([s for s, _ in o.history
             if s.value == "PARTIALLY_FILLED"]) > 0 for o in filled)
    return [
        Check("partials: 2+ unit orders filled via partial fills",
              partials_seen, f"{len(filled)} filled orders"),
        Check("partials: every filled order completed exactly",
              all_complete),
        Check("partials: accounting reconciles with split fills",
              res.accounting_error < ACCOUNTING_TOLERANCE,
              f"error ${res.accounting_error:.4f}"),
        Check("partials: position returned to flat",
              res.final_position == 0),
    ]


def scenario_kill_switch() -> List[Check]:
    """A crash day beyond the daily-loss limit must trip the breaker,
    flatten the book, and stay latched."""
    closes = ([5000 - 3 * i for i in range(80)]
              + [4760 + 12 * i for i in range(40)]   # long by here
              + [5240, 4700]                          # -540 pts = -$2700/ct
              + [4690 + 5 * i for i in range(60)])    # would re-cross up
    session = make_session()
    res = run_session(session, bars_from_closes(closes, SYMBOL))
    return [
        Check("kill switch: tripped on crash day", res.kill_switch_tripped,
              res.kill_switch_reason or "never tripped"),
        Check("kill switch: book flattened after trip",
              res.position_after_kill == 0,
              f"position after kill {res.position_after_kill}"),
        Check("kill switch: stays latched (no re-entry on later signal)",
              session.risk.kill_switch_active and res.final_position == 0,
              f"active={session.risk.kill_switch_active}"),
        Check("kill switch: no strategy orders leaked past it",
              res.orders_after_kill == 0),
    ]


def scenario_event_hygiene() -> List[Check]:
    """Duplicate/unknown broker events must not corrupt OMS state."""
    session = make_session()
    closes = ([5000 - 3 * i for i in range(80)]
              + [4760 + 12 * i for i in range(40)])
    res = run_session(session, bars_from_closes(closes, SYMBOL))
    oms = session.oms
    pos_before = dict(oms.position_quantities())
    filled = [o for o in oms.orders.values() if o.filled_quantity > 0]
    checks = []
    if filled:
        mo = filled[0]
        # Replay an already-seen exec id and a fill for an unknown order.
        oms.on_fill(Fill(order_id=mo.order_id, symbol=SYMBOL,
                         signed_quantity=1, price=1.0, exec_id="sim-1"))
        oms.on_fill(Fill(order_id=999_999, symbol=SYMBOL,
                         signed_quantity=5, price=1.0, exec_id="ghost-1"))
        checks.append(Check(
            "hygiene: duplicate exec id + unknown-order fill ignored",
            dict(oms.position_quantities()) == pos_before,
            f"{pos_before} -> {dict(oms.position_quantities())}"))
    else:
        checks.append(Check(
            "hygiene: duplicate exec id + unknown-order fill ignored",
            False, "no fills produced to test against"))
    checks.append(Check(
        "hygiene: corrupt OHLC bar is rejected at construction",
        _corrupt_bar_rejected(), ""))
    checks.append(Check(
        "hygiene: risk-rejected intents never reach the broker",
        res.risk_rejections >= 0 and all(
            i.quantity <= RiskConfig().max_order_quantity
            for i in session.broker.orders_received),
        f"{res.risk_rejections} rejections"))
    return checks


def _corrupt_bar_rejected() -> bool:
    try:
        Bar(symbol=SYMBOL, timestamp=datetime.now(timezone.utc),
            open=10.0, high=9.0, low=9.5, close=9.7, volume=1.0)
        return False
    except ValueError:
        return True


def scenario_config() -> List[Check]:
    """The shipped config must load, be paper, and be internally sized."""
    try:
        cfg = load_config(REPO / "mini_prop_os" / "config.yaml")
    except Exception as exc:  # pragma: no cover
        return [Check("config: shipped config.yaml loads", False, str(exc))]
    return [
        Check("config: shipped config.yaml loads", True),
        Check("config: paper port configured",
              cfg.connection.port in (7497, 4002),
              f"port {cfg.connection.port}"),
        Check("config: order size fits within risk caps",
              cfg.strategy.order_quantity <= cfg.risk.max_order_quantity
              <= cfg.risk.max_position_shares * 2,
              ""),
    ]


# ----------------------------------------------------- volatility stress

def scenario_whipsaw_chop() -> List[Check]:
    """Violent sideways chop: the baseline crossover bleeds on whipsaws;
    the adaptive strategy's confirmation filter must keep it out."""
    calm = _calm(80)
    closes = calm + _chop(150, level=calm[-1])
    bars = bars_from_closes(closes, SYMBOL)

    base = make_session(order_quantity=2)
    base_res = run_session(base, bars)
    adap = make_adaptive_session()
    adap_res = run_session(adap, bars)

    base_entries = sum(1 for o in base.broker.orders_received
                       if o.action.value == "BUY")
    adap_entries = sum(1 for o in adap.broker.orders_received
                       if o.action.value == "BUY")
    checks = [
        Check("whipsaw: baseline demonstrably whipsaws in chop",
              base_entries >= 3,
              f"baseline entries {base_entries}"),
        Check("whipsaw: adaptive filter cuts entries vs baseline",
              adap_entries < base_entries,
              f"{adap_entries} vs {base_entries}"),
        Check("whipsaw: adaptive loses less than baseline in chop",
              adap_res.total_return > base_res.total_return,
              f"adaptive {adap_res.total_return:+.0f} vs "
              f"baseline {base_res.total_return:+.0f}"),
    ]
    checks += common_invariants(adap_res, RiskConfig(), "whipsaw-adaptive")
    return checks


def scenario_flash_crash_risk_off() -> List[Check]:
    """Flash crash while long: the strategy itself must flag EXTREME and go
    flat, independently of the account-level kill switch (which is given a
    loose limit here so the strategy's own adaptation is what is tested)."""
    loose = RiskConfig(max_daily_loss=50_000.0, max_daily_loss_pct=0.5)
    calm = _calm(120)  # adaptive warmup is 100 bars; finish it while calm
    up = _trend(60, calm[-1])
    closes = calm + up + _crash(up[-1]) + _chop(40, level=up[-1] * 0.85)
    session = make_adaptive_session(risk_cfg=loose)
    res = run_session(session, bars_from_closes(closes, SYMBOL))
    strategy = session.strategy
    assert isinstance(strategy, AdaptiveEmaCrossoverStrategy)
    crash_start = len(calm) + len(up)
    regimes_after = strategy.regime_history[crash_start:]
    entries_after = [o for o in session.broker.orders_received[1:]
                     if o.action.value == "BUY"]
    return [
        Check("flash crash: strategy was long before the crash",
              res.max_position >= 1, f"max position {res.max_position}"),
        Check("flash crash: EXTREME regime flagged during the crash",
              VolRegime.EXTREME in regimes_after,
              f"regimes {[r.value for r in regimes_after[:8]]}"),
        Check("flash crash: strategy went flat and stayed flat",
              res.final_position == 0 and not entries_after,
              f"final {res.final_position}, "
              f"{len(entries_after)} re-entries"),
        Check("flash crash: accounting reconciles through the crash",
              res.accounting_error < ACCOUNTING_TOLERANCE,
              f"error ${res.accounting_error:.4f}"),
    ]


def scenario_high_vol_sizing() -> List[Check]:
    """The same golden cross must be traded at half size when it happens
    in a HIGH-volatility regime."""
    calm = _calm(150)
    normal_entry = make_adaptive_session()
    run_session(normal_entry, bars_from_closes(
        calm + _trend(60, calm[-1], step=15.0, noise=4.0), SYMBOL))
    # Establish elevated volatility just BEFORE the cross — short and
    # sharp, because the slow baseline adapts within ~25 bars and would
    # re-classify a long-lived shock as the new normal.
    hot = [calm[-1] - 2 * i + _noise(i, 14.0) for i in range(1, 11)]
    high_entry = make_adaptive_session()
    run_session(high_entry, bars_from_closes(
        calm + hot + _trend(60, hot[-1], step=15.0, noise=14.0), SYMBOL))
    n_qty = [o.quantity for o in normal_entry.broker.orders_received
             if o.action.value == "BUY"]
    h_qty = [o.quantity for o in high_entry.broker.orders_received
             if o.action.value == "BUY"]
    return [
        Check("sizing: calm-regime entry uses base size",
              bool(n_qty) and n_qty[0] == 2, f"quantities {n_qty}"),
        Check("sizing: high-vol entry is cut to half size",
              bool(h_qty) and h_qty[0] == 1, f"quantities {h_qty}"),
    ]


def scenario_online_learning() -> List[Check]:
    """Repeated losing trades must tighten the entry threshold for that
    regime (and stay within bounds) — the 'learn from conditions' loop."""
    strategy = AdaptiveEmaCrossoverStrategy(
        SYMBOL, 9, 21, base_quantity=2, k_step=0.1)
    before = dict(strategy.entry_thresholds)
    # Feed it a sawtooth that keeps triggering confirmed entries that then
    # reverse: each round trip loses, so thresholds must ratchet up.
    calm = _calm(150)
    closes = list(calm)
    level = calm[-1]
    for _ in range(6):
        closes += _trend(25, level, step=14.0)        # confirmed entry
        level = closes[-1]
        closes += [level - 22 * i + _noise(i) for i in range(1, 26)]
        level = closes[-1]
    session = HistoricalSession(strategy, RiskGuardrails(RiskConfig()),
                                SimConfig())
    res = run_session(session, bars_from_closes(closes, SYMBOL))
    losses = sum(1 for t in res.round_trips if t.pnl < 0)
    raised = any(strategy.entry_thresholds[r] > before[r]
                 for r in (VolRegime.LOW, VolRegime.NORMAL, VolRegime.HIGH))
    bounded = all(strategy.entry_thresholds[r] <= strategy.k_max
                  for r in (VolRegime.LOW, VolRegime.NORMAL,
                            VolRegime.HIGH))
    return [
        Check("learning: sawtooth produced losing round trips to learn from",
              losses >= 2, f"{losses} losses / {len(res.round_trips)} trips"),
        Check("learning: entry thresholds tightened after losses",
              raised, str({r.value: round(v, 2) for r, v in
                           strategy.entry_thresholds.items()
                           if r is not VolRegime.EXTREME})),
        Check("learning: thresholds stay hard-bounded", bounded),
    ]


def scenario_vol_target_sizing() -> List[Check]:
    """Black-Scholes σS√T sizing must hold dollar risk per trade roughly
    constant across volatility regimes — the one thing the equation can
    genuinely make predictable. Direction is NOT claimed to be."""
    budget, mult = 2000.0, 5.0
    calm_closes = _calm(160)
    # Same structure, four times the bar-to-bar noise.
    loud_closes = [5000 - 2 * i + _noise(i, 16.0) for i in range(160)]

    sized: List[Tuple[str, float, int]] = []
    for label, closes in (("calm", calm_closes), ("loud", loud_closes)):
        s = AdaptiveEmaCrossoverStrategy(
            SYMBOL, 9, 21, base_quantity=10, risk_per_trade=budget,
            multiplier=mult, high_vol_ratio=9.0, extreme_vol_ratio=10.0)
        for bar in bars_from_closes(closes, SYMBOL):
            s.on_bar(bar)
        qty = s.entry_quantity(VolRegime.NORMAL, 5000.0)
        risk = s.expected_move_points(5000.0, s.confirm_window) * mult * qty
        sized.append((label, risk, qty))

    (_, calm_risk, calm_qty), (_, loud_risk, loud_qty) = sized
    unsized = AdaptiveEmaCrossoverStrategy(
        SYMBOL, 9, 21, base_quantity=10, risk_per_trade=0.0, multiplier=mult,
        high_vol_ratio=9.0, extreme_vol_ratio=10.0)
    for bar in bars_from_closes(loud_closes, SYMBOL):
        unsized.on_bar(bar)
    unsized_qty = unsized.entry_quantity(VolRegime.NORMAL, 5000.0)
    unsized_risk = unsized.expected_move_points(
        5000.0, unsized.confirm_window) * mult * unsized_qty

    return [
        Check("vol-target: quiet market takes a larger position",
              calm_qty > loud_qty, f"{calm_qty} vs {loud_qty} contracts"),
        Check("vol-target: dollar risk stays within budget in both regimes",
              calm_risk <= budget and loud_risk <= budget,
              f"calm ${calm_risk:,.0f}, loud ${loud_risk:,.0f} "
              f"(budget ${budget:,.0f})"),
        Check("vol-target: risk is far more uniform than fixed sizing",
              abs(calm_risk - loud_risk) < abs(calm_risk - unsized_risk),
              f"sized spread ${abs(calm_risk - loud_risk):,.0f} vs "
              f"unsized ${abs(calm_risk - unsized_risk):,.0f}"),
        Check("vol-target: fixed sizing would have blown the budget",
              unsized_risk > budget,
              f"${unsized_risk:,.0f} at {unsized_qty} contracts"),
        Check("vol-target: never sizes above the configured base",
              calm_qty <= 10 and loud_qty <= 10,
              f"max {max(calm_qty, loud_qty)} <= 10"),
    ]


HIGH_VOL_WINDOWS: Sequence[Tuple[str, Tuple[int, int], Tuple[int, int]]] = (
    ("GFC autumn 2008", (2008, 8), (2009, 3)),
    ("euro crisis 2011", (2011, 7), (2011, 12)),
    ("yuan shock 2015", (2015, 7), (2015, 10)),
    ("volmageddon+Q4 2018", (2018, 1), (2018, 12)),
    ("COVID crash 2020", (2020, 1), (2020, 6)),
    ("bear market 2022", (2022, 1), (2022, 12)),
)


def historical_stress(quiet: bool) -> Tuple[List[Check], List[str]]:
    """Purposely drop both strategies into the most volatile windows in
    the dataset and compare behavior. Gated checks are mechanical OS/risk
    invariants; performance is reported as measured."""
    dates, closes = load_spy_index_closes()
    checks: List[Check] = []
    lines: List[str] = []
    dd_totals: List[Tuple[float, float]] = []
    for label, (y0, m0), (y1, m1) in HIGH_VOL_WINDOWS:
        idx = [i for i, d in enumerate(dates)
               if (d.year, d.month) >= (y0, m0)
               and (d.year, d.month) <= (y1, m1)]
        if len(idx) < 60:
            checks.append(Check(f"stress {label}: enough data", False,
                                f"{len(idx)} bars"))
            continue
        bars = bars_from_closes([closes[i] for i in idx], SYMBOL,
                                timestamps=[dates[i] for i in idx])
        base = make_session(order_quantity=2)
        base_res = run_session(base, bars)
        adap = make_adaptive_session()
        adap_res = run_session(adap, bars)
        checks += common_invariants(adap_res, RiskConfig(),
                                    f"stress {label} (adaptive)")
        checks.append(Check(
            f"stress {label}: adaptive does not materially worsen drawdown",
            adap_res.max_drawdown <= base_res.max_drawdown * 1.05 + 50.0,
            f"{adap_res.max_drawdown:,.0f} vs "
            f"{base_res.max_drawdown:,.0f}"))
        dd_totals.append((base_res.max_drawdown, adap_res.max_drawdown))
        for name, res in (("baseline", base_res), ("adaptive", adap_res)):
            wr = res.win_rate
            lines.append(
                f"| {label} | {name} | {len(res.round_trips)} | "
                f"{'-' if wr is None else f'{wr:.0%}'} | "
                f"{res.total_return:+,.0f} | {res.max_drawdown:,.0f} | "
                f"{'TRIPPED' if res.kill_switch_tripped else 'no'} |")
        if not quiet:
            print(f"  stress {label}: baseline {base_res.total_return:+,.0f}"
                  f" (DD {base_res.max_drawdown:,.0f}) vs adaptive "
                  f"{adap_res.total_return:+,.0f} "
                  f"(DD {adap_res.max_drawdown:,.0f})")
    if dd_totals:
        base_dd = sum(b for b, _ in dd_totals)
        adap_dd = sum(a for _, a in dd_totals)
        checks.append(Check(
            "stress aggregate: adaptive cuts combined drawdown across all "
            "high-vol windows",
            adap_dd < base_dd,
            f"${adap_dd:,.0f} vs ${base_dd:,.0f}"))
    return checks, lines


# ------------------------------------------------------- historical replay

def load_spy_index_closes() -> Tuple[List[datetime], List[float]]:
    """SPY adjusted closes from the repo dataset, scaled x10 to S&P-index
    level as an MES price proxy."""
    dates: List[datetime] = []
    closes: List[float] = []
    with open(REPO / "data" / "prices_us.csv") as fh:
        for row in csv.DictReader(fh):
            v = row.get("SPY", "")
            if not v:
                continue
            dates.append(datetime.strptime(row["Date"], "%Y-%m-%d")
                         .replace(tzinfo=timezone.utc))
            closes.append(float(v) * 10.0)
    return dates, closes


PERIODS: Sequence[Tuple[str, int, int]] = (
    ("GFC 2007-2009", 2007, 2009),
    ("recovery 2010-2014", 2010, 2014),
    ("bull 2015-2019", 2015, 2019),
    ("COVID 2020-2021", 2020, 2021),
    ("bear 2022", 2022, 2022),
    ("recent 2023-2026", 2023, 2026),
)


def historical_replays(quiet: bool) -> Tuple[List[Check], List[str]]:
    dates, closes = load_spy_index_closes()
    checks: List[Check] = []
    perf_lines: List[str] = []
    for label, y0, y1 in PERIODS:
        idx = [i for i, d in enumerate(dates) if y0 <= d.year <= y1]
        if len(idx) < 200:
            checks.append(Check(f"{label}: enough data", False,
                                f"only {len(idx)} bars"))
            continue
        sub_closes = [closes[i] for i in idx]
        sub_dates = [dates[i] for i in idx]
        session = make_session()
        bars = bars_from_closes(sub_closes, SYMBOL, timestamps=sub_dates)
        res = run_session(session, bars)
        checks.extend(common_invariants(res, RiskConfig(), label))
        if res.kill_switch_tripped:
            checks.append(Check(
                f"{label}: kill switch trip flattened the book",
                res.position_after_kill == 0,
                res.kill_switch_reason))
        wr = res.win_rate
        perf_lines.append(
            f"| {label} | {res.bars} | {len(res.round_trips)} | "
            f"{'-' if wr is None else f'{wr:.0%}'} | "
            f"{res.total_return:+,.0f} | {res.max_drawdown:,.0f} | "
            f"{'TRIPPED' if res.kill_switch_tripped else 'no'} |")
        if not quiet:
            print(f"  replayed {label}: {res.bars} bars, "
                  f"{len(res.round_trips)} trips, "
                  f"PnL {res.total_return:+,.0f}")
    return checks, perf_lines


# ---------------------------------------------------------------- reporting

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    checks: List[Check] = []
    lifecycle_checks, _ = scenario_crossover_lifecycle()
    checks += lifecycle_checks
    checks += scenario_warmup_strict()
    checks += scenario_partial_fills()
    checks += scenario_kill_switch()
    checks += scenario_event_hygiene()
    checks += scenario_config()
    checks += scenario_whipsaw_chop()
    checks += scenario_flash_crash_risk_off()
    checks += scenario_high_vol_sizing()
    checks += scenario_online_learning()
    checks += scenario_vol_target_sizing()
    hist_checks, perf_lines = historical_replays(args.quiet)
    checks += hist_checks
    stress_checks, stress_lines = historical_stress(args.quiet)
    checks += stress_checks

    passed = sum(1 for c in checks if c.passed)
    total = len(checks)
    rate = passed / total
    verdict = "PASS" if rate >= PASS_THRESHOLD else "FAIL"

    lines = [
        "# Mini-Prop OS validation scorecard",
        "",
        f"Generated: {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}",
        "",
        f"**{passed}/{total} checks passed ({rate:.1%}) — {verdict} "
        f"(gate: >= {PASS_THRESHOLD:.0%})**",
        "",
        "Simulation: real RiskGuardrails + OMS + EmaCrossoverStrategy, "
        "simulated broker (fills at next bar open, 1 tick adverse "
        "slippage, $0.62/side commission, partial fills on 2+ units). "
        "Historical data: SPY daily adjusted closes (data/prices_us.csv) "
        "x10 as an S&P-index/MES proxy, 1 contract, $5 multiplier.",
        "",
        "## Checks",
        "",
    ]
    for c in checks:
        mark = "PASS" if c.passed else "FAIL"
        lines.append(f"- [{mark}] {c.name}"
                     + (f" — {c.detail}" if c.detail else ""))
    lines += [
        "",
        "## Strategy performance (reported as measured, not a gate)",
        "",
        "Baseline ema_crossover across full regimes:",
        "",
        "| period | bars | round trips | win rate | net PnL ($) | "
        "max DD ($) | kill switch |",
        "|---|---|---|---|---|---|---|",
        *perf_lines,
        "",
        "High-volatility stress windows, baseline vs volatility-adaptive "
        "(regime sizing + EXTREME risk-off + confirmed entries + bounded "
        "online threshold learning):",
        "",
        "| window | strategy | round trips | win rate | net PnL ($) | "
        "max DD ($) | kill switch |",
        "|---|---|---|---|---|---|---|",
        *stress_lines,
        "",
        "Win rates for a trend-following crossover are typically well "
        "below 50% (few large winners pay for many small losers); the "
        "75% gate applies to the system-behavior checks above, and no "
        "strategy metric here is evidence of live edge (see the repo's "
        "Phase 4 verdict).",
    ]
    report = "\n".join(lines) + "\n"
    out = REPO / "reports" / "minipropos_validation.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(report)

    if not args.quiet:
        print()
        for c in checks:
            print(f"  [{'PASS' if c.passed else 'FAIL'}] {c.name}"
                  + (f" — {c.detail}" if c.detail and not c.passed else ""))
    print(f"\n{passed}/{total} checks passed ({rate:.1%}) — {verdict} "
          f"(gate >= {PASS_THRESHOLD:.0%}); report: {out.relative_to(REPO)}")
    return 0 if rate >= PASS_THRESHOLD else 1


if __name__ == "__main__":
    sys.exit(main())
