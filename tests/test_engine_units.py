"""Unit tests: config validation, state atomicity, costs, clamps, runner."""
from __future__ import annotations

import dataclasses
from datetime import date, timedelta

import pytest

from conftest import CONFIG_PATH, ConstWeights, flat_prices, with_costs
from engine.broker import PaperBroker
from engine.config import load_config, validate_config
from engine.costs import CostModel
from engine.errors import ConfigError, HaltError
from engine.journal import NullJournal
from engine.report import AT_TARGET_HEADER, NOT_AT_TARGET_HEADER
from engine.runner import run_cycle
from engine.state import EngineState, StateStore

TODAY = date(2026, 8, 31)


# ---- config ---------------------------------------------------------------

def test_config_loads_and_validates(cfg):
    assert cfg.universe
    assert cfg.execution.escalation_max_hops == 1


def test_config_rejects_escalation_chain(cfg):
    bad = dataclasses.replace(cfg, execution=dataclasses.replace(cfg.execution,
                                                                 escalation_max_hops=2))
    with pytest.raises(ConfigError):
        validate_config(bad)


def test_config_rejects_unverified_proportional(cfg):
    bad = with_costs(cfg, fee_model="proportional", proportional_rate=0.0)
    with pytest.raises(ConfigError):
        validate_config(bad)


def test_config_rejects_leverage_without_flag(cfg):
    bad = dataclasses.replace(cfg, risk=dataclasses.replace(
        cfg.risk, max_gross_exposure=2.0, allow_leverage=False))
    with pytest.raises(ConfigError):
        validate_config(bad)


def test_config_missing_file():
    with pytest.raises(ConfigError):
        load_config(CONFIG_PATH.parent / "nope.toml")


# ---- state ----------------------------------------------------------------

def test_state_roundtrip_and_backup(tmp_path):
    store = StateStore(tmp_path / "s.json")
    s1 = EngineState(peak_equity=123.45, positions={"A": 3.0}, cash=10.0)
    store.save(s1)
    s2 = store.load()
    assert s2 == s1
    store.save(EngineState(peak_equity=200.0))
    assert store.backup_path.exists(), "previous good state not kept as backup"
    assert not store.path.with_suffix(store.path.suffix + ".tmp").exists(), \
        "temp file left behind — write is not atomic"


def test_state_checksum_detects_tampering(tmp_path):
    store = StateStore(tmp_path / "s.json")
    store.save(EngineState(peak_equity=100.0))
    raw = store.path.read_text().replace("100.0", "999.0")
    store.path.write_text(raw)
    # Tampered main with no backup must refuse, not return 999.
    from engine.errors import StateError
    with pytest.raises(StateError):
        store.load()


# ---- costs ----------------------------------------------------------------

def test_fixed_minimum_fee_applies(cfg, cost_model):
    c = cost_model.order_cost(shares=1, price=50.0)
    assert c.commission == pytest.approx(cfg.costs.fixed_min_fee)
    big = cost_model.order_cost(shares=1000, price=50.0)
    assert big.commission == pytest.approx(
        max(cfg.costs.fixed_min_fee, cfg.costs.per_share_fee * 1000))


def test_spread_and_slippage_separate_from_commission(cost_model):
    c = cost_model.order_cost(shares=100, price=50.0)
    assert c.spread_cost > 0 and c.slippage_cost > 0
    assert c.total == pytest.approx(c.commission + c.spread_cost + c.slippage_cost)


# ---- risk clamps ----------------------------------------------------------

def test_clamp_respects_config_position_cap(cfg, risk):
    # 2x the cap in, cap out — holds for any configured cap value.
    w = risk.clamp_weights({cfg.universe[0]: cfg.risk.max_position_weight * 2})
    assert w[cfg.universe[0]] == pytest.approx(
        min(cfg.risk.max_position_weight, cfg.risk.max_gross_exposure))


def test_halted_state_raises(cfg, risk):
    with pytest.raises(HaltError):
        risk.check_not_halted(EngineState(halted=True, halt_reason="test"))


def test_hard_kill_on_drawdown(cfg, risk):
    peak = 10_000.0
    dd_equity = peak * (1 - cfg.risk.max_drawdown_pct - 0.05)
    prior = EngineState(peak_equity=peak, last_equity=dd_equity,
                        last_equity_date=(TODAY - timedelta(days=1)).isoformat())
    res = risk.pre_trade(prior, dd_equity, TODAY)
    from engine.risk import PreTradeDecision
    assert res.decision is PreTradeDecision.HARD_KILL


# ---- runner + report ------------------------------------------------------

def _bootstrap(tmp_path, equity=10_000.0):
    store = StateStore(tmp_path / "state.json")
    store.save(EngineState(peak_equity=equity, last_equity=equity,
                           last_equity_date=(TODAY - timedelta(days=1)).isoformat()))
    return store


def test_runner_full_cycle_converges_and_reports_at_target(cfg, tmp_path):
    store = _bootstrap(tmp_path)
    sym = cfg.universe[0]
    prices = flat_prices(list(cfg.universe), days=10, end=TODAY)
    broker = PaperBroker(cash=10_000.0, prices={s: 100.0 for s in cfg.universe},
                         cost_model=CostModel(cfg.costs))
    res = run_cycle(today=TODAY, cfg=cfg, store=store, broker=broker,
                    strategy=ConstWeights({sym: 0.4}), prices=prices,
                    journal=NullJournal(), decision_day=True)
    assert res.traded, "no trade happened — test proves nothing"
    assert res.report.splitlines()[0] == AT_TARGET_HEADER
    state = store.load()
    assert state.last_completed_period == TODAY.strftime("%Y-%m")

    # Second cycle in the same period must NOT re-trade (§5.9).
    n_before = len(broker.submissions)
    res2 = run_cycle(today=TODAY, cfg=cfg, store=store, broker=broker,
                     strategy=ConstWeights({sym: 0.4}), prices=prices,
                     journal=NullJournal(), decision_day=True)
    assert not res2.traded
    assert len(broker.submissions) == n_before, "re-traded an already-converged period"


def test_runner_halted_refuses(cfg, tmp_path):
    store = StateStore(tmp_path / "state.json")
    store.save(EngineState(halted=True, halt_reason="hard kill",
                           last_equity=1.0, last_equity_date="2026-08-30"))
    broker = PaperBroker(cash=10_000.0, prices={s: 100.0 for s in cfg.universe},
                         cost_model=CostModel(cfg.costs))
    with pytest.raises(HaltError):
        run_cycle(today=TODAY, cfg=cfg, store=store, broker=broker,
                  strategy=ConstWeights({}), prices=flat_prices(list(cfg.universe), days=10, end=TODAY),
                  journal=NullJournal(), decision_day=True)


def test_report_headers_are_distinct():
    assert AT_TARGET_HEADER != NOT_AT_TARGET_HEADER
    assert "NOT" in NOT_AT_TARGET_HEADER and "NOT" not in AT_TARGET_HEADER
