"""Shared fixtures. Thresholds come from config/engine.toml (§8) — tests
derive scenarios from those values instead of hardcoding their own copies.
"""
from __future__ import annotations

import dataclasses
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from engine.config import EngineConfig, load_config
from engine.costs import CostModel
from engine.risk import RiskEngine

REPO = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO / "config" / "engine.toml"


@pytest.fixture(scope="session")
def cfg() -> EngineConfig:
    return load_config(CONFIG_PATH)


def with_risk(cfg: EngineConfig, **kw) -> EngineConfig:
    return dataclasses.replace(cfg, risk=dataclasses.replace(cfg.risk, **kw))


def with_costs(cfg: EngineConfig, **kw) -> EngineConfig:
    return dataclasses.replace(cfg, costs=dataclasses.replace(cfg.costs, **kw))


@pytest.fixture
def cost_model(cfg) -> CostModel:
    return CostModel(cfg.costs)


@pytest.fixture
def risk(cfg, cost_model) -> RiskEngine:
    return RiskEngine(cfg.risk, cost_model)


def synth_prices(symbols, days=400, seed=0, drift=0.0004, vol=0.01, start=100.0,
                 start_date="2020-01-02") -> pd.DataFrame:
    """Geometric random walk with known properties (§4 Phase 3)."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start_date, periods=days)
    rets = rng.normal(drift, vol, size=(days, len(symbols)))
    prices = start * np.exp(np.cumsum(rets, axis=0))
    return pd.DataFrame(prices, index=idx, columns=list(symbols))


def flat_prices(symbols, days=300, price=100.0, end=None) -> pd.DataFrame:
    if end is not None:
        idx = pd.bdate_range(end=end, periods=days)
    else:
        idx = pd.bdate_range("2020-01-02", periods=days)
    return pd.DataFrame(price, index=idx, columns=list(symbols))


class ConstWeights:
    """Trivial strategy for engine tests (Phase 3 has no real strategy)."""

    def __init__(self, weights: dict[str, float]):
        self.weights = dict(weights)

    def target_weights(self, prices: pd.DataFrame, today: date) -> dict[str, float]:
        return dict(self.weights)


class Top1TrailingReturn:
    """Data-dependent toy strategy — exists so lookahead tampering would
    actually change decisions if lookahead were possible."""

    def __init__(self, lookback: int = 60):
        self.lookback = lookback

    def target_weights(self, prices: pd.DataFrame, today: date) -> dict[str, float]:
        window = prices.iloc[-self.lookback:].dropna(how="any")
        if len(window) < 2:
            return {}
        rets = window.iloc[-1] / window.iloc[0] - 1.0
        return {str(rets.idxmax()): 1.0}
