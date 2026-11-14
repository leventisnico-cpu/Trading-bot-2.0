"""Backtest summaries, the Go/no-go gate checklist, and the HTML report.

The report shows in-sample / out-of-sample / holdout side by side and fills
the SPEC "Go/no-go gates" automatically from whatever results exist. Gates that
need data not yet produced are PENDING; forward-test gates are MANUAL. The
verdict is GO only when every automatic gate passes AND nothing is pending —
forward gates must still be ticked by a human before paying.
"""

from __future__ import annotations

import html
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ftmo_bot.backtest import ftmo_sim
from ftmo_bot.backtest.engine import BacktestResult
from ftmo_bot.config import FtmoProfile, StrategyParams
from ftmo_bot.risk.ftmo_rules import Limits

SPLITS = ("insample", "oos", "holdout")
SYMBOLS = ("EURUSD", "GBPUSD", "NAS100", "XAUUSD")


# ------------------------------------------------------------------ metrics


def trade_metrics(trades: pd.DataFrame) -> dict[str, Any]:
    n = len(trades)
    if n == 0:
        return {
            "trades": 0,
            "expectancy_r": None,
            "win_rate": None,
            "profit_factor": None,
            "total_pnl": 0.0,
            "avg_win_r": None,
            "avg_loss_r": None,
        }
    r = trades["r_multiple"].to_numpy(np.float64)
    wins, losses = r[r > 0], r[r <= 0]
    gross_loss = -losses.sum()
    return {
        "trades": n,
        "expectancy_r": float(r.mean()),
        "win_rate": float((r > 0).mean()),
        "profit_factor": float(wins.sum() / gross_loss) if gross_loss > 0 else None,
        "total_pnl": float(trades["pnl_usd"].sum()),
        "avg_win_r": float(wins.mean()) if wins.size else None,
        "avg_loss_r": float(losses.mean()) if losses.size else None,
    }


def walk_forward(trades: pd.DataFrame, start: date, end: date) -> list[dict[str, Any]]:
    """Fixed params, rolling 6-month train / 3-month test: report each test window."""
    rows = []
    t0 = pd.Timestamp(start)
    while True:
        test_start = t0 + pd.DateOffset(months=6)
        test_end = test_start + pd.DateOffset(months=3)
        if test_start.date() > end:
            break
        d = (
            pd.to_datetime(trades["date_cest"])
            if len(trades)
            else pd.Series(dtype="datetime64[ns]")
        )
        sel = trades[(d >= test_start) & (d < test_end)] if len(trades) else trades
        m = trade_metrics(sel)
        rows.append(
            {
                "test_start": test_start.date().isoformat(),
                "test_end": (test_end - pd.Timedelta(days=1)).date().isoformat(),
                "trades": m["trades"],
                "expectancy_r": m["expectancy_r"],
                "total_pnl": m["total_pnl"],
            }
        )
        t0 += pd.DateOffset(months=3)
    return rows


def summarize_backtest(
    split: str,
    result: BacktestResult,
    engine: Limits,
    ftmo: Limits,
    profile: FtmoProfile,
    params: StrategyParams,
    news_events: int,
) -> dict[str, Any]:
    tr = result.trades
    days = ftmo_sim.days_from_frame(result.days) if len(result.days) else []
    windows = ftmo_sim.rolling(
        days, engine, ftmo, profile.phases[0].profit_target_pct, profile.min_trading_days
    )
    by_symbol = {s: trade_metrics(tr[tr["symbol"] == s]) for s in sorted(set(tr["symbol"]))}
    rej = result.rejections
    rej_counts = rej["reason"].str.split(":").str[0].value_counts().to_dict() if len(rej) else {}
    daily = result.days
    return {
        "split": split,
        "params_hash": params.params_hash,
        "start": result.start.isoformat(),
        "end": result.end.isoformat(),
        "days": len(daily),
        **trade_metrics(tr),
        "by_symbol": by_symbol,
        "exit_reasons": tr["exit_reason"].value_counts().to_dict() if len(tr) else {},
        "rejections": {str(k): int(v) for k, v in rej_counts.items()},
        "engine_halt_days": int(daily["halted"].sum()) if len(daily) else 0,
        "news_events_loaded": news_events,
        "ftmo_phase1": ftmo_sim.summarize(windows),
        "walk_forward": walk_forward(tr, result.start, result.end),
        "equity_daily": [
            [d.isoformat(), float(e)]
            for d, e in zip(daily.get("date_cest", []), daily.get("end_equity", []), strict=True)
        ],
    }


# ------------------------------------------------------------------ gates


@dataclass(frozen=True)
class Gate:
    section: str
    name: str
    status: str  # PASS | FAIL | PENDING | MANUAL
    detail: str


def _g(section: str, name: str, ok: bool | None, detail: str) -> Gate:
    status = "PENDING" if ok is None else "PASS" if ok else "FAIL"
    return Gate(section, name, status, detail)


def evaluate_gates(
    summaries: dict[str, dict[str, Any]],
    mc: dict[str, Any] | None,
    integrity: dict[str, dict[str, Any]],
    coverage_pct: float | None,
    challenge_fee: float,
) -> list[Gate]:
    g: list[Gate] = []
    S = "Data and code"
    if all(s in integrity for s in SYMBOLS):
        bad = [
            s
            for s in SYMBOLS
            if (integrity[s]["first_day"] or "9999") > "2020-01-31"
            or integrity[s]["failed_fraction"] > 0.05
        ]
        g.append(
            _g(
                S,
                "Tick data integrity checks pass for all four symbols, 2020–present",
                not bad,
                "failing: " + ", ".join(bad)
                if bad
                else "; ".join(f"{s} {integrity[s]['failed_days']} days excluded" for s in SYMBOLS),
            )
        )
    else:
        missing = [s for s in SYMBOLS if s not in integrity]
        g.append(
            _g(
                S,
                "Tick data integrity checks pass for all four symbols, 2020–present",
                None,
                "no integrity report for " + ", ".join(missing),
            )
        )
    g.append(
        _g(
            S,
            "risk/ftmo_rules.py at 100% branch coverage (incl. DST & midnight)",
            None if coverage_pct is None else coverage_pct >= 100.0,
            "not measured" if coverage_pct is None else f"{coverage_pct:.1f}%",
        )
    )
    g.append(
        Gate(
            S,
            "Backtest and live use the identical ftmo_rules.py code path",
            "MANUAL",
            "enforced by tests/test_same_path.py in CI — tick once CI is green",
        )
    )

    S = "Backtest (out-of-sample 2024–2025, after params frozen)"
    oos = summaries.get("oos")
    ins = summaries.get("insample")
    hold = summaries.get("holdout")

    def val(s: dict[str, Any] | None, *keys: str) -> Any:
        cur: Any = s
        for k in keys:
            if cur is None:
                return None
            cur = cur.get(k)
        return cur

    n = val(oos, "trades")
    g.append(
        _g(
            S,
            "≥ 500 trades across the four instruments",
            None if n is None else n >= 500,
            "no OOS run" if n is None else f"{n} trades",
        )
    )
    e = val(oos, "expectancy_r")
    g.append(
        _g(
            S,
            "Expectancy ≥ 0.25 R per trade after costs",
            None if oos is None else (e is not None and e >= 0.25),
            "no OOS run" if oos is None else f"{e if e is None else round(e, 3)} R",
        )
    )
    pr = val(oos, "ftmo_phase1", "pass_rate")
    unresolved = val(oos, "ftmo_phase1", "unresolved")
    windows = val(oos, "ftmo_phase1", "windows")
    enough = windows and unresolved is not None and unresolved <= 0.5 * windows
    g.append(
        _g(
            S,
            "Rolling-window FTMO Phase 1 pass rate ≥ 70%",
            None if pr is None else bool(enough and pr >= 0.70),
            "no OOS run"
            if pr is None
            else f"{pr:.1%} of resolved windows ({unresolved}/{windows} unresolved)",
        )
    )
    ipr = val(ins, "ftmo_phase1", "pass_rate")
    g.append(
        _g(
            S,
            "OOS pass rate ≥ 70% of in-sample pass rate (overfit check)",
            None if pr is None or ipr is None else (ipr > 0 and pr >= 0.7 * ipr),
            "needs in-sample and OOS"
            if pr is None or ipr is None
            else f"OOS {pr:.1%} vs IS {ipr:.1%} (ratio {pr / ipr if ipr else float('nan'):.2f})",
        )
    )
    dd = val(oos, "ftmo_phase1", "max_daily_dd_pct", "max")
    g.append(
        _g(
            S,
            "Max daily drawdown in any window < 4% of initial balance",
            None if dd is None else dd < 0.04,
            "no OOS run" if dd is None else f"{dd:.2%}",
        )
    )
    he = val(hold, "expectancy_r")
    hpr = val(hold, "ftmo_phase1", "pass_rate")
    g.append(
        _g(
            S,
            "Holdout (2026 YTD) run once; expectancy > 0, pass rate within 15 pts of OOS",
            None
            if hold is None or pr is None
            else (he is not None and he > 0 and hpr is not None and abs(hpr - pr) <= 0.15),
            "no holdout run"
            if hold is None or pr is None
            else f"expectancy {_fmt(he, 'r')}, pass {_fmt(hpr, 'pct')}",
        )
    )

    S = "Monte Carlo (10,000 stressed paths)"
    pb = val(mc, "p_both")
    g.append(
        _g(
            S,
            "P(pass Phase 1 and Phase 2) ≥ 60%",
            None if pb is None else pb >= 0.60,
            "not run" if pb is None else f"{pb:.1%}",
        )
    )
    pd_ = val(mc, "p_ftmo_daily_breach")
    g.append(
        _g(
            S,
            "P(breach daily loss at FTMO's 5%) ≤ 5%",
            None if pd_ is None else pd_ <= 0.05,
            "not run" if pd_ is None else f"{pd_:.2%}",
        )
    )
    cost = val(mc, "expected_cost_to_funded")
    g.append(
        _g(
            S,
            "Expected challenge cost to funded = fee ÷ P(pass) ≤ 2 × fee",
            None if mc is None else (cost is not None and cost <= 2 * challenge_fee),
            "not run"
            if mc is None
            else (
                "P(pass)=0" if cost is None else f"{cost:,.0f} vs limit {2 * challenge_fee:,.0f}"
            ),
        )
    )

    S = "Forward (FTMO Free Trial, 60 days)"
    for name in (
        "Guard verified: induced 2.5% drawdown flattened within 10 s, logged, Telegram alert",
        "Live fills within 1.5× backtest slippage assumptions",
        "Forward expectancy ≥ 0.15 R",
        "Zero unintended orders, zero double entries, zero positions held past session end",
    ):
        g.append(Gate(S, name, "MANUAL", "forward test — see RUNBOOK.md"))
    return g


def verdict(gates: list[Gate]) -> str:
    statuses = {x.status for x in gates if x.status != "MANUAL"}
    if "FAIL" in statuses:
        return "NO-GO"
    if "PENDING" in statuses:
        return "INCOMPLETE"
    return "BACKTEST GATES GREEN — forward gates still manual"


# ------------------------------------------------------------------ HTML


def _fmt(v: Any, kind: str = "") -> str:
    if v is None:
        return "—"
    if kind == "pct":
        return f"{v:.1%}"
    if kind == "r":
        return f"{v:+.3f} R"
    if kind == "usd":
        return f"${v:,.0f}"
    if isinstance(v, float):
        return f"{v:.3f}"
    return html.escape(str(v))


def _equity_svg(points: list[list[Any]], w: int = 560, h: int = 140) -> str:
    if len(points) < 2:
        return "<p class=muted>no equity data</p>"
    ys = [p[1] for p in points]
    lo, hi = min(ys), max(ys)
    span = hi - lo or 1.0
    coords = " ".join(
        f"{i * w / (len(ys) - 1):.1f},{h - (y - lo) / span * h:.1f}" for i, y in enumerate(ys)
    )
    return (
        f'<svg viewBox="0 0 {w} {h}" width="100%" height="{h}" role="img" '
        f'aria-label="equity curve"><polyline fill="none" stroke="var(--accent)" '
        f'stroke-width="1.5" points="{coords}"/></svg>'
        f"<p class=muted>{points[0][0]} → {points[-1][0]}: {_fmt(ys[0], 'usd')} → "
        f"{_fmt(ys[-1], 'usd')}</p>"
    )


ROWS: list[tuple[str, Callable[[dict[str, Any]], str]]] = [
    ("Period", lambda s: f"{s['start']} → {s['end']}"),
    ("Params hash", lambda s: s["params_hash"]),
    ("Trades", lambda s: _fmt(s["trades"])),
    ("Expectancy", lambda s: _fmt(s["expectancy_r"], "r")),
    ("Win rate", lambda s: _fmt(s["win_rate"], "pct")),
    ("Profit factor", lambda s: _fmt(s["profit_factor"])),
    ("Total P&L", lambda s: _fmt(s["total_pnl"], "usd")),
    ("Phase 1 pass rate (resolved windows)", lambda s: _fmt(s["ftmo_phase1"]["pass_rate"], "pct")),
    (
        "Windows passed / FTMO-failed / engine-halted / unresolved",
        lambda s: (
            f"{s['ftmo_phase1']['passed']} / {s['ftmo_phase1']['ftmo_failed']} / "
            f"{s['ftmo_phase1']['engine_halted']} / {s['ftmo_phase1']['unresolved']}"
        ),
    ),
    ("Median days to pass", lambda s: _fmt(s["ftmo_phase1"]["median_days_to_pass"])),
    (
        "Max daily DD (any window)",
        lambda s: _fmt(s["ftmo_phase1"]["max_daily_dd_pct"]["max"], "pct"),
    ),
    ("Engine daily-halt days", lambda s: _fmt(s["engine_halt_days"])),
    ("News events loaded", lambda s: _fmt(s["news_events_loaded"])),
]


def render_html(
    summaries: dict[str, dict[str, Any]],
    mc: dict[str, Any] | None,
    gates: list[Gate],
    warnings: list[str],
) -> str:
    v = verdict(gates)
    cls = "fail" if v == "NO-GO" else "pend" if v == "INCOMPLETE" else "pass"
    head = "".join(f"<th>{k}</th>" for k in SPLITS)
    rows = []
    for label, fn in ROWS:
        cells = "".join(
            f"<td>{fn(summaries[k]) if k in summaries else '<span class=muted>not run</span>'}</td>"
            for k in SPLITS
        )
        rows.append(f"<tr><th scope=row>{label}</th>{cells}</tr>")
    gate_rows = []
    section = None
    for gt in gates:
        if gt.section != section:
            section = gt.section
            gate_rows.append(f"<tr class=sec><th colspan=3>{html.escape(section)}</th></tr>")
        gate_rows.append(
            f"<tr><td><span class='badge {gt.status.lower()}'>{gt.status}</span></td>"
            f"<td>{html.escape(gt.name)}</td><td class=muted>{html.escape(gt.detail)}</td></tr>"
        )
    curves = "".join(
        f"<h3>{k}</h3>{_equity_svg(summaries[k]['equity_daily'])}" for k in SPLITS if k in summaries
    )
    wf = ""
    for k in SPLITS:
        if k in summaries and summaries[k]["walk_forward"]:
            body = "".join(
                f"<tr><td>{r['test_start']} → {r['test_end']}</td><td>{r['trades']}</td>"
                f"<td>{_fmt(r['expectancy_r'], 'r')}</td><td>{_fmt(r['total_pnl'], 'usd')}</td></tr>"
                for r in summaries[k]["walk_forward"]
            )
            wf += (
                f"<h3>{k}</h3><table><tr><th>Test window</th><th>Trades</th>"
                f"<th>Expectancy</th><th>P&amp;L</th></tr>{body}</table>"
            )
    mc_html = "<p class=muted>Monte Carlo not run.</p>"
    if mc and mc.get("paths"):
        mc_html = (
            f"<table><tr><th>Source split</th><td>{_fmt(mc.get('split'))}</td></tr>"
            f"<tr><th>Paths</th><td>{mc['paths']:,} (seed {mc['seed']})</td></tr>"
            f"<tr><th>P(Phase 1)</th><td>{_fmt(mc['p_phase1'], 'pct')}</td></tr>"
            f"<tr><th>P(Phase 2 | Phase 1)</th><td>{_fmt(mc['p_phase2_given_phase1'], 'pct')}</td></tr>"
            f"<tr><th>P(both)</th><td>{_fmt(mc['p_both'], 'pct')}</td></tr>"
            f"<tr><th>P(FTMO daily breach)</th><td>{_fmt(mc['p_ftmo_daily_breach'], 'pct')}</td></tr>"
            f"<tr><th>Expected fees to funded</th><td>{_fmt(mc['expected_cost_to_funded'], 'usd')}"
            f"</td></tr></table>"
        )
    warn = "".join(f"<li>{html.escape(w)}</li>" for w in warnings)
    return f"""<!doctype html>
<html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>FTMO Backtest Report</title>
<style>
:root {{ --bg:#fff; --fg:#1d1d1f; --muted:#6b6b70; --line:#e3e3e6; --accent:#2f5bd3;
  --pass:#1f7a3d; --fail:#b42318; --pend:#9a6700; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#141416; --fg:#ececf0; --muted:#9a9aa2;
  --line:#2c2c31; --accent:#7aa2ff; --pass:#4cc27a; --fail:#ff6b5e; --pend:#e0b341; }} }}
body {{ background:var(--bg); color:var(--fg); font:15px/1.5 system-ui,sans-serif;
  max-width:980px; margin:0 auto; padding:24px 16px; }}
table {{ border-collapse:collapse; width:100%; margin:8px 0 24px; display:block; overflow-x:auto; }}
th, td {{ text-align:left; padding:6px 10px; border-bottom:1px solid var(--line); vertical-align:top; }}
tr.sec th {{ padding-top:16px; }}
.muted {{ color:var(--muted); }}
.badge {{ font-weight:600; font-size:12px; padding:2px 8px; border-radius:10px; border:1px solid; }}
.pass {{ color:var(--pass); }} .fail {{ color:var(--fail); }} .pending, .pend {{ color:var(--pend); }}
.manual {{ color:var(--muted); }}
.verdict {{ font-size:22px; font-weight:700; }}
</style></head><body>
<h1>FTMO challenge backtest</h1>
<p class="verdict {cls}">Verdict: {html.escape(v)}</p>
<p class=muted>One red box = don't pay. The answer to a red gate is a different strategy family,
not parameter tuning.</p>
<ul>{warn}</ul>
<h2>In-sample vs out-of-sample vs holdout</h2>
<table><tr><th></th>{head}</tr>{"".join(rows)}</table>
<h2>Go/no-go checklist</h2>
<table>{"".join(gate_rows)}</table>
<h2>Monte Carlo</h2>{mc_html}
<h2>Equity (end of day)</h2>{curves or "<p class=muted>no runs</p>"}
<h2>Walk-forward (fixed params, 3-month test windows)</h2>{wf or "<p class=muted>no runs</p>"}
</body></html>
"""


def coverage_from_json(path: Path, module_suffix: str = "risk/ftmo_rules.py") -> float | None:
    data = json.loads(path.read_text())
    for name, f in data.get("files", {}).items():
        if name.replace("\\", "/").endswith(module_suffix):
            s = f["summary"]
            total = s["num_statements"] + s.get("num_branches", 0)
            covered = s["covered_lines"] + s.get("covered_branches", 0)
            return 100.0 * covered / total if total else 100.0
    return None


def build_report(
    reports_dir: Path,
    integrity_dir: Path,
    profile: FtmoProfile,
    coverage_json: Path | None = None,
) -> Path:
    summaries = {}
    for k in SPLITS:
        p = reports_dir / k / "summary.json"
        if p.exists():
            summaries[k] = json.loads(p.read_text())
    mc_path = reports_dir / "montecarlo.json"
    mc = json.loads(mc_path.read_text()) if mc_path.exists() else None
    integrity = {}
    for s in SYMBOLS:
        p = integrity_dir / f"{s}.json"
        if p.exists():
            integrity[s] = json.loads(p.read_text())
    cov = coverage_from_json(coverage_json) if coverage_json and coverage_json.exists() else None
    gates = evaluate_gates(summaries, mc, integrity, cov, profile.challenge_fee)
    warnings = []
    if any(s.get("news_events_loaded", 0) == 0 for s in summaries.values()):
        warnings.append(
            "News filter had no events for at least one run — supply a historical "
            "events CSV (--news-csv) or the backtest overstates tradeable sessions."
        )
    hashes = {s["params_hash"] for s in summaries.values()}
    if len(hashes) > 1:
        warnings.append(f"Splits were run with different parameter sets: {sorted(hashes)}")
    warnings.append(
        "Contract specs, typical spreads, commissions and the challenge fee marked "
        "VERIFY in config/ftmo_2step.yaml must be confirmed on the FTMO demo."
    )
    out = reports_dir / "report.html"
    out.write_text(render_html(summaries, mc, gates, warnings))
    (reports_dir / "gates.json").write_text(
        json.dumps({"verdict": verdict(gates), "gates": [g.__dict__ for g in gates]}, indent=2)
    )
    return out
