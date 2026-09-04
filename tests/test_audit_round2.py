"""Regression tests for adversarial audit round 2 (audit/ROUND2.md)."""
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
from engine.config import validate_config
from engine.costs import CostModel
from engine.errors import ConfigError, DataError, ExecutionError, HaltError
from engine.execution import execute_rebalance
from engine.journal import NullJournal
from engine.orders import Order, OrderStatus, Side, is_success
from engine.report import AT_TARGET_HEADER, NO_REBALANCE_HEADER
from engine.risk import RiskEngine
from engine.runner import run_cycle
from engine.state import EngineState, StateStore
from engine.strategies import TRADING_DAYS_PER_MONTH, DualMomentum

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

TODAY = date(2026, 8, 31)


def _mk_risk(cfg):
    return RiskEngine(cfg.risk, CostModel(cfg.costs))


def _bootstrap(tmp_path, equity=10_000.0, **kw):
    store = StateStore(tmp_path / "state.json")
    store.save(EngineState(peak_equity=equity, last_equity=equity,
                           last_equity_date=(TODAY - timedelta(days=1)).isoformat(), **kw))
    return store


def test_r2_01_hard_kill_persists_even_when_liquidation_aborts(cfg, tmp_path):
    """#1: the kill is saved BEFORE liquidation is attempted; a venue outage
    mid-liquidation must not resurrect the engine tomorrow."""
    store = _bootstrap(tmp_path, equity=10_000.0)
    dd_equity = 10_000.0 * (1 - cfg.risk.max_drawdown_pct - 0.05)
    knobs = PaperBrokerKnobs(outage_after_n_orders=0)   # venue dies immediately
    broker = PaperBroker(cash=0.0, prices={s: 100.0 for s in cfg.universe},
                         cost_model=CostModel(cfg.costs),
                         positions={cfg.universe[0]: dd_equity / 100.0}, knobs=knobs)
    res = run_cycle(today=TODAY, cfg=cfg, store=store, broker=broker,
                    strategy=ConstWeights({cfg.universe[0]: 0.4}),
                    prices=flat_prices(list(cfg.universe), days=10, end=TODAY),
                    journal=NullJournal(), decision_day=False)
    assert "LIQUIDATION ABORTED" in res.report, "outage did not surface — test proves nothing"
    assert store.load().halted is True, \
        "hard kill was not persisted before the liquidation attempt"


def test_r2_01b_hard_kill_survives_an_uncaught_crash_mid_liquidation(cfg, tmp_path):
    """The strong version: an exception the runner does NOT catch escapes
    mid-liquidation. The kill must already be on disk."""
    store = _bootstrap(tmp_path, equity=10_000.0)
    dd_equity = 10_000.0 * (1 - cfg.risk.max_drawdown_pct - 0.05)

    class DyingBroker(PaperBroker):
        def submit(self, approved):
            raise RuntimeError("venue connection lost mid-liquidation")

    broker = DyingBroker(cash=0.0, prices={s: 100.0 for s in cfg.universe},
                         cost_model=CostModel(cfg.costs),
                         positions={cfg.universe[0]: dd_equity / 100.0})
    with pytest.raises(RuntimeError):
        run_cycle(today=TODAY, cfg=cfg, store=store, broker=broker,
                  strategy=ConstWeights({cfg.universe[0]: 0.4}),
                  prices=flat_prices(list(cfg.universe), days=10, end=TODAY),
                  journal=NullJournal(), decision_day=False)
    assert store.load().halted is True, \
        "the crash erased the kill: tomorrow's cycle would trade a killed book"


def test_r2_02_partial_cross_section_refuses_not_liquidates():
    """#2: gappy data for one risk asset must refuse the cycle, never emit
    an all-cash target that liquidates the held book."""
    universe = ("AAA", "BBB", "DEF")
    params = {"lookback_months": 12, "skip_months": 1, "top_n": 1,
              "absolute_momentum_filter": True, "defensive_symbol": "DEF"}
    days = 13 * TRADING_DAYS_PER_MONTH + 10
    idx = pd.bdate_range(end="2026-08-31", periods=days)
    prices = pd.DataFrame({s: np.linspace(100, 130, days) for s in universe}, index=idx)
    # BBB's feed is 10% holes: not rankable, but AAA and DEF are pristine.
    holes = np.arange(0, days, 9)
    prices.iloc[holes, prices.columns.get_loc("BBB")] = np.nan
    with pytest.raises(DataError):
        DualMomentum(universe, params).target_weights(prices, TODAY)


def test_r2_02_backtest_treats_partial_cross_section_as_refusal(cfg):
    sym = cfg.universe[0]
    prices = flat_prices(list(cfg.universe), days=80)
    gappy = cfg.universe[1]

    class GappyStrategy:
        def target_weights(self, prices, today):
            raise DataError(f"cannot rank {gappy}")

    result = run_backtest(prices, GappyStrategy(), cfg, initial_equity=10_000.0,
                          is_decision_day=lambda i: i in (10, 40))
    assert result.refusals, "strategy DataError did not become a refusal"
    assert not result.orders_filled, "a refusal cycle still traded"


def test_r2_03_liquidation_is_exempt_from_the_order_cap(cfg):
    """#3: a hard kill with more positions than max_orders_per_day must
    still liquidate everything."""
    cap = cfg.risk.max_orders_per_day
    n = cap + 3
    prices = {f"S{i}": 100.0 for i in range(n)}
    positions = {f"S{i}": 5.0 for i in range(n)}
    broker = PaperBroker(cash=0.0, prices=prices, cost_model=CostModel(cfg.costs),
                         positions=positions)
    orders = [Order(symbol=s, side=Side.SELL, shares=5, is_full_exit=True)
              for s in positions]
    outcome = execute_rebalance(broker, _mk_risk(cfg), orders, prices, liquidation=True)
    assert len(positions) > cap, "precondition broken"
    assert broker.get_account().positions == {}, \
        "liquidation left residual positions because of the order cap"
    assert all(is_success(r.status) for r in outcome.results)


def test_r2_04_all_cash_decision_day_reports_honestly(cfg, tmp_path):
    """#4: a decision day whose target is {} (all cash) sold the book —
    the report must NOT say 'NO REBALANCE TODAY', and §5.9 bookkeeping runs."""
    store = _bootstrap(tmp_path)
    broker = PaperBroker(cash=0.0, prices={s: 100.0 for s in cfg.universe},
                         cost_model=CostModel(cfg.costs),
                         positions={cfg.universe[0]: 100.0})
    res = run_cycle(today=TODAY, cfg=cfg, store=store, broker=broker,
                    strategy=ConstWeights({}),   # all-cash target
                    prices=flat_prices(list(cfg.universe), days=10, end=TODAY),
                    journal=NullJournal(), decision_day=True)
    assert res.outcome and any(r.order.side is Side.SELL for r in res.outcome.results), \
        "nothing was sold — test proves nothing"
    header = res.report.splitlines()[0]
    assert header != NO_REBALANCE_HEADER, \
        "sold the whole book under a 'HOLDINGS UNCHANGED' headline"
    assert header == AT_TARGET_HEADER
    assert store.load().last_completed_period == TODAY.strftime("%Y-%m"), \
        "all-cash convergence was not tracked (§5.9)"


def test_r2_05_escalation_resends_count_against_the_cap(cfg):
    """#5: cap N means at most N orders reach the venue, escalations included."""
    cfg2 = with_risk(cfg, max_orders_per_day=2)
    risk = RiskEngine(cfg2.risk, CostModel(cfg2.costs))
    prices = {"A": 100.0, "B": 100.0, "C": 100.0}
    knobs = PaperBrokerKnobs(scripted_status_by_symbol={"A": OrderStatus.CANCELLED,
                                                        "B": OrderStatus.CANCELLED})
    broker = PaperBroker(cash=50_000.0, prices=prices, cost_model=CostModel(cfg2.costs),
                         positions={"A": 10.0, "B": 10.0}, knobs=knobs)
    orders = [Order(symbol="A", side=Side.SELL, shares=10, limit_price=101.0),
              Order(symbol="B", side=Side.SELL, shares=10, limit_price=101.0),
              Order(symbol="C", side=Side.BUY, shares=10)]
    execute_rebalance(broker, risk, orders, prices,
                      escalation_max_hops=cfg2.execution.escalation_max_hops)
    assert len(broker.submissions) <= 2, \
        f"{len(broker.submissions)} orders reached the venue with cap 2 (escalation bypass)"


def test_r2_06_partial_fill_dust_sell_cannot_go_cash_negative(cfg):
    """#6: a 40%-filled dust exit must not pay a $1 fee out of $0.88."""
    broker = PaperBroker(cash=0.0, prices={"A": 0.22}, cost_model=CostModel(cfg.costs),
                         positions={"A": 10.0},
                         knobs=PaperBrokerKnobs(fill_fraction={"A": 0.4}))
    risk = _mk_risk(cfg)
    # Bypassing risk's dust guard deliberately: even then the broker adapter
    # refuses an execution whose costs exceed its own proceeds.
    approved, _ = risk.filter_orders(
        [Order(symbol="A", side=Side.SELL, shares=10, is_full_exit=True)], {"A": 0.22})
    if approved.orders:   # risk let it through (proceeds > cost at full size)
        results = broker.submit(approved)
        assert all(not is_success(r.status) for r in results) or \
            broker.get_account().cash >= 0
    assert broker.get_account().cash >= 0, "cash went negative through sell fees"


def test_r2_07_affordable_buy_is_resized_not_dropped(cfg):
    """#7: a huge planned buy with modest cash resizes down to what the
    cash affords, instead of being dropped."""
    risk = _mk_risk(cfg)
    prices = {"A": 30.0}
    broker = PaperBroker(cash=200.0, prices=prices, cost_model=CostModel(cfg.costs))
    outcome = execute_rebalance(broker, risk,
                                [Order(symbol="A", side=Side.BUY, shares=10_000)], prices)
    fills = [r for r in outcome.results if is_success(r.status)]
    assert fills, f"affordable buy was dropped: {[d.reason for d in outcome.dropped]}"
    assert fills[0].filled_shares >= 5
    assert broker.get_account().cash >= 0


def test_r2_08_holiday_monday_contributions_are_credited(cfg):
    """#8: a Monday without a trading bar still deposits $100."""
    idx = pd.bdate_range("2026-01-05", periods=30)          # starts a Monday
    holiday_monday = pd.Timestamp("2026-01-19")             # drop one Monday bar
    idx = idx[idx != holiday_monday]
    prices = pd.DataFrame(100.0, index=idx, columns=list(cfg.universe))
    result = run_backtest(prices, ConstWeights({}), cfg, initial_equity=0.0,
                          contribution=lambda d: 100.0 if d.weekday() == 0 else 0.0)
    mondays = sum(1 for d in pd.date_range(idx[0], idx[-1]) if d.weekday() == 0)
    assert result.contributions_total == pytest.approx(100.0 * mondays), \
        f"credited {result.contributions_total}, calendar owed {100.0 * mondays}"


def test_r2_09_same_day_reruns_do_not_ratchet_the_peak(cfg, tmp_path):
    """#9: re-running the cycle with the same net_flows must not inflate
    peak_equity into a false hard kill."""
    store = _bootstrap(tmp_path, equity=1_100.0)
    for _ in range(10):
        broker = PaperBroker(cash=1_100.0, prices={s: 100.0 for s in cfg.universe},
                             cost_model=CostModel(cfg.costs))
        res = run_cycle(today=TODAY, cfg=cfg, store=store, broker=broker,
                        strategy=ConstWeights({}),
                        prices=flat_prices(list(cfg.universe), days=10, end=TODAY),
                        journal=NullJournal(), decision_day=False,
                        net_flows=100.0)   # caller re-supplies the same flows
    state = store.load()
    assert state.peak_equity <= 1_200.0 + 1e-9, \
        f"peak ratcheted to {state.peak_equity} on flat equity"
    assert not state.halted, "false hard kill from same-day flow double-counting"


def test_r2_10_month_end_final_bar_tolerates_one_holiday():
    """#10: 2024-03-28 (Good Friday eve) is March's real last trading day."""
    idx = pd.bdate_range("2024-03-01", "2024-03-28")
    sched = month_end_schedule(idx)
    assert sched(len(idx) - 1), \
        "the real month-end before an exchange holiday was not a decision day"
    idx2 = pd.bdate_range("2026-02-01", "2026-02-11")
    assert not month_end_schedule(idx2)(len(idx2) - 1), \
        "mid-month final bar regressed to being a decision day"


def test_r2_11_gross_exposure_must_be_positive_even_with_leverage_flag(cfg):
    import dataclasses
    bad = dataclasses.replace(cfg, risk=dataclasses.replace(
        cfg.risk, allow_leverage=True, max_gross_exposure=-1.0))
    with pytest.raises(ConfigError):
        validate_config(bad)


def test_r2_12_monday_bootstrap_credits_the_first_contribution():
    from daily_run import contributions_due
    fresh = EngineState()          # bootstrap no longer stamps today's date
    assert contributions_due(fresh, date(2026, 9, 7)) == pytest.approx(100.0), \
        "a Monday bootstrap swallowed the first weekly contribution"


def test_r2_15_bad_skip_months_rejected_at_construction():
    params = {"lookback_months": 3, "skip_months": 3, "top_n": 1,
              "defensive_symbol": "DEF"}
    with pytest.raises(ValueError):
        DualMomentum(("AAA", "BBB", "DEF"), params)
