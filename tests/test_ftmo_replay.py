"""The replay audit (``scripts/ftmo_replay.py``) on a small synthetic market:
the real bot through entries, the 5 steps, the cap and the keep-alive, with
every deal checked against the script's independent oracle."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ftmo_replay  # noqa: E402
from ftmo_bot import runner as runner_mod, scale_out  # noqa: E402

HISTORY = 210
# (dip sessions, then a rally if positive or a slide if negative)
CYCLES = ((3, 9), (3, -8), (3, 12), (4, 10), (3, -9), (3, 14))


def write_market(folder: Path) -> None:
    """Four indices: a steady rise, then sharp dips (RSI(2) under 10, over the
    200-day average) followed by a rally (the targets) or a slide (the stop)."""
    rets = [0.0015] * 225
    for dip, after in CYCLES:
        rets += [-0.012] * dip + [0.011 if after > 0 else -0.013] * abs(after) + [0.001] * 6
    rets, shifts = np.array(rets), (0, 1, 2, 4)
    days = pd.bdate_range("2011-03-23", periods=len(rets) + max(shifts))
    for name, shift, scale in zip(("qqq", "spy", "dia", "iwm"), shifts, (1.0, 0.8, 0.7, 1.2)):
        r = np.concatenate([np.full(shift, 0.0015), rets * scale,
                            np.full(max(shifts) - shift, 0.001)])
        c = 100 * np.cumprod(1 + r)
        o = np.concatenate([[100.0], c[:-1]])
        pd.DataFrame({"timestamp": [d.strftime("%Y-%m-%dT05:00:00+0000") for d in days],
                      "open": o, "high": np.maximum(o, c) * 1.002,
                      "low": np.minimum(o, c) * 0.998, "close": c}
                     ).to_csv(folder / f"{name}_long.csv", index=False)


def replay(tmp_path, order="low_first", sessions=None):
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    write_market(data)
    dates, inst = ftmo_replay.load_study(data)
    rp = ftmo_replay.Replay(dates, inst, "funded", order, tmp_path, HISTORY)
    rp.run(HISTORY, len(dates) if sessions is None else HISTORY + sessions)
    return rp


def test_the_bot_matches_the_oracle_through_wins_losses_and_the_cap(tmp_path):
    before = runner_mod.BAR_COUNT
    rp = replay(tmp_path)
    assert rp.problems == []
    assert runner_mod.BAR_COUNT == before                  # the run put it back
    closed = [t for t in rp.trades if t["ended_by"] == "stop"]
    assert len(closed) >= 12 and rp.count["entries"] == len(rp.trades)
    assert sum(t["parts"] for t in rp.trades) >= 8         # part closes happened
    assert sum(t["moves"] for t in rp.trades) >= 40        # and stop moves
    assert any(t["trail"] for t in closed) and any(not t["tp1"] for t in closed)
    assert rp.count["refused"] >= 1                        # the cap ran out of room
    assert rp.count["keepalives"] >= 2 and rp.count["plans"] == rp.count["sessions"]


def test_the_other_intraday_order_also_matches(tmp_path):
    rp = replay(tmp_path, order="high_first", sessions=60)
    assert rp.problems == [] and sum(t["parts"] for t in rp.trades) >= 2


def test_a_bot_that_sells_the_wrong_share_is_caught(tmp_path, monkeypatch):
    monkeypatch.setitem(scale_out.CLOSED, 1, 0.4)          # 40% at +1R, not half
    rp = replay(tmp_path, sessions=40)
    assert rp.problems and any("5 steps differ" in p for p in rp.problems)


def test_a_bot_that_trails_too_tight_is_caught(tmp_path, monkeypatch):
    monkeypatch.setattr(scale_out, "TRAIL_R", 0.5)
    rp = replay(tmp_path, sessions=40)
    assert rp.problems and any("5 steps differ" in p for p in rp.problems)


def test_oracle_on_a_hand_built_trade():
    """Entry 100, stop 90 (R = 10), 1 lot: +1R, then +1.5R, a close at 130
    (the stop trails to 120), then the stop."""
    t0 = ftmo_replay.bar_start(pd.Timestamp("2026-01-05").date(), 1)
    bar = lambda k, o, c, last=False: (t0 + k * ftmo_replay.BAR, o, max(o, c), min(o, c),   # noqa: E731
                                       c, last)
    bars = [bar(0, 100, 105), bar(1, 105, 110), bar(2, 110, 115), bar(3, 115, 130, True),
            bar(4, 130, 125), bar(5, 125, 119)]
    got = ftmo_replay.five_steps(bars, 100.0, 90.0, 1.0)
    kinds = [(k, round(v, 2), px) for k, _, v, px in got]
    assert kinds == [("sell", 0.5, 110), ("sl", 0.5, 100.0),       # step 3
                     ("sell", 0.25, 115), ("sl", 0.25, 110.0),     # step 4
                     ("sl", 0.25, 120.0),                          # step 5: 130 - 1R
                     ("sell", 0.25, 120.0)]                        # stopped at the trail


@pytest.mark.parametrize("vol0,stage,keep", [(18.75, 1, 9.37), (18.75, 2, 4.69),
                                             (0.01, 1, 0.01), (0.02, 2, 0.01), (0.03, 1, 0.01)])
def test_oracle_lot_rounding(vol0, stage, keep):
    assert ftmo_replay.keep_after(vol0, stage) == pytest.approx(keep)
