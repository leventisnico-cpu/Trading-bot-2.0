"""Quantitative primitives: Black-Scholes / Black-76 and volatility math.

Pure stdlib (no numpy/scipy), so the whole module runs in CI alongside the
rest of the broker-free core.
"""

from .blackscholes import (BlackScholesInputs, Greeks, black76_price,
                           black_scholes_price, expected_move, greeks,
                           implied_volatility, mad_to_sigma,
                           sigma_from_mad_ewma, vol_target_quantity)

__all__ = [
    "BlackScholesInputs", "Greeks", "black76_price", "black_scholes_price",
    "expected_move", "greeks", "implied_volatility", "mad_to_sigma",
    "sigma_from_mad_ewma", "vol_target_quantity",
]
