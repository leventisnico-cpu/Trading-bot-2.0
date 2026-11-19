"""research/ftmo_slots_sizing.py: the two rules of the pre-registered note
(a share of the room over the max-loss line; free slots) and its verdict
rule, on a made-up market."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_ftmo_replay import write_market  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "ftmo_slots_sizing", Path(__file__).resolve().parents[1] / "research" / "ftmo_slots_sizing.py")
ss = importlib.util.module_from_spec(_spec)
sys.modules["ftmo_slots_sizing"] = ss
_spec.loader.exec_module(ss)
so, v2 = ss.so, ss.v2


@pytest.fixture(scope="module")
def market(tmp_path_factory):
    folder = tmp_path_factory.mktemp("slots")
    write_market(folder)
    return ss.base.load_all(folder)


@pytest.mark.parametrize("key", ["V1", "W2"])
@pytest.mark.parametrize("b", [0, 1])
def test_without_the_rules_it_is_the_published_account(market, key, b):
    dates, inst = market
    ref, _ = so.full_run(dates, inst, v2.CONT_POL[key][b], v2.SafeAcct)
    mine, _ = so.full_run(dates, inst, ss.CONT_POL[key][b], ss.SlotAcct)
    assert len(ref.trades) > 10 and ref.trades == mine.trades


class Watched(ss.SlotAcct):
    """Records the most positions at risk (stop under entry) after any session."""
    most = 0

    def step(self, i):
        out = super().step(i)
        Watched.most = max(Watched.most, sum(p.stop < p.entry for p in self.pos.values()))
        return out


def test_free_slots_take_more_signals_with_never_more_than_two_at_risk(market):
    dates, inst = market
    v1, _ = so.full_run(dates, inst, ss.CONT_POL["V1"][0], ss.SlotAcct)
    Watched.most = 0
    s2, _ = so.full_run(dates, inst, ss.CONT_POL["S2"][0], Watched)
    assert v1.max_open == 2 and s2.max_open > 2          # free positions ride along
    assert s2.entered > v1.entered
    assert Watched.most == 2                             # the two slots still bind
    assert s2.sig["signals"] == v1.sig["signals"]        # the same signals, more of them taken


def account(key, balance=1.0):
    a = ss.SlotAcct([], {}, ss.FTMO_POL[key][0])
    a.cash = a.day_start = balance
    return a


def test_a_position_that_cannot_lose_takes_no_slot():
    def pos(entry, stop):
        return so.SPos(1.0, entry, stop, entry, 1.0, 5.0, 1.0, 0)
    for key, slots in (("V1", 3), ("S2", 1), ("S3", 1), ("W2+S2", 1), ("S1", 3)):
        a = account(key)
        a.pos = {"at risk": pos(100.0, 95.0), "at entry": pos(100.0, 100.0),
                 "locked in": pos(100.0, 105.0)}
        assert a.in_slots() == slots, key


def test_the_share_caps_an_entry_at_a_third_of_the_max_loss_room():
    # the first trade is the ordered 3%: a third of the 9.8% of room is more
    assert account("S1").allowed(1.0) == pytest.approx(0.03)
    assert account("V1").allowed(1.0) == pytest.approx(0.03)
    # 7% down: V1 may use all 2.8% of room, S1 a third of it
    assert account("V1", 0.93).allowed(0.93) == pytest.approx(0.03 * 0.93)
    assert account("S1", 0.93).allowed(0.93) == pytest.approx(0.028 / 3)
    assert account("S1 at 1/2", 0.93).allowed(0.93) == pytest.approx(0.014)
    # with the 1.5% buffer the room is 1.5%
    assert account("W2", 0.93).allowed(0.93) == pytest.approx(0.015)
    assert account("W2+S1", 0.93).allowed(0.93) == pytest.approx(0.005)
    # at the buffer itself nothing is left, and S1 never asks for more than V1
    assert account("S1", 0.902).allowed(0.902) == pytest.approx(0.0, abs=1e-12)
    for bal in (1.0, 0.97, 0.95, 0.93, 0.91):
        assert account("S1", bal).allowed(bal) <= account("V1", bal).allowed(bal) + 1e-15


def test_the_share_leaves_the_daily_room_as_it_was():
    a = account("S1")
    a.pos = {"x": so.SPos(1.0, 100.0, 97.0, 100.0, 1.0, 3.0, 1.0, 0)}   # 3 of open risk...
    a.pos["x"].units = 0.01                                             # ...as 0.03 of the account
    a.cash = 0.0                                                        # balance 1.0 = 0.01 x 100
    daily, total = a.rooms(1.0)
    assert (daily, total) == (pytest.approx(0.018), pytest.approx(0.068))
    assert a.allowed(1.0) == pytest.approx(0.018)        # the daily line binds, not the third


def rows(*cells):
    """(breached, baseline's, both within 18 months, baseline's, ever, baseline's) per cell,
    in the order 2011-18 pessimistic, optimistic, 2019-26 pessimistic, optimistic."""
    where = [(c, b) for c in ss.COHORTS for b in (0, 1)]
    return [(c, b, 100, *cell) for (c, b), cell in zip(where, cells)]


SAME = (10, 10, 30, 30, 40, 40)


def test_the_verdict_rule():
    assert ss.judge(rows(SAME, SAME, SAME, SAME)) == (True, False)       # equal is not better
    faster = (10, 10, 31, 30, 40, 40)
    more = (10, 10, 30, 30, 41, 40)
    assert ss.judge(rows(faster, more, SAME, SAME)) == (True, True)      # one cohort, both bounds
    assert ss.judge(rows(faster, SAME, more, SAME)) == (True, False)     # one bound each: no
    assert ss.judge(rows(faster, faster, SAME, (11, 10, 30, 30, 40, 40))) == (False, True)
    assert ss.judge(rows(faster, faster, SAME, (10, 10, 29, 30, 45, 40))) == (False, True)
    assert ss.judge(rows(faster, faster, SAME, (10, 10, 35, 30, 39, 40))) == (False, True)
    fewer_breaches = (5, 10, 30, 30, 40, 40)
    assert ss.judge(rows(*[fewer_breaches] * 4)) == (True, False)        # safer alone is not enough
