"""Go/no-go gate: backtest and live use the identical ftmo_rules.py code path.

The backtest engine produces a per-tick equity series that breaches the engine
daily limit. That exact series is replayed through the LIVE guard (mock MT5
reporting each equity value at each timestamp). Both must halt on the same tick
with the same reason, and every consumer must hold the same function objects.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from ftmo_bot.backtest import engine, ftmo_sim, montecarlo
from ftmo_bot.backtest.engine import BacktestEngine
from ftmo_bot.config import FtmoProfile, StrategyParams, engine_limits
from ftmo_bot.execution import order_router
from ftmo_bot.execution.mt5_client import MT5Client
from ftmo_bot.execution.notify import Notifier
from ftmo_bot.execution.state import StateStore
from ftmo_bot.risk import ftmo_rules, guard

from .fake_mt5 import FakeMT5
from .synth import DAY, day_bars, eurusd_market, h4_up, path_ticks, utc


def test_every_consumer_imports_the_same_rules_module() -> None:
    assert engine.ftmo_rules is ftmo_rules
    assert guard.ftmo_rules is ftmo_rules
    assert order_router.ftmo_rules is ftmo_rules
    for fn in (ftmo_sim.should_halt, montecarlo.should_halt):
        assert fn is ftmo_rules.should_halt


def test_backtest_and_live_guard_halt_on_the_same_tick(
    tmp_path: Path, params: StrategyParams, profile: FtmoProfile
) -> None:
    gbp = (
        day_bars("GBPUSD", DAY, 1.2710, 1.2690, 1.2715),
        h4_up("GBPUSD", utc(DAY, 9), 1.22, 0.001),
        path_ticks(utc(DAY, 9, 15), [(0, 1.2715), (60, 1.2705)], 0.0001),
    )
    path = [(0, 1.1015), (5, 1.1015), (5.2, 1.0700), (60, 1.0700)]
    md = eurusd_market(profile, path, extra={"GBPUSD": gbp})
    res = BacktestEngine(params, profile, md).run(DAY, DAY)
    day = res.days.iloc[0]
    assert bool(day.halted)

    fake = FakeMT5(equity=day.start_equity)
    now = {"t": utc(DAY, 0) + timedelta(seconds=1)}
    fake.now = now["t"]
    store = StateStore(tmp_path / "state")
    g = guard.Guard(
        MT5Client(fake, sleep=lambda s: None),
        store,
        engine_limits(profile, params),
        params,
        profile,
        Notifier(),
        clock=lambda: now["t"],
    )
    g.tick()  # 00:00 baseline = backtest day start equity

    live_halt_at = None
    for ts, eq in zip(res.equity.ts_utc, res.equity.equity, strict=True):
        now["t"] = ts.to_pydatetime()
        fake.now = now["t"]
        fake.equity = float(eq)
        if g.tick().halted is not None:
            live_halt_at = now["t"]
            break
    assert live_halt_at is not None
    halt = store.read_halt()
    assert halt is not None
    # The live guard's reason string is the backtest's, character for character.
    assert halt.reason == day.halt_reason
    # And it fired on the backtest's breach tick.
    breach = res.equity[res.equity.equity <= day.start_equity - 2_500].ts_utc.iloc[0]
    assert live_halt_at == breach.to_pydatetime()
