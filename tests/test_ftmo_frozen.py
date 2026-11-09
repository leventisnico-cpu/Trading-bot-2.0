"""A frozen account: flat, with no room left over the max-loss line and its
buffer. The bot cannot open anything on it, and now says so."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ftmo_bot import rules  # noqa: E402
from ftmo_bot.broker import Position  # noqa: E402
from ftmo_bot.runner import Runner, State  # noqa: E402
from test_ftmo_bot import FakeBroker, cfg, history, next_day, ny, open_session, planned  # noqa: E402
from test_ftmo_readiness import MainBroker, cli_config  # noqa: E402


def test_rooms_line_by_line():
    lim = rules.Limits(15000)                    # lines: daily start - 750, max-loss 13,500
    assert rules.rooms(14000, 14000, 0, lim, 0.015) == pytest.approx((720, 275))
    assert rules.rooms(13700, 13700, 0, lim, 0.015) == pytest.approx((720, -25))
    assert rules.rooms(13700, 13700, 0, lim) == pytest.approx((720, 170))      # 0.2% buffer
    assert rules.risk_room(13700, 13700, 0, lim, 0.015) == 0.0                 # never negative


def at_the_open(tmp_path, balance, **kw):
    """A planned US100 entry, the next open, and the account at ``balance``."""
    r, b, bars, ds = planned(tmp_path, dry_run=False, exit_mode="scale_out", **kw)
    nxt = next_day(ds[-1])
    open_session(bars, nxt)
    b.clock = ny(nxt, 9, 35)
    r.st.day = nxt.isoformat()                   # the FTMO day already rolled
    r.st.day_start_balance = balance
    b.balance = b.equity = balance
    return r, b


def test_a_flat_account_with_no_max_loss_room_is_called_frozen(tmp_path, caplog):
    r, b = at_the_open(tmp_path, 13700.0)        # 8.7% down: under 13,500 + 1.5%
    with caplog.at_level(logging.INFO, logger="ftmo_bot"):
        r.tick()
    assert [x for x in b.sent if x[0] == "buy"] == []
    frozen = [x for x in caplog.records if "FROZEN" in x.getMessage()]
    assert len(frozen) == 1 and frozen[0].levelno == logging.WARNING
    assert "13,725.00" in frozen[0].getMessage() and "new phase" in frozen[0].getMessage()
    assert r.entry_room() == (0.0, True)


def test_the_same_balance_trades_on_without_the_buffer(tmp_path, caplog):
    r, b = at_the_open(tmp_path, 13700.0, cap_max_loss_buffer=0.002)   # room 13,700 - 13,530
    with caplog.at_level(logging.INFO, logger="ftmo_bot"):
        r.tick()
    assert len([x for x in b.sent if x[0] == "buy"]) == 1
    assert not [x for x in caplog.records if "FROZEN" in x.getMessage()]


def test_no_room_while_a_position_is_open_is_not_frozen(tmp_path, caplog):
    r, b = at_the_open(tmp_path, 15000.0)
    px = b.quote("US500.cash")[1]
    b.pos = [Position(9, "US500.cash", 72.0, px, px - 10.0)]   # its stop risks the 720 of room
    r.st.held["US500"] = {"ticket": 9, "entry_day": "2026-01-02", "exit": "scale_out",
                          "stop0": px - 10.0, "stage": 0}
    with caplog.at_level(logging.INFO, logger="ftmo_bot"):
        r.tick()
    msgs = [x.getMessage() for x in caplog.records]
    assert any("skipped: no risk room left" in m for m in msgs)
    assert not any("FROZEN" in m for m in msgs)
    assert r.entry_room() == (0.0, False)


def test_entry_room_on_a_healthy_account_and_with_the_cap_off(tmp_path):
    bars, ds = history()
    b = FakeBroker(bars)
    b.clock = ny(ds[-1], 12, 0)
    r = Runner(cfg(tmp_path, dry_run=False), b)
    assert r.entry_room() == (pytest.approx(720.0), False)     # the daily line binds
    off = Runner(cfg(tmp_path / "off", dry_run=False, cap_combined_risk=False), b)
    assert off.entry_room() is None


def test_the_log_and_the_preflight_use_one_definition_of_frozen(tmp_path):
    bars, ds = history()
    b = FakeBroker(bars)
    b.clock = ny(ds[-1], 12, 0)
    r = Runner(cfg(tmp_path, dry_run=False), b)
    assert r._frozen(True, 7.5) and r._frozen(True, -25.0)     # 0.05% of 15,000 or less
    assert not r._frozen(True, 7.6)                            # a little room is not frozen
    assert not r._frozen(False, -25.0)                         # nor is an account in a trade
    b.balance = b.equity = 13732.6                             # 7.6 over 13,725: the room is small,
    assert r.entry_room() == (pytest.approx(7.6), False)       # and the preflight shows it as room
    b.balance = b.equity = 13732.5
    assert r.entry_room() == (pytest.approx(7.5), True)


class Low(MainBroker):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.balance = self.equity = 13700.0


def test_preflight_shows_the_room_or_the_freeze(tmp_path, monkeypatch, capsys):
    from ftmo_bot import __main__ as cli, broker_mt5
    MainBroker.seed = []
    monkeypatch.setattr(broker_mt5, "MainBroker", MainBroker, raising=False)
    monkeypatch.setattr(broker_mt5, "MT5Broker", MainBroker)
    assert cli.main(["preflight", "--config", cli_config(tmp_path, False)]) == 0
    out = capsys.readouterr().out
    assert "room for the next entry: 720.00 (4.8% of the account)" in out
    assert "FROZEN" not in out and "WARN" not in out
    monkeypatch.setattr(broker_mt5, "MT5Broker", Low)
    State(login=1, initial_balance=15000.0).save(tmp_path / "st.json")
    assert cli.main(["preflight", "--config", cli_config(tmp_path, False)]) == 0
    out = capsys.readouterr().out
    assert "WARN: FROZEN." in out and "13,725.00" in out and "room for the next" not in out
