"""Tests for the multi-signal ensemble (agreement to enter, one voice to exit)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

import pytest

from mini_prop_os.core.types import Action, Bar, OrderIntent
from mini_prop_os.strategy.base import BaseStrategy
from mini_prop_os.strategy.ensemble import EnsembleStrategy

SYM = "MES"
T0 = datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc)


class ScriptedStrategy(BaseStrategy):
    """A member whose votes are dictated by a script, for exact control."""

    def __init__(self, name: str, script: List[str], quantity: int = 2):
        super().__init__()
        self.strategy_id = name
        self.symbol = SYM
        self.script = list(script)
        self.quantity = quantity
        self._i = 0

    @property
    def warmup_bars(self) -> int:
        return 0

    def compute_signals(self, bar: Bar) -> List[OrderIntent]:
        action = self.script[self._i] if self._i < len(self.script) else ""
        self._i += 1
        if action == "BUY":
            return [OrderIntent(action=Action.BUY, symbol=SYM,
                                quantity=self.quantity,
                                strategy_id=self.strategy_id)]
        if action == "SELL":
            return [OrderIntent(action=Action.SELL, symbol=SYM,
                                quantity=max(self.position, 1),
                                strategy_id=self.strategy_id)]
        return []


def bar(i: int, price: float = 5000.0) -> Bar:
    return Bar(symbol=SYM, timestamp=T0 + timedelta(minutes=i), open=price,
               high=price + 1, low=price - 1, close=price, volume=100.0)


def drive(ens: EnsembleStrategy, n: int) -> List[OrderIntent]:
    out: List[OrderIntent] = []
    for i in range(n):
        for intent in ens.on_bar(bar(i)):
            out.append(intent)
            ens.on_own_fill(intent.signed_quantity, 5000.0)
    return out


# ----------------------------------------------------------- validation

def test_rejects_empty_membership():
    with pytest.raises(ValueError):
        EnsembleStrategy(SYM, [])


def test_rejects_impossible_agreement_threshold():
    m = ScriptedStrategy("a", [])
    with pytest.raises(ValueError):
        EnsembleStrategy(SYM, [m], min_agreement=2)
    with pytest.raises(ValueError):
        EnsembleStrategy(SYM, [m], min_agreement=0)


def test_rejects_members_trading_another_symbol():
    other = ScriptedStrategy("other", [])
    other.symbol = "QQQ"
    with pytest.raises(ValueError, match="different symbol"):
        EnsembleStrategy(SYM, [other], min_agreement=1)


def test_warmup_is_the_slowest_member():
    class Slow(ScriptedStrategy):
        @property
        def warmup_bars(self) -> int:
            return 200
    ens = EnsembleStrategy(SYM, [ScriptedStrategy("fast", []), Slow("slow", [])])
    assert ens.warmup_bars == 200


# -------------------------------------------------------------- voting

def test_entry_requires_the_agreement_threshold():
    a = ScriptedStrategy("a", ["BUY", "", "BUY"])
    b = ScriptedStrategy("b", ["", "", "BUY"])
    ens = EnsembleStrategy(SYM, [a, b], min_agreement=2)
    intents = drive(ens, 3)
    # Bar 0: only 'a' votes -> no entry. Bar 2: both -> entry.
    assert len(intents) == 1
    assert intents[0].action is Action.BUY
    assert "a" in intents[0].reason and "b" in intents[0].reason


def test_lone_vote_never_enters_under_unanimity():
    a = ScriptedStrategy("a", ["BUY"] * 5)
    b = ScriptedStrategy("b", [""] * 5)
    ens = EnsembleStrategy(SYM, [a, b], min_agreement=2)
    assert drive(ens, 5) == []


def test_single_member_ensemble_passes_signals_through():
    a = ScriptedStrategy("a", ["BUY"])
    ens = EnsembleStrategy(SYM, [a], min_agreement=1)
    assert len(drive(ens, 1)) == 1


def test_exit_needs_only_one_voice():
    """Shedding risk is never gated on consensus."""
    a = ScriptedStrategy("a", ["BUY", "SELL"])
    b = ScriptedStrategy("b", ["BUY", ""])
    ens = EnsembleStrategy(SYM, [a, b], min_agreement=2)
    intents = drive(ens, 2)
    assert [i.action for i in intents] == [Action.BUY, Action.SELL]
    assert ens.position == 0
    assert "a" in intents[1].reason


def test_exit_beats_entry_on_the_same_bar():
    """A simultaneous buy and sell resolves to the safe direction."""
    a = ScriptedStrategy("a", ["BUY", "SELL"])
    b = ScriptedStrategy("b", ["BUY", "BUY"])
    ens = EnsembleStrategy(SYM, [a, b], min_agreement=1)
    intents = drive(ens, 2)
    assert [i.action for i in intents] == [Action.BUY, Action.SELL]


def test_no_duplicate_entry_while_already_long():
    a = ScriptedStrategy("a", ["BUY", "BUY", "BUY"])
    b = ScriptedStrategy("b", ["BUY", "BUY", "BUY"])
    ens = EnsembleStrategy(SYM, [a, b], min_agreement=2)
    assert len(drive(ens, 3)) == 1


# --------------------------------------------------------------- sizing

def test_size_is_the_most_conservative_member_proposal():
    a = ScriptedStrategy("a", ["BUY"], quantity=5)
    b = ScriptedStrategy("b", ["BUY"], quantity=2)
    ens = EnsembleStrategy(SYM, [a, b], min_agreement=2)
    assert drive(ens, 1)[0].quantity == 2


def test_explicit_quantity_overrides_member_proposals():
    a = ScriptedStrategy("a", ["BUY"], quantity=5)
    b = ScriptedStrategy("b", ["BUY"], quantity=2)
    ens = EnsembleStrategy(SYM, [a, b], min_agreement=2, quantity=3)
    assert drive(ens, 1)[0].quantity == 3


def test_rejects_invalid_explicit_quantity():
    with pytest.raises(ValueError):
        EnsembleStrategy(SYM, [ScriptedStrategy("a", [])], quantity=0)


# ------------------------------------------------------ fill propagation

def test_fills_reach_every_member():
    """A member that thinks it is flat while the ensemble is long would
    keep proposing entries."""
    a = ScriptedStrategy("a", ["BUY"])
    b = ScriptedStrategy("b", ["BUY"])
    ens = EnsembleStrategy(SYM, [a, b], min_agreement=2)
    drive(ens, 1)
    assert ens.position == 2
    assert a.position == 2 and b.position == 2


def test_votes_are_recorded_for_diagnosis():
    a = ScriptedStrategy("a", ["BUY"])
    b = ScriptedStrategy("b", [""])
    ens = EnsembleStrategy(SYM, [a, b], min_agreement=2)
    drive(ens, 1)
    assert ens.last_votes == ["a"]
