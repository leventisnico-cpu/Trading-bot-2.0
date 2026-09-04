"""Regression tests for adversarial audit round 1 (audit/ROUND1.md).

Each test is named for its finding number and fails against the
pre-fix code (the audit's repro scripts in audit/ prove that).
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from conftest import ConstWeights, flat_prices, with_risk
from engine.backtest import month_end_schedule, run_backtest
from engine.broker import PaperBroker, PaperBrokerKnobs
from engine.costs import CostModel
from engine.errors import DataError, StateError
from engine.execution import execute_rebalance
from engine.journal import Journal, NullJournal
from engine.orders import Order, OrderStatus, Side
from engine.portfolio import compute_orders
from engine.report import NO_REBALANCE_HEADER
from engine.risk import PreTradeDecision, RiskEngine
from engine.runner import run_cycle
from engine.state import EngineState, StateStore

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

TODAY = date(2026, 8, 31)


def _mk_risk(cfg):
    return RiskEngine(cfg.risk, CostModel(cfg.costs))


def _bootstrap(tmp_path, equity=10_000.0):
    store = StateStore(tmp_path / "state.json")
    store.save(EngineState(peak_equity=equity, last_equity=equity,
                           last_equity_date=(TODAY - timedelta(days=1)).isoformat()))
    return store


def test_a01_order_cap_enforced_on_the_real_execution_path(cfg):
    """#1: the cap must bind in execute_rebalance, not only in a helper."""
    cap = cfg.risk.max_orders_per_day
    n = cap + 5
    prices = {f"S{i}": 100.0 for i in range(n)}
    broker = PaperBroker(cash=1e6, prices=prices, cost_model=CostModel(cfg.costs))
    orders = [Order(symbol=f"S{i}", side=Side.BUY, shares=2) for i in range(n)]
    outcome = execute_rebalance(broker, _mk_risk(cfg), orders, prices)
    assert len(orders) > cap, "precondition broken: not enough orders to exceed the cap"
    assert len(broker.submissions) <= cap, \
        f"{len(broker.submissions)} orders reached the broker; cap is {cap}"
    assert any("cap" in d.reason for d in outcome.dropped), "cap drops not recorded"


def test_a02_decision_day_is_calendar_month_end():
    """#2: the paper job must decide on the LAST business day of the month,
    from the calendar — not 'the newest bar fetched so far'."""
    from daily_run import is_last_trading_day_of_month
    idx = pd.bdate_range("2026-08-01", "2026-08-12")   # fetched data ends 'today'
    assert not is_last_trading_day_of_month(date(2026, 8, 3), idx), \
        "first trading day of the month classified as the last"
    assert not is_last_trading_day_of_month(date(2026, 8, 12), idx)
    assert is_last_trading_day_of_month(date(2026, 8, 31), pd.bdate_range("2026-08-01", "2026-08-31"))


def test_a03_backtest_hard_kills_between_decision_days(cfg):
    """#3: kill switches run every bar in the backtest, exactly as live."""
    sym = cfg.universe[0]
    prices = flat_prices(list(cfg.universe), days=120)
    crash_at = 60   # NOT a decision day
    drop = min(0.95, (cfg.risk.max_drawdown_pct + 0.10) / cfg.risk.max_position_weight)
    prices.iloc[crash_at:, prices.columns.get_loc(sym)] = 100.0 * (1 - drop)
    result = run_backtest(prices, ConstWeights({sym: cfg.risk.max_position_weight}), cfg,
                          initial_equity=10_000.0,
                          is_decision_day=lambda i: i == 10)   # only one decision, long before
    assert any(r.order.symbol == sym for r in result.orders_filled), \
        "position never opened — test proves nothing"
    assert result.halted, \
        "a drawdown past the kill limit between decision days did not halt the backtest"
    assert result.final_positions.get(sym, 0.0) == 0.0, "hard kill did not liquidate"


def test_a05_nan_close_on_fill_day_does_not_crater_equity(cfg):
    """#5: a held symbol with one missing close keeps its last mark."""
    syms = list(cfg.universe)
    held, other = syms[0], syms[1]
    prices = flat_prices(syms, days=80)
    nan_day = 42
    prices.iloc[nan_day, prices.columns.get_loc(held)] = np.nan
    result = run_backtest(prices, ConstWeights({held: 0.5, other: 0.4}), cfg,
                          initial_equity=10_000.0,
                          is_decision_day=lambda i: i in (10, nan_day - 1))
    eq = result.equity
    day_move = abs(eq.iloc[nan_day] - eq.iloc[nan_day - 1])
    assert result.final_positions.get(held, 0) > 0, "position never held — test proves nothing"
    assert day_move < 500, \
        f"equity moved {day_move:,.0f} on a flat day with one NaN close — marked at $0"


def test_a06_dust_exit_refused_instead_of_negative_cash(cfg):
    """#6: closing a position whose exit costs more than it is worth must be
    refused (dust), not fill into negative cash."""
    risk = _mk_risk(cfg)
    prices = {"A": 0.50}
    order = Order(symbol="A", side=Side.SELL, shares=1, is_full_exit=True)
    approved, dropped = risk.filter_orders([order], prices)
    assert not approved.orders, "a costs-more-than-it's-worth exit was approved"
    assert any("dust" in d.reason for d in dropped)

    # A normal full exit (worth more than its cost) still goes through.
    ok = Order(symbol="B", side=Side.SELL, shares=1, is_full_exit=True)
    approved2, _ = risk.filter_orders([ok], {"B": 50.0})
    assert approved2.orders, "ordinary full exits must still be exempt from size filters"


def test_a07_buys_resize_after_partial_fills_consume_cash(cfg):
    """#7: cash consumed by a partial fill must be seen by the next buy's
    sizing (re-read, not tracked), so it resizes instead of being rejected."""
    risk = _mk_risk(cfg)
    prices = {"A": 100.0, "B": 100.0}
    knobs = PaperBrokerKnobs(fill_fraction={"A": 0.6})
    broker = PaperBroker(cash=1_000.0, prices=prices, cost_model=CostModel(cfg.costs),
                         knobs=knobs)
    orders = [Order(symbol="A", side=Side.BUY, shares=5),
              Order(symbol="B", side=Side.BUY, shares=5)]
    outcome = execute_rebalance(broker, risk, orders, prices)
    partials = [r for r in outcome.results if r.status is OrderStatus.PARTIALLY_FILLED]
    assert partials, "no partial fill occurred — test proves nothing"
    b_results = [r for r in outcome.results if r.order.symbol == "B"]
    assert b_results and all(r.status is not OrderStatus.REJECTED for r in b_results), \
        "the follow-on buy was rejected wholesale instead of sized to confirmed cash"
    assert broker.get_account().cash >= 0


def test_a08_ordinary_day_report_does_not_cry_wolf(cfg, tmp_path):
    """#8: a converged portfolio on a no-decision day must not headline
    'NOT AT TARGET'."""
    store = _bootstrap(tmp_path)
    broker = PaperBroker(cash=5_000.0, prices={s: 100.0 for s in cfg.universe},
                         cost_model=CostModel(cfg.costs),
                         positions={cfg.universe[0]: 20.0})
    res = run_cycle(today=TODAY, cfg=cfg, store=store, broker=broker,
                    strategy=ConstWeights({cfg.universe[0]: 0.4}),
                    prices=flat_prices(list(cfg.universe), days=10, end=TODAY),
                    journal=NullJournal(), decision_day=False)
    assert res.report.splitlines()[0] == NO_REBALANCE_HEADER, res.report.splitlines()[0]


def test_a09_new_month_resets_the_retry_counter(cfg, tmp_path):
    """#9: one bad month must not soft-brick every future month."""
    store = StateStore(tmp_path / "state.json")
    store.save(EngineState(peak_equity=10_000.0, last_equity=10_000.0,
                           last_equity_date=(TODAY - timedelta(days=1)).isoformat(),
                           rebalance_retries=cfg.risk.max_rebalance_retries,
                           retry_period="2026-07"))
    broker = PaperBroker(cash=10_000.0, prices={s: 100.0 for s in cfg.universe},
                         cost_model=CostModel(cfg.costs))
    res = run_cycle(today=TODAY, cfg=cfg, store=store, broker=broker,
                    strategy=ConstWeights({cfg.universe[0]: 0.4}),
                    prices=flat_prices(list(cfg.universe), days=10, end=TODAY),
                    journal=NullJournal(), decision_day=True)
    assert res.traded, "a fresh month's rebalance was refused because of LAST month's retries"
    assert "LOUD WARNING" not in res.report


def test_a10_deposits_do_not_mask_a_daily_loss(cfg):
    """#10: a -15% market day with a deposit must still stand down."""
    risk = _mk_risk(cfg)
    prior = EngineState(peak_equity=1_000.0, last_equity=1_000.0,
                        last_equity_date=(TODAY - timedelta(days=1)).isoformat())
    market_loss = 2 * cfg.risk.max_daily_loss_pct
    deposit = 100.0
    equity_today = 1_000.0 * (1 - market_loss) + deposit
    res = risk.pre_trade(prior, equity_today, TODAY, net_flows=deposit)
    assert res.daily_return == pytest.approx(-market_loss), \
        "the deposit leaked into the measured daily return"
    assert res.decision is PreTradeDecision.STAND_DOWN

    # And a deposit alone must not fire anything.
    calm = risk.pre_trade(prior, 1_000.0 + deposit, TODAY, net_flows=deposit)
    assert calm.decision is PreTradeDecision.OK


def test_a11_zero_equity_decision_day_does_not_crash(cfg, tmp_path):
    """#11: the documented deployment shape ($0 start) on a decision day."""
    store = StateStore(tmp_path / "state.json")
    store.save(EngineState(last_equity_date=(TODAY - timedelta(days=1)).isoformat()))
    broker = PaperBroker(cash=0.0, prices={s: 100.0 for s in cfg.universe},
                         cost_model=CostModel(cfg.costs))
    res = run_cycle(today=TODAY, cfg=cfg, store=store, broker=broker,
                    strategy=ConstWeights({cfg.universe[0]: 0.4}),
                    prices=flat_prices(list(cfg.universe), days=10, end=TODAY),
                    journal=NullJournal(), decision_day=True)
    assert not res.traded
    assert "no capital yet" in res.report


def test_a12_journal_keeps_fills_from_an_aborted_rebalance(cfg, tmp_path):
    """#12: fills that really executed must be journaled even when the
    rebalance aborts mid-flight."""
    risk = _mk_risk(cfg)
    prices = {"A": 100.0, "B": 100.0}
    knobs = PaperBrokerKnobs(outage_after_n_orders=1)
    broker = PaperBroker(cash=5_000.0, prices=prices, cost_model=CostModel(cfg.costs),
                         positions={"A": 10.0}, knobs=knobs)
    journal = Journal(tmp_path / "journal.jsonl")
    orders = [Order(symbol="A", side=Side.SELL, shares=10, is_full_exit=True),
              Order(symbol="B", side=Side.BUY, shares=10)]
    from engine.errors import ExecutionError
    with pytest.raises(ExecutionError):
        execute_rebalance(broker, risk, orders, prices, journal=journal)
    assert broker.get_account().positions.get("A") is None, \
        "the sell never filled — test proves nothing"
    text = (tmp_path / "journal.jsonl").read_text()
    assert '"order_result"' in text and '"A"' in text, \
        "the executed sell left no trace in the journal"


def test_a13_target_that_floors_to_zero_shares_is_a_full_exit(cfg):
    """#13: FM#4 variant — nonzero target weight, zero target shares."""
    # weight 0.005 of $10,000 = $50 targeted, price $60 -> floors to 0 shares
    orders = compute_orders({"A": 3.0}, {"A": 0.005}, {"A": 60.0}, 10_000.0,
                            no_trade_band=cfg.risk.no_trade_band)
    assert (0.005 * 10_000.0) / 60.0 < 1, "precondition broken: target does not floor to 0"
    assert len(orders) == 1
    assert orders[0].side is Side.SELL and orders[0].is_full_exit, \
        "a sell of the entire position was not flagged is_full_exit"


def test_a14_dataset_ending_mid_month_is_not_a_decision_day():
    """#14: the final bar only counts if it IS the month's last bday."""
    idx = pd.bdate_range("2026-01-01", "2026-02-11")
    sched = month_end_schedule(idx)
    flagged = [idx[i].date() for i in range(len(idx)) if sched(i)]
    assert date(2026, 1, 30) in flagged
    assert date(2026, 2, 11) not in flagged, "mid-month final bar treated as month-end"
    idx2 = pd.bdate_range("2026-01-01", "2026-01-30")
    sched2 = month_end_schedule(idx2)
    assert sched2(len(idx2) - 1), "a genuine month-end final bar must still count"


def test_a15_torn_state_now_always_refuses(cfg, tmp_path):
    """#4 (strict semantics): corrupt main NEVER silently falls back to the
    stale backup — a human restores it deliberately."""
    store = StateStore(tmp_path / "state.json")
    store.save(EngineState(halted=False))
    store.save(EngineState(halted=True, halt_reason="hard kill"))
    raw = store.path.read_text()
    store.path.write_text(raw[: len(raw) // 3])   # tear BEFORE the halted bytes
    with pytest.raises(StateError):
        store.load()


def test_a16_nan_target_weight_refuses_not_crashes(cfg):
    risk = _mk_risk(cfg)
    with pytest.raises(DataError):
        risk.clamp_weights({"A": float("nan")})
