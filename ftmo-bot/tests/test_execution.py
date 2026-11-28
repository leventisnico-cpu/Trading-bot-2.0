"""Phase 5: state, guard, router, runner against a mocked MetaTrader5."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from ftmo_bot.config import FtmoProfile, StrategyParams, engine_limits, risk_amount
from ftmo_bot.execution.mt5_client import MT5Client, MT5Error
from ftmo_bot.execution.notify import Notifier
from ftmo_bot.execution.order_router import OrderRouter
from ftmo_bot.execution.runner import RefuseToStart, Runner
from ftmo_bot.execution.state import HaltRecord, StateStore, idempotency_key
from ftmo_bot.risk import ftmo_rules
from ftmo_bot.risk.guard import Guard
from ftmo_bot.strategy.asian_breakout import AsianBreakout

from .fake_mt5 import FakeMT5, FakePosition
from .synth import DAY, day_bars, h4_up, utc

MIDNIGHT = utc(DAY, 0, 0) + timedelta(seconds=2)


class Clock:
    def __init__(self, t: datetime, fake: FakeMT5) -> None:
        self.t = t
        self.fake = fake
        fake.now = t

    def __call__(self) -> datetime:
        return self.t

    def set(self, t: datetime) -> None:
        self.t = t
        self.fake.now = t


class Rig:
    def __init__(
        self, tmp: Path, params: StrategyParams, profile: FtmoProfile, start: datetime = MIDNIGHT
    ) -> None:
        self.fake = FakeMT5()
        self.clock = Clock(start, self.fake)
        self.params, self.profile = params, profile
        self.store = StateStore(tmp / "state")
        self.limits = engine_limits(profile, params)
        self.notes = Notifier()
        self.client = MT5Client(self.fake, sleep=lambda s: None)
        self.guard = Guard(
            self.client, self.store, self.limits, params, profile, self.notes, self.clock
        )

    def router(self) -> OrderRouter:
        return OrderRouter(
            self.client,
            self.store,
            self.limits,
            self.profile,
            risk_amount(self.profile, self.params),
            self.notes,
            self.clock,
        )

    def runner(self, require_demo: bool = False) -> Runner:
        return Runner(
            self.client,
            self.store,
            self.router(),
            AsianBreakout(self.params),
            self.params,
            self.profile,
            self.limits,
            self.notes,
            self.clock,
            require_demo=require_demo,
        )

    def open_position(
        self,
        symbol: str = "EURUSD",
        price: float = 1.1016,
        sl: float = 1.0990,
        tp: float = 1.1066,
        magic: int | None = None,
    ) -> None:
        self.fake.positions.append(
            FakePosition(
                len(self.fake.positions) + 1,
                symbol,
                0,
                3.0,
                price,
                sl,
                tp,
                price,
                self.profile.magic if magic is None else magic,
                "x",
            )
        )
        self.fake.bid[symbol] = price - 0.0001


# ------------------------------------------------------------------ state


def test_state_roundtrips(tmp_path: Path) -> None:
    s = StateStore(tmp_path)
    now = datetime(2026, 3, 4, 10, tzinfo=UTC)
    assert s.load_baseline() is None and s.heartbeat_age(now) is None and s.read_halt() is None
    b = ftmo_rules.Baseline(date(2026, 3, 4), 100_500.0, now)
    s.save_baseline(b)
    assert s.load_baseline() == b
    s.write_heartbeat(now - timedelta(seconds=4))
    assert s.heartbeat_fresh(now, 10) and not s.heartbeat_fresh(now + timedelta(seconds=7), 10)
    s.add_key("k")
    s.add_key("k")
    assert s.has_key("k") and not s.has_key("j")
    s.write_halt(HaltRecord("overall", "r", date(2026, 3, 3), now))
    assert not s.clear_daily_halt(date(2026, 3, 4))  # overall halts never auto-clear
    s.halt_path.write_text("garbage")
    assert s.read_halt() is not None and s.read_halt().kind == "manual"  # type: ignore[union-attr]
    st = s.load_runner()
    st.day, st.consecutive_losses = date(2026, 3, 4), 1
    s.save_runner(st)
    assert s.load_runner().consecutive_losses == 1
    assert idempotency_key("EURUSD", "2026-03-04", "long") == "EURUSD|2026-03-04|long"


# ------------------------------------------------------------------ guard


def test_guard_snapshots_baseline_and_survives_restart(
    tmp_path: Path, params: StrategyParams, profile: FtmoProfile
) -> None:
    rig = Rig(tmp_path, params, profile)
    rig.guard.tick()
    b = rig.store.load_baseline()
    assert b is not None and b.day == DAY and b.equity == 100_000 and not b.late
    # Mid-day restart with equity down: a NEW guard keeps the midnight baseline.
    rig.fake.equity = 98_800.0
    rig.clock.set(utc(DAY, 13))
    g2 = Guard(rig.client, rig.store, rig.limits, params, profile, rig.notes, rig.clock)
    out = g2.tick()
    assert out.baseline == 100_000 and out.halted is None


def test_guard_flattens_on_induced_drawdown(
    tmp_path: Path, params: StrategyParams, profile: FtmoProfile
) -> None:
    rig = Rig(tmp_path, params, profile)
    rig.guard.tick()
    rig.clock.set(utc(DAY, 9, 30))
    rig.open_position()
    rig.open_position("GBPUSD", 1.2716, 1.2690, 1.2766)
    rig.fake.pending = [77]
    assert rig.guard.tick().closed == []  # in session, inside limits
    rig.fake.equity = 97_499.0  # 2.5% drawdown induced
    rig.clock.set(utc(DAY, 9, 30) + timedelta(seconds=5))
    out = rig.guard.tick()
    assert out.halted == "daily" and sorted(out.closed) == [1, 2]
    assert rig.fake.positions == [] and rig.fake.pending == []
    halt = rig.store.read_halt()
    assert halt is not None and halt.kind == "daily" and "daily loss" in halt.reason
    assert any("GUARD HALT" in m for m in rig.notes.sent)
    # Within 10 s of the breach (one 5 s poll), and heartbeat keeps flowing.
    assert rig.store.heartbeat_fresh(rig.clock(), 10)
    # Next day: daily halt clears; new baseline.
    rig.fake.equity = 97_499.0
    rig.clock.set(utc(DAY + timedelta(days=1), 0, 0) + timedelta(seconds=3))
    out = rig.guard.tick()
    assert out.halted is None and rig.store.read_halt() is None


def test_guard_overall_halt_needs_human(
    tmp_path: Path, params: StrategyParams, profile: FtmoProfile
) -> None:
    rig = Rig(tmp_path, params, profile)
    rig.fake.equity = 95_000.0
    rig.guard.tick()  # baseline 95k (late snapshot is fine here)
    rig.fake.equity = 94_000.0
    rig.clock.set(utc(DAY, 10))
    assert rig.guard.tick().halted == "overall"
    rig.clock.set(utc(DAY + timedelta(days=2), 10))
    rig.fake.equity = 94_000.0
    assert rig.guard.tick().halted == "overall"  # not auto-cleared


def test_guard_overall_supersedes_daily(
    tmp_path: Path, params: StrategyParams, profile: FtmoProfile
) -> None:
    rig = Rig(tmp_path, params, profile)
    rig.guard.tick()
    rig.fake.equity = 97_000.0
    assert rig.guard.tick().halted == "daily"
    rig.fake.equity = 93_000.0
    assert rig.guard.tick().halted == "overall"


def test_guard_withholds_heartbeat_when_mt5_down(
    tmp_path: Path, params: StrategyParams, profile: FtmoProfile
) -> None:
    rig = Rig(tmp_path, params, profile)
    rig.fake.fail_account = True
    out = rig.guard.tick()
    assert out.equity is None and rig.store.heartbeat_age(rig.clock()) is None
    assert any("unreachable" in m for m in rig.notes.sent)


def test_guard_backstops_time_exit_and_friday(
    tmp_path: Path, params: StrategyParams, profile: FtmoProfile
) -> None:
    rig = Rig(tmp_path, params, profile)
    rig.guard.tick()
    rig.open_position()
    rig.clock.set(utc(DAY, 11, 46))  # past EURUSD's 11:45 time exit
    assert rig.guard.tick().closed == [1]
    friday = date(2026, 3, 6)
    rig.clock.set(utc(friday, 21, 0) + timedelta(seconds=1))
    rig.open_position("XAUUSD", 2300.0, 2290.0, 2320.0)
    out = rig.guard.tick()
    assert out.reason == "friday cutoff" and out.closed == [1]


def test_guard_daily_summary_once(
    tmp_path: Path, params: StrategyParams, profile: FtmoProfile
) -> None:
    rig = Rig(tmp_path, params, profile)
    rig.guard.tick()
    rig.clock.set(utc(DAY, 0, 5))
    rig.guard.tick()
    rig.guard.tick()
    assert sum(m.startswith("DAILY") for m in rig.notes.sent) == 1


# ------------------------------------------------------------------ runner


def _market(rig: Rig) -> None:
    rig.fake.set_rates("EURUSD", 15, day_bars("EURUSD", DAY, 1.1010, 1.0990, 1.1015))
    rig.fake.set_rates("EURUSD", rig.fake.TIMEFRAME_H4, h4_up("EURUSD", utc(DAY, 9), 1.05, 0.001))
    rig.fake.bid["EURUSD"] = 1.1015


def test_runner_refuses_start_on_stale_heartbeat_or_halt(
    tmp_path: Path, params: StrategyParams, profile: FtmoProfile
) -> None:
    rig = Rig(tmp_path, params, profile)
    with pytest.raises(RefuseToStart, match="missing"):
        rig.runner().preflight()
    rig.guard.tick()
    rig.clock.set(MIDNIGHT + timedelta(seconds=11))
    with pytest.raises(RefuseToStart, match="old"):
        rig.runner().preflight()
    rig.guard.tick()
    rig.runner().preflight()  # fresh → ok
    rig.store.write_halt(HaltRecord("daily", "test", DAY, rig.clock()))
    with pytest.raises(RefuseToStart, match="HALT"):
        rig.runner().preflight()


def test_paper_mode_requires_demo(
    tmp_path: Path, params: StrategyParams, profile: FtmoProfile
) -> None:
    rig = Rig(tmp_path, params, profile)
    rig.guard.tick()
    rig.fake.trade_mode = 2
    with pytest.raises(RefuseToStart, match="demo"):
        rig.runner(require_demo=True).preflight()


def test_runner_places_with_server_side_sl_tp_and_restart_does_not_double_enter(
    tmp_path: Path, params: StrategyParams, profile: FtmoProfile
) -> None:
    rig = Rig(tmp_path, params, profile)
    rig.guard.tick()
    _market(rig)
    rig.clock.set(utc(DAY, 9, 15) + timedelta(seconds=20))
    rig.guard.tick()
    rig.runner().step()
    deals = [r for r in rig.fake.sent if r["action"] == 1]
    assert len(deals) == 1
    o = deals[0]
    assert o["sl"] == pytest.approx(1.0990) and o["tp"] == pytest.approx(1.1065)
    assert o["volume"] == pytest.approx(3.0) and o["magic"] == profile.magic
    assert rig.store.has_key("EURUSD|2026-03-04|long")
    # Crash + restart: a brand-new runner/strategy re-warms and sees the same
    # fresh breakout, but the persisted idempotency key blocks a second entry.
    rig.fake.positions.clear()
    rig.clock.set(rig.clock() + timedelta(seconds=10))
    rig.guard.tick()
    rig.runner().step()
    assert len([r for r in rig.fake.sent if r["action"] == 1]) == 1
    assert any("duplicate" in m for m in rig.notes.sent)


def test_runner_ignores_stale_signals_after_restart(
    tmp_path: Path, params: StrategyParams, profile: FtmoProfile
) -> None:
    rig = Rig(tmp_path, params, profile)
    _market(rig)
    rig.clock.set(utc(DAY, 9, 45))  # breakout bar closed 30 min ago
    rig.guard.tick()
    rig.runner().step()
    assert rig.fake.sent == []


def test_router_blocks_without_heartbeat_halt_or_baseline(
    tmp_path: Path, params: StrategyParams, profile: FtmoProfile
) -> None:
    from ftmo_bot.strategy.base import Signal

    rig = Rig(tmp_path, params, profile)
    sig = Signal("EURUSD", "long", 1.1015, 1.0990, 1.1065, "EURUSD:2026-03-04")
    r = rig.router()
    assert "heartbeat" in r.place(sig, 0).reason
    rig.store.write_heartbeat(rig.clock())
    assert "baseline" in r.place(sig, 0).reason
    rig.guard.tick()
    assert "soft stop" in r.place(sig, 2).reason  # can_open in the path
    rig.store.write_halt(HaltRecord("daily", "x", DAY, rig.clock()))
    assert "HALT" in r.place(sig, 0).reason
    rig.store.halt_path.unlink()
    rig.fake.reject_orders = True
    res = r.place(sig, 0)
    assert not res.placed and "order failed" in res.reason
    assert rig.store.has_key("EURUSD|2026-03-04|long")  # key persisted before sending
    assert rig.fake.sent and rig.fake.sent[-1]["sl"] == 1.0990


def test_router_counts_unknown_positions_as_unbounded_risk(
    tmp_path: Path, params: StrategyParams, profile: FtmoProfile
) -> None:
    from ftmo_bot.strategy.base import Signal

    rig = Rig(tmp_path, params, profile)
    rig.guard.tick()
    rig.open_position("USDJPY", 150.0, 0.0, 0.0)
    sig = Signal("EURUSD", "long", 1.1015, 1.0990, 1.1065, "EURUSD:2026-03-04")
    assert "projected" in rig.router().place(sig, 0).reason


def test_runner_breakeven_once(
    tmp_path: Path, params: StrategyParams, profile: FtmoProfile
) -> None:
    rig = Rig(tmp_path, params, profile)
    rig.clock.set(utc(DAY, 9, 30))
    rig.guard.tick()
    rig.open_position()
    run = rig.runner()
    run.step()  # learns original stop
    rig.fake.bid["EURUSD"] = 1.1043  # +1.04 R
    run.step()
    run.step()
    mods = [r for r in rig.fake.sent if r["action"] == 6]
    assert len(mods) == 1 and mods[0]["sl"] == pytest.approx(1.1016)
    assert mods[0]["tp"] == pytest.approx(1.1066)


def test_runner_time_exit_and_friday_flatten(
    tmp_path: Path, params: StrategyParams, profile: FtmoProfile
) -> None:
    rig = Rig(tmp_path, params, profile)
    rig.guard.tick()
    rig.open_position()
    rig.clock.set(utc(DAY, 11, 45))
    rig.runner().step()
    assert rig.fake.positions == []
    friday = date(2026, 3, 6)
    rig.clock.set(utc(friday, 21, 0))
    rig.open_position("XAUUSD", 2300.0, 2290.0, 2320.0)
    rig.runner().step()
    assert rig.fake.positions == []
    assert any("(friday)" in m for m in rig.notes.sent)


def test_runner_tracks_consecutive_losses(
    tmp_path: Path, params: StrategyParams, profile: FtmoProfile
) -> None:
    rig = Rig(tmp_path, params, profile)
    rig.clock.set(utc(DAY, 9, 30))
    rig.guard.tick()
    rig.open_position()
    run = rig.runner()
    run.step()
    rig.client.close_position(rig.client.positions()[0])  # fake books a -1.0 deal
    run.step()
    assert rig.store.load_runner().consecutive_losses == 1


def test_mt5_client_retries_then_raises(profile: FtmoProfile) -> None:
    fake = FakeMT5(fail_account=True)
    sleeps: list[float] = []
    c = MT5Client(fake, retries=2, retry_delay_s=0.1, sleep=sleeps.append)
    with pytest.raises(MT5Error):
        c.account()
    assert sleeps == [0.1, 0.2]


def test_mt5_client_server_time_conversion() -> None:
    fake = FakeMT5()
    c = MT5Client(fake, server_tz="Europe/Athens")
    # Server wall-clock 12:00 EET (UTC+2) on 2026-01-15 encoded as if UTC.
    t = datetime(2026, 1, 15, 12, tzinfo=UTC).timestamp()
    assert c._server_to_utc(t) == datetime(2026, 1, 15, 10, tzinfo=UTC)
