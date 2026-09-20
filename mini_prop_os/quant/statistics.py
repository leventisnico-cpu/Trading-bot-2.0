"""Multiple-testing statistics: is a measured Sharpe ratio real, or search noise?

Why this module exists
----------------------
Automated strategy search — an LLM proposing formulaic alphas, a grid sweep,
or a human trying ideas until one works — is a *multiple testing* machine.
Test enough strategies on the same history and some will show a high Sharpe
ratio through luck alone. Selecting the best of N trials and reporting its
in-sample Sharpe is not evidence; it is the definition of selection bias.

The size of the effect is not subtle. Under the null that every strategy is
worthless, the expected maximum Sharpe across N independent trials grows
roughly with √(2·ln N): search 100 strategies on 2 years of daily data and
the best worthless one is expected to post a Sharpe near 1.0.

This module implements the standard corrections (Bailey & López de Prado):

* :func:`probabilistic_sharpe_ratio` — probability the true Sharpe exceeds a
  benchmark, correcting for track length, skew, and fat tails.
* :func:`expected_max_sharpe` — the Sharpe a *worthless* strategy is expected
  to reach as the best of N trials. The bar selection must clear.
* :func:`deflated_sharpe_ratio` — PSR measured against that bar. This is the
  number that answers "is this real?"
* :func:`minimum_track_record_length` — how much data is needed before a
  Sharpe can be called significant at all.

Deliberately conservative choices: non-normality is penalized (fat tails and
negative skew make a Sharpe less trustworthy, and the formulas reflect
that), and every function degrades to a defensible answer rather than an
optimistic one when inputs are degenerate.

Pure stdlib; no numpy or scipy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

#: Euler-Mascheroni constant, used in the expected-maximum order statistic.
EULER_MASCHERONI = 0.5772156649015329

#: Trading periods per year for common bar sizes.
PERIODS_PER_YEAR_DAILY = 252
PERIODS_PER_YEAR_MINUTE = 252 * 1380  # ~23h futures session


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """Inverse standard normal CDF (probit).

    Acklam's rational approximation refined by two Newton steps against the
    erf-based CDF, which brings it to near machine precision without scipy.
    """
    if not 0.0 < p < 1.0:
        raise ValueError(f"p must be in (0, 1): {p}")
    a = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00)
    p_low, p_high = 0.02425, 1.0 - 0.02425
    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        x = (((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / \
            ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1.0)
    elif p <= p_high:
        q = p - 0.5
        r = q * q
        x = (((((a[0]*r + a[1])*r + a[2])*r + a[3])*r + a[4])*r + a[5])*q / \
            (((((b[0]*r + b[1])*r + b[2])*r + b[3])*r + b[4])*r + 1.0)
    else:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        x = -(((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / \
            ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1.0)
    # Newton refinement: f(x) = Phi(x) - p, f'(x) = phi(x).
    for _ in range(2):
        err = _norm_cdf(x) - p
        pdf = math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)
        if pdf < 1e-300:
            break
        x -= err / pdf
    return x


def _is_negligible_sd(sd: float, mean: float,
                      returns: Sequence[float]) -> bool:
    """True when a standard deviation is floating-point residue, not spread.

    Summing squared deviations of a constant series does not land exactly on
    zero, so a flat return stream yields an sd near 1e-18 rather than 0.
    Dividing by that produces a Sharpe around 1e15 and a strategy that never
    traded gets graded as flawless. The comparison must therefore be
    relative to the data's own scale, never against zero.
    """
    scale = max(abs(mean), max((abs(r) for r in returns), default=0.0))
    if scale <= 0.0:
        return sd <= 0.0
    return sd < scale * 1e-12


def _moments(returns: Sequence[float]) -> tuple[float, float, float, float]:
    """Mean, sample stdev, skewness, and *non-excess* kurtosis."""
    n = len(returns)
    if n < 2:
        raise ValueError("need at least 2 observations")
    mean = sum(returns) / n
    devs = [r - mean for r in returns]
    var = sum(d * d for d in devs) / (n - 1)
    sd = math.sqrt(var)
    if _is_negligible_sd(sd, mean, returns):
        return mean, 0.0, 0.0, 3.0  # constant series: normal-like defaults
    m3 = sum(d ** 3 for d in devs) / n
    m4 = sum(d ** 4 for d in devs) / n
    pop_sd = math.sqrt(sum(d * d for d in devs) / n)
    skew = m3 / (pop_sd ** 3)
    kurt = m4 / (pop_sd ** 4)  # non-excess: 3.0 for a normal distribution
    return mean, sd, skew, kurt


def sharpe_ratio(returns: Sequence[float],
                 periods_per_year: Optional[int] = None,
                 risk_free_rate: float = 0.0) -> float:
    """Sharpe ratio of a return series.

    Args:
        returns: per-period returns (not percentages).
        periods_per_year: if given, annualize by √periods; otherwise the
            per-period Sharpe is returned.
        risk_free_rate: per-period risk-free rate to subtract.

    Returns:
        0.0 for a constant series — an undefined Sharpe is reported as no
        evidence, never as infinity.
    """
    if len(returns) < 2:
        return 0.0
    excess = [r - risk_free_rate for r in returns]
    mean, sd, _, _ = _moments(excess)
    if sd <= 0:
        return 0.0
    sr = mean / sd
    return sr * math.sqrt(periods_per_year) if periods_per_year else sr


def probabilistic_sharpe_ratio(
    observed_sr: float,
    n_observations: int,
    benchmark_sr: float = 0.0,
    skew: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    """Probability that the true Sharpe exceeds ``benchmark_sr``.

    ``PSR = Φ[ (SR − SR*)·√(n−1) / √(1 − γ₃·SR + (γ₄−1)/4·SR²) ]``

    Negative skew and fat tails (γ₄ > 3) inflate the denominator, lowering
    confidence — which is correct: a Sharpe earned with occasional large
    losses is less trustworthy than the same number earned smoothly.

    Args:
        observed_sr: the measured Sharpe, in the same time unit as the
            observation count (do not mix an annualized SR with a daily n).
        n_observations: number of return observations.
        benchmark_sr: the Sharpe to beat (0 = "better than nothing";
            :func:`expected_max_sharpe` for a selection-corrected bar).
        skew: return skewness.
        kurtosis: **non-excess** kurtosis (3.0 = normal).

    Returns:
        A probability in [0, 1]; 0.0 when there is too little data to judge.
    """
    if n_observations < 2:
        return 0.0
    variance_term = (1.0
                     - skew * observed_sr
                     + 0.25 * (kurtosis - 1.0) * observed_sr * observed_sr)
    if variance_term <= 0:
        # Extreme skew/kurtosis combinations make the estimator undefined.
        return 0.0
    z = ((observed_sr - benchmark_sr) * math.sqrt(n_observations - 1)
         / math.sqrt(variance_term))
    return _norm_cdf(z)


def expected_max_sharpe(n_trials: int, sr_variance_across_trials: float) -> float:
    """The Sharpe a *worthless* strategy is expected to reach as best of N.

    ``E[max SR] ≈ √V · [(1−γ)·Φ⁻¹(1 − 1/N) + γ·Φ⁻¹(1 − 1/(N·e))]``

    This is the bar that selection must clear. With more trials, the bar
    rises — searching harder does not make a finding stronger, it makes the
    evidence required greater.

    Args:
        n_trials: how many strategies/configurations were actually tried.
            Counting only the ones you liked defeats the purpose.
        sr_variance_across_trials: variance of the Sharpe ratios observed
            across those trials.
    """
    if n_trials < 1:
        raise ValueError("n_trials must be >= 1")
    if sr_variance_across_trials <= 0:
        return 0.0
    if n_trials == 1:
        return 0.0  # no selection took place, so nothing to deflate
    sqrt_v = math.sqrt(sr_variance_across_trials)
    g = EULER_MASCHERONI
    term_1 = _norm_ppf(1.0 - 1.0 / n_trials)
    term_2 = _norm_ppf(1.0 - 1.0 / (n_trials * math.e))
    return sqrt_v * ((1.0 - g) * term_1 + g * term_2)


def deflated_sharpe_ratio(
    observed_sr: float,
    n_observations: int,
    n_trials: int,
    sr_variance_across_trials: float,
    skew: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    """Probability the strategy is real, after correcting for the search.

    The Probabilistic Sharpe Ratio measured against
    :func:`expected_max_sharpe` instead of zero. This is the number to quote
    when a strategy was *selected* from many candidates — the situation in
    every automated factor-discovery pipeline.

    Returns:
        A probability in [0, 1]. Below ~0.95 the finding is not distinguishable
        from the best of N coin flips.
    """
    bar = expected_max_sharpe(n_trials, sr_variance_across_trials)
    return probabilistic_sharpe_ratio(
        observed_sr=observed_sr, n_observations=n_observations,
        benchmark_sr=bar, skew=skew, kurtosis=kurtosis)


def minimum_track_record_length(
    observed_sr: float,
    benchmark_sr: float = 0.0,
    skew: float = 0.0,
    kurtosis: float = 3.0,
    confidence: float = 0.95,
) -> Optional[float]:
    """Observations needed before ``observed_sr`` beats the benchmark at
    ``confidence``.

    ``MinTRL = 1 + [1 − γ₃·SR + (γ₄−1)/4·SR²]·(Z_α / (SR − SR*))²``

    Returns:
        The required number of observations, or ``None`` when the observed
        Sharpe does not exceed the benchmark at all (no track length can
        rescue it).
    """
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be in (0, 1)")
    edge = observed_sr - benchmark_sr
    if edge <= 0:
        return None
    variance_term = (1.0 - skew * observed_sr
                     + 0.25 * (kurtosis - 1.0) * observed_sr * observed_sr)
    if variance_term <= 0:
        return None
    z = _norm_ppf(confidence)
    return 1.0 + variance_term * (z / edge) ** 2


@dataclass(frozen=True)
class CredibilityVerdict:
    """The full picture behind an accept/reject decision."""

    observed_sharpe: float
    n_observations: int
    n_trials: int
    selection_bar: float
    probabilistic_sharpe: float
    deflated_sharpe: float
    min_track_record: Optional[float]
    credible: bool
    reason: str

    def summary(self) -> str:
        head = "CREDIBLE" if self.credible else "NOT CREDIBLE"
        return (f"{head}: Sharpe {self.observed_sharpe:.3f} over "
                f"{self.n_observations} obs from {self.n_trials} trial(s); "
                f"selection bar {self.selection_bar:.3f}, "
                f"DSR {self.deflated_sharpe:.3f}. {self.reason}")


def assess_credibility(
    returns: Sequence[float],
    n_trials: int = 1,
    sr_variance_across_trials: float = 0.0,
    confidence: float = 0.95,
    periods_per_year: Optional[int] = None,
) -> CredibilityVerdict:
    """End-to-end verdict on whether a return series shows a real edge.

    Sharpe, skew, and kurtosis are measured from ``returns``; the deflated
    Sharpe is computed against the selection bar implied by ``n_trials``.
    The verdict is ``credible`` only when DSR >= ``confidence``.

    Note the per-period Sharpe is used for the statistics regardless of
    ``periods_per_year`` (which only affects the reported figure), because
    the observation count and the Sharpe must share a time unit.
    """
    if len(returns) < 2:
        return CredibilityVerdict(
            0.0, len(returns), n_trials, 0.0, 0.0, 0.0, None, False,
            "Not enough observations to compute a Sharpe ratio.")

    _, sd, skew, kurt = _moments(returns)
    if sd <= 0:
        return CredibilityVerdict(
            0.0, len(returns), n_trials, 0.0, 0.0, 0.0, None, False,
            "Return series has no variance; a Sharpe ratio is undefined.")

    sr_period = sharpe_ratio(returns)
    n = len(returns)
    bar = expected_max_sharpe(n_trials, sr_variance_across_trials)
    psr = probabilistic_sharpe_ratio(sr_period, n, 0.0, skew, kurt)
    dsr = deflated_sharpe_ratio(sr_period, n, n_trials,
                                sr_variance_across_trials, skew, kurt)
    min_trl = minimum_track_record_length(sr_period, bar, skew, kurt,
                                          confidence)
    reported = (sr_period * math.sqrt(periods_per_year)
                if periods_per_year else sr_period)

    credible = dsr >= confidence
    if credible:
        reason = (f"Survives correction for {n_trials} trial(s) at "
                  f"{confidence:.0%} confidence.")
    elif sr_period <= 0:
        reason = "Sharpe ratio is not positive."
    elif sr_period <= bar:
        reason = (f"Sharpe {sr_period:.3f} does not clear the "
                  f"{bar:.3f} expected from selecting the best of "
                  f"{n_trials} worthless trials.")
    elif min_trl is not None:
        reason = (f"Needs about {min_trl:.0f} observations to reach "
                  f"{confidence:.0%} confidence; have {n}.")
    else:
        reason = "Insufficient evidence after multiple-testing correction."

    return CredibilityVerdict(
        observed_sharpe=reported, n_observations=n, n_trials=n_trials,
        selection_bar=bar, probabilistic_sharpe=psr, deflated_sharpe=dsr,
        min_track_record=min_trl, credible=credible, reason=reason)
