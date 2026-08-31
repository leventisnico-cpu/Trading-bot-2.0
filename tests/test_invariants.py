"""§3 invariants — each test fails if the enforcement is removed."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from conftest import ConstWeights, Top1TrailingReturn, flat_prices, synth_prices, with_costs, with_risk
from engine.backtest import run_backtest
from engine.broker import PaperBroker
from engine.costs import CostModel
from engine.orders import Order, Side
from engine.risk import ApprovedOrders, RiskEngine


def test_inv1_no_lookahead_bit_identical_before_tamper_date(cfg):
    """§3.1 required test: multiply all prices after T by 5; the equity
    curve at and before T must be bit-identical."""
    prices = synth_prices(cfg.universe, days=300, seed=42)
    T = prices.index[200]
    tampered = prices.copy()
    tampered.loc[tampered.index > T] *= 5.0

    strat = Top1TrailingReturn(lookback=60)
    base = run_backtest(prices, strat, cfg, initial_equity=10_000.0)
    tamp = run_backtest(tampered, Top1TrailingReturn(lookback=60), cfg, initial_equity=10_000.0)

    # Precondition: the tamper actually changed the world after T.
    assert not tamp.equity.loc[tamp.equity.index > T].equals(
        base.equity.loc[base.equity.index > T]) or (
        tamp.final_positions == {} and base.final_positions == {}), \
        "tamper had no effect at all — test proves nothing"
    before_base = base.equity.loc[:T].to_numpy()
    before_tamp = tamp.equity.loc[:T].to_numpy()
    assert np.array_equal(before_base, before_tamp), \
        "equity before T changed when only prices after T changed — lookahead exists"


def test_inv2_decisions_fill_at_next_bar(cfg):
    """§3.2: decisions on bar t fill at bar t+1, not bar t."""
    sym = cfg.universe[0]
    prices = flat_prices(list(cfg.universe), days=40, price=100.0)
    # Decision day at position 20; the NEXT bar jumps to 120.
    prices.iloc[21:, prices.columns.get_loc(sym)] = 120.0
    decision_pos = 20

    result = run_backtest(
        prices, ConstWeights({sym: cfg.risk.max_position_weight}), cfg,
        initial_equity=10_000.0,
        is_decision_day=lambda i: i == decision_pos)

    fills = [r for r in result.orders_filled if r.order.symbol == sym]
    assert fills, "no fill occurred — test proves nothing"
    assert fills[0].fill_price == pytest.approx(120.0), \
        f"filled at {fills[0].fill_price}, i.e. the decision bar's price — execution lag missing"


def test_inv3_backtest_applies_live_constraints_parity(cfg):
    """§3.3: position caps and minimum order sizes bind in the backtest
    exactly as live — a strategy asking for 100% gets the config cap."""
    sym = cfg.universe[0]
    prices = flat_prices(list(cfg.universe), days=120)
    result = run_backtest(prices, ConstWeights({sym: 1.0}), cfg, initial_equity=10_000.0)

    assert result.orders_filled, "nothing traded — test proves nothing"
    final_notional = result.final_positions.get(sym, 0.0) * 100.0
    final_equity = result.equity.iloc[-1]
    weight = final_notional / final_equity
    assert weight <= cfg.risk.max_position_weight + 0.02, \
        f"backtest holds {weight:.1%} > max_position_weight {cfg.risk.max_position_weight:.1%}"


def test_inv3_min_order_notional_binds_in_backtest(cfg):
    sym = cfg.universe[0]
    cfg2 = with_risk(cfg, min_order_notional=1e9)  # nothing can pass
    prices = flat_prices(list(cfg.universe), days=80)
    result = run_backtest(prices, ConstWeights({sym: 0.4}), cfg2, initial_equity=10_000.0)
    assert not result.orders_filled, "an order filled despite an impossible minimum — no parity"
    assert result.orders_dropped, "orders were not even generated — test proves nothing"


def test_inv4_no_shorting_no_leverage_structurally(cfg, risk):
    """§3.4: clamped, not avoided. Hostile weights cannot produce shorts
    or leverage."""
    hostile = {s: (2.0 if i == 0 else -1.0) for i, s in enumerate(cfg.universe)}
    clamped = risk.clamp_weights(hostile)
    assert all(w >= 0 for w in clamped.values()), "short weight survived the clamp"
    assert sum(abs(w) for w in clamped.values()) <= min(1.0, cfg.risk.max_gross_exposure) + 1e-9

    # Gross-exposure clamp must bind on its own: every symbol at the
    # per-position cap sums well past 1.0 and must be scaled back down.
    levered = {s: cfg.risk.max_position_weight for s in cfg.universe}
    assert sum(levered.values()) > min(1.0, cfg.risk.max_gross_exposure), \
        "precondition broken: config cannot express gross > cap; add symbols"
    scaled = risk.clamp_weights(levered)
    gross = sum(abs(w) for w in scaled.values())
    assert gross <= min(1.0, cfg.risk.max_gross_exposure) + 1e-9, \
        f"gross exposure {gross:.2f} survived the clamp — leverage is possible"

    # And through a full backtest: cash never negative, positions never short.
    prices = flat_prices(list(cfg.universe), days=100)
    result = run_backtest(prices, ConstWeights(hostile), cfg, initial_equity=5_000.0)
    assert result.final_cash >= 0
    assert all(sh >= 0 for sh in result.final_positions.values())


def test_inv5_costs_scale_dependent_fixed_fees(cfg):
    """§3.5/§6: initial_equity is a real input — fixed per-order fees drag
    a small account harder than a large one."""
    assert cfg.costs.fee_model == "fixed_per_order", "config no longer fixed-fee; update test"
    prices = flat_prices(list(cfg.universe), days=260)
    strat = {cfg.universe[0]: cfg.risk.max_position_weight}
    small = run_backtest(prices, ConstWeights(strat), cfg, initial_equity=2_500.0)
    large = run_backtest(prices, ConstWeights(strat), cfg, initial_equity=100_000.0)
    assert small.orders_filled and large.orders_filled, "no trades — test proves nothing"
    small_drag = small.costs_paid / 2_500.0
    large_drag = large.costs_paid / 100_000.0
    assert small_drag > large_drag, \
        "fixed fees showed no scale dependence — cost model is behaving like flat bps"


def test_inv6_no_path_to_broker_bypasses_risk(cfg, cost_model):
    """§3.6: brokers only accept ApprovedOrders; only RiskEngine mints them."""
    broker = PaperBroker(cash=1000.0, prices={"X": 10.0}, cost_model=cost_model)
    raw = [Order(symbol="X", side=Side.BUY, shares=5)]
    with pytest.raises(TypeError):
        broker.submit(raw)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        ApprovedOrders(raw)  # cannot be constructed outside the risk engine
    with pytest.raises(TypeError):
        ApprovedOrders(raw, token=object())


def test_inv5_proportional_fees_scale_neutral(cfg):
    """The other fee shape: proportional costs are the same fraction at any
    size (this is what makes turnover, not account size, the binding
    constraint on proportional venues)."""
    cfg2 = with_costs(cfg, fee_model="proportional", proportional_rate=0.0040)
    model = CostModel(cfg2.costs)
    f_small = model.all_in_fraction(shares=10, price=10.0)
    f_large = model.all_in_fraction(shares=10_000, price=10.0)
    assert f_small == pytest.approx(f_large), "proportional fees must be scale-neutral"
