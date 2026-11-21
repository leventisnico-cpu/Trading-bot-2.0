"""End-to-end CLI smoke test on SYNTHETIC ticks (pipeline wiring, not a result)."""

from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

import yaml

from ftmo_bot.cli import main

from .conftest import ROOT
from .synth import write_structured_market

START = date(2023, 1, 2)
DAYS = 45


def test_cli_pipeline_end_to_end(tmp_path: Path) -> None:
    cfg = tmp_path / "config"
    shutil.copytree(ROOT / "config", cfg)
    strat = yaml.safe_load((cfg / "strategy.yaml").read_text())
    strat["splits"] = {
        "insample": ["2023-01-02", "2023-01-31"],
        "oos": ["2023-02-01", "2023-02-15"],
        "holdout": ["2023-02-16", None],
    }
    (cfg / "strategy.yaml").write_text(yaml.safe_dump(strat))
    raw = tmp_path / "raw"
    write_structured_market(raw, START, DAYS)
    common = [
        "--config-dir",
        str(cfg),
        "--raw-dir",
        str(raw),
        "--bars-dir",
        str(tmp_path / "bars"),
        "--integrity-dir",
        str(tmp_path / "integ"),
        "--reports-dir",
        str(tmp_path / "reports"),
        "--calendar-dir",
        str(tmp_path / "cal"),
    ]

    assert main([*common, "resample"]) == 0
    assert main([*common, "integrity"]) == 0
    assert main([*common, "backtest", "--split", "oos"]) == 2  # refused: no in-sample yet
    assert main([*common, "backtest", "--split", "insample"]) == 0
    summary = json.loads((tmp_path / "reports" / "insample" / "summary.json").read_text())
    assert summary["split"] == "insample" and summary["days"] > 0
    assert summary["trades"] >= 10, summary  # the engine really traded
    assert set(summary["exit_reasons"]) <= {"target", "stop", "breakeven", "time", "guard_halt"}
    assert summary["news_events_loaded"] == 0
    assert main([*common, "montecarlo", "--split", "insample", "--paths", "50"]) == 0
    mc = json.loads((tmp_path / "reports" / "montecarlo.json").read_text())
    assert mc["paths"] == 50 and 0.0 <= mc["p_both"] <= 1.0
    assert main([*common, "backtest", "--split", "oos"]) == 0
    assert main([*common, "backtest", "--split", "oos"]) == 2  # refused: already run once
    assert main([*common, "backtest", "--split", "holdout"]) == 0
    assert main([*common, "backtest", "--split", "holdout"]) == 2  # touched once
    html = (tmp_path / "reports" / "report.html").read_text()
    assert "Go/no-go checklist" in html
    gates = json.loads((tmp_path / "reports" / "gates.json").read_text())
    assert gates["verdict"] in ("NO-GO", "INCOMPLETE")  # synthetic data never goes green
    ledger = (tmp_path / "reports" / "ledger.jsonl").read_text().splitlines()
    assert [json.loads(x)["split"] for x in ledger] == ["insample", "oos", "holdout"]
