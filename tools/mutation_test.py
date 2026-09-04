#!/usr/bin/env python3
"""Mutation testing for safety-critical paths (§8).

Each mutation reverts ONE safety enforcement. The suite must FAIL under
every mutation; a mutation the suite survives means that fix is
unprotected. Run: python3 tools/mutation_test.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# (path, description, old_snippet, mutated_snippet)
MUTATIONS = [
    ("engine/risk.py", "FM1: daily-loss check compares today with today (always 0)",
     "daily_return = (current_equity - net_flows) / prior_state.last_equity - 1.0",
     "daily_return = current_equity / current_equity - 1.0"),

    ("engine/risk.py", "A10: deposits leak into the measured daily return",
     "daily_return = (current_equity - net_flows) / prior_state.last_equity - 1.0",
     "daily_return = current_equity / prior_state.last_equity - 1.0"),

    ("engine/execution.py", "FM2: buys sized off planned cash incl. unconfirmed sell proceeds",
     "        available = broker.get_account().cash",
     "        available = broker.get_account().cash + sum(\n            s.shares * prices.get(s.symbol, 0.0) for s in sells)"),

    ("engine/execution.py", "A01: order cap not applied to the batch",
     "    orders, cap_dropped = truncate_to_cap(orders, risk.cfg.max_orders_per_day)",
     "    orders, cap_dropped = list(orders), []"),

    ("engine/orders.py", "FM3: buys reordered ahead of sells",
     "    return [o for o in orders if o.side is Side.SELL] + [o for o in orders if o.side is Side.BUY]",
     "    return [o for o in orders if o.side is Side.BUY] + [o for o in orders if o.side is Side.SELL]"),

    ("engine/risk.py", "FM4: min-size filter applied to full exits too",
     "if notional < self.cfg.min_order_notional and not o.is_full_exit:",
     "if notional < self.cfg.min_order_notional:"),

    ("engine/portfolio.py", "FM4b: no-trade band swallows full exits",
     "        full_exit = tgt_shares == 0 and cur_shares > 0\n        if full_exit:",
     "        full_exit = False\n        if full_exit:"),

    ("engine/portfolio.py", "A13: full exit keyed on raw weight, not target shares",
     "        full_exit = tgt_shares == 0 and cur_shares > 0\n        if full_exit:",
     "        full_exit = tgt_w == 0.0 and cur_shares > 0\n        if full_exit:"),

    ("engine/state.py", "FM5: unreadable state resets to defaults",
     "            try:\n                return _deserialize(self.path.read_text())\n            except Exception as exc:",
     "            try:\n                return _deserialize(self.path.read_text())\n            except Exception as exc:\n                return EngineState()"),

    ("engine/orders.py", "FM6: success decided by failure blacklist",
     "def is_success(status: OrderStatus) -> bool:\n    return status in SUCCESS_STATUSES",
     "def is_success(status: OrderStatus) -> bool:\n    return status not in {OrderStatus.CANCELLED, OrderStatus.ERROR}"),

    ("engine/data.py", "FM7: NaN last value not treated as missing",
     "        if pd.isna(col.iloc[-1]):\n            problems.append(f\"{sym}: last value is NaN\")\n            continue",
     "        if False:\n            problems.append(f\"{sym}: last value is NaN\")\n            continue"),

    ("engine/portfolio.py", "FM7b: held symbol without a price becomes a full sell",
     "    if missing:\n        # Failure mode #7: a data gap must never read as \"target weight 0\".\n        raise DataError(f\"held symbols with no price: {missing} — refusing to compute orders\")",
     "    if missing:\n        prices = dict(prices)\n        for m in missing:\n            prices[m] = 1e-9"),

    ("engine/portfolio.py", "FM8: basket vol is the average of per-asset vols",
     "    var = float(w @ cov @ w)",
     "    import numpy as _np\n    var = float((_np.sum(_np.abs(w) * _np.sqrt(_np.diag(cov)))) ** 2)"),

    ("engine/runner.py", "FM9: completion measured by orders submitted, not convergence",
     "        if converged(positions, target_weights, px, equity, cfg.risk.rebalance_tolerance):",
     "        if traded:"),

    ("engine/execution.py", "FM10: escalated order is itself escalatable (chain possible)",
     "        more, more_dropped = _submit_single(broker, risk, market, prices, journal)",
     "        market = Order(symbol=order.symbol, side=order.side, shares=order.shares,\n                       is_full_exit=order.is_full_exit, limit_price=order.limit_price)\n        more, more_dropped, _e = _submit_with_escalation(broker, risk, market, prices, max_hops, journal)"),

    ("engine/risk.py", "FM11: equity floor kills accounts that never reached it",
     "        floor_armed = prior_state.peak_equity >= self.cfg.min_equity_floor\n        if floor_armed and current_equity < self.cfg.min_equity_floor:",
     "        floor_armed = True\n        if floor_armed and current_equity < self.cfg.min_equity_floor:"),

    ("engine/backtest.py", "INV1: strategy sees the whole price frame (lookahead)",
     "            visible = prices.iloc[: i + 1]",
     "            visible = prices"),

    ("engine/backtest.py", "INV2: fills at the decision bar's price (no execution lag)",
     "        row_ff = prices_ff.iloc[i]",
     "        row_ff = prices_ff.iloc[max(i - 1, 0)]"),

    ("engine/backtest.py", "A03: kill switches evaluated only on decision days",
     "        pre = None\n        if not state.halted and equity > 0:",
     "        pre = None\n        if not state.halted and equity > 0 and is_decision_day(i):"),

    ("engine/runner.py", "A09: retry counter survives into new periods",
     "        if state.retry_period != period:\n            state.retry_period = period\n            state.rebalance_retries = 0",
     "        if False:\n            state.retry_period = period\n            state.rebalance_retries = 0"),

    ("engine/risk.py", "INV4: shorts survive the clamp",
     "            if not self.cfg.allow_short:\n                w = max(0.0, w)",
     "            if False:\n                w = max(0.0, w)"),

    ("engine/risk.py", "INV4b: leverage survives the clamp",
     "        if gross > cap and gross > 0:\n            scale = cap / gross\n            clamped = {s: w * scale for s, w in clamped.items()}",
     "        if False:\n            scale = cap / gross\n            clamped = {s: w * scale for s, w in clamped.items()}"),

    ("engine/broker.py", "INV6: broker accepts unapproved orders",
     "        if not isinstance(approved, ApprovedOrders):\n            raise TypeError(",
     "        if False:\n            raise TypeError("),

    ("engine/state.py", "INV7: non-atomic state write",
     "        tmp = self.path.with_suffix(self.path.suffix + \".tmp\")\n        with open(tmp, \"w\") as f:\n            f.write(payload)\n            f.flush()\n            os.fsync(f.fileno())",
     "        tmp = self.path\n        with open(tmp, \"w\") as f:\n            f.write(payload)\n            f.flush()\n            os.fsync(f.fileno())"),
]


def run_suite() -> bool:
    proc = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q", "-x",
                           "--timeout=300" if False else "-p", "no:cacheprovider"],
                          cwd=REPO, capture_output=True, text=True)
    return proc.returncode == 0


def main() -> int:
    unprotected = []
    for path, desc, old, new in MUTATIONS:
        target = REPO / path
        original = target.read_text()
        if old not in original:
            print(f"[BROKEN MUTATION] {desc}: snippet not found in {path}")
            unprotected.append(desc + " (snippet drifted)")
            continue
        try:
            target.write_text(original.replace(old, new, 1))
            survived = run_suite()
            status = "SURVIVED (UNPROTECTED!)" if survived else "killed"
            print(f"[{status}] {desc}")
            if survived:
                unprotected.append(desc)
        finally:
            target.write_text(original)
    if not run_suite():
        print("ERROR: suite not green after restore — repo left dirty?")
        return 2
    if unprotected:
        print(f"\n{len(unprotected)} mutation(s) survived — write the missing tests:")
        for d in unprotected:
            print(f"  - {d}")
        return 1
    print(f"\nAll {len(MUTATIONS)} mutations killed. Every safety fix is detected by a test.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
