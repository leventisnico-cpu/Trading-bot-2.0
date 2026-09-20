"""Tests for the Black-Scholes / Black-76 module and the volatility math.

Pricing is checked against closed-form identities (put-call parity, known
textbook values) rather than against itself, so a sign or factor error
cannot pass by agreeing with a bug.
"""

from __future__ import annotations

import math

import pytest

from mini_prop_os.quant.blackscholes import (BlackScholesInputs, black76_price,
                                             black_scholes_price,
                                             expected_move, greeks,
                                             implied_volatility, mad_to_sigma,
                                             sigma_from_mad_ewma,
                                             vol_target_quantity)


def inputs(**kw) -> BlackScholesInputs:
    params = dict(spot=100.0, strike=100.0, time_to_expiry=1.0, rate=0.05,
                  volatility=0.2, option_type="call")
    params.update(kw)
    return BlackScholesInputs(**params)


# ------------------------------------------------------------- validation

@pytest.mark.parametrize("bad", [
    dict(spot=0.0), dict(spot=-1.0), dict(spot=float("nan")),
    dict(strike=0.0), dict(time_to_expiry=-0.5), dict(volatility=-0.1),
    dict(rate=float("inf")), dict(option_type="straddle"),
])
def test_invalid_inputs_rejected(bad):
    with pytest.raises(ValueError):
        inputs(**bad)


# ---------------------------------------------------------------- pricing

def test_atm_call_matches_known_textbook_value():
    # S=K=100, T=1, r=5%, sigma=20% is the standard worked example.
    assert black_scholes_price(inputs()) == pytest.approx(10.4506, abs=1e-4)


def test_atm_put_matches_known_textbook_value():
    assert black_scholes_price(inputs(option_type="put")) == \
        pytest.approx(5.5735, abs=1e-4)


@pytest.mark.parametrize("S,K,T,r,sigma", [
    (100.0, 100.0, 1.0, 0.05, 0.2),
    (6500.0, 6400.0, 30 / 365, 0.04, 0.15),
    (50.0, 75.0, 2.0, 0.01, 0.45),
    (1200.0, 900.0, 0.25, 0.03, 0.8),
])
def test_put_call_parity(S, K, T, r, sigma):
    """C - P = S - K·e^(-rT) must hold exactly, for any parameters."""
    call = black_scholes_price(inputs(spot=S, strike=K, time_to_expiry=T,
                                      rate=r, volatility=sigma))
    put = black_scholes_price(inputs(spot=S, strike=K, time_to_expiry=T,
                                     rate=r, volatility=sigma,
                                     option_type="put"))
    assert call - put == pytest.approx(S - K * math.exp(-r * T), abs=1e-9)


def test_black76_parity_uses_forward():
    """Futures parity: C - P = e^(-rT)(F - K)."""
    F, K, T, r = 6500.0, 6400.0, 0.25, 0.04
    call = black76_price(inputs(spot=F, strike=K, time_to_expiry=T, rate=r,
                                volatility=0.18))
    put = black76_price(inputs(spot=F, strike=K, time_to_expiry=T, rate=r,
                               volatility=0.18, option_type="put"))
    assert call - put == pytest.approx(math.exp(-r * T) * (F - K), abs=1e-9)


def test_black76_differs_from_spot_model_by_carry():
    """Using the spot model on a futures option mis-prices it — the two
    models must not silently agree when the rate is non-zero."""
    kw = dict(spot=6500.0, strike=6500.0, time_to_expiry=0.5, rate=0.05,
              volatility=0.2)
    assert black_scholes_price(inputs(**kw)) != \
        pytest.approx(black76_price(inputs(**kw)), abs=1.0)


def test_price_is_monotonic_in_volatility():
    prices = [black_scholes_price(inputs(volatility=s))
              for s in (0.1, 0.2, 0.3, 0.5)]
    assert prices == sorted(prices)


def test_zero_time_and_zero_vol_degenerate_to_intrinsic():
    itm = inputs(spot=120.0, strike=100.0, time_to_expiry=0.0, rate=0.0)
    assert black_scholes_price(itm) == pytest.approx(20.0)
    otm = inputs(spot=80.0, strike=100.0, time_to_expiry=0.0, rate=0.0)
    assert black_scholes_price(otm) == pytest.approx(0.0)
    # Zero volatility with time left: discounted intrinsic, no crash.
    assert black_scholes_price(
        inputs(spot=120.0, volatility=0.0)) == pytest.approx(
            120.0 - 100.0 * math.exp(-0.05), abs=1e-9)


def test_price_never_below_intrinsic_or_above_spot():
    for S in (60.0, 100.0, 140.0):
        price = black_scholes_price(inputs(spot=S))
        assert price >= max(S - 100.0 * math.exp(-0.05), 0.0) - 1e-9
        assert price <= S


# ----------------------------------------------------------------- greeks

def test_call_and_put_delta_differ_by_one():
    g_call = greeks(inputs())
    g_put = greeks(inputs(option_type="put"))
    assert g_call.delta - g_put.delta == pytest.approx(1.0, abs=1e-9)
    assert 0.0 < g_call.delta < 1.0
    assert -1.0 < g_put.delta < 0.0


def test_gamma_and_vega_are_identical_for_call_and_put():
    g_call, g_put = greeks(inputs()), greeks(inputs(option_type="put"))
    assert g_call.gamma == pytest.approx(g_put.gamma, abs=1e-12)
    assert g_call.vega == pytest.approx(g_put.vega, abs=1e-12)
    assert g_call.gamma > 0 and g_call.vega > 0


def test_delta_matches_numerical_derivative():
    """Analytic delta must equal dPrice/dSpot computed numerically."""
    h = 1e-5
    up = black_scholes_price(inputs(spot=100.0 + h))
    down = black_scholes_price(inputs(spot=100.0 - h))
    assert greeks(inputs()).delta == pytest.approx((up - down) / (2 * h),
                                                   abs=1e-6)


def test_vega_matches_numerical_derivative():
    h = 1e-6
    up = black_scholes_price(inputs(volatility=0.2 + h))
    down = black_scholes_price(inputs(volatility=0.2 - h))
    assert greeks(inputs()).vega == pytest.approx((up - down) / (2 * h),
                                                  abs=1e-4)


def test_long_option_theta_is_negative():
    """Time decay: a long option loses value as expiry approaches."""
    assert greeks(inputs()).theta < 0
    assert greeks(inputs(option_type="put")).theta < 0


def test_greeks_degenerate_at_expiry():
    g = greeks(inputs(spot=120.0, time_to_expiry=0.0))
    assert g.delta == 1.0 and g.gamma == 0.0 and g.vega == 0.0


# ------------------------------------------------------ implied volatility

@pytest.mark.parametrize("sigma", [0.05, 0.12, 0.2, 0.45, 1.2])
@pytest.mark.parametrize("strike", [80.0, 100.0, 130.0])
def test_implied_vol_round_trips(sigma, strike):
    """Price at a known sigma, solve it back out."""
    inp = inputs(strike=strike, volatility=sigma)
    price = black_scholes_price(inp)
    assert implied_volatility(price, inp) == pytest.approx(sigma, abs=1e-5)


def test_implied_vol_round_trips_for_black76():
    inp = inputs(spot=6500.0, strike=6600.0, time_to_expiry=0.25,
                 volatility=0.18)
    price = black76_price(inp)
    assert implied_volatility(price, inp, model="black76") == \
        pytest.approx(0.18, abs=1e-5)


def test_implied_vol_returns_none_for_impossible_prices():
    inp = inputs()
    assert implied_volatility(-1.0, inp) is None        # negative
    assert implied_volatility(1e9, inp) is None         # above any sigma
    assert implied_volatility(0.0, inp) is None         # below intrinsic
    assert implied_volatility(10.0, inputs(time_to_expiry=0.0)) is None


def test_implied_vol_survives_deep_otm_where_vega_vanishes():
    """Newton alone diverges here; the bisection fallback must hold."""
    inp = inputs(spot=100.0, strike=400.0, time_to_expiry=0.05,
                 volatility=0.6)
    price = black_scholes_price(inp)
    result = implied_volatility(price, inp)
    assert result is None or result == pytest.approx(0.6, abs=1e-3)


# ------------------------------------------------- volatility math (used)

def test_mad_to_sigma_applies_the_correct_factor():
    """E|X| = sigma*sqrt(2/pi), so the conversion is sqrt(pi/2) ~ 1.2533."""
    assert mad_to_sigma(1.0) == pytest.approx(1.2533, abs=1e-4)
    assert mad_to_sigma(0.0) == 0.0
    assert mad_to_sigma(-1.0) == 0.0          # garbage in, zero out
    assert mad_to_sigma(float("nan")) == 0.0


def test_mad_conversion_recovers_sigma_from_normal_samples():
    """Sanity-check the factor against an actual normal distribution."""
    import random
    rng = random.Random(7)
    true_sigma = 0.013
    sample = [rng.gauss(0.0, true_sigma) for _ in range(200_000)]
    mad = sum(abs(x) for x in sample) / len(sample)
    assert mad_to_sigma(mad) == pytest.approx(true_sigma, rel=0.02)


def test_sigma_scales_with_square_root_of_time():
    one_bar = sigma_from_mad_ewma(0.01, bars=1)
    four_bars = sigma_from_mad_ewma(0.01, bars=4)
    assert four_bars == pytest.approx(2.0 * one_bar, abs=1e-12)
    with pytest.raises(ValueError):
        sigma_from_mad_ewma(0.01, bars=0)


def test_expected_move_is_the_diffusion_term():
    # sigma*S*sqrt(T): 20% vol, 6500 index, 1 year => 1300 points.
    assert expected_move(6500.0, 0.2, 1.0) == pytest.approx(1300.0)
    # Quarter of a year halves it (sqrt(0.25) = 0.5).
    assert expected_move(6500.0, 0.2, 0.25) == pytest.approx(650.0)
    # Two sigma doubles it.
    assert expected_move(6500.0, 0.2, 1.0, sigmas=2.0) == pytest.approx(2600.0)
    assert expected_move(0.0, 0.2, 1.0) == 0.0
    assert expected_move(6500.0, -0.2, 1.0) == 0.0


# ------------------------------------------------- volatility-target sizing

def test_vol_target_sizing_holds_dollar_risk_constant():
    """The point of the whole exercise: same risk, different regimes."""
    budget, spot, mult = 500.0, 6500.0, 5.0
    calm = vol_target_quantity(budget, spot, sigma=0.0031, multiplier=mult)
    wild = vol_target_quantity(budget, spot, sigma=0.0124, multiplier=mult)
    assert calm > wild >= 1           # four times the vol, a quarter the size
    # Risk actually taken stays under budget in both regimes.
    for qty, sigma in ((calm, 0.0031), (wild, 0.0124)):
        risk = expected_move(spot, sigma) * mult * qty
        assert risk <= budget


def test_vol_target_sizing_stands_aside_when_one_contract_is_too_risky():
    # 5% per-bar sigma on a 6500 index = $1625/contract risk vs $200 budget.
    assert vol_target_quantity(200.0, 6500.0, sigma=0.05,
                               multiplier=5.0) == 0


def test_vol_target_sizing_refuses_to_size_without_volatility():
    """Zero sigma would divide by zero and imply infinite size."""
    assert vol_target_quantity(1000.0, 6500.0, sigma=0.0, multiplier=5.0) == 0


def test_vol_target_sizing_respects_hard_cap():
    assert vol_target_quantity(1_000_000.0, 6500.0, sigma=0.001,
                               multiplier=5.0, max_quantity=4) == 4


def test_vol_target_sizing_rejects_bad_budget_or_multiplier():
    assert vol_target_quantity(0.0, 6500.0, 0.01, 5.0) == 0
    assert vol_target_quantity(-100.0, 6500.0, 0.01, 5.0) == 0
    assert vol_target_quantity(500.0, 6500.0, 0.01, multiplier=0.0) == 0


def test_vol_target_sizing_scales_with_horizon():
    """A longer hold means a wider expected move and a smaller position."""
    one_bar = vol_target_quantity(5000.0, 6500.0, 0.002, 5.0, horizon=1.0)
    nine_bars = vol_target_quantity(5000.0, 6500.0, 0.002, 5.0, horizon=9.0)
    assert nine_bars < one_bar
