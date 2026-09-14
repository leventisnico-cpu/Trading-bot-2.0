"""Unit tests for mini_prop_os.risk.guardrails — pre-trade checks and the
daily-loss kill switch. Pure logic; no broker or network required."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from mini_prop_os.core.types import (Action, IntentSource, OrderIntent,
                                     OrderType)
from mini_prop_os.risk.guardrails import (PortfolioSnapshot, RiskGuardrails)


@dataclass(frozen=True)
class Limits:
    max_position_shares: int = 100
    max_position_notional: float = 60_000.0
    max_order_quantity: int = 50
    max_gross_notional: float = 120_000.0
    max_daily_loss: float = 1_000.0
    max_daily_loss_pct: float = 0.02
    allow_short: bool = False
    kill_switch_flattens: bool = True


def guard(**kw) -> RiskGuardrails:
    return RiskGuardrails(Limits(**kw))


def intent(action=Action.BUY, symbol="SPY", qty=10, order_type=OrderType.MARKET,
           limit_price=None, source=IntentSource.STRATEGY) -> OrderIntent:
    return OrderIntent(action=action, symbol=symbol, quantity=qty,
                       order_type=order_type, limit_price=limit_price,
                       source=source, strategy_id="test")


def snap(positions=None, prices=None) -> PortfolioSnapshot:
    return PortfolioSnapshot(positions=positions or {},
                             last_prices=prices if prices is not None
                             else {"SPY": 500.0})


# ------------------------------------------------------------ happy path

def test_valid_market_buy_approved():
    d = guard().validate(intent(), snap())
    assert d.approved, d.reason


def test_valid_limit_order_approved():
    d = guard().validate(
        intent(order_type=OrderType.LIMIT, limit_price=499.5), snap())
    assert d.approved, d.reason


# ------------------------------------------------------ parameter checks

@pytest.mark.parametrize("qty", [0, -5])
def test_non_positive_quantity_rejected(qty):
    d = guard().validate(intent(qty=qty), snap())
    assert not d.approved and "positive" in d.reason


def test_non_integer_quantity_rejected():
    bad = intent()
    object.__setattr__(bad, "quantity", 2.5)
    d = guard().validate(bad, snap())
    assert not d.approved and "integer" in d.reason


def test_empty_symbol_rejected():
    d = guard().validate(intent(symbol="  "), snap())
    assert not d.approved and "symbol" in d.reason


@pytest.mark.parametrize("lp", [None, 0.0, -1.0, float("nan"), float("inf")])
def test_limit_order_requires_positive_finite_price(lp):
    d = guard().validate(
        intent(order_type=OrderType.LIMIT, limit_price=lp), snap())
    assert not d.approved and "limit price" in d.reason


@pytest.mark.parametrize("price", [None, 0.0, -3.0, float("nan")])
def test_market_order_with_no_valid_reference_price_rejected(price):
    prices = {} if price is None else {"SPY": price}
    d = guard().validate(intent(), snap(prices=prices))
    assert not d.approved and "reference price" in d.reason


# ------------------------------------------------------------- size caps

def test_order_quantity_cap():
    d = guard().validate(intent(qty=51), snap())
    assert not d.approved and "max_order_quantity" in d.reason
    assert guard().validate(intent(qty=50), snap()).approved


def test_position_share_cap_counts_existing_position():
    g = guard()
    # 60 existing + 50 order = 110 > 100 cap.
    d = g.validate(intent(qty=50), snap(positions={"SPY": 60}))
    assert not d.approved and "max_position_shares" in d.reason
    # 50 + 50 = 100 exactly at cap is allowed.
    assert g.validate(intent(qty=50), snap(positions={"SPY": 50})).approved


def test_position_notional_cap():
    # 50sh + 50sh @ 700 = 70,000 > 60,000.
    d = guard().validate(
        intent(qty=50), snap(positions={"SPY": 50}, prices={"SPY": 700.0}))
    assert not d.approved and "max_position_notional" in d.reason


def test_gross_notional_cap_across_symbols():
    g = guard(max_gross_notional=30_000.0)
    positions = {"QQQ": 50}
    prices = {"QQQ": 400.0, "SPY": 500.0}  # existing gross = 20,000
    # +25 SPY @ 500 = 12,500 -> 32,500 > 30,000.
    d = g.validate(intent(qty=25),
                   PortfolioSnapshot(positions=positions, last_prices=prices))
    assert not d.approved and "max_gross_notional" in d.reason
    # +20 SPY = 10,000 -> 30,000 exactly: allowed.
    d = g.validate(intent(qty=20),
                   PortfolioSnapshot(positions=positions, last_prices=prices))
    assert d.approved, d.reason


def test_unpriceable_existing_position_blocks_new_exposure():
    d = guard().validate(
        intent(), PortfolioSnapshot(positions={"QQQ": 10},
                                    last_prices={"SPY": 500.0}))
    assert not d.approved and "cannot price" in d.reason


# ------------------------------------------------------------- shorting

def test_sell_below_flat_rejected_when_shorts_disallowed():
    d = guard().validate(intent(action=Action.SELL, qty=10),
                         snap(positions={"SPY": 5}))
    assert not d.approved and "short" in d.reason


def test_sell_to_flat_allowed():
    d = guard().validate(intent(action=Action.SELL, qty=10),
                         snap(positions={"SPY": 10}))
    assert d.approved, d.reason


def test_short_allowed_when_configured():
    d = guard(allow_short=True).validate(
        intent(action=Action.SELL, qty=10), snap())
    assert d.approved, d.reason


# ----------------------------------------------- daily loss kill switch

def test_daily_loss_currency_limit_trips_kill_switch():
    g = guard()
    g.mark_start_of_day(100_000.0)
    assert g.update_equity(99_100.0) is False          # -900 < 1000 limit...
    assert not g.kill_switch_active
    # pct limit: 2% of 100k = 2000; currency limit 1000 is tighter.
    assert g.update_equity(99_000.0) is True           # -1000 hits limit
    assert g.kill_switch_active
    assert "daily loss" in g.kill_reason


def test_daily_loss_pct_limit_is_tighter_for_small_accounts():
    g = guard()  # pct limit: 2% of 20k = 400 < 1000
    g.mark_start_of_day(20_000.0)
    assert g.update_equity(19_650.0) is False
    assert g.update_equity(19_600.0) is True
    assert g.kill_switch_active


def test_kill_switch_blocks_strategy_orders_but_not_flatten():
    g = guard()
    g.trip("test trip")
    assert not g.validate(intent(), snap()).approved
    flatten = g.flatten_intents({"SPY": 30})
    assert len(flatten) == 1
    f = flatten[0]
    assert f.action is Action.SELL and f.quantity == 30
    assert f.source is IntentSource.RISK_FLATTEN
    d = g.validate(f, snap(positions={"SPY": 30}))
    assert d.approved, d.reason


def test_flatten_intents_cover_both_directions_and_skip_flat():
    g = guard()
    intents = g.flatten_intents({"SPY": 10, "QQQ": -4, "IWM": 0})
    by_symbol = {i.symbol: i for i in intents}
    assert set(by_symbol) == {"SPY", "QQQ"}
    assert by_symbol["SPY"].action is Action.SELL
    assert by_symbol["QQQ"].action is Action.BUY
    assert by_symbol["QQQ"].quantity == 4


def test_kill_switch_reset_requires_operator():
    g = guard()
    g.trip("x")
    with pytest.raises(ValueError):
        g.reset("")
    g.reset("human@desk")
    assert not g.kill_switch_active
    assert g.validate(intent(), snap()).approved


def test_equity_updates_before_start_of_day_do_not_trip():
    g = guard()
    assert g.update_equity(1.0) is False
    assert not g.kill_switch_active


def test_non_finite_equity_ignored():
    g = guard()
    g.mark_start_of_day(50_000.0)
    assert g.update_equity(float("nan")) is False
    assert not g.kill_switch_active
    assert g.daily_pnl == 0.0  # last good mark retained


def test_mark_start_of_day_rejects_bad_equity():
    g = guard()
    for bad in (0.0, -5.0, float("nan")):
        with pytest.raises(ValueError):
            g.mark_start_of_day(bad)
