"""connection.market_data_type: config field and the reqMarketDataType call."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

from mini_prop_os.core.config import (MARKET_DATA_TYPE_CODES, ConfigError,
                                      ConnectionConfig, load_config)
from mini_prop_os.core.marketdata import request_market_data_type

REPO = Path(__file__).resolve().parents[1]


class StubIb:
    def __init__(self) -> None:
        self.codes: list[int] = []

    def reqMarketDataType(self, code: int) -> None:
        self.codes.append(code)


def test_default_is_realtime_and_codes_match_tws_api():
    assert ConnectionConfig().market_data_type == "realtime"
    assert MARKET_DATA_TYPE_CODES == {"realtime": 1, "frozen": 2, "delayed": 3}


@pytest.mark.parametrize("mode", ["realtime", "delayed", "frozen"])
def test_valid_modes_accepted(mode):
    assert ConnectionConfig(market_data_type=mode).market_data_type == mode


def test_invalid_mode_rejected_at_load(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("connection:\n  market_data_type: fast\n")
    with pytest.raises(ConfigError, match="market_data_type"):
        load_config(p)


def test_request_market_data_type_issues_the_call():
    ib = StubIb()
    assert request_market_data_type(ib, "delayed") == 3
    assert ib.codes == [3]
    with pytest.raises(ValueError):
        request_market_data_type(ib, "bogus")


def test_app_requests_configured_type_before_subscribing_bars(tmp_path):
    """Full post-connect setup against a stub IB: the market data type
    must be requested before the first historical-bar request."""
    ib_insync = pytest.importorskip("ib_insync")
    from mini_prop_os.app import TradingApp

    cfg_path = tmp_path / "c.yaml"
    cfg_path.write_text(
        "connection: {port: 4002, market_data_type: delayed}\n"
        "contract: {symbol: SPY, sec_type: STK, exchange: SMART, "
        "multiplier: 1.0}\n"
        "strategy: {name: ema_crossover, use_rth: true, order_quantity: 10}\n"
        "risk: {max_position_shares: 50, max_order_quantity: 10}\n"
        f"execution: {{execution_log_path: '{tmp_path / 'x.jsonl'}'}}\n"
        f"logging: {{file: '{tmp_path / 'x.log'}'}}\n")
    cfg = load_config(cfg_path)
    app = TradingApp(cfg)

    calls: list[str] = []

    class Row:
        tag, value = "NetLiquidation", "1000000.0"

    class Stub:
        def reqMarketDataType(self, code: int) -> None:
            calls.append(f"mdt:{code}")

        async def qualifyContractsAsync(self, *contracts):
            calls.append("qualify")
            return list(contracts)

        async def accountSummaryAsync(self, account=""):
            return [Row()]

        async def reqPositionsAsync(self):
            return []

        async def reqAllOpenOrdersAsync(self):
            return []

        async def reqHistoricalDataAsync(self, *a, **kw):
            calls.append("bars")
            return ib_insync.BarDataList()

    app.conn._ib = Stub()  # type: ignore[assignment]
    asyncio.run(app._on_connected())
    assert calls[:2] == ["mdt:3", "qualify"]
    assert "bars" in calls
    assert app._trading_enabled.is_set()


def test_tfsa_paper_config_runs_on_delayed_data():
    cfg = load_config(REPO / "deploy" / "config.tfsa-paper.yaml")
    assert cfg.connection.market_data_type == "delayed"
