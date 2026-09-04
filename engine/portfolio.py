"""Target weights -> orders, convergence, and basket volatility.

- A held symbol with no price is a refusal, never a sell-everything (§5.7).
- Full exits carry is_full_exit=True so no minimum-size filter can eat
  them (§5.4).
- Completion is measured by convergence to target, never by order count
  (§5.9).
- Basket volatility uses the covariance matrix, sqrt(w'Σw) (§5.8).
"""
from __future__ import annotations

import math

import numpy as np

from .errors import DataError
from .orders import Order, Side, sort_for_submission


def compute_orders(
    positions: dict[str, float],
    target_weights: dict[str, float],
    prices: dict[str, float],
    equity: float,
    *,
    no_trade_band: float = 0.0,
) -> list[Order]:
    """Diff current positions against target weights, in whole shares.

    no_trade_band: skip trades whose weight change is below this fraction of
    equity — EXCEPT full exits, which are always emitted.
    """
    held = {s for s, sh in positions.items() if sh > 0}
    missing = sorted(held - set(prices))
    if missing:
        # Failure mode #7: a data gap must never read as "target weight 0".
        raise DataError(f"held symbols with no price: {missing} — refusing to compute orders")
    if equity <= 0:
        raise ValueError(f"equity must be > 0, got {equity}")

    orders: list[Order] = []
    symbols = held | {s for s, w in target_weights.items() if w != 0}
    for sym in sorted(symbols):
        px = prices.get(sym)
        if px is None or px <= 0:
            raise DataError(f"no valid price for {sym}")
        cur_shares = positions.get(sym, 0.0)
        tgt_w = target_weights.get(sym, 0.0)
        tgt_shares = math.floor((tgt_w * equity) / px)
        delta = tgt_shares - cur_shares
        # Full exit whenever the TARGET SHARE COUNT is zero — including a
        # small nonzero weight that floors to 0 shares. Keying on the raw
        # weight let min-size filters eat a sell of the entire position
        # forever (audit round 1, finding #13).
        full_exit = tgt_shares == 0 and cur_shares > 0
        if full_exit:
            orders.append(Order(symbol=sym, side=Side.SELL, shares=cur_shares, is_full_exit=True))
            continue
        if delta == 0:
            continue
        weight_change = abs(delta) * px / equity
        if weight_change < no_trade_band:
            continue
        if delta > 0:
            orders.append(Order(symbol=sym, side=Side.BUY, shares=delta))
        else:
            orders.append(Order(symbol=sym, side=Side.SELL, shares=-delta))
    return sort_for_submission(orders)


def deviations(
    positions: dict[str, float],
    target_weights: dict[str, float],
    prices: dict[str, float],
    equity: float,
) -> dict[str, float]:
    """Per-symbol |actual weight - target weight|."""
    if equity <= 0:
        raise ValueError("equity must be > 0")
    out = {}
    for sym in set(positions) | set(target_weights):
        px = prices.get(sym)
        # NaN is truthy — `if px` once let a NaN price propagate into the
        # deviations and poison convergence. Explicit checks only.
        bad_px = px is None or px != px or px <= 0
        if bad_px and positions.get(sym, 0.0) > 0:
            raise DataError(f"held symbol {sym} has no usable price")
        actual = 0.0 if bad_px else positions.get(sym, 0.0) * px / equity
        out[sym] = abs(actual - target_weights.get(sym, 0.0))
    return out


def converged(
    positions: dict[str, float],
    target_weights: dict[str, float],
    prices: dict[str, float],
    equity: float,
    tolerance: float,
) -> bool:
    """Did the portfolio actually reach target? (§5.9 — never order count.)

    Whole-share rounding means small deviations are inherent; tolerance
    comes from config (risk.rebalance_tolerance).
    """
    devs = deviations(positions, target_weights, prices, equity)
    # Whole-share granularity: a symbol that cannot be represented closer than
    # one share is considered converged at its nearest representable weight.
    for sym, dev in devs.items():
        px = prices.get(sym)
        granularity = 0.0 if (px is None or px != px or px <= 0) else px / equity
        if dev > max(tolerance, granularity):
            return False
    return True


def basket_volatility(weights: dict[str, float], cov: np.ndarray, symbols: list[str]) -> float:
    """sqrt(w'Σw). Averaging per-asset vols once under-invested a real book
    by ~40% (§5.8): three uncorrelated 20%-vol assets are an ~11.5%-vol
    basket, not 20%."""
    w = np.array([weights.get(s, 0.0) for s in symbols], dtype=float)
    if cov.shape != (len(symbols), len(symbols)):
        raise ValueError(f"covariance shape {cov.shape} does not match {len(symbols)} symbols")
    var = float(w @ cov @ w)
    if var < -1e-12:
        raise ValueError("negative portfolio variance — covariance matrix is not PSD")
    return math.sqrt(max(var, 0.0))
