"""python -m ftmo_bot {preflight|plan|run} --config deploy/ftmo/config.yaml [--execute]

* preflight: read-only checks (terminal, account, symbols, today's plan).
* plan:      read-only; prints what the bot would do at the next open.
* run:       the daily loop. Orders are only logged unless the config says
             ``dry_run: false`` AND ``--execute`` is given (two opt-ins).
"""

from __future__ import annotations

import argparse
import logging
import sys

from . import fast4, sessions
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
    if a.command in ("preflight", "plan"):
        now = b.now()
        ok = True
        for s, sym in cfg.symbols.items():
            spec = b.spec(sym)
            if not spec.exists:
                print(f"FAIL {s}: symbol {sym} not found in Market Watch")
                ok = False
                continue
            ss = [x for x in sessions.build(b.bars(sym, 30, 5000), 30, now)
                  if x.complete]
            ind = fast4.indicators(ss)
            print(f"PASS {s} ({sym}): lots {spec.volume_min}-{spec.volume_max} "
                  f"step {spec.volume_step}; {len(ss)} sessions, last "
                  f"{ss[-1].day} close {ind.close:.2f}, SMA200 "
                  f"{ind.sma200 if ind.sma200 is None else round(ind.sma200, 2)}, "
                  f"RSI2 {ind.rsi2:.1f}, ATR {ind.atr14:.2f}"
                  + ("  <- ENTRY SIGNAL" if ind.sma200 and ind.close > ind.sma200
                     and ind.rsi2 < 10 else ""))
            if len(ss) < 205:
                print(f"FAIL {s}: only {len(ss)} sessions; need 205+")
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
