"""Backtester on synthetic data with known properties (§4 Phase 3)."""
from __future__ import annotations

import pytest

from conftest import ConstWeights, flat_prices, synth_prices
from engine.backtest import run_backtest


def test_no_trades_equity_equals_contributions(cfg):
    prices = flat_prices(list(cfg.universe), days=100)
    result = run_backtest(prices, ConstWeights({}), cfg, initial_equity=1_000.0,
                          contribution=lambda d: 100.0 if d.weekday() == 0 else 0.0)
    assert not result.orders_filled
    assert result.contributions_total > 0, "no contributions landed — test proves nothing"
    assert result.equity.iloc[-1] == pytest.approx(1_000.0 + result.contributions_total)
    assert result.costs_paid == 0.0


def test_flat_market_loses_exactly_costs(cfg):
    sym = cfg.universe[0]
    prices = flat_prices(list(cfg.universe), days=200)
    result = run_backtest(prices, ConstWeights({sym: 0.4}), cfg, initial_equity=10_000.0)
    assert result.orders_filled, "no trades — test proves nothing"
    assert result.costs_paid > 0
    assert result.equity.iloc[-1] == pytest.approx(10_000.0 - result.costs_paid)


def test_uptrend_is_captured(cfg):
    sym = cfg.universe[0]
    prices = flat_prices(list(cfg.universe), days=250)
    # Deterministic 60% rise over the series for one symbol.
    import numpy as np
    prices[sym] = 100.0 * np.linspace(1.0, 1.6, len(prices))
    result = run_backtest(prices, ConstWeights({sym: 0.4}), cfg, initial_equity=10_000.0)
    assert result.orders_filled, "no trades — test proves nothing"
    assert result.equity.iloc[-1] > 10_000.0, "held a rising asset and made nothing"


def test_hard_kill_liquidates_and_stays_halted(cfg):
    sym = cfg.universe[0]
    prices = flat_prices(list(cfg.universe), days=200)
    crash_at = 120
    # Deep enough that the BOOK's drawdown (position weight x asset drop)
    # clears the configured kill limit with margin.
    asset_drop = min(0.95, (cfg.risk.max_drawdown_pct + 0.10) / cfg.risk.max_position_weight)
    prices.iloc[crash_at:, prices.columns.get_loc(sym)] = 100.0 * (1 - asset_drop)

    result = run_backtest(
        prices, ConstWeights({sym: cfg.risk.max_position_weight}), cfg,
        initial_equity=10_000.0,
        # Decide early (build position), then repeatedly after the crash.
        is_decision_day=lambda i: i in (10, 125, 130, 150, 190))
    assert any(r.order.symbol == sym for r in result.orders_filled), \
        "position never opened — test proves nothing"
    assert result.halted, "drawdown beyond the hard-kill limit did not halt"
    assert result.final_positions.get(sym, 0.0) == 0.0, "halt did not liquidate"
    assert result.halts, "halt event was not recorded"


def test_soft_halt_stands_down_for_the_day(cfg):
    sym = cfg.universe[0]
    prices = flat_prices(list(cfg.universe), days=100)
    drop_at = 50
    drop = 2 * cfg.risk.max_daily_loss_pct
    # One-day drop big enough to trip the soft halt but tiny vs drawdown kill:
    # position is small, so equity moves less than the asset. Make it bigger:
    prices.iloc[drop_at:, prices.columns.get_loc(sym)] = 100.0 * (1 - drop / 0.4)

    result = run_backtest(
        prices, ConstWeights({sym: 0.4}), cfg, initial_equity=10_000.0,
        is_decision_day=lambda i: i in (10, drop_at))
    stand_downs = [h for h in result.halts if "daily loss" in h[1]]
    assert stand_downs, "daily loss beyond the limit did not stand down"
    assert not result.halted, "soft halt escalated to a permanent halt"


def test_contributions_are_invested_over_time(cfg):
    sym = cfg.universe[0]
    prices = flat_prices(list(cfg.universe), days=260)
    result = run_backtest(
        prices, ConstWeights({sym: cfg.risk.max_position_weight}), cfg,
        initial_equity=0.0,
        contribution=lambda d: 100.0 if d.weekday() == 0 else 0.0)
    assert result.contributions_total >= 4_000.0
    assert result.final_positions.get(sym, 0.0) > 0, \
        "a contribution stream never produced a position"
