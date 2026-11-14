"""Shared fixtures: real config files and synthetic market data builders."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ftmo_bot.config import FtmoProfile, StrategyParams, load_profile, load_strategy
from ftmo_bot.strategy.base import Bar

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def params() -> StrategyParams:
    return load_strategy(ROOT / "config" / "strategy.yaml")


@pytest.fixture(scope="session")
def profile() -> FtmoProfile:
    return load_profile(ROOT / "config" / "ftmo_2step.yaml")


def make_ticks(
    start: datetime,
    end: datetime,
    every: timedelta,
    price: float | Sequence[float],
    spread: float = 0.00010,
) -> pd.DataFrame:
    """Regular ticks in [start, end). ``price`` is the bid (scalar or one per tick)."""
    n = int((end - start) / every)
    ts = (
        pd.date_range(start, periods=n, freq=every, tz=UTC)
        if start.tzinfo is None
        else pd.date_range(start, periods=n, freq=every)
    )
    bid = np.full(n, price, dtype=float) if np.isscalar(price) else np.asarray(price, float)
    return pd.DataFrame({"ts_utc": ts, "bid": bid, "ask": bid + spread})


def bar(
    symbol: str, ts: datetime, o: float, h: float, low: float, c: float, minutes: int = 15
) -> Bar:
    return Bar(symbol, ts, o, h, low, c, minutes)
