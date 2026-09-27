"""Unit tests for the EMA-crossover strategy signal logic (pure, no broker)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, List

import pytest

from mini_prop_os.core.types import Action, Bar, IntentSource, OrderIntent
from mini_prop_os.strategy.ema_crossover import EmaCrossoverStrategy

T0 = datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc)


def bars(closes: Iterable[float], symbol: str = "SPY") -> List[Bar]:
    out = []
    for i, c in enumerate(closes):
        out.append(Bar(symbol=symbol, timestamp=T0 + timedelta(minutes=i),
                       open=c, high=c + 0.05, low=c - 0.05, close=c,
                       volume=1000.0))
    return out


def strat(**kw) -> EmaCrossoverStrategy:
    params = dict(symbol="SPY", fast_period=3, slow_period=7,
                  order_quantity=10, warmup_bars=10)
    params.update(kw)
    return EmaCrossoverStrategy(**params)


def run(s: EmaCrossoverStrategy, closes: Iterable[float],
        fill_on_intent: bool = True) -> List[OrderIntent]:
    """Feed bars; optionally simulate immediate fills so position feedback
    matches live behavior."""
    all_intents: List[OrderIntent] = []
    for bar in bars(closes):
        for it in s.on_bar(bar):
            all_intents.append(it)
            if fill_on_intent:
                s.on_own_fill(it.signed_quantity, bar.close)
    return all_intents


# A path that trends down long enough to warm up with fast<slow, then turns
# sharply up (golden cross), then sharply down again (death cross).
DOWN = [100 - 0.3 * i for i in range(15)]        # bars 1..15, fast < slow
UP = [DOWN[-1] + 1.0 * i for i in range(1, 11)]  # strong up: golden cross
DOWN2 = [UP[-1] - 1.5 * i for i in range(1, 11)]  # strong down: death cross


def test_constructor_validation():
    with pytest.raises(ValueError):
        EmaCrossoverStrategy("SPY", fast_period=10, slow_period=5)
    with pytest.raises(ValueError):
        EmaCrossoverStrategy("SPY", fast_period=5, slow_period=5)
    with pytest.raises(ValueError):
        EmaCrossoverStrategy("SPY", order_quantity=0)


def test_no_signals_during_warmup():
    s = strat(warmup_bars=50)
    intents = run(s, DOWN + UP)  # 25 bars < 50 warmup
    assert intents == []
    assert not s.is_warm


def test_golden_cross_emits_single_buy():
    s = strat()
    intents = run(s, DOWN + UP)
    assert [i.action for i in intents] == [Action.BUY]
    buy = intents[0]
    assert buy.symbol == "SPY"
    assert buy.quantity == 10
    assert buy.source is IntentSource.STRATEGY
    assert buy.strategy_id == "ema_crossover"
    assert s.position == 10
    # EMAs really did cross.
    assert s.ema_fast is not None and s.ema_slow is not None
    assert s.ema_fast > s.ema_slow


def test_death_cross_exits_entire_position():
    s = strat()
    intents = run(s, DOWN + UP + DOWN2)
    assert [i.action for i in intents] == [Action.BUY, Action.SELL]
    sell = intents[1]
    assert sell.quantity == 10  # exits the full position
    assert s.position == 0


def test_death_cross_while_flat_emits_nothing():
    # Without fills the BUY never establishes a position, so the later
    # death cross must not emit a SELL (long-only, position-aware).
    s = strat()
    intents = run(s, DOWN + UP + DOWN2, fill_on_intent=False)
    assert [i.action for i in intents] == [Action.BUY]


def test_no_repeated_entries_without_new_cross():
    s = strat()
    # After the golden cross, keep trending up: no further intents.
    intents = run(s, DOWN + UP + [UP[-1] + i for i in range(1, 20)])
    assert len(intents) == 1


def test_partial_fill_feedback_sizes_exit_correctly():
    s = strat()
    for bar in bars(DOWN + UP):
        for it in s.on_bar(bar):
            assert it.action is Action.BUY
            s.on_own_fill(6, bar.close)  # only 6 of 10 filled
    assert s.position == 6
    sells = [i for b in bars(DOWN2) for i in s.on_bar(b)]
    assert len(sells) == 1
    assert sells[0].action is Action.SELL
    assert sells[0].quantity == 6  # exit what we actually hold


def test_foreign_symbol_bars_ignored():
    s = strat()
    run(s, DOWN)
    seen_before = s.ema_fast
    out = s.on_bar(Bar(symbol="QQQ", timestamp=T0 + timedelta(hours=5),
                       open=1, high=1, low=1, close=1, volume=1))
    assert out == []
    assert s.ema_fast == seen_before  # untouched by the foreign bar


def test_non_positive_close_skipped_without_corrupting_emas():
    s = strat()
    run(s, DOWN)
    before = (s.ema_fast, s.ema_slow)
    s.on_bar(Bar(symbol="SPY", timestamp=T0 + timedelta(hours=6),
                 open=-1.0, high=0.0, low=-1.0, close=0.0, volume=0.0))
    assert (s.ema_fast, s.ema_slow) == before


def test_prime_produces_no_intents_but_warms_state():
    s = strat()
    s.prime(bars(DOWN + UP))  # crossover inside the primed history
    assert s.is_warm
    assert s.position == 0  # priming must never imply trades
    # A fresh down-turn after priming can still signal (state is live).
    intents = [i for b in bars(DOWN2) for i in s.on_bar(b)]
    assert intents == []  # flat, long-only: nothing to exit


def test_bar_ohlc_consistency_enforced():
    with pytest.raises(ValueError):
        Bar(symbol="SPY", timestamp=T0, open=10.0, high=9.0, low=9.5,
            close=9.7, volume=1.0)
