"""Dual momentum strategy tests (Phase 4)."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from engine.strategies import TRADING_DAYS_PER_MONTH, DualMomentum

TODAY = date(2026, 8, 31)
UNIVERSE = ("AAA", "BBB", "CCC", "DEF")
PARAMS = {"lookback_months": 12, "skip_months": 1, "top_n": 1,
          "absolute_momentum_filter": True, "defensive_symbol": "DEF"}
DAYS = (12 + 1) * TRADING_DAYS_PER_MONTH + 10


def frame(**series) -> pd.DataFrame:
    idx = pd.bdate_range(end="2026-08-31", periods=DAYS)
    return pd.DataFrame({k: v for k, v in series.items()}, index=idx)


def trend(start: float, end: float) -> np.ndarray:
    return np.linspace(start, end, DAYS)


def test_picks_the_strongest_riser():
    prices = frame(AAA=trend(100, 160), BBB=trend(100, 120), CCC=trend(100, 105),
                   DEF=trend(100, 101))
    w = DualMomentum(UNIVERSE, PARAMS).target_weights(prices, TODAY)
    assert w == {"AAA": 1.0}


def test_absolute_filter_sends_to_defensive():
    prices = frame(AAA=trend(100, 80), BBB=trend(100, 70), CCC=trend(100, 60),
                   DEF=trend(100, 104))
    w = DualMomentum(UNIVERSE, PARAMS).target_weights(prices, TODAY)
    assert w == {"DEF": 1.0}


def test_everything_negative_means_cash():
    prices = frame(AAA=trend(100, 80), BBB=trend(100, 70), CCC=trend(100, 60),
                   DEF=trend(100, 90))
    w = DualMomentum(UNIVERSE, PARAMS).target_weights(prices, TODAY)
    assert w == {}, "negative defensive momentum must fall through to cash"


def test_skip_month_excludes_the_most_recent_month():
    """A spike entirely inside the skip window must not win."""
    steady = trend(100, 130)                      # BBB: steady +30%
    spike = np.full(DAYS, 100.0)                  # AAA: flat, then a last-month moonshot
    spike[-TRADING_DAYS_PER_MONTH:] = 300.0
    prices = frame(AAA=spike, BBB=steady, CCC=trend(100, 101), DEF=trend(100, 101))
    w = DualMomentum(UNIVERSE, PARAMS).target_weights(prices, TODAY)
    assert w == {"BBB": 1.0}, \
        "last-month spike won — the skip month is not being excluded"


def test_insufficient_history_stays_in_cash():
    idx = pd.bdate_range(end="2026-08-31", periods=60)
    prices = pd.DataFrame({s: np.linspace(100, 110, 60) for s in UNIVERSE}, index=idx)
    w = DualMomentum(UNIVERSE, PARAMS).target_weights(prices, TODAY)
    assert w == {}


def test_top2_splits_equally():
    params = dict(PARAMS, top_n=2)
    prices = frame(AAA=trend(100, 160), BBB=trend(100, 140), CCC=trend(100, 105),
                   DEF=trend(100, 101))
    w = DualMomentum(UNIVERSE, params).target_weights(prices, TODAY)
    assert w == {"AAA": 0.5, "BBB": 0.5}


def test_weights_never_exceed_one():
    prices = frame(AAA=trend(100, 160), BBB=trend(100, 140), CCC=trend(100, 120),
                   DEF=trend(100, 110))
    for top_n in (1, 2, 3):
        w = DualMomentum(UNIVERSE, dict(PARAMS, top_n=top_n)).target_weights(prices, TODAY)
        assert sum(w.values()) <= 1.0 + 1e-12


def test_bad_top_n_rejected():
    with pytest.raises(ValueError):
        DualMomentum(UNIVERSE, dict(PARAMS, top_n=5))
