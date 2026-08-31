"""Data validation (§5.7).

A missing or stale price must never silently become "target weight 0" —
that path once liquidated a real position. If any required symbol (the
universe plus anything currently held) is missing, stale, or has a NaN
last value, the engine refuses to trade for the cycle.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from .errors import DataError


def validate_prices(
    prices: pd.DataFrame,
    required_symbols: set[str],
    asof: date,
    max_staleness_days: int,
) -> None:
    """Raise DataError unless every required symbol has a fresh, non-NaN price.

    `prices`: DataFrame indexed by date (ascending), one column per symbol.
    """
    if prices.empty:
        raise DataError("price frame is empty")
    problems = []
    cutoff = asof - timedelta(days=max_staleness_days)
    for sym in sorted(required_symbols):
        if sym not in prices.columns:
            problems.append(f"{sym}: missing from price data")
            continue
        col = prices[sym]
        # A present column whose LAST value is NaN is exactly failure mode #7.
        if pd.isna(col.iloc[-1]):
            problems.append(f"{sym}: last value is NaN")
            continue
        last_valid = col.last_valid_index()
        last_date = last_valid.date() if hasattr(last_valid, "date") else last_valid
        if last_date < cutoff:
            problems.append(f"{sym}: stale (last {last_date}, cutoff {cutoff})")
    if problems:
        raise DataError("refusing to trade — bad price data: " + "; ".join(problems))


def latest_prices(prices: pd.DataFrame, symbols: set[str]) -> dict[str, float]:
    """Last observed price per symbol. Call validate_prices first."""
    out = {}
    for sym in symbols:
        out[sym] = float(prices[sym].iloc[-1])
    return out
