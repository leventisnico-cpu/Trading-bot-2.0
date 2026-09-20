"""Tests for multiple-testing statistics (Deflated Sharpe and friends).

Checked against analytic properties and simulation — a selection-bias
correction that is itself wrong is worse than none, because it grants
false confidence.
"""

from __future__ import annotations

import math
import random

import pytest

from mini_prop_os.quant import statistics as st


# ------------------------------------------------------------ primitives

@pytest.mark.parametrize("p,expected", [
    (0.975, 1.959963985), (0.95, 1.644853627), (0.5, 0.0),
    (0.025, -1.959963985), (0.999, 3.090232306), (0.001, -3.090232306),
])
def test_probit_matches_known_quantiles(p, expected):
    assert st._norm_ppf(p) == pytest.approx(expected, abs=1e-8)


def test_probit_inverts_the_cdf():
    for x in (-3.0, -1.0, 0.0, 0.5, 2.5):
        assert st._norm_ppf(st._norm_cdf(x)) == pytest.approx(x, abs=1e-8)


@pytest.mark.parametrize("p", [0.0, 1.0, -0.1, 1.5])
def test_probit_rejects_out_of_range(p):
    with pytest.raises(ValueError):
        st._norm_ppf(p)


def test_moments_recover_normal_parameters():
    rng = random.Random(11)
    sample = [rng.gauss(0.002, 0.01) for _ in range(100_000)]
    mean, sd, skew, kurt = st._moments(sample)
    assert mean == pytest.approx(0.002, abs=2e-4)
    assert sd == pytest.approx(0.01, rel=0.02)
    assert skew == pytest.approx(0.0, abs=0.05)
    assert kurt == pytest.approx(3.0, abs=0.1)   # non-excess


# ---------------------------------------------------------- sharpe ratio

def test_sharpe_ratio_and_annualization():
    returns = [0.01, -0.005, 0.02, 0.0, 0.015, -0.01]
    per_period = st.sharpe_ratio(returns)
    annual = st.sharpe_ratio(returns, periods_per_year=252)
    assert annual == pytest.approx(per_period * math.sqrt(252))


def test_sharpe_of_constant_series_is_zero_not_infinite():
    assert st.sharpe_ratio([0.01] * 50) == 0.0
    assert st.sharpe_ratio([0.0] * 50) == 0.0
    assert st.sharpe_ratio([0.01]) == 0.0


# ------------------------------------------------- probabilistic sharpe

def test_psr_rises_with_track_length():
    short = st.probabilistic_sharpe_ratio(0.1, 30)
    long = st.probabilistic_sharpe_ratio(0.1, 3000)
    assert 0.0 < short < long < 1.0


def test_psr_is_half_when_sharpe_equals_benchmark():
    assert st.probabilistic_sharpe_ratio(0.1, 500, benchmark_sr=0.1) == \
        pytest.approx(0.5, abs=1e-9)


def test_psr_penalizes_negative_skew_and_fat_tails():
    base = st.probabilistic_sharpe_ratio(0.1, 500, 0.0, skew=0.0,
                                         kurtosis=3.0)
    skewed = st.probabilistic_sharpe_ratio(0.1, 500, 0.0, skew=-1.5,
                                           kurtosis=3.0)
    fat = st.probabilistic_sharpe_ratio(0.1, 500, 0.0, skew=0.0,
                                        kurtosis=12.0)
    assert skewed < base, "negative skew must reduce confidence"
    assert fat < base, "fat tails must reduce confidence"


def test_psr_returns_zero_without_enough_data():
    assert st.probabilistic_sharpe_ratio(2.0, 1) == 0.0


# -------------------------------------------------- expected max sharpe

def test_selection_bar_rises_with_more_trials():
    bars = [st.expected_max_sharpe(n, 0.25) for n in (2, 10, 100, 1000)]
    assert bars == sorted(bars)
    assert all(b > 0 for b in bars)


def test_single_trial_has_no_selection_bar():
    assert st.expected_max_sharpe(1, 0.25) == 0.0


def test_zero_variance_across_trials_gives_no_bar():
    assert st.expected_max_sharpe(500, 0.0) == 0.0


def test_expected_max_sharpe_matches_simulation():
    """The analytic bar must match the empirical max of N worthless trials."""
    rng = random.Random(5)
    n_trials, n_obs, trials = 50, 250, []
    for _ in range(400):
        sharpes = [st.sharpe_ratio([rng.gauss(0.0, 0.01)
                                    for _ in range(n_obs)])
                   for _ in range(n_trials)]
        trials.append(max(sharpes))
    empirical = sum(trials) / len(trials)
    # Variance of a Sharpe estimate under the null is about 1/n_obs.
    analytic = st.expected_max_sharpe(n_trials, 1.0 / n_obs)
    assert analytic == pytest.approx(empirical, rel=0.15)


def test_expected_max_sharpe_rejects_bad_trial_count():
    with pytest.raises(ValueError):
        st.expected_max_sharpe(0, 0.25)


# ------------------------------------------------------- deflated sharpe

def test_deflation_reduces_confidence_as_search_widens():
    """Confidence must fall monotonically as more trials are searched.

    A strong Sharpe is used so the values stay in a measurable range;
    with a weak one the deflated probability saturates at zero and the
    ordering is no longer observable (see the saturation test below).
    """
    confidences = [st.deflated_sharpe_ratio(0.6, 500, n, 0.04)
                   for n in (1, 5, 50, 500, 5000)]
    assert confidences == sorted(confidences, reverse=True)
    assert confidences[0] > confidences[-1], "widening the search must cost"


def test_deflation_saturates_at_zero_for_a_weak_sharpe():
    """A Sharpe below the selection bar earns no confidence at all, and
    searching further cannot push it below zero."""
    weak = [st.deflated_sharpe_ratio(0.12, 500, n, 0.04)
            for n in (100, 10_000)]
    assert all(w == 0.0 for w in weak)


def test_deflated_sharpe_rejects_the_best_of_many_noise_trials():
    """The core claim: pick the best of N worthless strategies, and the
    correction must refuse to call it real."""
    rng = random.Random(99)
    n_obs, n_trials = 252, 200
    series = [[rng.gauss(0.0, 0.01) for _ in range(n_obs)]
              for _ in range(n_trials)]
    sharpes = [st.sharpe_ratio(s) for s in series]
    best_idx = max(range(n_trials), key=lambda i: sharpes[i])
    mean_sr = sum(sharpes) / n_trials
    variance = sum((s - mean_sr) ** 2 for s in sharpes) / (n_trials - 1)

    naive = st.probabilistic_sharpe_ratio(sharpes[best_idx], n_obs)
    verdict = st.assess_credibility(series[best_idx], n_trials=n_trials,
                                    sr_variance_across_trials=variance)
    assert naive > 0.9, "the naive view should look convincing (that's the trap)"
    assert not verdict.credible, "deflation must reject pure search noise"
    assert verdict.deflated_sharpe < naive


def test_deflated_sharpe_accepts_a_genuinely_strong_signal():
    """A real, large edge must still survive correction — the test must not
    simply reject everything."""
    rng = random.Random(3)
    strong = [rng.gauss(0.004, 0.005) for _ in range(2000)]  # SR ~0.8/period
    verdict = st.assess_credibility(strong, n_trials=50,
                                    sr_variance_across_trials=0.01)
    assert verdict.credible, verdict.summary()
    assert verdict.deflated_sharpe > 0.95


# -------------------------------------------- minimum track record length

def test_min_track_record_shrinks_as_edge_grows():
    weak = st.minimum_track_record_length(0.05)
    strong = st.minimum_track_record_length(0.5)
    assert weak is not None and strong is not None
    assert weak > strong > 0


def test_min_track_record_is_none_without_an_edge():
    assert st.minimum_track_record_length(0.1, benchmark_sr=0.1) is None
    assert st.minimum_track_record_length(-0.2) is None


def test_min_track_record_rejects_bad_confidence():
    with pytest.raises(ValueError):
        st.minimum_track_record_length(0.5, confidence=1.0)


# ------------------------------------------------------------- verdicts

def test_verdict_handles_degenerate_inputs_conservatively():
    assert not st.assess_credibility([]).credible
    assert not st.assess_credibility([0.01]).credible
    flat = st.assess_credibility([0.01] * 100)
    assert not flat.credible and "undefined" in flat.reason


def test_verdict_summary_is_informative():
    rng = random.Random(1)
    v = st.assess_credibility([rng.gauss(0.0, 0.01) for _ in range(300)],
                              n_trials=40, sr_variance_across_trials=0.01)
    text = v.summary()
    assert "CREDIBLE" in text and "Sharpe" in text and "trial" in text


def test_losing_strategy_is_never_credible():
    rng = random.Random(8)
    losing = [rng.gauss(-0.003, 0.01) for _ in range(1000)]
    v = st.assess_credibility(losing)
    assert not v.credible and v.observed_sharpe < 0
