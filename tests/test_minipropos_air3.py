"""AIR3 trend rule: 5% bands around the 200-day average, one lot, no
pyramiding, level signals, plus its config fields and the SMH paper
deploy config."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

import pytest

from mini_prop_os.core.config import ConfigError, StrategyConfig, load_config
from mini_prop_os.core.types import Action, Bar, OrderIntent
from mini_prop_os.strategy import registry
from mini_prop_os.strategy.air3_trend import Air3TrendStrategy

REPO = Path(__file__).resolve().parents[1]
AIR3_CFG = REPO / "deploy" / "config.tfsa-paper-air3.yaml"


def bars(closes: List[float], symbol: str = "SMH") -> List[Bar]:
    t0 = datetime(2020, 1, 1, tzinfo=timezone.utc)
    return [Bar(symbol, t0 + timedelta(days=i), c, c + 0.5, c - 0.5, c, 1e6)
            for i, c in enumerate(closes)]


def run(s: Air3TrendStrategy, seq: List[Bar]) -> List[OrderIntent]:
    out: List[OrderIntent] = []
    for b in seq:
        for it in s.on_bar(b):
            out.append(it)
            s.on_own_fill(it.signed_quantity, b.close)
    return out


def small(fast: int = 5, slow: int = 20, lot: int = 1) -> Air3TrendStrategy:
    """Short periods so tests stay readable; the rule is identical."""
    return Air3TrendStrategy("SMH", order_quantity=lot, fast_period=fast,
                             slow_period=slow)


def test_nothing_before_the_slow_average_exists():
    s = small()
    assert run(s, bars([100.0] * 19)) == []
    assert s.regime == "warmup" and s.sma_slow is None
    assert run(s, bars([100.0])) == []       # 20th bar: ready, but flat
    assert s.is_ready and s.regime == "out"
    assert s.sma_slow == pytest.approx(100.0)


def test_buys_once_above_the_entry_band_with_fast_over_slow():
    s = small()
    run(s, bars([100.0] * 20))               # SMA20 = 100, entry = 105
    assert run(s, bars([104.0])) == []       # inside the band: nothing
    intents = run(s, bars([106.0]))          # 106 > 105 and SMA5 > SMA20
    assert [i.action for i in intents] == [Action.BUY]
    assert intents[0].quantity == 1 and intents[0].symbol == "SMH"
    assert s.position == 1 and s.regime == "in"
    # Level signal: the condition stays true, but no second buy.
    assert run(s, bars([110.0, 115.0, 120.0])) == []
    assert s.position == 1


def test_fast_below_slow_blocks_entry():
    s = small()
    # Falling for 20 bars: SMA5 sits below SMA20 even though the last
    # close is 5% above the 20-bar average.
    seq = [200.0 - 5 * i for i in range(20)]  # 200 .. 105, avg 152.5
    run(s, bars(seq))
    assert s.sma_fast < s.sma_slow
    # 161 > 1.05 * SMA20 but SMA5 (now ~ 118) < SMA20: still no entry.
    assert run(s, bars([161.0])) == []


def test_sells_only_below_the_exit_band_and_not_in_between():
    s = small()
    run(s, bars([100.0] * 20))
    run(s, bars([106.0]))                    # in at 106
    # Dips to 98 (below SMA but above 0.95 x SMA ~ 95.3): hold.
    assert run(s, bars([98.0])) == []
    assert s.position == 1
    exit_level = s.exit_level
    intents = run(s, bars([exit_level - 1.0]))
    assert [i.action for i in intents] == [Action.SELL]
    assert intents[0].quantity == 1 and s.position == 0
    assert s.regime == "out"


def test_no_immediate_reentry_after_exit():
    s = small()
    run(s, bars([100.0] * 20 + [106.0]))
    run(s, bars([90.0]))                     # exit
    assert s.position == 0
    # Back to 100: above the exit band but below the entry band -> flat.
    assert run(s, bars([100.0])) == []
    assert s.position == 0


def test_sell_closes_the_whole_position():
    s = small(lot=3)
    run(s, bars([100.0] * 20 + [106.0]))
    assert s.position == 3
    intents = run(s, bars([80.0]))
    assert intents[0].action is Action.SELL and intents[0].quantity == 3


def test_parameter_validation():
    with pytest.raises(ValueError):
        Air3TrendStrategy("SMH", order_quantity=0)
    with pytest.raises(ValueError):
        Air3TrendStrategy("SMH", fast_period=200, slow_period=50)
    with pytest.raises(ValueError):
        Air3TrendStrategy("SMH", entry_band=1.5)
    with pytest.raises(ValueError):
        Air3TrendStrategy("")


def test_defaults_match_the_astral_rule():
    s = Air3TrendStrategy("SMH")
    assert (s.fast_period, s.slow_period) == (50, 200)
    assert s.entry_band == 0.05 and s.exit_band == 0.05
    assert s.warmup_bars == 200 and s.order_quantity == 1


def test_config_fields_and_validation():
    cfg = StrategyConfig(name="air3_trend", bar_size="1 day",
                         history_duration="2 Y", order_quantity=1,
                         use_rth=True)
    assert (cfg.trend_fast_period, cfg.trend_slow_period) == (50, 200)
    with pytest.raises(ConfigError):
        StrategyConfig(name="air3_trend", trend_fast_period=300)
    with pytest.raises(ConfigError):
        StrategyConfig(name="air3_trend", trend_entry_band=1.0)


def test_registered_and_not_marked_deployable():
    """It faces the gate like every other strategy and fails it on SMH,
    so main.py refuses a live port with it."""
    assert "air3_trend" in registry.strategy_names()
    s = registry.get_spec("air3_trend").factory("SMH", 1, 1.0)
    assert isinstance(s, Air3TrendStrategy) and s.order_quantity == 1
    assert registry.is_deployable("air3_trend") is False
    assert registry.refuse_live_reason("air3_trend", 4001) is not None
    assert registry.refuse_live_reason("air3_trend", 4002) is None


def test_smh_paper_config_matches_the_astral_deployment():
    cfg = load_config(AIR3_CFG)
    assert cfg.connection.port == 4002
    assert cfg.contract.symbol == "SMH" and cfg.contract.sec_type == "STK"
    assert cfg.strategy.name == "air3_trend"
    assert cfg.strategy.bar_size == "1 day"
    assert cfg.strategy.use_rth is True
    assert cfg.strategy.order_quantity == 1
    assert cfg.risk.max_position_shares == 1
    assert cfg.risk.max_order_quantity == 1
    # One ~$630 share with headroom; never more than the account could buy.
    assert 700 <= cfg.risk.max_position_notional <= 1500
    # The rule has no stop: the daily-loss breaker must not fire on a
    # normal 5% SMH day on a one-share position.
    assert cfg.risk.max_daily_loss >= 0.10 * 870
    assert cfg.risk.allow_short is False


def test_app_factory_builds_air3_from_config():
    pytest.importorskip("ib_insync")   # app.py wires ib_insync; CI lacks it
    from mini_prop_os.app import build_strategy
    cfg = load_config(AIR3_CFG)
    s = build_strategy(cfg)
    assert isinstance(s, Air3TrendStrategy)
    assert s.symbol == "SMH" and s.slow_period == 200
