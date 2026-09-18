"""Tests for the historical paper-trading harness (mini_prop_os/sim.py).

Fast synthetic runs only — the full historical scorecard lives in
scripts/validate_minipropos.py and also runs in CI.
"""

from __future__ import annotations

import pytest

from mini_prop_os.core.config import RiskConfig
from mini_prop_os.risk.guardrails import RiskGuardrails
from mini_prop_os.sim import (HistoricalSession, SimConfig, bars_from_closes,
                              run_session)
from mini_prop_os.strategy.ema_crossover import EmaCrossoverStrategy

SYMBOL = "MES"

DOWN = [5000 - 3 * i for i in range(80)]
UP = [4760 + 12 * i for i in range(40)]
DOWN2 = [5240 - 15 * i for i in range(40)]


def make_session(**risk_kw) -> HistoricalSession:
    strategy = EmaCrossoverStrategy(SYMBOL, 9, 21, order_quantity=1)
    risk = RiskGuardrails(RiskConfig(**risk_kw) if risk_kw else RiskConfig())
    return HistoricalSession(strategy, risk, SimConfig())


def test_round_trip_through_real_pipeline():
    session = make_session()
    res = run_session(session, bars_from_closes(DOWN + UP + DOWN2, SYMBOL))
    assert res.max_position == 1
    assert res.min_position == 0          # long-only held
    assert res.final_position == 0
    assert len(res.round_trips) == 1
    assert res.round_trips[0].pnl > 0     # caught the up-trend
    assert res.accounting_error < 0.01
    assert res.open_orders_at_end == 0


def test_kill_switch_flattens_and_latches():
    closes = DOWN + UP + [5240, 4700] + [4690 + 5 * i for i in range(60)]
    session = make_session()
    res = run_session(session, bars_from_closes(closes, SYMBOL))
    assert res.kill_switch_tripped
    assert res.position_after_kill == 0
    assert res.final_position == 0        # later golden cross ignored
    assert res.orders_after_kill == 0
    assert session.risk.kill_switch_active


def test_partial_fill_execution_reconciles():
    session_strategy = EmaCrossoverStrategy(SYMBOL, 9, 21, order_quantity=4)
    risk = RiskGuardrails(RiskConfig(
        max_position_shares=10, max_order_quantity=10,
        max_position_notional=500_000.0, max_gross_notional=500_000.0))
    session = HistoricalSession(session_strategy, risk, SimConfig())
    res = run_session(session, bars_from_closes(DOWN + UP + DOWN2, SYMBOL))
    filled = [o for o in session.oms.orders.values()
              if o.filled_quantity > 0]
    assert filled and all(o.remaining_quantity == 0 for o in filled)
    assert res.accounting_error < 0.01


def test_fills_use_next_bar_open_with_adverse_slippage():
    session = make_session()
    run_session(session, bars_from_closes(DOWN + UP, SYMBOL))
    buys = [o for o in session.oms.orders.values()
            if o.filled_quantity > 0]
    assert buys
    # 1 tick of adverse slippage on a buy: fill >= the open it filled at.
    cfg = session.sim_cfg
    for mo in buys:
        assert mo.avg_fill_price % cfg.tick_size == pytest.approx(0.0)


def test_bars_from_closes_are_valid_and_open_is_prev_close():
    bars = bars_from_closes([100.0, 101.0, 99.5], SYMBOL)
    assert bars[1].open == 100.0
    assert bars[2].open == 101.0
    for b in bars:
        assert b.low <= b.open <= b.high
        assert b.low <= b.close <= b.high
