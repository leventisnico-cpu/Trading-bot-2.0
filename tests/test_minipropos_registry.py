"""Strategy registry, DEPLOYABLE markers, live-port refusal, and the
expectancy gate's fold/gate arithmetic (no data replay here)."""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mini_prop_os.strategy import registry
from mini_prop_os.strategy.registry import (deployable_marker, is_deployable,
                                            refuse_live_reason,
                                            strategy_names,
                                            unregistered_strategy_modules)

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import expectancy  # noqa: E402


def test_shipped_losers_are_marked_not_deployable():
    assert is_deployable("ema_crossover") is False
    assert is_deployable("adaptive_ema") is False


def test_every_strategy_module_is_registered():
    assert unregistered_strategy_modules() == ()
    for name in strategy_names():
        s = registry.get_spec(name).factory("SPY", 10, 1.0)
        assert s.symbol == "SPY"


def test_marker_parsing_defaults_to_not_deployable():
    assert deployable_marker(None) is None
    assert deployable_marker("no marker here") is None
    assert deployable_marker("x\nDEPLOYABLE: yes\n") is True
    assert deployable_marker("x\n  deployable: NO\n") is False
    assert deployable_marker("DEPLOYABLE: maybe") is None


def test_unknown_strategy_raises():
    with pytest.raises(KeyError, match="unknown strategy"):
        registry.get_spec("nope")


@pytest.mark.parametrize("port", [7496, 4001, 4003])
def test_live_port_refused_for_non_deployable_strategy(port):
    reason = refuse_live_reason("adaptive_ema", port)
    assert reason is not None and "LIVE" in reason and str(port) in reason


@pytest.mark.parametrize("port", [7497, 4002])
def test_paper_ports_always_allowed(port):
    assert refuse_live_reason("adaptive_ema", port) is None


def test_live_port_allowed_only_when_marked_yes(monkeypatch):
    monkeypatch.setattr(registry, "is_deployable", lambda name: True)
    assert refuse_live_reason("adaptive_ema", 4001) is None
    monkeypatch.setattr(registry, "is_deployable", lambda name: False)
    assert refuse_live_reason("adaptive_ema", 4001) is not None


def test_main_refuses_live_start_with_losing_strategy(tmp_path):
    """End-to-end: python -m mini_prop_os exits 4 before touching the socket."""
    pytest.importorskip("ib_insync")
    cfg = tmp_path / "live.yaml"
    cfg.write_text(
        "connection: {port: 4003}\n"
        "contract: {symbol: SPY, sec_type: STK, exchange: SMART, multiplier: 1.0}\n"
        "strategy: {name: ema_crossover, order_quantity: 1}\n"
        "risk: {max_order_quantity: 1}\n"
        f"execution: {{execution_log_path: '{tmp_path / 'x.jsonl'}'}}\n"
        f"logging: {{file: '{tmp_path / 'x.log'}'}}\n")
    proc = subprocess.run([sys.executable, "-m", "mini_prop_os",
                           "--config", str(cfg)], cwd=REPO,
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 4, proc.stdout + proc.stderr
    assert "REFUSING TO START" in proc.stdout + proc.stderr


# ------------------------------------------------------ expectancy maths

def test_fold_slices_are_contiguous_and_cover_everything():
    s = expectancy.fold_slices(10, 3)
    assert s == [(0, 3), (3, 7), (7, 10)]
    assert s[0][0] == 0 and s[-1][1] == 10
    for (a, b), (c, d) in zip(s, s[1:]):
        assert b == c


def test_buy_and_hold_pays_costs_once_and_marks_to_market():
    final, curve = expectancy.buy_and_hold([100.0, 110.0, 120.0], lot=10,
                                           cash=10_000.0,
                                           commission_per_share=0.10)
    # buy 10 @ 100.01 + $1 commission, hold: 10_000 - 1000.1 - 1 + 10*120
    assert final == pytest.approx(10_000 - 1000.1 - 1.0 + 1200.0)
    assert curve[0] == pytest.approx(10_000 - 1000.1 - 1.0 + 1000.0)


def _leg(beats: bool, label: str = "x") -> expectancy.Leg:
    t = datetime(2020, 1, 1, tzinfo=timezone.utc)
    return expectancy.Leg(label, t, t, 1, 110.0 if beats else 90.0, 0.0, 0.0,
                          0.0, 0, None, 100.0, 0.0, 0.0, False)


def test_gate_requires_two_of_three_folds_and_full_sample(monkeypatch):
    def fake_run_leg(label, *a, **k):
        return outcomes[label]
    monkeypatch.setattr(expectancy, "run_leg", fake_run_leg)
    dates = [datetime(2020, 1, i + 1, tzinfo=timezone.utc) for i in range(9)]
    closes = [100.0] * 9

    outcomes = {"fold 1/3": _leg(True), "fold 2/3": _leg(True),
                "fold 3/3": _leg(False), "full sample": _leg(True)}
    assert expectancy.evaluate("s", "SPY", dates, closes, 3, 10, 1e4).deployable

    outcomes["full sample"] = _leg(False)      # 2/3 folds but full fails
    assert not expectancy.evaluate("s", "SPY", dates, closes, 3, 10, 1e4).deployable

    outcomes = {"fold 1/3": _leg(True), "fold 2/3": _leg(False),
                "fold 3/3": _leg(False), "full sample": _leg(True)}
    assert not expectancy.evaluate("s", "SPY", dates, closes, 3, 10, 1e4).deployable


def test_gate_rule_is_printed(capsys, monkeypatch):
    monkeypatch.setattr(expectancy, "load_closes",
                        lambda p, s: ([datetime(2020, 1, 1, tzinfo=timezone.utc)] * 400,
                                      [100.0] * 400))
    monkeypatch.setattr(expectancy, "evaluate",
                        lambda *a, **k: expectancy.Verdict(
                            "ema_crossover", [_leg(False)] * 4, False, 0, False))
    assert expectancy.main(["--strategy", "ema_crossover"]) == 1
    out = capsys.readouterr().out
    assert expectancy.GATE_RULE in out
    assert "NOT DEPLOYABLE" in out
