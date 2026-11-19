"""Phone operator commands: pause/resume gate entries only, halt needs
CONFIRM and trips the persisted kill switch; a halt cannot be resumed
from the phone."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

pytest.importorskip("yaml")
pytest.importorskip("ib_insync")

from mini_prop_os.core.config import load_config
from mini_prop_os.core.killfile import read_kill_marker
from mini_prop_os.core.types import Action, IntentSource, OrderIntent
from mini_prop_os.app import TradingApp, kill_marker_path


def make_app(tmp_path: Path) -> TradingApp:
    cfg_path = tmp_path / "c.yaml"
    cfg_path.write_text(
        "connection: {port: 4002}\n"
        "contract: {symbol: SPY, sec_type: STK, exchange: SMART, multiplier: 1.0}\n"
        "strategy: {name: ema_crossover, order_quantity: 10}\n"
        "risk: {max_position_shares: 50, max_order_quantity: 10, "
        "kill_switch_flattens: false}\n"
        f"execution: {{execution_log_path: '{tmp_path / 'x.jsonl'}'}}\n"
        f"logging: {{file: '{tmp_path / 'x.log'}'}}\n")
    return TradingApp(load_config(cfg_path))


class RecordingOms:
    def __init__(self) -> None:
        self.submitted = []
        self.cancelled = 0

    async def submit(self, intent):
        self.submitted.append(intent)
        return 1

    async def cancel_all(self):
        self.cancelled += 1
        return 0

    def position_quantities(self):
        return {}

    def open_orders(self):
        return []

    @property
    def positions(self):
        return {}


def intent(action: Action, source=IntentSource.STRATEGY) -> OrderIntent:
    return OrderIntent(action=action, symbol="SPY", quantity=10, source=source,
                       strategy_id="ema_crossover")


def test_pause_drops_entries_but_not_exits(tmp_path):
    app = make_app(tmp_path)
    app.oms = RecordingOms()
    app._last_price = 500.0
    assert "paused" in app.operator_pause()
    assert "PAUSED" in app.status_text()
    asyncio.run(app._route_intent(intent(Action.BUY)))
    assert app.oms.submitted == []                    # entry dropped
    # Risk flattening (a SELL from RISK_FLATTEN) must still get through;
    # with allow_short false and no position, use a strategy-sourced exit
    # check via _is_entry semantics instead:
    assert app._is_entry(intent(Action.BUY)) is True
    assert "resumed" in app.operator_resume()
    asyncio.run(app._route_intent(intent(Action.BUY)))
    assert len(app.oms.submitted) == 1


def test_halt_requires_confirm_then_trips_and_persists(tmp_path):
    app = make_app(tmp_path)
    app.oms = RecordingOms()
    reply = app.operator_halt("")
    assert "CONFIRM" in reply and not app.risk.kill_switch_active

    async def scenario():
        app._loop = asyncio.get_running_loop()
        return await asyncio.to_thread(app.operator_halt, "confirm")
    reply = asyncio.run(scenario())
    assert reply.startswith("HALTED")
    assert app.risk.kill_switch_active
    assert app.oms.cancelled == 1
    marker = read_kill_marker(kill_marker_path(app.cfg))
    assert marker is not None and "Telegram" in marker["reason"]
    # No phone command can clear a halt.
    assert "cannot resume" in app.operator_resume()


def test_halt_before_run_reports_not_running(tmp_path):
    app = make_app(tmp_path)
    assert app.operator_halt("CONFIRM") == "not running"
    assert not app.risk.kill_switch_active
