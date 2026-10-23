"""Phase 4: engine fills/costs, FTMO sim, Monte Carlo, report, ledger."""

from __future__ import annotations

import dataclasses
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ftmo_bot.backtest import ftmo_sim, ledger, montecarlo, report
from ftmo_bot.backtest.engine import BacktestEngine, floor_spread
from ftmo_bot.config import FtmoProfile, StrategyParams, engine_limits, ftmo_limits
from ftmo_bot.risk import ftmo_rules

from .synth import DAY, day_bars, eurusd_market, h4_up, path_ticks, utc

ENTRY_BID = 1.1015
SPREAD = 0.0001
SLIP = 0.00002
FILL = ENTRY_BID + SPREAD + SLIP  # 1.10162
LOTS = 3.0  # 750 / (0.0025 * 100000)
COMM = 3.0 * LOTS * 2


def run(params: StrategyParams, profile: FtmoProfile, path, **kw):  # type: ignore[no-untyped-def]
    eng = BacktestEngine(params, profile, eurusd_market(profile, path, **kw))
    return eng.run(DAY, DAY)


def only_trade(res):  # type: ignore[no-untyped-def]
    assert len(res.trades) == 1, res.rejections
    return res.trades.iloc[0]


def test_floor_spread_uses_worse_of_tick_and_typical() -> None:
    bid, ask = floor_spread(np.array([1.0, 1.0]), np.array([1.00001, 1.0005]), 0.0002)
    assert ask[0] - bid[0] == pytest.approx(0.0002)
    assert (bid[0] + ask[0]) / 2 == pytest.approx(1.000005)
    assert ask[1] - bid[1] == pytest.approx(0.0005)


def test_target_fills_at_touch(params: StrategyParams, profile: FtmoProfile) -> None:
    t = only_trade(run(params, profile, [(0, ENTRY_BID), (30, 1.1070)]))
    assert t.exit_reason == "target"
    assert t.entry_price == pytest.approx(FILL)
    assert t.lots == pytest.approx(LOTS)
    assert t.exit_price == pytest.approx(ENTRY_BID + 2 * 0.0025)
    assert t.pnl_usd == pytest.approx((1.1065 - FILL) * LOTS * 100_000 - COMM)
    assert t.r_multiple == pytest.approx(t.pnl_usd / 750)
    assert t.session_id == "EURUSD:2026-03-04" and t.mfe >= t.pnl_usd - 1e-9


def test_stop_fills_first_tick_through_with_slippage(
    params: StrategyParams, profile: FtmoProfile
) -> None:
    res = run(params, profile, [(0, ENTRY_BID), (20, 1.0980)])
    t = only_trade(res)
    assert t.exit_reason == "stop"
    assert t.exit_price <= 1.0990 - SLIP + 1e-12
    assert t.exit_price >= 1.0990 - SLIP - 0.00002  # first tick through, not the bottom
    assert t.pnl_usd == pytest.approx((t.exit_price - FILL) * LOTS * 100_000 - COMM)
    assert t.mae <= t.pnl_usd
    # Daily summary carries the intraday low.
    d = res.days.iloc[0]
    assert d.min_equity <= d.end_equity and d.trades == 1


def test_breakeven_once_then_exit_at_entry(params: StrategyParams, profile: FtmoProfile) -> None:
    one_r = FILL + (FILL - 1.0990)
    t = only_trade(run(params, profile, [(0, ENTRY_BID), (20, one_r + 0.0001), (40, 1.0995)]))
    assert t.exit_reason == "breakeven"
    assert t.stop == pytest.approx(FILL)
    assert t.pnl_usd == pytest.approx(-COMM - (FILL - t.exit_price) * LOTS * 100_000)
    assert t.pnl_usd < 0 and t.pnl_usd > -100


def test_time_exit_15_minutes_before_session_end(
    params: StrategyParams, profile: FtmoProfile
) -> None:
    t = only_trade(run(params, profile, [(0, ENTRY_BID), (200, 1.1020)]))
    assert t.exit_reason == "time"
    assert t.exit_ts == utc(DAY, 11, 45)
    assert t.exit_ts.tzinfo is not None


def test_engine_halt_flattens_everything_and_blocks_the_day(
    params: StrategyParams, profile: FtmoProfile
) -> None:
    """EURUSD gaps far through its stop; GBPUSD (same slot, same direction) is
    flattened by the guard logic and nothing else trades that day."""
    gbp_b15 = day_bars("GBPUSD", DAY, 1.2710, 1.2690, 1.2715, breakout_at=(9, 0))
    gbp_b4 = h4_up("GBPUSD", utc(DAY, 9), 1.22, 0.0010)
    gbp_ticks = path_ticks(utc(DAY, 9, 15), [(0, 1.2715), (60, 1.2705)], SPREAD)
    path = [(0, ENTRY_BID), (5, ENTRY_BID), (5.2, 1.0700), (60, 1.0700)]
    md = eurusd_market(profile, path, extra={"GBPUSD": (gbp_b15, gbp_b4, gbp_ticks)})
    res = BacktestEngine(params, profile, md).run(DAY, DAY)
    reasons = dict(zip(res.trades.symbol, res.trades.exit_reason, strict=True))
    assert reasons == {"EURUSD": "stop", "GBPUSD": "guard_halt"}
    d = res.days.iloc[0]
    # An 8% single-tick gap crosses both thresholds; the day-local view (overall
    # measured from the day baseline, see engine docstring) reports it as overall.
    assert bool(d.halted) and "loss" in d.halt_reason
    assert d.start_equity - d.min_equity >= 2_500


def test_pre_trade_check_rejects_and_logs(params: StrategyParams, profile: FtmoProfile) -> None:
    tight = dataclasses.replace(profile, engine_daily_loss_pct=0.007)  # 700 < 750 risk
    res = run(params, tight, [(0, ENTRY_BID), (30, 1.1070)])
    assert res.trades.empty
    assert res.rejections.reason.str.contains("projected daily").any()


def test_excluded_day_blocks_entries(params: StrategyParams, profile: FtmoProfile) -> None:
    md = eurusd_market(profile, [(0, ENTRY_BID), (30, 1.1070)])
    md.excluded = {"EURUSD": {DAY}}
    res = BacktestEngine(params, profile, md).run(DAY, DAY)
    assert res.trades.empty and "integrity" in res.rejections.reason.iloc[0]


def test_fill_beyond_stop_rejected(params: StrategyParams, profile: FtmoProfile) -> None:
    res = run(params, profile, [(0, 1.0985), (30, 1.0985)])
    assert res.trades.empty and "beyond" in res.rejections.reason.iloc[0]


def test_engine_uses_the_rules_module() -> None:
    from ftmo_bot.backtest import engine as eng

    assert eng.ftmo_rules is ftmo_rules


# ------------------------------------------------------------------ ftmo_sim


def test_ftmo_sim_uses_same_functions() -> None:
    assert ftmo_sim.daily_loss is ftmo_rules.daily_loss
    assert ftmo_sim.overall_loss is ftmo_rules.overall_loss
    assert ftmo_sim.should_halt is ftmo_rules.should_halt
    assert ftmo_sim.target_reached is ftmo_rules.target_reached
    assert montecarlo.should_halt is ftmo_rules.should_halt


def _days(rows: list[tuple[float, float, float, bool]]) -> list[ftmo_sim.Day]:
    d0 = date(2024, 1, 1)
    return [
        ftmo_sim.Day(d0 + timedelta(days=i), s, lo, e, tr) for i, (s, lo, e, tr) in enumerate(rows)
    ]


def test_ftmo_sim_pass_requires_min_trading_days(
    params: StrategyParams, profile: FtmoProfile
) -> None:
    eng, ftmo = engine_limits(profile, params), ftmo_limits(profile, params)
    days = _days(
        [
            (100_000, 100_000, 111_000, True),
            (111_000, 111_000, 111_000, True),
            (111_000, 111_000, 111_000, True),
            (111_000, 111_000, 111_000, True),
        ]
    )
    w = ftmo_sim.simulate_window(days, 0, eng, ftmo, 0.10, 4)
    assert w.outcome == "passed" and w.trading_days == 4 and w.days_elapsed == 4


def test_ftmo_sim_rebases_each_window(params: StrategyParams, profile: FtmoProfile) -> None:
    eng, ftmo = engine_limits(profile, params), ftmo_limits(profile, params)
    # Starting at day 1 (equity 90k) is a fresh 100k challenge, not a breach.
    days = _days([(100_000, 90_000, 90_000, True), (90_000, 90_000, 101_000, True)])
    assert ftmo_sim.simulate_window(days, 0, eng, ftmo, 0.10, 1).outcome == "ftmo_failed"
    w = ftmo_sim.simulate_window(days, 1, eng, ftmo, 0.10, 1)
    assert w.outcome == "passed"  # 90k -> 101k is +11k on a fresh 100k account


def test_ftmo_sim_engine_vs_ftmo(params: StrategyParams, profile: FtmoProfile) -> None:
    eng, ftmo = engine_limits(profile, params), ftmo_limits(profile, params)
    # 3% intraday dip: engine daily halt (counted), FTMO fine.
    days = _days([(100_000, 97_000, 99_000, True), (99_000, 99_000, 99_000, False)])
    w = ftmo_sim.simulate_window(days, 0, eng, ftmo, 0.10, 1)
    assert w.engine_daily_halts == 1 and w.outcome == "unresolved"
    # Slow bleed to -6% overall: engine halts the bot before FTMO's -10%.
    bleed = _days(
        [
            (100_000 - 2000 * i, 100_000 - 2000 * (i + 1), 100_000 - 2000 * (i + 1), True)
            for i in range(4)
        ]
    )
    w = ftmo_sim.simulate_window(bleed, 0, eng, ftmo, 0.10, 1)
    assert w.outcome == "engine_halted" and w.days_elapsed == 3
    summary = ftmo_sim.summarize(ftmo_sim.rolling(bleed, eng, ftmo, 0.10, 1))
    # Windows from day 0 and day 1 both reach -6,000; later ones do not.
    assert summary["windows"] == 4 and summary["engine_halted"] == 2
    assert summary["max_daily_dd_pct"]["max"] == pytest.approx(0.02)


def test_ftmo_sim_empty() -> None:
    s = ftmo_sim.summarize([])
    assert s["windows"] == 0 and s["pass_rate"] == 0.0


# ------------------------------------------------------------------ Monte Carlo


def _trades(pnls: list[float], per_day: int = 1) -> pd.DataFrame:
    rows = []
    for i, p in enumerate(pnls):
        d = date(2024, 1, 1) + timedelta(days=i // per_day)
        rows.append(
            {
                "date_cest": d,
                "exit_ts": pd.Timestamp(d, tz="UTC") + pd.Timedelta(minutes=i),
                "pnl_usd": p,
                "mae": min(p, 0.0) - 10,
                "spread_cost_usd": 20.0,
                "pip_value_usd": 30.0,
            }
        )
    return pd.DataFrame(rows)


def test_montecarlo_winners_pass_losers_fail(params: StrategyParams, profile: FtmoProfile) -> None:
    eng, ftmo = engine_limits(profile, params), ftmo_limits(profile, params)
    win = montecarlo.run(_trades([1_500.0] * 20), eng, ftmo, (0.10, 0.05), 4, 540, paths=300)
    assert win["p_phase1"] == 1.0 and win["p_both"] == 1.0
    assert win["expected_cost_to_funded"] == pytest.approx(540)
    lose = montecarlo.run(_trades([-800.0] * 20), eng, ftmo, (0.10, 0.05), 4, 540, paths=300)
    assert lose["p_both"] == 0.0 and lose["expected_cost_to_funded"] is None
    assert lose["outcomes"].get("phase1:engine_overall", 0) == 300


def test_montecarlo_guard_caps_daily_loss(params: StrategyParams, profile: FtmoProfile) -> None:
    eng, ftmo = engine_limits(profile, params), ftmo_limits(profile, params)
    # Days of 4 x -800 would breach 2.5% intraday; the guard caps each day.
    res = montecarlo.run(
        _trades([-800.0] * 40, per_day=4), eng, ftmo, (0.10, 0.05), 4, 540, paths=200
    )
    assert res["p_ftmo_daily_breach"] == 0.0
    assert montecarlo.run(_trades([]), eng, ftmo, (0.1,), 4, 540)["paths"] == 0


def test_montecarlo_deterministic_seed(params: StrategyParams, profile: FtmoProfile) -> None:
    eng, ftmo = engine_limits(profile, params), ftmo_limits(profile, params)
    t = _trades([1_500.0, -800.0, 700.0, -760.0, 1_500.0] * 10)
    a = montecarlo.run(t, eng, ftmo, (0.10, 0.05), 4, 540, paths=200, seed=1)
    b = montecarlo.run(t, eng, ftmo, (0.10, 0.05), 4, 540, paths=200, seed=1)
    assert a == b


# ------------------------------------------------------------------ ledger


def test_ledger_enforces_oos_and_holdout_discipline(tmp_path: Path) -> None:
    p = tmp_path / "ledger.jsonl"
    with pytest.raises(ledger.LedgerRefusal):
        ledger.check(p, "oos", "h1")
    ledger.check(p, "insample", "h1")
    ledger.record(p, "insample", "h1")
    with pytest.raises(ledger.LedgerRefusal):
        ledger.check(p, "holdout", "h1")
    ledger.check(p, "oos", "h1")
    ledger.record(p, "oos", "h1")
    with pytest.raises(ledger.LedgerRefusal, match="already run once"):
        ledger.check(p, "oos", "h1")
    # Changing params resets the OOS clock: in-sample must run again first.
    with pytest.raises(ledger.LedgerRefusal, match="no in-sample"):
        ledger.check(p, "oos", "h2")
    ledger.check(p, "holdout", "h1")
    ledger.record(p, "holdout", "h1")
    with pytest.raises(ledger.LedgerRefusal, match="touched once"):
        ledger.check(p, "holdout", "h1")
    with pytest.raises(ValueError):
        ledger.check(p, "train", "h1")


# ------------------------------------------------------------------ report


def _summary(trades: int, exp: float, pr: float, dd: float, unresolved: int = 0) -> dict:  # type: ignore[type-arg]
    return {
        "trades": trades,
        "expectancy_r": exp,
        "params_hash": "h",
        "start": "2024-01-01",
        "end": "2025-12-31",
        "win_rate": 0.5,
        "profit_factor": 1.5,
        "total_pnl": 1.0,
        "engine_halt_days": 0,
        "news_events_loaded": 10,
        "ftmo_phase1": {
            "pass_rate": pr,
            "unresolved": unresolved,
            "windows": 100,
            "passed": 1,
            "ftmo_failed": 0,
            "engine_halted": 0,
            "median_days_to_pass": 30,
            "max_daily_dd_pct": {"max": dd},
        },
        "walk_forward": [],
        "equity_daily": [["2024-01-01", 1.0], ["2024-01-02", 2.0]],
    }


def test_gates_all_green_and_one_red() -> None:
    integ = {
        s: {"first_day": "2020-01-01", "failed_fraction": 0.01, "failed_days": 3}
        for s in report.SYMBOLS
    }
    mc = {"p_both": 0.65, "p_ftmo_daily_breach": 0.01, "expected_cost_to_funded": 830.0}
    sums = {
        "insample": _summary(900, 0.4, 0.8, 0.03),
        "oos": _summary(600, 0.3, 0.75, 0.035),
        "holdout": _summary(100, 0.2, 0.7, 0.02),
    }
    gates = report.evaluate_gates(sums, mc, integ, 100.0, 540)
    auto = [g for g in gates if g.status != "MANUAL"]
    assert all(g.status == "PASS" for g in auto), [g for g in auto if g.status != "PASS"]
    assert report.verdict(gates).startswith("BACKTEST GATES GREEN")
    sums["oos"] = _summary(600, 0.3, 0.50, 0.035)  # overfit: 0.50 < 0.7 * 0.8
    gates = report.evaluate_gates(sums, mc, integ, 100.0, 540)
    failed = {g.name for g in gates if g.status == "FAIL"}
    assert any("overfit" in n for n in failed) and any("≥ 70%" in n for n in failed)
    assert report.verdict(gates) == "NO-GO"


def test_gates_pending_without_runs() -> None:
    gates = report.evaluate_gates({}, None, {}, None, 540)
    assert report.verdict(gates) == "INCOMPLETE"
    assert {g.status for g in gates} == {"PENDING", "MANUAL"}


def test_build_report_html(tmp_path: Path, profile: FtmoProfile) -> None:
    (tmp_path / "insample").mkdir()
    (tmp_path / "insample" / "summary.json").write_text(json.dumps(_summary(10, 0.1, 0.5, 0.01)))
    cov = tmp_path / "coverage.json"
    cov.write_text(
        json.dumps(
            {
                "files": {
                    "src/ftmo_bot/risk/ftmo_rules.py": {
                        "summary": {
                            "num_statements": 10,
                            "covered_lines": 10,
                            "num_branches": 4,
                            "covered_branches": 4,
                        }
                    }
                }
            }
        )
    )
    out = report.build_report(tmp_path, tmp_path / "integ", profile, cov)
    text = out.read_text()
    assert "In-sample vs out-of-sample vs holdout" in text and "INCOMPLETE" in text
    gates = json.loads((tmp_path / "gates.json").read_text())
    cov_gate = next(g for g in gates["gates"] if "branch coverage" in g["name"])
    assert cov_gate["status"] == "PASS"


def test_trade_metrics_and_walk_forward() -> None:
    t = pd.DataFrame(
        {
            "r_multiple": [2.0, -1.0, -1.0, 1.0],
            "pnl_usd": [1, 2, 3, 4],
            "date_cest": [date(2024, 1, 5), date(2024, 7, 5), date(2024, 8, 1), date(2024, 11, 1)],
        }
    )
    m = report.trade_metrics(t)
    assert m["expectancy_r"] == pytest.approx(0.25) and m["profit_factor"] == pytest.approx(1.5)
    wf = report.walk_forward(t, date(2024, 1, 1), date(2024, 12, 31))
    assert wf[0]["test_start"] == "2024-07-01" and wf[0]["trades"] == 2
    assert report.trade_metrics(t.iloc[:0])["trades"] == 0
