"""Unit tests for the volatility-adaptive EMA strategy (pure, no broker)."""

from __future__ import annotations

import math
from typing import Iterable, List

import pytest

from mini_prop_os.core.types import Action, OrderIntent
from mini_prop_os.sim import bars_from_closes
from mini_prop_os.strategy.adaptive_ema import (AdaptiveEmaCrossoverStrategy,
                                                VolRegime)

SYM = "MES"


def strat(**kw) -> AdaptiveEmaCrossoverStrategy:
    params = dict(symbol=SYM, fast_period=3, slow_period=7,
                  base_quantity=2, warmup_bars=20, vol_fast_period=5,
                  vol_slow_period=40, confirm_window=10, learn=True,
                  high_vol_ratio=2.5, extreme_vol_ratio=4.0)
    params.update(kw)
    return AdaptiveEmaCrossoverStrategy(**params)


def run(s: AdaptiveEmaCrossoverStrategy, closes: Iterable[float],
        fill: bool = True) -> List[OrderIntent]:
    out: List[OrderIntent] = []
    for bar in bars_from_closes(list(closes), SYM):
        for it in s.on_bar(bar):
            out.append(it)
            if fill:
                s.on_own_fill(it.signed_quantity, bar.close)
    return out


# Deterministic +/-4pt noise keeps baseline volatility realistic: a series
# with literally zero variance makes every transition look like a vol
# explosion, which no real market exhibits.
def _noise(i: int, amp: float = 4.0) -> float:
    return amp if i % 2 == 0 else -amp


def calm(n: int, start: float = 5000.0, step: float = -2.0) -> List[float]:
    return [start + step * i + _noise(i) for i in range(n)]


def trend_up(n: int, start: float, step: float = 15.0) -> List[float]:
    return [start + step * i + _noise(i) for i in range(1, n + 1)]


def chop(n: int, level: float = 5000.0, amp: float = 12.0) -> List[float]:
    return [level + (amp if i % 2 == 0 else -amp) for i in range(n)]


def violent(n: int, start: float, pct: float = 0.05) -> List[float]:
    out, p = [], start
    for i in range(n):
        p *= (1 + pct) if i % 2 == 0 else (1 - pct)
        out.append(p)
    return out


# ------------------------------------------------------------- validation

def test_constructor_validation():
    with pytest.raises(ValueError):
        strat(fast_period=9, slow_period=5)
    with pytest.raises(ValueError):
        strat(base_quantity=0)
    with pytest.raises(ValueError):
        strat(vol_fast_period=50, vol_slow_period=40)
    with pytest.raises(ValueError):
        strat(high_vol_ratio=3.0, extreme_vol_ratio=2.0)


# --------------------------------------------------------------- regimes

def test_regime_detects_volatility_explosion():
    s = strat(high_vol_ratio=1.6, extreme_vol_ratio=2.5)  # shipped defaults
    run(s, calm(120))
    assert s.regime in (VolRegime.LOW, VolRegime.NORMAL)
    n_before = len(s.regime_history)
    run(s, violent(20, calm(120)[-1]))
    during = s.regime_history[n_before:]
    # The explosion must be flagged EXTREME while it is new; the slow
    # baseline then adapts, so the *final* regime may normalize — that
    # re-normalization is the "adapt to the new normal" behavior.
    assert VolRegime.EXTREME in during


def test_size_scales_down_with_volatility():
    s = strat(base_quantity=4)
    assert s.size_for_regime(VolRegime.LOW) == 4
    assert s.size_for_regime(VolRegime.NORMAL) == 4
    assert s.size_for_regime(VolRegime.HIGH) == 2
    assert s.size_for_regime(VolRegime.EXTREME) == 0


def test_extreme_regime_exits_position_and_blocks_entries():
    s = strat(high_vol_ratio=1.6, extreme_vol_ratio=2.5)  # shipped defaults
    intents = run(s, calm(60) + trend_up(40, calm(60)[-1]))
    assert [i.action for i in intents] == [Action.BUY]
    assert s.position > 0
    # Volatility explosion: must go flat (death cross or EXTREME risk-off,
    # whichever fires first) and never re-enter during the violence.
    last = trend_up(40, calm(60)[-1])[-1]
    more = run(s, violent(24, last))
    assert any(i.action is Action.SELL for i in more)
    assert not [i for i in more if i.action is Action.BUY]
    assert s.position == 0
    assert VolRegime.EXTREME in s.regime_history[-24:]


# --------------------------------------------------- confirmation filter

def test_strong_trend_enters_within_confirm_window():
    s = strat()
    intents = run(s, calm(60) + trend_up(40, calm(60)[-1]))
    assert [i.action for i in intents] == [Action.BUY]
    assert intents[0].quantity == 2  # base size in calm conditions


def test_chop_produces_no_entries():
    # Alternating +/- bars cross the EMAs repeatedly but the spread never
    # confirms, so the filter keeps the bot out of the whipsaw entirely.
    s = strat()
    level = calm(60)[-1]  # chop around where the calm segment ended
    intents = run(s, calm(60) + chop(120, level=level))
    assert [i for i in intents if i.action is Action.BUY] == []
    # And it must be the confirmation filter doing the blocking, not the
    # EXTREME risk-off gate.
    assert s.regime is not VolRegime.EXTREME


def test_death_cross_exit_is_never_filtered():
    s = strat()
    run(s, calm(60) + trend_up(40, calm(60)[-1]))
    assert s.position > 0
    last = calm(60)[-1] + 15 * 40
    exits = run(s, [last - 18 * i for i in range(1, 41)])
    assert any(i.action is Action.SELL for i in exits)
    assert s.position == 0


# --------------------------------------------------------------- learning

def test_losing_trades_raise_entry_threshold_bounded():
    s = strat(k_step=0.2, k_max=0.5)
    base = s.entry_thresholds[VolRegime.NORMAL]
    # Simulate completed losing round trips directly through fills.
    for _ in range(5):
        s._entry_regime = VolRegime.NORMAL
        s.on_own_fill(2, 5000.0)   # entry
        s.on_own_fill(-2, 4900.0)  # exit at a loss
    assert s.entry_thresholds[VolRegime.NORMAL] == pytest.approx(0.5)
    assert s.entry_thresholds[VolRegime.NORMAL] <= s.k_max
    assert s.regime_stats[VolRegime.NORMAL].trades == 5
    assert s.regime_stats[VolRegime.NORMAL].wins == 0
    assert base < 0.5


def test_winning_trades_relax_entry_threshold_bounded():
    s = strat(k_step=0.2, k_min=0.0)
    for _ in range(5):
        s._entry_regime = VolRegime.NORMAL
        s.on_own_fill(2, 5000.0)
        s.on_own_fill(-2, 5100.0)  # exit at a profit
    assert s.entry_thresholds[VolRegime.NORMAL] == pytest.approx(0.0)
    assert s.regime_stats[VolRegime.NORMAL].wins == 5


def test_learning_disabled_keeps_thresholds_fixed():
    s = strat(learn=False)
    before = dict(s.entry_thresholds)
    for _ in range(3):
        s._entry_regime = VolRegime.NORMAL
        s.on_own_fill(2, 5000.0)
        s.on_own_fill(-2, 4900.0)
    assert s.entry_thresholds == before


def test_extreme_threshold_is_never_learnable():
    s = strat(k_step=0.2)
    s._entry_regime = VolRegime.EXTREME
    s.on_own_fill(1, 5000.0)
    s.on_own_fill(-1, 5100.0)
    assert math.isinf(s.entry_thresholds[VolRegime.EXTREME])


def test_partial_fills_learn_from_true_average_prices():
    s = strat(k_step=0.1)
    s._entry_regime = VolRegime.NORMAL
    s.on_own_fill(1, 5000.0)   # partial entry 1
    s.on_own_fill(1, 5010.0)   # partial entry 2 -> avg 5005
    s.on_own_fill(-1, 5050.0)  # partial exit 1
    s.on_own_fill(-1, 5060.0)  # partial exit 2 -> win
    st = s.regime_stats[VolRegime.NORMAL]
    assert st.trades == 1 and st.wins == 1
    assert st.total_pnl_points == pytest.approx(
        (5050 - 5005) + (5060 - 5005))
