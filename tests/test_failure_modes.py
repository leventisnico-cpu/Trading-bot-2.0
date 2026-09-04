"""§5 — named regression tests for real bugs that passed a green suite.

Every test states its failure mode number. Thresholds come from
config/engine.toml (§8).
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from conftest import ConstWeights, flat_prices, with_risk
from engine.broker import PaperBroker, PaperBrokerKnobs
from engine.costs import CostModel
from engine.data import validate_prices
from engine.errors import DataError, StateError
from engine.execution import execute_rebalance
from engine.journal import NullJournal
from engine.orders import Order, OrderStatus, Side, is_success, truncate_to_cap
from engine.portfolio import basket_volatility, compute_orders, converged
from engine.risk import PreTradeDecision, RiskEngine
from engine.runner import run_cycle
from engine.state import EngineState, StateStore
from engine.backtest import run_backtest

TODAY = date(2026, 8, 31)


def _mk_risk(cfg):
    return RiskEngine(cfg.risk, CostModel(cfg.costs))


# ---------------------------------------------------------------------------
def test_fm01_daily_loss_kill_switch_uses_prior_equity(cfg):
    """FM#1: the runner once saved today's equity into state before the risk
    check, so measured daily return was always exactly 0.00%. The check must
    see PRIOR equity."""
    risk = _mk_risk(cfg)
    drop = 2 * cfg.risk.max_daily_loss_pct
    prior = EngineState(peak_equity=10_000.0, last_equity=10_000.0,
                        last_equity_date=(TODAY - timedelta(days=1)).isoformat())
    equity_today = 10_000.0 * (1 - drop)

    result = risk.pre_trade(prior, equity_today, TODAY)
    assert result.daily_return == pytest.approx(-drop), \
        "daily return computed as ~0 — the check is comparing today with today"
    assert result.decision is PreTradeDecision.STAND_DOWN


def test_fm01_runner_orders_state_write_after_check(cfg, tmp_path):
    """Full-cycle version: even though run_cycle updates state at the end,
    the stand-down must fire from the PRIOR day's equity."""
    store = StateStore(tmp_path / "state.json")
    store.save(EngineState(peak_equity=10_000.0, last_equity=10_000.0,
                           last_equity_date=(TODAY - timedelta(days=1)).isoformat()))
    drop = 2 * cfg.risk.max_daily_loss_pct
    sym = cfg.universe[0]
    prices = flat_prices(list(cfg.universe), days=10, end=TODAY)
    broker = PaperBroker(cash=10_000.0 * (1 - drop), prices={s: 100.0 for s in cfg.universe},
                         cost_model=CostModel(cfg.costs))
    result = run_cycle(today=TODAY, cfg=cfg, store=store, broker=broker,
                       strategy=ConstWeights({sym: 0.4}), prices=prices,
                       journal=NullJournal(), decision_day=True)
    assert not result.traded, "traded through a daily loss beyond the soft-halt limit"
    assert any("standing down" in n for n in [result.report]), result.report
    # State was still updated afterwards (write happens AFTER the check).
    assert store.load().last_equity == pytest.approx(10_000.0 * (1 - drop))


# ---------------------------------------------------------------------------
def test_fm02_buys_sized_off_confirmed_cash_after_sell_fails(cfg):
    """FM#2: a sell the exchange later rejected once left buys spending cash
    that was never freed. Buys must be sized off re-read, demonstrable cash."""
    risk = _mk_risk(cfg)
    prices = {"A": 50.0, "B": 10.0}
    knobs = PaperBrokerKnobs(scripted_status_by_symbol={"A": OrderStatus.REJECTED})
    broker = PaperBroker(cash=300.0, prices=prices, cost_model=CostModel(cfg.costs),
                         positions={"A": 10.0}, knobs=knobs)
    orders = [
        Order(symbol="A", side=Side.SELL, shares=10, is_full_exit=True),  # would free 500
        Order(symbol="B", side=Side.BUY, shares=40),                      # wants 400
    ]
    outcome = execute_rebalance(broker, risk, orders, prices,
                                escalation_max_hops=cfg.execution.escalation_max_hops)

    sells = [o for o in broker.submissions if o.side is Side.SELL]
    assert sells, "sell was never submitted — test proves nothing"
    account = broker.get_account()
    assert account.cash >= 0, "cash went negative: buys spent unconfirmed sale proceeds"
    assert account.positions.get("A") == 10.0, "rejected sell somehow removed the position"
    # The strong claim is about SUBMISSION, not fills: even a buy the venue
    # would reject must never be sent larger than confirmed cash.
    submitted_buys = [o for o in broker.submissions if o.side is Side.BUY]
    assert submitted_buys, "no buy was even attempted — test proves nothing"
    for o in submitted_buys:
        assert o.shares * prices[o.symbol] <= 300.0, \
            f"submitted a {o.shares}-share buy needing more than the confirmed 300 in cash"


# ---------------------------------------------------------------------------
def test_fm03_sells_first_and_buys_dropped_at_cap(cfg):
    """FM#3: an order filter once put buys ahead of sells and truncated
    sells first — exactly backwards."""
    sells = [Order(symbol=f"S{i}", side=Side.SELL, shares=1) for i in range(3)]
    buys = [Order(symbol=f"B{i}", side=Side.BUY, shares=1) for i in range(3)]
    cap = 4
    kept, dropped = truncate_to_cap(buys + sells, cap)  # deliberately buys-first input
    assert len(kept) == cap
    assert [o.side for o in kept[:3]] == [Side.SELL] * 3, "sells were not kept first"
    assert all(d.order.side is Side.BUY for d in dropped), "a sell was dropped before a buy"


def test_fm03_execution_submits_sells_before_buys(cfg):
    risk = _mk_risk(cfg)
    prices = {"A": 100.0, "B": 100.0}
    broker = PaperBroker(cash=5_000.0, prices=prices, cost_model=CostModel(cfg.costs),
                         positions={"A": 20.0})
    orders = [Order(symbol="B", side=Side.BUY, shares=10),
              Order(symbol="A", side=Side.SELL, shares=20, is_full_exit=True)]
    execute_rebalance(broker, risk, orders, prices)
    assert broker.submissions, "nothing was submitted — test proves nothing"
    sides = [o.side for o in broker.submissions]
    assert sides.index(Side.SELL) < sides.index(Side.BUY), "buy submitted before sell"


# ---------------------------------------------------------------------------
def test_fm04_full_exits_exempt_from_minimum_size_filters(cfg):
    """FM#4: a no-trade band applied to exits meant positions ratcheted down
    but never closed."""
    risk = _mk_risk(cfg)
    equity = 10_000.0
    # Position worth less than min_order_notional AND below the no-trade band.
    small_shares = max(1, int((cfg.risk.min_order_notional - 1) // 10))
    positions = {"A": float(small_shares)}
    prices = {"A": 10.0}
    notional = small_shares * 10.0
    assert notional < cfg.risk.min_order_notional, "precondition broken: position not small"
    assert notional / equity < cfg.risk.no_trade_band, "precondition broken: above band"

    orders = compute_orders(positions, {"A": 0.0}, prices, equity,
                            no_trade_band=cfg.risk.no_trade_band)
    assert len(orders) == 1 and orders[0].is_full_exit, "full exit was swallowed by the band"

    approved, dropped = risk.filter_orders(orders, prices)
    assert approved.orders and approved.orders[0].is_full_exit, \
        f"risk filters ate the full exit: {[d.reason for d in dropped]}"


# ---------------------------------------------------------------------------
def test_fm05_torn_state_file_refuses_to_trade(cfg, tmp_path):
    """FM#5: a torn state file once reloaded as 'not halted' and resurrected
    a killed system. Strict semantics after audit round 1 finding #4: any
    corrupt main file is a refusal — never a silent fallback to the stale
    backup, which may predate the halt."""
    store = StateStore(tmp_path / "state.json")
    store.save(EngineState(halted=False, peak_equity=1.0))
    store.save(EngineState(halted=True, halt_reason="hard kill", peak_equity=1.0))

    # Tear the main file mid-write (both before and after the halted bytes).
    raw = store.path.read_text()
    for cut in (len(raw) // 3, len(raw) // 2, 9 * len(raw) // 10):
        store.path.write_text(raw[:cut])
        with pytest.raises(StateError):
            store.load()


def test_fm05_unreadable_state_and_backup_refuse_to_trade(tmp_path):
    store = StateStore(tmp_path / "state.json")
    store.save(EngineState(halted=True))
    store.path.write_text("garbage")
    if store.backup_path.exists():
        store.backup_path.write_text("also garbage")
    with pytest.raises(StateError):
        store.load()


def test_fm05_missing_state_needs_explicit_bootstrap(tmp_path):
    store = StateStore(tmp_path / "state.json")
    with pytest.raises(StateError):
        store.load()
    fresh = store.load(allow_fresh=True)
    assert fresh.halted is False and fresh.peak_equity == 0.0


# ---------------------------------------------------------------------------
@pytest.mark.parametrize("status", list(OrderStatus))
def test_fm06_success_is_a_whitelist(status):
    """FM#6: REJECTED wasn't on a failure blacklist and read as success.
    Only FILLED is success; every other status — including ones added
    later — is failure."""
    if status is OrderStatus.FILLED:
        assert is_success(status)
    else:
        assert not is_success(status), f"{status} treated as success"


def test_fm06_rejected_rebalance_not_marked_complete(cfg, tmp_path):
    store = StateStore(tmp_path / "state.json")
    store.save(EngineState(peak_equity=10_000.0, last_equity=10_000.0,
                           last_equity_date=(TODAY - timedelta(days=1)).isoformat()))
    sym = cfg.universe[0]
    prices = flat_prices(list(cfg.universe), days=10, end=TODAY)
    broker = PaperBroker(cash=10_000.0, prices={s: 100.0 for s in cfg.universe},
                         cost_model=CostModel(cfg.costs),
                         knobs=PaperBrokerKnobs(reject_all=True))
    result = run_cycle(today=TODAY, cfg=cfg, store=store, broker=broker,
                       strategy=ConstWeights({sym: 0.4}), prices=prices,
                       journal=NullJournal(), decision_day=True)
    assert result.outcome is not None and result.outcome.results, \
        "no orders were attempted — test proves nothing"
    state = store.load()
    assert state.last_completed_period == "", \
        "an all-REJECTED rebalance was marked complete"
    assert "NOT AT TARGET" in result.report.splitlines()[0], \
        "partial rebalance described in the same words as a complete one (§11)"


# ---------------------------------------------------------------------------
def test_fm07_missing_or_nan_symbol_refuses_to_trade(cfg):
    """FM#7: a one-symbol data gap once became 'target weight 0' and
    liquidated a real position."""
    prices = flat_prices(["A", "B"], days=30)
    with pytest.raises(DataError):
        validate_prices(prices, {"A", "B", "C"}, TODAY, cfg.data.max_staleness_days)

    nan_tail = prices.copy()
    nan_tail.loc[nan_tail.index[-1], "B"] = np.nan
    with pytest.raises(DataError):
        validate_prices(nan_tail, {"A", "B"},
                        nan_tail.index[-1].date(), cfg.data.max_staleness_days)

    with pytest.raises(DataError):
        compute_orders({"B": 10.0}, {"A": 0.5}, {"A": 100.0}, 10_000.0)


def test_fm07_backtest_data_gap_keeps_position(cfg):
    prices = flat_prices(list(cfg.universe), days=120)
    sym = cfg.universe[0]
    # Buy early, then the feed for sym dies for the rest of the series.
    gap_start = 80
    prices.iloc[gap_start:, prices.columns.get_loc(sym)] = np.nan
    result = run_backtest(prices, ConstWeights({sym: 0.4}), cfg, initial_equity=10_000.0,
                          is_decision_day=lambda i: i in (10, 100))
    assert any(r.order.symbol == sym for r in result.orders_filled), \
        "position was never opened — test proves nothing"
    assert result.refusals, "data gap did not trigger a refusal"
    assert result.final_positions.get(sym, 0) > 0, \
        "data gap liquidated the position instead of refusing to trade"


# ---------------------------------------------------------------------------
def test_fm08_basket_vol_uses_covariance_not_average(cfg):
    """FM#8: averaging per-asset vols once under-invested by ~40%. Three
    uncorrelated 20%-vol assets are an ~11.5%-vol basket."""
    symbols = ["A", "B", "C"]
    vol = 0.20
    cov = np.eye(3) * vol**2
    w = {s: 1.0 / 3.0 for s in symbols}
    basket = basket_volatility(w, cov, symbols)
    assert basket == pytest.approx(vol / np.sqrt(3), rel=1e-6)  # ~11.55%
    naive_average = vol
    assert abs(basket - naive_average) > 0.05, \
        "basket vol equals the naive average — covariance is not being used"


# ---------------------------------------------------------------------------
def test_fm09_completion_is_convergence_not_order_count(cfg, tmp_path):
    """FM#9: a rebalance needing more orders than the daily cap was never
    'complete' by order count and re-traded forever, paying spread daily."""
    store = StateStore(tmp_path / "state.json")
    store.save(EngineState(peak_equity=10_000.0, last_equity=10_000.0,
                           last_equity_date=(TODAY - timedelta(days=1)).isoformat()))
    sym = cfg.universe[0]
    prices = flat_prices(list(cfg.universe), days=10, end=TODAY)
    # Broker fills only 5% of anything: convergence is impossible.
    broker = PaperBroker(cash=10_000.0, prices={s: 100.0 for s in cfg.universe},
                         cost_model=CostModel(cfg.costs),
                         knobs=PaperBrokerKnobs(fill_fraction={sym: 0.05}))
    strategy = ConstWeights({sym: 0.4})

    traded_flags = []
    warned = False
    for _ in range(cfg.risk.max_rebalance_retries + 1):
        res = run_cycle(today=TODAY, cfg=cfg, store=store, broker=broker,
                        strategy=strategy, prices=prices,
                        journal=NullJournal(), decision_day=True)
        traded_flags.append(res.traded)
        if "LOUD WARNING" in res.report:
            warned = True
    assert traded_flags[0] is True, "never traded at all — test proves nothing"
    state = store.load()
    assert state.last_completed_period == "", "unconverged rebalance marked complete"
    assert warned, "retry cap reached without a loud warning (§5.9)"
    assert traded_flags[-1] is False, "still re-trading after the retry cap"


def test_fm09_converged_by_portfolio_state_not_orders(cfg):
    prices = {"A": 100.0}
    assert not converged({"A": 2.0}, {"A": 0.4}, prices, 10_000.0,
                         cfg.risk.rebalance_tolerance)
    assert converged({"A": 40.0}, {"A": 0.4}, prices, 10_000.0,
                     cfg.risk.rebalance_tolerance)


# ---------------------------------------------------------------------------
def test_fm10_escalation_is_one_hop_never_a_chain(cfg):
    """FM#10: an unfilled limit was once cancelled and re-sent forever.
    Exactly one escalation; the escalated market order gets no budget."""
    risk = _mk_risk(cfg)
    prices = {"A": 100.0}
    knobs = PaperBrokerKnobs(scripted_status_by_symbol={"A": OrderStatus.CANCELLED})
    broker = PaperBroker(cash=10_000.0, prices=prices, cost_model=CostModel(cfg.costs),
                         positions={"A": 10.0}, knobs=knobs)
    order = Order(symbol="A", side=Side.SELL, shares=10, limit_price=101.0)
    outcome = execute_rebalance(broker, risk, [order], prices,
                                escalation_max_hops=cfg.execution.escalation_max_hops)
    assert len(broker.submissions) == 2, \
        f"{len(broker.submissions)} submissions — escalation chained (must be exactly 2: limit + one market)"
    assert outcome.escalations == 1
    assert broker.submissions[1].limit_price is None, "escalated order was not a market order"


def test_fm11_equity_floor_does_not_kill_an_account_still_accumulating(cfg):
    """FM#11 (found in THIS build's Phase 4): a $0-start account with weekly
    contributions was hard-killed on its first decision day because equity
    was 'below the floor' it had never reached — and 11 years of backtest
    sat in cash while reporting success. The floor must only arm once
    equity has ever reached it."""
    risk = _mk_risk(cfg)
    floor = cfg.risk.min_equity_floor
    assert floor > 0, "config floor is 0 — test proves nothing"

    # Never reached the floor: growing account must be left alone.
    prior = EngineState(peak_equity=floor * 0.4, last_equity=floor * 0.4,
                        last_equity_date=(TODAY - timedelta(days=1)).isoformat())
    res = risk.pre_trade(prior, floor * 0.5, TODAY)
    assert res.decision is PreTradeDecision.OK, \
        f"accumulating account killed below a floor it never reached: {res.reason}"

    # Once armed (peak above floor), falling below it must still kill.
    armed = EngineState(peak_equity=floor * 10, last_equity=floor * 1.1,
                        last_equity_date=(TODAY - timedelta(days=1)).isoformat())
    res2 = risk.pre_trade(armed, floor * 0.9, TODAY)
    assert res2.decision is PreTradeDecision.HARD_KILL, \
        "armed floor no longer kills — the fix disabled the kill switch"


def test_fm11_zero_start_backtest_actually_invests(cfg):
    prices = flat_prices(list(cfg.universe), days=260)
    from conftest import ConstWeights as CW
    result = run_backtest(prices, CW({cfg.universe[0]: 1.0}), cfg, initial_equity=0.0,
                          contribution=lambda d: 100.0 if d.weekday() == 0 else 0.0,
                          is_decision_day=lambda i: i in (5, 40, 80, 120))
    assert not result.halted, "zero-start accumulation run was halted"
    assert result.orders_filled, "contribution stream never produced a trade"


def test_fm10_successful_escalation_stops_there(cfg):
    risk = _mk_risk(cfg)
    prices = {"A": 100.0}
    order = Order(symbol="A", side=Side.SELL, shares=10, limit_price=101.0)
    knobs = PaperBrokerKnobs(scripted_status={order.id: OrderStatus.CANCELLED})
    broker = PaperBroker(cash=10_000.0, prices=prices, cost_model=CostModel(cfg.costs),
                         positions={"A": 10.0}, knobs=knobs)
    outcome = execute_rebalance(broker, risk, [order], prices)
    assert len(broker.submissions) == 2
    assert any(is_success(r.status) for r in outcome.results), \
        "market escalation did not fill — test proves nothing"
