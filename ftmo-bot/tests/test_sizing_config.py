"""Sizing arithmetic, config loading and notifier behaviour."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from ftmo_bot.config import (
    FtmoProfile,
    StrategyParams,
    engine_limits,
    ftmo_limits,
    load_profile,
    risk_amount,
)
from ftmo_bot.execution.notify import Notifier
from ftmo_bot.risk import sizing

from .conftest import ROOT


@dataclass(frozen=True)
class Sig:
    side: sizing.Side
    entry: float
    stop: float


def test_config_matches_spec(params: StrategyParams, profile: FtmoProfile) -> None:
    eng, ftmo = engine_limits(profile, params), ftmo_limits(profile, params)
    assert (eng.daily_loss_limit, eng.overall_loss_limit) == pytest.approx((2_500, 6_000))
    assert (ftmo.daily_loss_limit, ftmo.overall_loss_limit) == pytest.approx((5_000, 10_000))
    assert risk_amount(profile, params) == pytest.approx(750)
    assert [p.profit_target_pct for p in profile.phases] == [0.10, 0.05]
    assert params.instruments["NAS100"].range.start.hour == 9
    assert eng.correlated_groups == (frozenset({"EURUSD", "GBPUSD"}),)
    assert len(params.params_hash) == 16


def test_one_step_profile_is_same_schema() -> None:
    p = load_profile(ROOT / "config" / "ftmo_1step.yaml")
    assert p.ftmo_daily_loss_pct == 0.03 and p.overall_mode == "eod_trailing"


def test_size_for_rounds_down_and_respects_min_max(profile: FtmoProfile) -> None:
    eur = profile.contracts["EURUSD"]
    assert sizing.size_for(Sig("long", 1.1015, 1.0990), eur, 750) == pytest.approx(3.0)
    assert sizing.size_for(Sig("short", 1.1000, 1.10237), eur, 750) == pytest.approx(3.16)
    assert sizing.size_for(Sig("long", 1.2, 1.0), eur, 10) == 0.0  # below min lot
    assert sizing.size_for(Sig("long", 1.10001, 1.1), eur, 1e9) == eur.max_lot
    with pytest.raises(ValueError):
        sizing.size_for(Sig("long", 1.1, 1.1), eur, 750)
    with pytest.raises(ValueError):
        sizing.size_for(Sig("long", 1.1, 1.0), eur, 0)


def test_risk_never_exceeds_target_after_rounding(profile: FtmoProfile) -> None:
    for sym, entry, stop in (
        ("XAUUSD", 2300.0, 2291.37),
        ("NAS100", 18000.0, 17931.0),
        ("GBPUSD", 1.27, 1.26713),
    ):
        spec = profile.contracts[sym]
        lots = sizing.size_for(Sig("long", entry, stop), spec, 750)
        assert lots > 0 and abs(entry - stop) * spec.value_per_price_unit(lots) <= 750 + 1e-9
        proj = sizing.projected_loss(Sig("long", entry, stop), spec, 750, spec.typical_spread)
        assert proj > 750


def test_risk_to_stop(profile: FtmoProfile) -> None:
    eur = profile.contracts["EURUSD"]
    r = sizing.risk_to_stop("long", 3.0, 1.1010, 1.0990, eur)
    assert r == pytest.approx(0.0020 * 300_000 + 9 + 0.00002 * 300_000)
    # Stop above the mark for a long (after breakeven, in profit): only exit costs.
    assert sizing.risk_to_stop("short", 3.0, 1.0990, 1.1000, eur) == pytest.approx(
        0.0010 * 300_000 + 9 + 6
    )


def test_notifier_posts_and_swallows_errors(tmp_path: Path) -> None:
    posts: list[tuple[str, bytes]] = []
    n = Notifier("tok", "chat", "https://hc", post=lambda u, b: posts.append((u, b)))
    n.send("hello")
    n.ping()
    assert "bottok/sendMessage" in posts[0][0] and b"hello" in posts[0][1]
    assert posts[1][0] == "https://hc"

    def boom(u: str, b: bytes) -> None:
        raise OSError("down")

    bad = Notifier("tok", "chat", "https://hc", post=boom)
    bad.send("x")  # must not raise
    bad.ping()
    quiet = Notifier()
    quiet.send("y")
    quiet.ping()
    assert quiet.sent == ["y"]
