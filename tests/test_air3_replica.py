"""research/air3_replica.py: the local replica of Astral's AIR3 (41110) and
aligned buy-and-hold (41122) backtests, checked on synthetic daily bars."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

_spec = importlib.util.spec_from_file_location(
    "air3_replica", Path(__file__).resolve().parents[1] / "research" / "air3_replica.py")
replica = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(replica)

CAP, BUY, SELL = 100000.0, 1.0002 * 1.0001, 0.9998 * 0.9999   # 2 bp slip + 1 bp comm


def bars(closes, opens=None) -> pd.DataFrame:
    days = pd.bdate_range("2020-01-01", periods=len(closes)).date
    return pd.DataFrame({"date": days, "open": opens if opens is not None else closes,
                         "close": closes})


def window(df):
    return str(df["date"].iloc[0]), str(df["date"].iloc[-1])


def test_buy_and_hold_fills_at_the_first_eligible_close_after_220_warmup_bars():
    df = bars([100.0] * 230)
    r = replica.run(df, *window(df), "bh")
    assert r["from"] == df["date"][220]
    qty = 0.95 * CAP / 100.0
    assert r["ret"] == pytest.approx((CAP - qty * 100.0 * BUY + qty * 100.0) / CAP - 1)
    assert r["open"] and r["closed"] == 0


def test_air3_signal_fills_at_the_next_open_sized_on_the_signal_close():
    closes = [100.0] * 220 + [100.0 + k for k in range(1, 21)]      # bars 220..239: 101..120
    opens = [c - 0.5 for c in closes]
    df = bars(closes, opens)
    c = df["close"]
    s200, s50 = c.rolling(200).mean(), c.rolling(50).mean()
    sig = next(i for i in range(220, len(c))
               if c[i] > 1.05 * s200[i] and s50[i] > s200[i])
    assert sig > 220                       # not the first eligible bar
    r = replica.run(df, *window(df), "air3")
    qty = 0.95 * CAP / c[sig]              # sized on the signal close
    cash = CAP - qty * opens[sig + 1] * BUY
    assert r["ret"] == pytest.approx((cash + qty * c.iloc[-1]) / CAP - 1)
    assert r["open"] and r["closed"] == 0
    assert r["open_trade"] == pytest.approx(r["ret"])     # equity basis, one trade


def test_air3_entry_true_on_the_first_eligible_bar_fills_at_that_close():
    closes = [100.0 + i for i in range(240)]                # steady climb
    df = bars(closes, [x - 0.5 for x in closes])
    r = replica.run(df, *window(df), "air3")
    qty = 0.95 * CAP / closes[220]
    cash = CAP - qty * closes[220] * BUY
    assert r["ret"] == pytest.approx((cash + qty * closes[-1]) / CAP - 1)
    assert r["from"] == replica.run(df, *window(df), "bh")["from"] == df["date"][220]


def test_air3_sell_fills_at_the_next_open_and_trade_return_is_on_equity():
    up = [100.0 + i for i in range(240)]                    # in from bar 220's close
    down = [up[-1] - 15.0 * k for k in range(1, 15)]        # falls through 0.95 x SMA200
    closes = up + down + [down[-1]] * 3
    opens = [x + 0.25 for x in closes]
    df = bars(closes, opens)
    c = df["close"]
    s200 = c.rolling(200).mean()
    out = next(i for i in range(221, len(c)) if c[i] < 0.95 * s200[i])
    r = replica.run(df, *window(df), "air3")
    qty = 0.95 * CAP / c[220]
    cash = CAP - qty * c[220] * BUY + qty * opens[out + 1] * SELL
    assert r["closed"] == 1 and not r["open"]
    assert r["trades"] == [round(100 * (cash / CAP - 1), 1)]
    assert r["ret"] == pytest.approx(cash / CAP - 1)
    assert r["win"] == 0.0


def test_a_gap_up_at_the_fill_never_overdraws_cash():
    closes = [100.0] * 220 + [100.0 + k for k in range(1, 21)]
    df = bars(closes, list(closes))
    c = df["close"]
    s200, s50 = c.rolling(200).mean(), c.rolling(50).mean()
    sig = next(i for i in range(220, len(c)) if c[i] > 1.05 * s200[i] and s50[i] > s200[i])
    df.loc[sig + 1, "open"] = c[sig] * 1.10                  # +10% gap at the fill
    r = replica.run(df, *window(df), "air3")
    qty = CAP / (df["open"][sig + 1] * BUY)                  # capped at the cash on hand
    assert r["ret"] == pytest.approx(qty * c.iloc[-1] / CAP - 1)


def test_a_window_shorter_than_the_warmup_is_refused():
    df = bars([100.0] * 220)
    with pytest.raises(ValueError):
        replica.run(df, *window(df), "air3")
