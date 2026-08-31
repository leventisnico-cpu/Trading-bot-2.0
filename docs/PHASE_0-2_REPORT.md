# Phase 0–2 Report — Asset Class, Venue, and Strategy Evidence

**Parameters:** deployable capital = **$100/week contribution stream** (starting near $0);
jurisdiction = **Canada**; runtime = engineer's choice.

Per §12 of the engine prompt, Phases 0–2 are reported here and **no engine code is
written until the operator responds**. Per §2: "do not deploy" is an acceptable outcome,
and this report contains one partial instance of it.

---

## Phase 0 — Deriving the asset class from capital

The capital input is not a lump sum. It is a **contribution stream**: ~$433/month,
~$5,200/year, starting from approximately zero. This changes the analysis in two ways:

1. **The account crosses viability thresholds over time.** Any threshold framed as
   "minimum viable capital" becomes a *date*, not a yes/no.
2. **Contributions are a free rebalancing mechanism.** New cash can be directed toward
   whatever the signal currently favors, achieving most of the rebalance without selling —
   which cuts both turnover cost and (in a taxable account) realized gains.

### Where the evidence ladder meets the money

| Market | Evidence quality | Min viable | Reached at $100/wk | Verdict |
|---|---|---|---|---|
| Futures trend | Strongest (100+ yrs, every decade positive) | ~$15–25k | **~year 3–5** | Out of reach for now. **The unlock number is ~$15,000.** Not quietly downgraded — named, per Phase 0 rules. |
| Equity ETF momentum | Strong; ~40% of premium survives publication | ~$2,500 | **~month 6** | **Target system.** Viable within the first year. |
| Crypto @ Kraken | Weak (~1 decade, one bull market dominates) | ~$100 | week 1 | Mechanically perfect fit, and rejected for exactly the reason §4 warns about: it is the *convenient* market, not the *evidenced* one. |
| Retail FX | Worst documented | ~$500 | — | Out. |
| Bonds direct / MBS | — | $50k+ | — | Out (ETF proxies are just equities). |

### Phase 0 verdict

**Asset class: equity ETFs, Canadian-listed (CAD-denominated), monthly cadence.**

- Canadian-listed ETFs (TSX: e.g. broad US equity, international developed, emerging,
  bonds, gold — all available as CAD-listed funds) are chosen over US-listed ones because
  a $433/month CAD→USD conversion at IBKR costs a **USD 2.00 minimum per conversion
  (~0.5% of a monthly contribution)** — an entirely avoidable structural drag at this size.
- Monthly decision cadence, with orders batched to one buy-cycle per month. A $1.00
  fixed commission on a $433 batched order is **0.23%**; the same commission on four
  separate $100 weekly orders is 1% each. Batching monthly is worth ~4x on fee drag,
  and monthly momentum is where the evidence is anyway (weekly adds turnover, not edge).
- The engine must treat asset class as **config, not architecture** (§4 Phase 0 rule):
  broker behind an interface, universe + cost model in config. When equity crosses
  ~$15k, a futures-trend config becomes discussable without a rewrite.

### The honest problem: the first ~6 months

Below ~$2,500, fixed per-order fees plus minimum lot sizes make even a monthly-batched
ETF system marginal, and no automatable Canadian venue is commission-free (see Phase 1).
The system therefore has a **ramp mode**: from month 0 the engine runs in
paper/signal mode and the operator executes one batched buy per month by hand
(~5 minutes/month); automated live execution activates only once equity clears the
threshold in config. This is stated in the report rather than hidden: **"do not deploy
live execution below ~$2,500" is part of the verdict.**

---

## Phase 1 — Venue research (Canada, small account, automatable)

Every automatable-venue claim below was checked against current sources this week.
Items marked ⚠ could not be re-verified against the primary page from this build
environment (egress-blocked) and **must be confirmed against the live schedule before
funding an account**.

| Venue | API for individuals? | Fees (small orders) | Finding |
|---|---|---|---|
| **Wealthsimple** | **No.** No public API; ToS prohibits automated trading; accounts flagged and warned/terminated. | $0 commission | Out, despite free trades. |
| **Questrade** | **Read-only.** Order-placement API endpoints exist but trade execution is restricted to approved partner developers; individual customers get account + market data only. | — | Out for execution; usable as a free data source. |
| **Alpaca** | Yes, excellent | $0 | **Does not onboard Canadian residents.** Out. |
| **IBKR Canada** | Yes — TWS API / Client Portal API. **But** retail Web API access requires the Client Portal Gateway (local Java process, interactive 2FA login); self-service headless OAuth is institutional-only as of now, "considered for individuals, no ETA." | ⚠ Fixed: CAD 0.01/share, **min CAD 1.00/order**; Tiered: min ~CAD 0.35. FX conversion min USD 2.00. No inactivity fee. Fractional shares supported for US & Canadian listings (⚠ API support for fractional has conflicting documentation — verify; design assumes **whole shares** so this cannot bite). | **Selected venue.** Only Canadian equity broker that both onboards individuals and permits API trading. |
| **Kraken (Payward Canada)** | Yes — plain REST + API keys, fully headless | 0.25% maker / 0.40% taker, proportional (scale-neutral) | Registered Restricted Dealer in all provinces (OSC, Apr 2025). Viable fallback venue *if the operator overrides Phase 0 on evidence grounds* — kept as a config option, not the recommendation. |

### Runtime decision (was "you pick")

- **Signal engine, backtests, reporting: GitHub Actions.** Free (public repo or within
  free minutes), satisfies §0.5's "prefer a free runtime." Paper mode needs no
  credentials (§9), so this runs from day 1.
- **Live execution at IBKR cannot run on GitHub Actions** — the gateway requirement
  means fully-unattended live trading needs a persistent machine. At month-6 equity
  (~$2,600), a $5/month VPS is ~2.3%/year — worse than the trading costs it enables,
  exactly the trap §0.5 describes. So: manual execution of the engine's monthly order
  list until equity makes a persistent runtime cheap relative to assets
  (~$10k → 0.6%/yr), or until the operator prefers running the gateway on their own
  machine once a month (free, ~5 min).

This is the one place the build deviates from "runs unattended": at this capital level,
full automation of the *execution* leg costs more than it saves. The engine automates
everything else — data, signals, sizing, risk checks, order list, reporting.

---

## Phase 2 — Strategy family evidence

**Family: dual momentum (cross-sectional + absolute) on a small ETF universe, monthly.**

- **Cross-sectional momentum**: 12-month (skip most recent month) relative strength,
  documented since Jegadeesh & Titman (1993), robust across markets and decades.
- **Time-series (absolute) momentum**: Moskowitz, Ooi & Pedersen (2012); used as a
  filter — when the selected asset's own excess return is negative, hold cash/short-term
  bonds instead. This is the component that historically cuts drawdowns.
- **Post-publication decay**: McLean & Pontiff (2016) measure ~58% of factor premia
  evaporating post-publication — the engine's expectations must be set against the
  *surviving* ~42%, not the in-sample numbers. Sharpe expectation after decay and
  costs: **~0.4–0.7. Anything above ~1.5 in our backtest is treated as a bug (§2).**
- **Discounts applied per §4 Phase 2**: crypto momentum studies (short sample, one
  bull market) are not evidence for this system; momentum papers assuming
  institutional costs (0.5–4bps) do **not** transfer directly — our real cost is a
  CAD 1.00 fixed commission plus ~5–10bps spread on Canadian-listed ETFs, which the
  cost model prices **per order from actual notional** (§6), never as flat bps.
- **Universe** (config, not code): 4–6 liquid TSX-listed CAD ETFs spanning US equity,
  international developed, emerging markets, Canadian equity, and a bond/cash sleeve —
  the classic dual-momentum menu, expressed in CAD to avoid FX drag.

**Cost-model check (per §6):** with monthly decisions, contribution-directed buys, and
sells only on signal change, expected turnover is well below the 7.3x/yr of the
document's ETF example — most months the only order is one buy with new cash. At
CAD 1.00/order fixed, projected fee drag at month-6 equity is roughly 0.5–0.9%/yr,
falling as the account grows (fixed fees improve with size). The backtest will produce
the required **net-return-by-account-size table**, and if it shows the strategy losing
to buy-and-hold DCA net of real costs at year-1 sizes, the report will say
**"do not deploy"** in the headline.

---

## What happens next (pending operator response, per §12)

1. Operator picks the path (question asked separately).
2. **Phase 3**: engine + tests, no strategy — backtester, per-order cost model, risk
   layer with veto power, atomic state/journal; all §3 invariants with
   failing-when-removed tests; all §5 failure modes with named regression tests;
   synthetic data first.
3. **Phase 4**: dual-momentum strategy + honest backtest vs buy-and-hold DCA,
   walk-forward, parameter & cost sensitivity, net-return-by-size. Plain-language verdict.
4. **Phase 5–6** only if Phase 4's verdict earns it.

## Stated assumptions (defaults taken, per §12.3)

- Account type: taxable or TFSA at IBKR Canada is the operator's call and does not
  change the build (TFSA is likely preferable for a Canadian; **not** financial advice —
  contribution-based rebalancing minimizes realized gains either way).
- No leverage, no shorting, structurally clamped (§3.4).
- Whole-share orders only, so IBKR's ambiguous fractional-API support cannot bite;
  residual cash carries to the next month.
- Data source for signals: free EOD data (e.g. Questrade market-data API or public EOD
  sources), validated for staleness/NaN per §5.7 before any decision.
