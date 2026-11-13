# FTMO bot replay on real 30-minute bars (2025-02-10 to 2026-10-02)

Run 2026-10-04: `python scripts/ftmo_shadow.py --bars-dir <dir> --dir <out>
--start 2025-02-10T09:00:00-05:00 --until 2026-10-02T16:10:00-04:00`.
Input: Astral 30-minute bars of QQQ/SPY/DIA/IWM (2024-04-15 to 2026-10-02),
sha256 QQQ `0d403269...`, SPY `7f989221...`, DIA `96d65107...`, IWM `9e27330a...`.

The bot code (the same `ftmo_bot.Runner` the MT5 bot runs, with no
shadow-specific hooks) traded a simulated CAD 15,000
FTMO account at 3% risk, ticked every 30 minutes of each US session
(09:35 to 16:05 New York), seeing only bars that had ended. Stops rest in
the simulated broker (`ftmo_bot/broker_sim.py`) and fill at the stop or
at a gapping open. ETF proxies, no FX, no swap, 0.005% half-spread.
Polling every 30 minutes, the first entry chance is 10:05 at the 09:30
bar's close (the live bot buys at about 09:31).

## Result

* **Phase 1 (+10%) reached; the bot flattened and halted on 2026-01-05**,
  236 weekdays after the 2025-02-10 start. Balance CAD 16,546.58.
* 21 strategy trades, 17 winners (81%); 1 stop-loss
  (-269.87). Plus 6 keep-alive
  open/closes during quiet spells (25 days without a fill).
* Lowest equity 14,575.09 on 2025-02-28 (max-loss floor 13,500.00).
  Closest approach to a daily floor: 176.53 above it on
  2025-10-14. No guard trip, no breach, 0 tick errors in 236 weekdays
  of trading (430 including the halted months after). Lowest
  equity marks open positions at each 30-minute bar's low; the live bot
  polls every minute.
* **Combined-risk cap** (`cap_combined_risk: true`): a second position
  is sized so that both stops together stay above the daily and
  max-loss lines (about 1.8% instead of 3%). The same replay without
  the cap: 17 trades, Phase 1 on 2025-11-20 (204 weekdays), but equity
  came within 42.91 of the daily line on 2025-10-14 (DIA and SPY open
  together); with the cap the closest approach is the one above.
* **Parity:** all 21 entries match an independent pandas computation
  of the FAST-4 signal on the prior session; the signals not taken all
  came while both slots were full.

One path, one period: this checks that the code does what the rule
says on real data. It is not a new estimate of the odds:
`research/ftmo_fast_pass.md` (18% of start dates passed both phases
within 18 months at 3%) was computed without the combined-risk cap,
which trades some speed for not failing on a two-stop day.

## Trades

| entry (NY) | proxy | lots | entry | stop | exit (NY) | exit price | P&L | why |
|---|---|---|---|---|---|---|---|---|
| 2025-02-24T10:05 | QQQ | 11.81 | 523.37 | 500.52 | 2025-02-27T16:00 | 500.52 | -269.87 | stop |
| 2025-02-28T10:05 | SPY | 12.87 | 586.06 | 565.08 | 2025-03-03T10:05 | 593.02 | +89.59 | exit |
| 2025-02-24T10:05 | DIA | 31.98 | 434.41 | 420.34 | 2025-03-03T10:05 | 439.25 | +154.67 | exit |
| 2025-05-22T10:05 | QQQ | 8.56 | 516.53 | 484.89 | 2025-05-28T10:05 | 521.24 | +40.39 | exit |
| 2025-05-22T10:05 | SPY | 14.88 | 584.21 | 554.04 | 2025-05-28T10:05 | 590.76 | +97.46 | exit |
| 2025-08-01T10:05 | IWM | 45.07 | 213.24 | 203.18 | 2025-08-05T10:05 | 221.10 | +354.17 | exit |
| 2025-08-01T10:05 | DIA | 22.00 | 434.75 | 422.63 | 2025-08-06T10:05 | 440.90 | +135.22 | exit |
| 2025-08-20T10:05 | QQQ | 25.74 | 562.21 | 544.03 | 2025-08-25T10:05 | 570.91 | +224.02 | exit |
| 2025-08-20T10:05 | SPY | 16.25 | 635.42 | 619.91 | 2025-08-25T10:05 | 644.31 | +144.40 | exit |
| 2025-09-26T10:05 | DIA | 41.11 | 463.17 | 451.52 | 2025-09-29T10:05 | 462.04 | -46.71 | exit |
| 2025-09-26T10:05 | IWM | 22.23 | 241.33 | 230.50 | 2025-09-30T10:05 | 241.56 | +5.02 | exit |
| 2025-10-10T10:05 | DIA | 41.89 | 465.10 | 453.70 | 2025-10-15T10:05 | 466.00 | +37.43 | exit |
| 2025-10-13T10:05 | SPY | 13.53 | 662.91 | 645.02 | 2025-10-16T10:05 | 666.60 | +49.92 | exit |
| 2025-11-05T10:05 | IWM | 18.66 | 243.19 | 230.35 | 2025-11-06T10:05 | 242.97 | -4.09 | exit |
| 2025-11-05T10:05 | DIA | 32.61 | 472.30 | 457.57 | 2025-11-11T10:05 | 474.95 | +86.18 | exit |
| 2025-11-14T10:05 | IWM | 36.75 | 236.38 | 223.24 | 2025-11-24T10:05 | 238.14 | +64.54 | exit |
| 2025-11-18T10:05 | SPY | 9.69 | 658.68 | 634.23 | 2025-11-25T10:05 | 668.84 | +98.39 | exit |
| 2025-12-15T10:05 | QQQ | 16.77 | 613.97 | 584.89 | 2025-12-19T10:05 | 616.62 | +44.42 | exit |
| 2025-12-18T10:05 | SPY | 10.40 | 678.09 | 655.77 | 2025-12-22T10:05 | 683.94 | +60.76 | exit |
| 2025-12-31T10:05 | IWM | 46.11 | 247.79 | 237.14 | 2026-01-05T10:35 | 251.99 | +193.66 | target |
| 2026-01-02T10:05 | QQQ | 10.20 | 621.22 | 598.79 | 2026-01-05T10:35 | 619.95 | -12.97 | target |
