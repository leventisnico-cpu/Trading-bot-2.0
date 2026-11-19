"""The run loop survives a terminal that was closed and reopened: after
RECONNECT_AFTER failed ticks it reopens the broker link, and after
GIVE_UP_AFTER it exits so the watchdog starts a fresh bot (2026-11-18:
the link stayed dead for 17 hours behind a live process)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ftmo_bot import runner as runner_mod  # noqa: E402
from ftmo_bot.runner import GIVE_UP_AFTER, RECONNECT_AFTER  # noqa: E402
from test_ftmo_bot import FakeBroker  # noqa: E402
from test_ftmo_selftest import runner  # noqa: E402


class Stop(Exception):
    pass


class LinkDown(FakeBroker):
    """account() fails like a dead MT5 IPC link until reconnect() succeeds."""
    def __init__(self, bars, fixable=True):
        super().__init__(bars)
        self.down, self.fixable, self.reconnects = False, fixable, 0

    def account(self):
        if self.down:
            raise RuntimeError("no account: (-10001, 'IPC send failed')")
        return super().account()

    def reconnect(self):
        self.reconnects += 1
        self.down = not self.fixable
        return self.fixable


def naps(monkeypatch, limit):
    """Stub the loop's sleep: count the naps, end the loop after ``limit``."""
    seen = []

    def sleep(seconds):
        seen.append(seconds)
        if len(seen) >= limit:
            raise Stop()
    monkeypatch.setattr(runner_mod._time, "sleep", sleep)
    return seen


def test_the_link_is_reopened_after_two_failed_ticks(tmp_path, monkeypatch, caplog):
    r, b = runner(tmp_path, broker=LinkDown, hour=12, minute=0, keep_awake=False)
    b.down = True                                  # the terminal was closed after the start
    seen = naps(monkeypatch, RECONNECT_AFTER + 2)
    with caplog.at_level("INFO", logger="ftmo_bot"), pytest.raises(Stop):
        r.run()
    assert b.reconnects == 1                       # once, after the second failure
    assert len(seen) == RECONNECT_AFTER + 2        # then the ticks went through
    assert f"tick failed ({RECONNECT_AFTER} in a row)" in caplog.text
    assert f"reconnected to the terminal after {RECONNECT_AFTER} failed ticks" in caplog.text
    assert "giving up" not in caplog.text


def test_the_bot_exits_for_the_watchdog_when_the_link_stays_dead(tmp_path, monkeypatch, caplog):
    r, b = runner(tmp_path, broker=LinkDown, hour=12, minute=0, keep_awake=False)
    b.down, b.fixable = True, False               # closed, and never reopened
    seen = naps(monkeypatch, GIVE_UP_AFTER + 5)
    with caplog.at_level("INFO", logger="ftmo_bot"):
        r.run()                                    # returns instead of looping forever
    assert len(seen) == GIVE_UP_AFTER - 1
    assert b.reconnects == GIVE_UP_AFTER - RECONNECT_AFTER
    assert f"giving up after {GIVE_UP_AFTER} failed ticks in a row" in caplog.text
    assert "reconnect to the terminal failed" in caplog.text


def test_a_broker_without_reconnect_just_keeps_ticking(tmp_path, monkeypatch, caplog):
    class Plain(FakeBroker):
        def __init__(self, bars):
            super().__init__(bars)
            self.left = 0

        def account(self):
            if self.left:
                self.left -= 1
                raise RuntimeError("no account")
            return super().account()
    r, b = runner(tmp_path, broker=Plain, hour=12, minute=0, keep_awake=False)
    b.left = RECONNECT_AFTER
    seen = naps(monkeypatch, RECONNECT_AFTER + 1)
    with caplog.at_level("INFO", logger="ftmo_bot"), pytest.raises(Stop):
        r.run()
    assert len(seen) == RECONNECT_AFTER + 1
    assert "reconnected to the terminal" not in caplog.text
    assert "reconnect to the terminal failed" not in caplog.text
