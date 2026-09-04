"""Backtester (§3.1, §3.2, §3.3).

Parity by construction: fills go through the SAME code path as live —
portfolio.compute_orders -> RiskEngine.filter_orders -> execute_rebalance
against a PaperBroker with the real cost model. A backtest that takes
positions live cannot is fiction; here they share the code.

Lag: decisions on bar t see prices[:t] only and fill at bar t+1's price.
The no-lookahead invariant is covered by a bit-identity test (§3.1).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable, Protocol

import pandas as pd

from .broker import PaperBroker
from .config import EngineConfig
from .costs import CostModel
from .data import latest_prices, validate_prices
from .errors import DataError
from .execution import execute_rebalance
from .orders import Order, Side
from .portfolio import compute_orders
from .risk import PreTradeDecision, RiskEngine
from .state import EngineState


class Strategy(Protocol):
    def target_weights(self, prices: pd.DataFrame, today: date) -> dict[str, float]:
        """prices contains ONLY bars at or before the decision bar."""
        ...


@dataclass
class BacktestResult:
    equity: "pd.Series"
    contributions_total: float
    costs_paid: float
    orders_filled: list = field(default_factory=list)
    orders_dropped: list = field(default_factory=list)
    refusals: list = field(default_factory=list)         # (date, reason) data refusals
    halts: list = field(default_factory=list)            # (date, reason)
    halted: bool = False
    final_positions: dict = field(default_factory=dict)
    final_cash: float = 0.0


def month_end_schedule(index: pd.DatetimeIndex) -> Callable[[int], bool]:
    """Decision on the last trading day of each month.

    The final bar of the dataset counts only if it genuinely is the last
    business day of its month — data that happens to end mid-month must
    not fabricate a decision day (audit round 1, finding #14).
    """
    period = pd.Series(index.to_period("M"), index=range(len(index)))
    flags = (period != period.shift(-1)).to_numpy().copy()
    # Tolerance of one business day: exchanges close on holidays bdate_range
    # doesn't know (e.g. Good Friday), so a final bar one bday short of the
    # calendar month-end is still the month's real last trading day
    # (audit round 2, finding #10).
    last = index[-1]
    month_end = last + pd.offsets.MonthEnd(0)
    remaining = pd.bdate_range(last + pd.offsets.BDay(1), month_end)
    flags[-1] = len(remaining) <= 1
    return lambda i: bool(flags[i])


def run_backtest(
    prices: pd.DataFrame,
    strategy: Strategy,
    cfg: EngineConfig,
    *,
    initial_equity: float,
    contribution: Callable[[date], float] = lambda d: 0.0,
    is_decision_day: Callable[[int], bool] | None = None,
) -> BacktestResult:
    """prices: daily closes, DatetimeIndex ascending, one column per symbol.

    initial_equity is a REAL input (§6): the same strategy at a different
    account size produces different net results under fixed fees.
    """
    if not prices.index.is_monotonic_increasing:
        raise ValueError("price index must be ascending")
    if initial_equity < 0:
        raise ValueError("initial_equity must be >= 0")

    cost_model = CostModel(cfg.costs)
    risk = RiskEngine(cfg.risk, cost_model)
    if is_decision_day is None:
        is_decision_day = month_end_schedule(prices.index)

    cash = float(initial_equity)
    positions: dict[str, float] = {}
    state = EngineState(peak_equity=initial_equity, last_equity=initial_equity)
    pending: list[Order] | None = None
    contributions_total = 0.0
    costs_paid = 0.0
    equity_curve = []
    result = BacktestResult(equity=None, contributions_total=0.0, costs_paid=0.0)

    # Carry-forward frame for marking and fills: only PAST values feed each
    # row (ffill looks backward), so no lookahead — and a symbol whose close
    # is missing on a given bar keeps its last known mark instead of
    # cratering the equity curve to $0 (audit round 1, finding #5).
    prices_ff = prices.ffill()

    n = len(prices.index)
    prev_date = None
    for i in range(n):
        today = prices.index[i].date()
        # Credit contributions for EVERY calendar day since the previous
        # bar, not just bar dates — a Monday the market is closed still
        # deposits $100 (audit round 2, finding #8: ~10% of deposits went
        # missing across holiday Mondays).
        if prev_date is None:
            span = [today]
        else:
            span = [prev_date + timedelta(days=k)
                    for k in range(1, (today - prev_date).days + 1)]
        c = 0.0
        for d in span:
            ci = float(contribution(d))
            if ci < 0:
                raise ValueError("withdrawal schedules are not supported (negative contribution)")
            c += ci
        prev_date = today
        if c > 0:
            cash += c
            contributions_total += c

        row_ff = prices_ff.iloc[i]
        mark_prices = {s: float(row_ff[s]) for s in prices.columns if not pd.isna(row_ff[s])}
        equity = cash + sum(sh * mark_prices.get(sym, 0.0) for sym, sh in positions.items())

        # ---- fill leg: orders decided on bar i-1 fill at bar i (§3.2). ----
        # Liquidation orders from a hard kill also fill here, so no halted guard.
        if pending is not None:
            fill_prices = mark_prices
            broker = PaperBroker(cash=cash, prices=fill_prices, cost_model=cost_model,
                                 positions=positions)
            pre_cost_equity = broker.get_account().equity
            outcome = execute_rebalance(
                broker, risk, pending, fill_prices,
                escalation_max_hops=cfg.execution.escalation_max_hops)
            account = broker.get_account()
            cash = account.cash
            positions = account.positions
            costs_paid += pre_cost_equity - account.equity  # execution cost = equity lost to fills
            result.orders_filled += [r for r in outcome.results]
            result.orders_dropped += [(today, d) for d in outcome.dropped]
            equity = account.equity
            pending = None

        # ---- risk gate: kill switches run EVERY bar, exactly as live does
        # (audit round 1, finding #3 — evaluating them only on decision days
        # let the backtest sail through drawdowns that live would kill on).
        pre = None
        if not state.halted and equity > 0:
            pre = risk.pre_trade(state, equity, today, net_flows=c)
            if pre.decision is PreTradeDecision.HARD_KILL:
                # Liquidate at next bar and halt permanently (§7).
                state.halted = True
                state.halt_reason = pre.reason
                result.halts.append((today, pre.reason))
                liquidation = [
                    Order(symbol=s, side=Side.SELL, shares=sh, is_full_exit=True)
                    for s, sh in positions.items() if sh > 0
                ]
                pending = liquidation or None

        # ---- decision leg: bar i sees prices[: i + 1] only (§3.1) --------
        if (is_decision_day(i) and not state.halted and equity > 0
                and pre is not None and pre.decision is not PreTradeDecision.HARD_KILL):
            if pre.decision is PreTradeDecision.STAND_DOWN:
                result.halts.append((today, pre.reason))
                pending = None
            else:
                visible = prices.iloc[: i + 1]
                required = set(cfg.universe) | {s for s, sh in positions.items() if sh > 0}
                try:
                    # A DataError from ANY of these — validation, the
                    # strategy's own view of its window, or order
                    # computation — is a refusal for the cycle, never a
                    # liquidation (§5.7; audit round 2, finding #2).
                    validate_prices(visible, required, today, cfg.data.max_staleness_days)
                    px_now = latest_prices(visible, required)
                    weights = risk.clamp_weights(strategy.target_weights(visible, today))
                    pending = compute_orders(
                        positions, weights, px_now, equity,
                        no_trade_band=cfg.risk.no_trade_band) or None
                except DataError as exc:
                    result.refusals.append((today, str(exc)))
                    pending = None

        # Deposits raise the peak baseline 1:1 (a deposit is not a gain).
        state.peak_equity = max(state.peak_equity + max(c, 0.0), equity)
        if state.last_equity_date != today.isoformat():
            state.last_equity = equity
            state.last_equity_date = today.isoformat()
        equity_curve.append(equity)

    result.equity = pd.Series(equity_curve, index=prices.index, name="equity")
    result.contributions_total = contributions_total
    result.costs_paid = costs_paid
    result.halted = state.halted
    result.final_positions = positions
    result.final_cash = cash
    return result
