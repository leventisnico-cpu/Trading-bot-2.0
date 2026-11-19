"""Free slots (``free_slots``, the operator's order of 2026-11-10; S2 of
research/ftmo_slots_sizing.md): a position whose stop is at or over its
entry takes none of the ``max_positions`` slots."""

from __future__ import annotations

import logging
import sys
from datetime import timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ftmo_bot import fast4  # noqa: E402
from ftmo_bot.broker import Position, Spec  # noqa: E402
from ftmo_bot.config import FtmoConfig, load  # noqa: E402
from ftmo_bot.runner import Runner, State, slot_rule  # noqa: E402
from test_ftmo_bot import FakeBroker, cfg, history, next_day, ny, open_session  # noqa: E402
from test_ftmo_readiness import MainBroker, cli_config, pinned_mt5  # noqa: E402
from test_ftmo_scale_out import Scene  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
R = 20.0                                  # entry to first stop of the seeded positions


# ------------------------------------------------------------- config

def test_free_slots_are_on_by_the_operators_order():
    """S2 did not pass its pre-registered rule; the operator ordered it on
    (2026-11-10, "free slots on") for the trial and the challenge."""
    assert FtmoConfig().free_slots is True
    for name in ("config.trial.yaml", "config.example.yaml"):
        c = load(ROOT / "deploy/ftmo" / name)
        assert c.free_slots is True and c.max_positions == 2


@pytest.mark.parametrize("line", ["free_slots:\n", "free_slots: 1\n", "free_slots: maybe\n"])
def test_free_slots_must_be_true_or_false(tmp_path, line):
    p = tmp_path / "c.yaml"
    p.write_text(line)
    with pytest.raises(ValueError, match="free_slots must be true or false"):
        load(p)


def test_free_slots_can_be_switched_off(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("free_slots: false\n")
    assert load(p).free_slots is False


def test_the_slot_rule_is_spelled_out_for_the_operator():
    assert slot_rule(FtmoConfig()) == ("2 positions at risk; a position whose stop is at "
                                       "or over its entry takes no slot")
    assert slot_rule(FtmoConfig(free_slots=False)) == ("2 positions; every open position "
                                                       "takes a slot")


# ------------------------------------------------------------ the plan

def ind(close, sma200, sma5, rsi, atr=10.0):
    return fast4.Indicators(close, sma200, sma5, rsi, atr)


def test_plan_gives_a_free_position_no_slot():
    i = {"US100": ind(105, 90, 101, 50), "US500": ind(105, 90, 101, 50),
         "US30": ind(100, 90, 101, 3), "US2000": ind(100, 90, 101, 5)}
    held = {"US100": 3, "US500": 2}
    keep = set(held)                                       # the 5 steps manage both
    assert fast4.plan(i, held, keep=keep).entries == []    # both take a slot
    assert fast4.plan(i, held, keep=keep, free={"US100"}).entries == ["US30"]
    p = fast4.plan(i, held, keep=keep, free={"US100", "US500"})
    assert p.entries == ["US30", "US2000"] and p.exits == []
    assert set(p.atr) == {"US30", "US2000"}
    i["US100"] = ind(100, 90, 101, 1)                      # a free, held index signals again
    assert fast4.plan(i, held, keep=keep, free=keep).entries == ["US30", "US2000"]


def test_a_free_position_that_exits_is_not_counted_twice():
    i = {"US100": ind(105, 90, 101, 50),                   # close > SMA5: FAST-4's exit
         "US500": ind(100, 90, 101, 4), "US30": ind(100, 90, 101, 3),
         "US2000": ind(100, 90, 101, 5)}
    p = fast4.plan(i, {"US100": 2}, free={"US100"})
    assert p.exits == ["US100"] and p.entries == ["US30", "US500"]     # two slots, not three


# ---------------------------------------------------------- the runner

def seeded(tmp_path, at_risk=(), free=(), **kw):
    """A runner holding 5-step positions before the plan of the last close:
    ``free`` with half sold and the stop at the entry (step 3 done),
    ``at_risk`` still on their first stop. US100 signals at that close."""
    bars, ds = history()
    b = FakeBroker(bars)
    b.clock = ny(ds[-1], 16, 10)
    kw.setdefault("dry_run", False)
    r = Runner(cfg(tmp_path, exit_mode="scale_out", **kw), b)
    for k, s in enumerate(list(at_risk) + list(free), start=5):
        sym = r.cfg.symbols[s]
        entry = bars[sym][-2][4] - 8                       # the bid stays over the entry
        done = s in free
        b.pos.append(Position(k, sym, 1.0, entry, entry if done else entry - R))
        r.st.held[s] = {"ticket": k, "entry_day": ds[-5].isoformat(), "exit": "scale_out",
                        "stop0": entry - R, "stage": int(done), "vol0": 2.0 if done else 1.0}
        if done:
            r.st.held[s]["sl_set"] = entry
    return r, b, bars, ds


@pytest.mark.parametrize("at_risk,free,entries", [
    ((), ("US500", "US30"), ["US100"]),                    # two open, none takes a slot
    (("US500",), ("US30",), ["US100"]),                    # one slot taken
    (("US500", "US30"), (), []),                           # both taken
    (("US500", "US30"), ("US2000",), []),                  # three open, both taken
])
def test_the_plan_counts_only_positions_at_risk(tmp_path, at_risk, free, entries):
    r, b, _, _ = seeded(tmp_path, at_risk, free)
    r.tick()
    assert r.st.pending_entries == entries
    assert [x for x in b.sent if x[0] != "buy"] == []      # the seeded trades were left alone
    assert r._slots_used(b.pos) == len(at_risk)
    assert r._free_symbols(b.pos) == set(free)


def test_with_free_slots_off_every_position_takes_a_slot(tmp_path):
    r, b, bars, ds = seeded(tmp_path, free=("US500", "US30"), free_slots=False)
    r.tick()
    assert r.st.pending_entries == []
    assert r._slots_used(b.pos) == 2 and r._free_symbols(b.pos) == set()


def test_an_entry_is_taken_beside_two_positions_that_cannot_lose(tmp_path):
    r, b, bars, ds = seeded(tmp_path, free=("US500", "US30"))
    r.tick()
    nxt = next_day(ds[-1])
    open_session(bars, nxt)
    b.clock = ny(nxt, 9, 35)
    r.tick()
    buys = [x for x in b.sent if x[0] == "buy"]
    assert len(buys) == 1 and buys[0][1] == "US100.cash"
    assert len(b.pos) == 3 and set(r.st.held) == {"US500", "US30", "US100"}
    _, ask = b.quote("US100.cash")
    assert buys[0][2] * (ask - buys[0][3]) <= 0.03 * 15000 + 1e-6      # still 3% at most
    assert r._slots_used(b.pos) == 1                       # only the new one is at risk


def test_a_planned_entry_is_refused_when_two_positions_are_at_risk_by_the_open(tmp_path,
                                                                                caplog):
    r, b, bars, ds = seeded(tmp_path, at_risk=("US500",), free=("US30",))
    r.tick()
    assert r.st.pending_entries == ["US100"]
    px = bars["US2000.cash"][-2][4]                        # opened outside the bot overnight
    b.pos.append(Position(9, "US2000.cash", 1.0, px - 8, px - 8 - R))
    nxt = next_day(ds[-1])
    open_session(bars, nxt)
    b.clock = ny(nxt, 9, 35)
    with caplog.at_level(logging.INFO, logger="ftmo_bot"):
        r.tick()
    assert [x for x in b.sent if x[0] == "buy"] == [] and len(b.pos) == 3
    assert "entry US100 refused: already 2 positions (max 2)" in caplog.text


def test_a_refused_stop_move_keeps_the_slot_until_it_goes_through(tmp_path):
    sc = Scene(tmp_path)
    p, r = sc.enter()
    sc.b.fail_modify = True
    sc.at(9, 40, US100=p.price_open + r + 1)               # +1R: half sold, stop move refused
    assert sc.sent("part") and sc.b.pos[0].sl == pytest.approx(p.sl)
    assert sc.r._slots_used(sc.b.pos) == 1 and sc.r._free_symbols(sc.b.pos) == set()
    sc.b.fail_modify = False
    sc.at(9, 46)                                           # the retry, five minutes on
    assert sc.b.pos[0].sl == pytest.approx(p.price_open)
    assert sc.r._slots_used(sc.b.pos) == 0 and sc.r._free_symbols(sc.b.pos) == {"US100"}


class QuarterStep(FakeBroker):
    """Stops sit on a 0.25 grid, as MT5 rounds them."""

    def spec(self, symbol):
        return Spec(True, 0.01, 0.01, 50, 0.25)


@pytest.mark.parametrize("broker,entry,sl,free", [
    (FakeBroker, 100.0, 100.0, True),                      # at the entry
    (FakeBroker, 100.0, 104.0, True),                      # over it
    (FakeBroker, 100.0, 99.99, False),                     # a cent under: still at risk
    (FakeBroker, 100.0, 0.0, False),                       # no stop at all
    (QuarterStep, 100.10, 100.0, True),                    # the nearest step to an average fill
    (QuarterStep, 100.10, 99.75, False),                   # a whole step under it
])
def test_a_stop_counts_as_at_the_entry_to_the_brokers_price_step(tmp_path, broker, entry,
                                                                 sl, free):
    bars, ds = history()
    b = broker(bars)
    b.clock = ny(ds[-1], 12, 0)
    r = Runner(cfg(tmp_path, exit_mode="scale_out"), b)
    p = Position(5, "US500.cash", 1.0, entry, sl)
    assert r._is_free(p) is free and r._slots_used([p]) == int(not free)
    off = Runner(cfg(tmp_path, exit_mode="scale_out", free_slots=False), b)
    assert off._is_free(p) is False and off._slots_used([p]) == 1


class NoSpec(FakeBroker):
    def spec(self, symbol):
        raise RuntimeError("symbol_info failed")


def test_an_unreadable_price_step_keeps_the_slot_and_stops_nothing(tmp_path, caplog):
    bars, ds = history()
    b = NoSpec(bars)
    b.clock = ny(ds[-1], 12, 0)
    r = Runner(cfg(tmp_path, exit_mode="scale_out"), b)
    at_entry = Position(5, "US500.cash", 1.0, 100.0, 100.0)
    under = Position(6, "US30.cash", 1.0, 100.10, 100.0)
    assert r._is_free(at_entry) is True                    # needs no price step
    with caplog.at_level(logging.WARNING, logger="ftmo_bot"):
        assert r._is_free(under) is False                  # unknown: the slot stays taken
    assert "price step unreadable" in caplog.text
    assert r._slots_used([at_entry, under]) == 1


def test_with_free_slots_off_the_plan_does_not_read_positions(tmp_path):
    r, b, _, _ = seeded(tmp_path, free=("US500", "US30"), free_slots=False)
    b.fail_positions = True                                # any read would raise
    assert r.compute_plan(b.clock)[1].entries == []
    on, b2, _, _ = seeded(tmp_path / "on", free=("US500", "US30"))
    b2.fail_positions = True
    with pytest.raises(RuntimeError, match="positions_get failed"):
        on.compute_plan(b2.clock)                          # free slots need the stops


def test_mt5_reports_the_price_step(monkeypatch):
    fake, b = pinned_mt5(monkeypatch, None)
    assert b.spec("US500.cash") == Spec(True, 0.01, 0.01, 500, 0.01)
    info = fake.symbol_info("US500.cash")
    info.trade_tick_size = 0.0                             # not reported: from the digits
    monkeypatch.setattr(fake, "symbol_info", lambda s: info)
    assert b.spec("US500.cash").tick == pytest.approx(0.01)


# ------------------------------------------- keep-alive and self-test

def test_keepalive_runs_with_two_at_risk_and_one_free(tmp_path):
    r, b, bars, ds = seeded(tmp_path, at_risk=("US500", "US30"), free=("US2000",))
    b.clock = ny(ds[-1], 10, 15)
    held = list(b.pos)
    r.roll_day(b.clock)
    r.st.last_fill = (b.clock - timedelta(days=26)).isoformat()
    r.keepalive(b.clock, held)
    assert [x[0] for x in b.sent] == ["buy", "close"] and b.pos == held


def test_selftest_runs_beside_four_open_positions(tmp_path):
    r, b, bars, ds = seeded(tmp_path, at_risk=("US100", "US30"), free=("US500", "US2000"))
    b.clock = ny(ds[-1], 10, 15)
    held = list(b.pos)
    lines = r.selftest(b.clock)
    assert [ok for ok, _ in lines] == [True, True, True, True], lines
    assert b.pos == held                                   # only its own ticket was touched


# --------------------------------------------------------------- the CLI

@pytest.mark.parametrize("extra,line", [
    ("", "slots: 2 positions at risk; a position whose stop is at or over its entry "
         "takes no slot\n"),
    ("free_slots: false\n", "slots: 2 positions; every open position takes a slot\n"),
])
@pytest.mark.parametrize("command", ["preflight", "plan"])
def test_cli_prints_the_slot_rule(tmp_path, monkeypatch, capsys, command, extra, line):
    from ftmo_bot import __main__ as cli, broker_mt5
    monkeypatch.setattr(broker_mt5, "MT5Broker", MainBroker)
    MainBroker.seed = []
    cli.main([command, "--config", cli_config(tmp_path, True, extra=extra)])
    assert line in capsys.readouterr().out


@pytest.mark.parametrize("command", ["preflight", "plan"])
def test_cli_says_which_open_positions_take_a_slot(tmp_path, monkeypatch, capsys, command):
    from ftmo_bot import __main__ as cli, broker_mt5
    monkeypatch.setattr(broker_mt5, "MT5Broker", MainBroker)
    MainBroker.seed = [Position(5, "US500.cash", 1.0, 100, 100),      # stop at the entry
                       Position(6, "US30.cash", 1.0, 100, 90)]        # first stop
    held = {"US500": {"ticket": 5, "entry_day": "2026-10-29", "exit": "scale_out",
                      "stop0": 90.0, "stage": 1},
            "US30": {"ticket": 6, "entry_day": "2026-10-29", "exit": "scale_out",
                     "stop0": 90.0, "stage": 0}}
    State(login=1, held=held).save(tmp_path / "st.json")
    before = (tmp_path / "st.json").read_text()
    cli.main([command, "--config", cli_config(tmp_path, False)])
    out = capsys.readouterr().out
    assert "takes no slot; taken now: 1 of 2; no slot taken by US500\n" in out
    assert MainBroker.last.sent == [] and (tmp_path / "st.json").read_text() == before
