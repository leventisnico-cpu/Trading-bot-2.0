# Prop-native strategies under FTMO 2-Step Swing rules

Rules: `research/prop_native.md` (pre-registered). Risk 1.5% per trade, stop 2×ATR, notional cap 5×, CAD 15,000 account.

| symbol | strategy | trades | win rate | profit factor | avg win | avg loss | pass ≤18 mo | by third | median days to pass | main failure | funded survives 1y | median funded 1y | reward (CAD) | GO bar |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| QQQ | PROP-A | 154 | 65% | 1.30 | +0.86% | -1.23% | 0% | 0% / 0% / 0% | 4404 | P2 unfinished 56% | 100% | +1.2% | 147 | **NO-GO** |
| QQQ | PROP-B | 81 | 41% | 1.21 | +2.40% | -1.36% | 0% | 0% / 1% / 0% | 2025 | P2 unfinished 18% | 100% | +0.4% | 52 | **NO-GO** |
| SMH | PROP-A | 174 | 67% | 1.57 | +0.80% | -1.06% | 0% | 0% / 0% / 0% | 3692 | P2 unfinished 29% | 100% | +1.2% | 142 | **info only** |
| SMH | PROP-B | 101 | 40% | 1.18 | +2.40% | -1.33% | 3% | 0% / 0% / 10% | 1688 | P1 max_loss 16% | 100% | +0.0% | 4 | **info only** |

Trade P&L is in fractions of the balance at entry. Evaluation starts need 18 months of data after them; funded starts 252 trading days.
