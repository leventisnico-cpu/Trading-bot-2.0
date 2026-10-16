"""python -m ftmo_bot {preflight|plan|run} --config deploy/ftmo/config.yaml [--execute]

* preflight: read-only checks (terminal, account, symbols, indicators).
* plan:      read-only; prints the FAST-4 exits and entries from the last
             completed session, i.e. what the bot does at the next open.
* run:       the daily loop. Orders are only logged unless the config says
             ``dry_run: false`` AND ``--execute`` is given (two opt-ins).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import fast4, sessions
from .runner import BAR_COUNT, MIN_SESSIONS
from .config import load


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ftmo_bot")
    ap.add_argument("command", choices=["preflight", "plan", "run"])
    ap.add_argument("--config", required=True)
    ap.add_argument("--execute", action="store_true",
                    help="send real orders (also needs dry_run: false in the config)")
    a = ap.parse_args(argv)
    cfg = load(a.config)
    if a.command != "run" or not a.execute:
        cfg.dry_run = True
    Path(cfg.log_path).parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(),
                                  logging.FileHandler(cfg.log_path)])
    from .broker_mt5 import MT5Broker
    b = MT5Broker(cfg.mt5_path)
    acct = b.account()
    print(f"account {acct.login} on {acct.server}, {acct.currency} "
          f"balance {acct.balance:,.2f} equity {acct.equity:,.2f}, "
          f"algo trading {'ON' if acct.trade_allowed else 'OFF'}")
    if a.command == "plan":
        from .runner import Runner
        r = Runner(cfg, b)                  # reads state; never saves it
        held = r.st.held
        print(f"held by the bot: {held or 'nothing'}")
        res = r.compute_plan(b.now())
        if res is None:
            print("no plan: symbols do not share a completed session (see log)")
            return 1
        day, p = res
        print(f"plan from the {day} session, for the next open (09:31-10:30 NY):")
        print(f"  exits:   {', '.join(p.exits) or 'none'}")
        for s in p.entries:
            _, ask = b.quote(cfg.symbols[s])
            print(f"  entry:   {s} at ~{ask:.2f}, stop ~"
                  f"{ask - cfg.atr_stop_mult * p.atr[s]:.2f} "
                  f"({cfg.risk_per_trade:.0%} of balance at risk)")
        if not p.entries:
            print("  entries: none")
        return 0
    if a.command == "preflight":
        now = b.now()
        ok = True
        for s, sym in cfg.symbols.items():
            spec = b.spec(sym)
            if not spec.exists:
                print(f"FAIL {s}: symbol {sym} not found in Market Watch")
                ok = False
                continue
            ss = [x for x in sessions.build(b.bars(sym, 30, BAR_COUNT), 30, now)
                  if x.complete]
            if len(ss) < 2:
                print(f"FAIL {s}: {len(ss)} completed sessions in the terminal's history")
                ok = False
                continue
            ind = fast4.indicators(ss)
            verdict = "PASS" if len(ss) >= MIN_SESSIONS else "FAIL"
            print(f"{verdict} {s} ({sym}): lots {spec.volume_min}-{spec.volume_max} "
                  f"step {spec.volume_step}; {len(ss)} sessions, last "
                  f"{ss[-1].day} close {ind.close:.2f}, SMA200 "
                  f"{ind.sma200 if ind.sma200 is None else round(ind.sma200, 2)}, "
                  f"RSI2 {ind.rsi2:.1f}, ATR {ind.atr14:.2f}"
                  + ("  <- ENTRY SIGNAL" if ind.sma200 and ind.close > ind.sma200
                     and ind.rsi2 < 10 else ""))
            if len(ss) < MIN_SESSIONS:
                print(f"FAIL {s}: only {len(ss)} sessions; need {MIN_SESSIONS}+ "
                      "(raise Tools > Options > Charts > Max bars in chart)")
                ok = False
        if not acct.trade_allowed:
            print("WARN: enable Algo Trading in the terminal before `run --execute`")
        return 0 if ok else 1
    from .runner import Runner
    r = Runner(cfg, b)
    r.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
