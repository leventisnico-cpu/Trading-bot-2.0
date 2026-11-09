"""The MT5 self-test: one tiny round trip through every order the 5 steps
send (``Runner.selftest`` and the ``selftest`` command)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ftmo_bot.broker import Fill  # noqa: E402
from ftmo_bot.runner import Runner, State  # noqa: E402
from test_ftmo_bot import FakeBroker, cfg, history, ny  # noqa: E402
from test_ftmo_readiness import MainBroker, cli_config  # noqa: E402

SYM = "US500.cash"


def runner(tmp_path, broker=FakeBroker, hour=10, minute=15, **kw):
    bars, ds = history()
    b = broker(bars)
    b.clock = ny(ds[-1], hour, minute)
    kw.setdefault("dry_run", False)
    return Runner(cfg(tmp_path, **kw), b), b


def test_selftest_sends_each_order_once_and_ends_flat(tmp_path):
    r, b = runner(tmp_path)
    ask = b.quote(SYM)[1]
    lines = r.selftest(b.clock)
    assert [ok for ok, _ in lines] == [True, True, True, True], lines
    buy, part, sl, close = b.sent
    assert buy[:3] == ("buy", SYM, 0.02) and buy[3] == pytest.approx(ask * 0.95)
    assert part[:3] == ("part", SYM, 0.01) and part[3] == "FAST4 selftest part"
    assert sl[:2] == ("sl", SYM) and sl[2] == pytest.approx(ask * 0.96)
    assert close == ("close", SYM, 0.01, "FAST4 selftest")
    assert b.pos == [] and r.st.held == {} and r.st.to_close == []
    st = State.load(tmp_path / "st.json")              # it traded: saved as such
    assert len(st.trading_days) == 1 and st.last_fill == b.clock.isoformat()


@pytest.mark.parametrize("hour,minute", [(9, 59), (10, 46), (12, 0)])
def test_selftest_runs_only_in_the_round_trip_window(tmp_path, hour, minute):
    r, b = runner(tmp_path, hour=hour, minute=minute)
    lines = r.selftest(b.clock)
    assert len(lines) == 1 and not lines[0][0] and "10:00-10:45" in lines[0][1]
    assert b.sent == [] and not (tmp_path / "st.json").exists()


@pytest.mark.parametrize("state", [dict(halted="max-loss"), dict(target_locked="2026-01-02"),
                                   dict(blocked_until="2999-01-01")])
def test_selftest_refuses_when_entries_are_off(tmp_path, state):
    r, b = runner(tmp_path)
    for k, v in state.items():
        setattr(r.st, k, v)
    lines = r.selftest(b.clock)
    assert len(lines) == 1 and not lines[0][0] and lines[0][1].startswith("not sent")
    assert b.sent == []


def test_selftest_refuses_near_a_loss_line(tmp_path):
    r, b = runner(tmp_path)
    b.equity = 13520.0                                  # within 0.2% of the max-loss line
    lines = r.selftest(b.clock)
    assert len(lines) == 1 and not lines[0][0] and "max-loss" in lines[0][1]
    assert b.sent == []


def test_selftest_in_dry_run_sends_nothing(tmp_path):
    r, b = runner(tmp_path, dry_run=True)
    lines = r.selftest(b.clock)
    assert len(lines) == 1 and lines[0][0] and lines[0][1].startswith("DRY-RUN")
    assert b.sent == [] and not (tmp_path / "st.json").exists()


class NoBuy(FakeBroker):
    def buy(self, symbol, volume, sl, magic, comment):
        self.sent.append(("buy-refused", symbol))
        return Fill(False, message="10017 trade disabled")


def test_selftest_reports_a_refused_buy_and_counts_no_trade(tmp_path):
    r, b = runner(tmp_path, broker=NoBuy)
    lines = r.selftest(b.clock)
    assert len(lines) == 1 and not lines[0][0] and "10017" in lines[0][1]
    assert r.st.trading_days == [] and r.st.last_fill is None and b.pos == []


class NoPartClose(FakeBroker):
    def close(self, position, magic, comment, volume=None):
        if volume is not None:
            self.sent.append(("part-refused", position.symbol))
            return Fill(False, message="10006 rejected")
        return super().close(position, magic, comment, volume)


def test_selftest_reports_a_refused_part_close_and_still_ends_flat(tmp_path):
    r, b = runner(tmp_path, broker=NoPartClose)
    lines = r.selftest(b.clock)
    assert [ok for ok, _ in lines] == [True, False, True, True], lines
    assert "0.02 left" in lines[1][1]
    assert b.sent[-1] == ("close", SYM, 0.02, "FAST4 selftest") and b.pos == []


def test_selftest_reports_a_refused_stop_move_and_still_ends_flat(tmp_path):
    r, b = runner(tmp_path)
    b.fail_modify = True
    lines = r.selftest(b.clock)
    assert [ok for ok, _ in lines] == [True, True, False, True], lines
    assert b.pos == [] and r.st.to_close == []


def test_a_selftest_close_that_fails_is_queued_for_run(tmp_path):
    r, b = runner(tmp_path)
    b.fail_close = True                                 # the part close and the final close
    lines = r.selftest(b.clock)
    assert [ok for ok, _ in lines] == [True, False, True, False], lines
    ticket = b.pos[0].ticket
    assert r.st.to_close == [ticket] and r.st.held == {}
    b.fail_close = False
    r.tick()                                            # `run` closes it, and never adopts it
    assert b.pos == [] and r.st.to_close == [] and r.st.held == {}


class BuyFillsThenRaises(FakeBroker):
    def buy(self, symbol, volume, sl, magic, comment):
        super().buy(symbol, volume, sl, magic, comment)
        raise ConnectionError("no reply")


def test_a_selftest_buy_that_raises_after_filling_is_closed_again(tmp_path):
    r, b = runner(tmp_path, broker=BuyFillsThenRaises)
    lines = r.selftest(b.clock)
    assert len(lines) == 1 and not lines[0][0]
    assert "no reply" in lines[0][1] and "The position it opened was closed." in lines[0][1]
    assert b.pos == [] and r.st.to_close == [] and r.st.held == {}
    assert len(r.st.trading_days) == 1                  # a position was opened


def test_a_selftest_buy_that_raises_and_cannot_be_closed_is_queued_for_run(tmp_path):
    r, b = runner(tmp_path, broker=BuyFillsThenRaises)
    b.fail_close = True
    lines = r.selftest(b.clock)
    assert len(lines) == 1 and not lines[0][0] and "`run` will retry it" in lines[0][1]
    assert r.st.to_close == [b.pos[0].ticket]
    b.fail_close = False
    r.tick()                                            # closed, never adopted as a trade
    assert b.pos == [] and r.st.to_close == [] and r.st.held == {}


def test_a_selftest_buy_that_raises_without_filling_opens_nothing(tmp_path):
    r, b = runner(tmp_path)
    b.fail_buy = True
    lines = r.selftest(b.clock)
    assert len(lines) == 1 and not lines[0][0] and "No position was opened." in lines[0][1]
    assert b.pos == [] and r.st.trading_days == [] and r.st.to_close == []


class PositionsDieAfterTheBuy(FakeBroker):
    def buy(self, symbol, volume, sl, magic, comment):
        f = super().buy(symbol, volume, sl, magic, comment)
        self.fail_positions = True                      # the terminal goes away
        return f


def test_an_error_after_the_selftest_buy_queues_its_ticket_for_run(tmp_path):
    r, b = runner(tmp_path, broker=PositionsDieAfterTheBuy)
    lines = r.selftest(b.clock)
    assert len(lines) == 1 and not lines[0][0] and "error after the buy" in lines[0][1]
    ticket = b.pos[0].ticket
    assert r.st.to_close == [ticket]
    assert State.load(tmp_path / "st.json").to_close == [ticket]   # saved: a restart keeps it
    b.fail_positions = False
    r.tick()                                            # `run` closes it, and never adopts it
    assert b.pos == [] and r.st.to_close == [] and r.st.held == {}


class Unlisted(FakeBroker):
    def buy(self, symbol, volume, sl, magic, comment):
        f = super().buy(symbol, volume, sl, magic, comment)
        self.hidden, self.pos = self.pos, []            # filled, but not in the list yet
        return f


def test_a_selftest_position_that_is_not_listed_is_queued(tmp_path):
    r, b = runner(tmp_path, broker=Unlisted)
    lines = r.selftest(b.clock)
    assert len(lines) == 1 and not lines[0][0] and "not listed" in lines[0][1]
    assert r.st.to_close == [b.hidden[0].ticket]
    b.pos = b.hidden                                    # it shows up after all
    r.tick()
    assert b.pos == [] and r.st.to_close == [] and r.st.held == {}


# ------------------------------------------------------------- the CLI

class TenFifteen(MainBroker):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.clock = self.clock.replace(hour=10, minute=15)


def patched(monkeypatch, broker=TenFifteen):
    from ftmo_bot import broker_mt5
    monkeypatch.setattr(broker_mt5, "MT5Broker", broker)
    MainBroker.seed = []


def test_cli_selftest_prints_a_line_per_order(tmp_path, monkeypatch, capsys):
    from ftmo_bot import __main__ as cli
    patched(monkeypatch)
    assert cli.main(["selftest", "--config", cli_config(tmp_path, False), "--execute"]) == 0
    out = capsys.readouterr().out
    assert out.count("PASS ") == 4 and "FAIL" not in out
    assert "self-test passed: this account takes every order the 5 steps send" in out
    assert [x[0] for x in MainBroker.last.sent] == ["buy", "part", "sl", "close"]
    assert "trading days 1 of 4" in out                 # it counted as a trading day


@pytest.mark.parametrize("dry_run,execute", [(True, False), (True, True), (False, False)])
def test_cli_selftest_without_both_opt_ins_sends_nothing(tmp_path, monkeypatch, capsys,
                                                         dry_run, execute):
    from ftmo_bot import __main__ as cli
    patched(monkeypatch)
    argv = ["selftest", "--config", cli_config(tmp_path, dry_run)] + (
        ["--execute"] if execute else [])
    assert cli.main(argv) == 0
    out = capsys.readouterr().out
    assert "DRY-RUN, nothing sent" in out and "PASS" not in out
    assert MainBroker.last.sent == [] and not (tmp_path / "st.json").exists()


def test_cli_selftest_outside_the_window_fails_and_sends_nothing(tmp_path, monkeypatch, capsys):
    from ftmo_bot import __main__ as cli
    patched(monkeypatch, MainBroker)                    # its clock reads 12:00
    assert cli.main(["selftest", "--config", cli_config(tmp_path, False), "--execute"]) == 1
    out = capsys.readouterr().out
    assert "FAIL not sent" in out and "self-test NOT passed" in out
    assert MainBroker.last.sent == []


def test_cli_selftest_refuses_while_run_holds_the_state(tmp_path, monkeypatch):
    from ftmo_bot import __main__ as cli, lock
    patched(monkeypatch)
    held = lock.for_state(str(tmp_path / "st.json"))
    assert held.acquire()
    try:
        assert cli.main(["selftest", "--config", cli_config(tmp_path, False), "--execute"]) == 1
        assert MainBroker.last.sent == []
    finally:
        held.release()
