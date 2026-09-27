"""Black-Scholes / Black-76 pricing, Greeks, and the volatility math the
trading system actually uses.

What this module is for
-----------------------
The Black-Scholes PDE

    ∂f/∂t + rS ∂f/∂S + ½σ²S² ∂²f/∂S² = rf

prices a derivative *relative* to its underlying under no-arbitrage. Note
what is absent: the underlying's expected return (drift) μ. It cancels in
the hedged-portfolio derivation — that cancellation is the theorem. The
model therefore contains **no directional information** and cannot predict
where a price is going; it assumes precisely that you cannot.

What it does give us, and what this module exports for the strategy, is the
diffusion term ``σS√T``: the scale of price movement over a horizon. That
makes *risk per trade* controllable even though P&L is not predictable:

* :func:`expected_move` — the 1-sigma move of the underlying over a horizon,
  the correct scale for thresholds, stops, and targets (an ATR proxy is a
  cruder estimate of the same quantity).
* :func:`vol_target_quantity` — position size such that a 1-sigma adverse
  move costs a fixed dollar risk budget, so exposure is constant across
  volatility regimes instead of constant in contracts.

The pricing and Greeks functions are complete and correct for their stated
models; they exist so options work (hedging, IV-based regime input) can be
built on a verified base rather than reimplemented ad hoc.

Model selection
---------------
:func:`black_scholes_price` is the spot model (equities). For options on
**futures** — MES/ES included — the correct variant is Black-76
(:func:`black76_price`), where the forward already embeds the cost of carry
and the drift term is zero. Using the spot model on a futures option
mis-prices it by roughly the carry.

Caveats that matter in production
---------------------------------
* Constant σ is assumed. Real volatility clusters and jumps — which is why
  ``strategy/adaptive_ema.py`` measures regimes instead of trusting one σ.
* Log-normal returns are assumed: real markets have fat tails, so 1-sigma
  bands under-state crash risk. Sizing off them controls ordinary risk, not
  gap risk. The daily-loss kill switch, not this math, is the tail defense.
* European exercise, no dividends (spot model), frictionless trading.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Optional

OptionType = Literal["call", "put"]

#: E|X| = σ√(2/π) for a zero-mean normal, so σ = E|X| · √(π/2).
MAD_TO_SIGMA = math.sqrt(math.pi / 2.0)

_SQRT_2PI = math.sqrt(2.0 * math.pi)


def _norm_cdf(x: float) -> float:
    """Standard normal CDF via the error function (stdlib only)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    """Standard normal PDF."""
    return math.exp(-0.5 * x * x) / _SQRT_2PI


@dataclass(frozen=True)
class BlackScholesInputs:
    """Inputs to the pricing models.

    Args:
        spot: underlying price S (the *forward* F for Black-76).
        strike: strike K.
        time_to_expiry: T in years (e.g. 30/365 for 30 calendar days).
        rate: continuously-compounded risk-free rate r, as a decimal.
        volatility: annualized σ, as a decimal (0.20 = 20%).
        option_type: "call" or "put".
    """

    spot: float
    strike: float
    time_to_expiry: float
    rate: float
    volatility: float
    option_type: OptionType = "call"

    def __post_init__(self) -> None:
        if self.spot <= 0 or not math.isfinite(self.spot):
            raise ValueError(f"spot must be positive and finite: {self.spot}")
        if self.strike <= 0 or not math.isfinite(self.strike):
            raise ValueError(f"strike must be positive: {self.strike}")
        if self.time_to_expiry < 0 or not math.isfinite(self.time_to_expiry):
            raise ValueError(
                f"time_to_expiry must be >= 0: {self.time_to_expiry}")
        if self.volatility < 0 or not math.isfinite(self.volatility):
            raise ValueError(f"volatility must be >= 0: {self.volatility}")
        if not math.isfinite(self.rate):
            raise ValueError(f"rate must be finite: {self.rate}")
        if self.option_type not in ("call", "put"):
            raise ValueError(f"option_type must be call/put: "
                             f"{self.option_type!r}")


def _d1_d2(spot: float, strike: float, t: float, drift: float,
           sigma: float) -> tuple[float, float]:
    """d1, d2 for a log-normal model with the given drift term."""
    vol_sqrt_t = sigma * math.sqrt(t)
    d1 = (math.log(spot / strike) + (drift + 0.5 * sigma * sigma) * t) \
        / vol_sqrt_t
    return d1, d1 - vol_sqrt_t


def _intrinsic(spot: float, strike: float, option_type: OptionType) -> float:
    return (max(spot - strike, 0.0) if option_type == "call"
            else max(strike - spot, 0.0))


def black_scholes_price(inp: BlackScholesInputs) -> float:
    """European option price under Black-Scholes (spot model, no dividends).

    ``C = S·N(d1) − K·e^(−rT)·N(d2)``; puts by parity. At T=0 or σ=0 the
    model degenerates to discounted intrinsic value, which is returned
    directly rather than dividing by zero.
    """
    S, K, T = inp.spot, inp.strike, inp.time_to_expiry
    if T == 0.0 or inp.volatility == 0.0:
        disc_k = K * math.exp(-inp.rate * T)
        return (max(S - disc_k, 0.0) if inp.option_type == "call"
                else max(disc_k - S, 0.0))
    d1, d2 = _d1_d2(S, K, T, inp.rate, inp.volatility)
    disc = math.exp(-inp.rate * T)
    if inp.option_type == "call":
        return S * _norm_cdf(d1) - K * disc * _norm_cdf(d2)
    return K * disc * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def black76_price(inp: BlackScholesInputs) -> float:
    """European option on a **future** (Black-76): ``inp.spot`` is the
    forward/futures price F.

    ``C = e^(−rT)[F·N(d1) − K·N(d2)]`` — the drift term is zero because the
    futures price already embeds carry. This is the correct model for
    options on MES/ES and other futures.
    """
    F, K, T = inp.spot, inp.strike, inp.time_to_expiry
    disc = math.exp(-inp.rate * T)
    if T == 0.0 or inp.volatility == 0.0:
        return disc * _intrinsic(F, K, inp.option_type)
    d1, d2 = _d1_d2(F, K, T, 0.0, inp.volatility)
    if inp.option_type == "call":
        return disc * (F * _norm_cdf(d1) - K * _norm_cdf(d2))
    return disc * (K * _norm_cdf(-d2) - F * _norm_cdf(-d1))


@dataclass(frozen=True)
class Greeks:
    """Sensitivities of the option price.

    ``delta`` per $1 of underlying, ``gamma`` per $1², ``vega`` per 1.00 of
    volatility (divide by 100 for "per vol point"), ``theta`` per year
    (divide by 365 for per-day), ``rho`` per 1.00 of rate.
    """

    price: float
    delta: float
    gamma: float
    vega: float
    theta: float
    rho: float


def greeks(inp: BlackScholesInputs) -> Greeks:
    """Black-Scholes (spot model) price and first/second-order Greeks.

    At expiry or zero volatility the Greeks degenerate: delta becomes the
    0/1 step of intrinsic value and the rest are zero.
    """
    S, K, T, r, sigma = (inp.spot, inp.strike, inp.time_to_expiry,
                         inp.rate, inp.volatility)
    price = black_scholes_price(inp)
    if T == 0.0 or sigma == 0.0:
        if inp.option_type == "call":
            delta = 1.0 if S > K else 0.0
        else:
            delta = -1.0 if S < K else 0.0
        return Greeks(price, delta, 0.0, 0.0, 0.0, 0.0)

    d1, d2 = _d1_d2(S, K, T, r, sigma)
    sqrt_t = math.sqrt(T)
    disc = math.exp(-r * T)
    pdf_d1 = _norm_pdf(d1)

    gamma = pdf_d1 / (S * sigma * sqrt_t)
    vega = S * pdf_d1 * sqrt_t
    common_theta = -(S * pdf_d1 * sigma) / (2.0 * sqrt_t)
    if inp.option_type == "call":
        delta = _norm_cdf(d1)
        theta = common_theta - r * K * disc * _norm_cdf(d2)
        rho = K * T * disc * _norm_cdf(d2)
    else:
        delta = _norm_cdf(d1) - 1.0
        theta = common_theta + r * K * disc * _norm_cdf(-d2)
        rho = -K * T * disc * _norm_cdf(-d2)
    return Greeks(price, delta, gamma, vega, theta, rho)


def implied_volatility(
    market_price: float,
    inp: BlackScholesInputs,
    *,
    model: Literal["bs", "black76"] = "bs",
    tolerance: float = 1e-8,
    max_iterations: int = 100,
) -> Optional[float]:
    """Solve for the σ that reproduces ``market_price``.

    Newton-Raphson on vega with a bisection fallback, because vega collapses
    for deep in/out-of-the-money options and pure Newton diverges there.

    Convergence is measured on the **σ bracket**, not on price alone: where
    vega is small a price match to 1e-8 can still leave σ wrong in the 4th
    decimal, so a price-only criterion reports false precision.

    The result is also checked for *identifiability*. Far from the money the
    price underflows to the same value for every σ in a wide range; the
    quote then carries no information about volatility and a solver that
    "converges" is really returning its own initial guess. That case yields
    ``None``.

    Returns:
        The implied volatility, or ``None`` when no σ in (0, 5] reproduces
        the price (stale quotes, prices below intrinsic or above the
        underlying) or when σ is not identifiable from the price. Returning
        None rather than a fabricated number keeps bad marks out of the
        risk layer.
    """
    if not math.isfinite(market_price) or market_price < 0:
        return None
    T = inp.time_to_expiry
    if T <= 0:
        return None

    price_fn = black_scholes_price if model == "bs" else black76_price

    def priced_at(sigma: float) -> float:
        return price_fn(BlackScholesInputs(
            spot=inp.spot, strike=inp.strike, time_to_expiry=T,
            rate=inp.rate, volatility=sigma, option_type=inp.option_type))

    lo, hi = 1e-9, 5.0
    price_lo, price_hi = priced_at(lo), priced_at(hi)
    # Outside the achievable price range there is no solution.
    if market_price < price_lo - tolerance or market_price > price_hi + tolerance:
        return None

    sigma = 0.25  # a sane starting guess for index volatility
    for _ in range(max_iterations):
        diff = priced_at(sigma) - market_price
        if diff > 0:
            hi = sigma
        else:
            lo = sigma
        # Stop only once sigma itself is pinned down, not merely the price.
        if hi - lo < 1e-10:
            break
        # Newton step, guarded: vega must be meaningful and the step must
        # stay strictly inside the bracket, else fall back to bisection.
        vega = greeks(BlackScholesInputs(
            spot=inp.spot, strike=inp.strike, time_to_expiry=T,
            rate=inp.rate, volatility=sigma,
            option_type=inp.option_type)).vega
        if vega > 1e-10:
            candidate = sigma - diff / vega
            if lo < candidate < hi:
                sigma = candidate
                continue
        sigma = 0.5 * (lo + hi)

    if abs(priced_at(sigma) - market_price) > 1e-6:
        return None
    # Identifiability: the price must actually respond to volatility. If a
    # 1bp change in sigma leaves the price numerically unchanged, any sigma
    # fits and the "solution" is just the starting guess.
    probe = max(abs(priced_at(min(sigma + 1e-4, 5.0)) - priced_at(sigma)),
                abs(priced_at(sigma) - priced_at(max(sigma - 1e-4, 1e-9))))
    if probe < 1e-12:
        return None
    return sigma


# --------------------------------------------------------------------------
# The volatility math the trading strategy uses
# --------------------------------------------------------------------------

def mad_to_sigma(mean_abs_deviation: float) -> float:
    """Convert a mean absolute return to a standard deviation.

    An EWMA of ``|log return|`` is a mean absolute deviation, not a sigma.
    For a zero-mean normal, ``E|X| = σ√(2/π)``, so ``σ = E|X|·√(π/2)``.
    Skipping this conversion understates volatility by ~20%.
    """
    if not math.isfinite(mean_abs_deviation) or mean_abs_deviation < 0:
        return 0.0
    return mean_abs_deviation * MAD_TO_SIGMA


def sigma_from_mad_ewma(mad_ewma: float, bars: int = 1) -> float:
    """Per-bar σ from a MAD EWMA, scaled to a horizon of ``bars`` bars.

    Diffusion scales with the square root of time, so σ over N bars is
    ``σ_bar · √N``.
    """
    if bars < 1:
        raise ValueError("bars must be >= 1")
    return mad_to_sigma(mad_ewma) * math.sqrt(bars)


def expected_move(spot: float, sigma: float, horizon_years: float = 1.0,
                  sigmas: float = 1.0) -> float:
    """The ``σ·S·√T`` diffusion scale: expected move over a horizon.

    Args:
        spot: current price.
        sigma: volatility over the same time unit as ``horizon_years``
            (annualized σ with T in years; per-bar σ with T in bars).
        horizon_years: horizon in those units.
        sigmas: how many standard deviations (1.0 ≈ 68% of outcomes under
            the model's normal assumption — real tails are fatter).

    Returns:
        The move in price units, always non-negative.
    """
    if spot <= 0 or sigma < 0 or horizon_years < 0 or sigmas < 0:
        return 0.0
    return spot * sigma * math.sqrt(horizon_years) * sigmas


def vol_target_quantity(
    risk_budget: float,
    spot: float,
    sigma: float,
    multiplier: float = 1.0,
    horizon: float = 1.0,
    *,
    max_quantity: Optional[int] = None,
    sigmas: float = 1.0,
) -> int:
    """Contracts sized so a ``sigmas``-sigma adverse move costs ~``risk_budget``.

    This is the honest use of the Black-Scholes framework in a directional
    strategy: it cannot tell you *whether* a trade wins, but it holds the
    dollar risk of each trade roughly constant as volatility changes, so a
    position taken in a turbulent regime carries the same exposure as one
    taken in a calm regime.

    Args:
        risk_budget: dollars to put at risk for a 1-sigma adverse move.
        spot: current price.
        sigma: volatility over ``horizon``'s time unit.
        multiplier: contract multiplier (5.0 for MES, 50.0 for ES, 1 stock).
        horizon: holding horizon in the same unit as ``sigma``.
        max_quantity: optional hard cap applied after sizing.
        sigmas: standard deviations the budget must absorb.

    Returns:
        A non-negative integer quantity — 0 when volatility is so high that
        even one contract exceeds the budget, which is a correct "stand
        aside" signal rather than an error.
    """
    if risk_budget <= 0 or multiplier <= 0:
        return 0
    move = expected_move(spot, sigma, horizon, sigmas)
    risk_per_contract = move * multiplier
    if risk_per_contract <= 0:
        return 0  # no measurable volatility yet: do not size blind
    qty = int(risk_budget // risk_per_contract)
    if max_quantity is not None:
        qty = min(qty, max_quantity)
    return max(0, qty)
