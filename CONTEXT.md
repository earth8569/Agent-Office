# Context — Agent Office (AI Crypto Trading System)

A multi-agent ("office") system in which specialised AI agents collaborate to
analyse crypto markets and execute trades. The system runs first in **Paper**
mode and is promoted to **Live** mode once proven.

## Glossary

### Paper→Live Promotion Gate
Promotion from Paper to Live is a **deliberate manual decision** (never
automatic; via a LangGraph human-in-the-loop interrupt), allowed only after a
written checklist is met:
- **Track record:** ≥ ~2–3 months of live Paper **and** ≥ ~30–50 closed trades,
  weighted to **post-Jan-2026** data (the lookahead-free window).
- **Net positive after costs** (fees + funding), not just gross.
- **Risk behaved:** kill-switch never tripped (or only acceptably); drawdown
  within tolerance.
- **LLMs earned their cost:** the LLM judgment layer **beat or matched the
  [Rule-Based Baseline](#rule-based-baseline)** — else run the free baseline.
- **Zero unresolved execution/reconciliation bugs.**

On flip, **Live starts tiny**: minimum capital and a **reduced leverage cap
(~2×)** for the first weeks, ramping toward the 5× ceiling only once live
behaviour matches Paper.

### Trading Mode
The execution environment a trade is routed to. Two values:

- **Paper** — full closed loop (signal → order → fill → position → P&L) executed
  against a simulated or exchange-testnet balance. **No real capital at risk.**
  This is the v1 target.
- **Live** — agents place real orders with real money on a real exchange.

Paper and Live share one order-execution interface; switching is a configuration
change pointed at a different execution adapter, **not** a rewrite. Live is
enabled only after the Paper loop is proven.

### Agent
An **LLM-reasoning** specialist (not a numeric/algorithmic bot). In this system
(hybrid — ADR 0003) agents apply *judgment* over a pre-computed **indicator
snapshot**: debating, weighing, and deciding (Bull/Bear, Research Manager,
Trader, Risk Manager, Portfolio Manager). They decide **what** and **whether**;
deterministic (non-LLM) code computes the indicators, decides **how fast**, and
**enforces limits**.

### State & Persistence
- **Store:** a single **SQLite** file (single-user local Windows app;
  transactional so money-state can't half-write). Holds the **audit log** (every
  Office decision and every Execution/Risk Layer accept/reject — see ADR 0002),
  the **equity curve / peak equity / daily P&L** (the inputs to the drawdown
  kill-switch and daily-loss limit), and a cache.
- **Source of truth for positions/balances:** the **exchange (OKX)** — OKX demo
  in Paper, OKX live in Live. SQLite mirrors but does not override it.

### Runtime
- **Live** runs on a small **always-on cloud VM/VPS** for a reliable unattended
  4h cadence. **Local Windows** is for development and Paper only.
- **Stops are exchange-native:** every mandatory stop-loss is a **native stop
  order placed on OKX at entry**, so an open position stays protected even when
  the agent is offline. Protection never depends on process/machine uptime.
- The loop is **idempotent and reconcile-first** — a missed cycle is harmless.

See ADR 0004.

### Reconciliation
At the **start of every Decision Cycle**, the system reconciles local SQLite
state against OKX (positions, balances, fills) before any new trade — so a
crash, manual trade, or partial fill cannot desync the risk math.

### Fail-Safe Behavior
When anything goes wrong mid-cycle (LLM API down/rate-limited, malformed agent
output, OKX API error), the system **aborts that cycle without opening or
modifying positions** and logs it — never trade on degraded/uncertain state.
This is safe because open positions are already protected by exchange-native
stops (ADR 0004). An **unresolved reconciliation mismatch halts trading and
alerts** — it never guesses.

### Notifications
**Push to Telegram** on the events that matter: every trade opened/closed, every
Execution/Risk Layer rejection, any kill-switch or daily-loss-limit trip, and
any cycle abort/error. Routine "nothing happened" cycles stay silent (optional
daily digest). The SQLite audit log is the full record; Telegram is the alert
layer.

### Decision Cycle
One full pass of the Office over the Watchlist, **triggered on the close of each
4-hour candle** (~6 cycles/day). Not tick- or timer-driven — decisions are made
only on **closed** candles for reproducibility. Analysts read two timeframes:
**4h** (the decision signal) and **1D** (higher-timeframe trend bias).

### Tech Stack
- **Language:** Python.
- **Orchestration:** **LangGraph** (parallel fan-out for the analyst pool +
  sequential stages downstream; supports human-in-the-loop interrupts for the
  Paper→Live gate).
- **LLM access:** **API only** — the agents call the model API programmatically
  inside LangGraph nodes. The web chat UI (ChatGPT/Claude) **cannot** run this:
  the system runs unattended on each 4h candle close and fans out to many
  agents, which needs a key + SDK, not a chat window. Requires an API key.
- **Model:** provider-agnostic by design (a per-node config). Default:
  **Claude Opus 4.8** (`claude-opus-4-8`) for judgment-heavy stages (Research
  Manager, Trader, Portfolio Manager), **Claude Haiku 4.5** for the shallow
  parallel technical sub-analysts. Provider/model choice is settled by **A/B on
  the backtest** (realized P&L + token cost), not generic benchmarks.
- **Exchange:** OKX via **CCXT** (demo for Paper, live for Live).

**Model pricing & cutoffs** (verified 2026-06-06, per 1M tokens):
| Model | Input | Output | Context | Knowledge cutoff |
|---|---|---|---|---|
| Opus 4.8 `claude-opus-4-8` | $5 | $25 | 1M | Jan 2026 |
| Sonnet 4.6 `claude-sonnet-4-6` | $3 | $15 | 1M | Aug 2025 |
| Haiku 4.5 `claude-haiku-4-5` | $1 | $5 | 200K | Feb 2025 |

Prompt caching ≈ 0.1× on cache reads; Batch API = 50% off. Rough cost: one
office run ≈ ~200K tokens for a 5-asset cycle ≈ **~$2/cycle on Opus** → live
Paper ≈ **~$360/mo**. A full-year 5-asset backtest ≈ **~$4.4K on Opus**, hence
backtests run on **Haiku + caching + Batch + sampled candles**.

### Office
The decision pipeline, modelled on the **TradingAgents** framework (LangGraph,
Python) but **hybrid** (ADR 0003): a deterministic stage 1 feeds an LLM
judgment layer (stages 2–5). Structured in stages:

1. **Indicator Engine** (deterministic Python — **not** LLM). Computes the
   technical features from OHLCV (4h + 1D) across four lenses, in parallel:
   - **Trend** — direction, moving averages, market structure
   - **Momentum** — RSI, MACD, divergences
   - **Support/Resistance** — key levels, breakouts
   - **Volume & Volatility** — volume profile, ATR, squeeze
   Output is one structured **indicator snapshot** per asset. This replaces the
   LLM analyst pool — numeric work belongs in exact, free, deterministic code.
   See ADR 0003.
2. **Research Team** (LLM): a **Bull Researcher** and **Bear Researcher** argue
   opposing cases *over the indicator snapshot*, judged by a **Research
   Manager** who issues a balanced call.
3. **Trader** (LLM): turns the surviving thesis into a concrete proposed action
   (direction, size, leverage, entry/exit, stop).
4. **Risk Manager** (LLM): a sanity check that can veto.
5. **Portfolio Manager** (LLM): allocates capital across the Watchlist and
   issues the final *intended* decision.

Stages 2–5 are the **LLM judgment layer** — the only place tokens are spent. The
deterministic Indicator Engine feeds them; the deterministic Execution/Risk
Layer gates them. There is **no separate synthesis step** before the debate —
the Bull/Bear read the snapshot directly and the Research Manager synthesises
after (ADR 0003 entry-point choice A).

### Rule-Based Baseline
A pure-rule strategy that consumes the **same** indicator snapshot and emits a
decision with **no LLM**. Run alongside the LLM judgment layer so realized P&L
gives a direct, cheap answer to "do the LLMs actually beat plain rules?" Also
serves as the fully-backtestable, lookahead-free reference strategy.

Reference frameworks (TradingAgents and its crypto fork) are **analysis-only**.
This system differs by adding real Paper→Live execution and, critically, a
deterministic [Execution / Risk Layer](#execution--risk-layer) that sits
**below** the Portfolio Manager and can override any LLM. See ADR 0002.

### Trading Horizon
**Swing trading** — decisions made on a cadence of hours up to daily. The system
is explicitly **not** built for scalping/HFT (incompatible with LLM latency and
cost). Reasoning quality matters more than speed.

### Execution / Risk Layer
The deterministic, non-LLM code path that takes an agent decision and turns it
into orders, while enforcing hard limits. It is the **final authority** and can
override any LLM, including the Portfolio Manager. Any trade that violates a hard
limit (≤5× leverage, max position, max exposure, max drawdown, kill-switch) is
**rejected outright** and logged — never silently modified. See ADR 0002.

### Venue
The exchange trades are routed to. **OKX** — chosen for leveraged products, a
demo-trading environment (used for Paper mode), and mature CCXT support.
Rejected: *Binance Thailand* (spot only — Thai SEC restricts retail
derivatives, so no leverage; nascent CCXT support) and *global Binance Futures*
(geo-restricted for Thai residents). Jurisdiction/legality of using OKX is
managed by the operator, not the system. See ADR 0001.

### Watchlist
The fixed, hand-picked set of instruments the office watches and trades — a
**tight list of ~3–7 liquid majors** (e.g. BTC, ETH, SOL) on the perpetual-swap
market. Configurable but small by design: keeps LLM token cost bounded, data
quality high, and leveraged concentration risk manageable. A dynamic
full-market scanner is explicitly **out of scope for v1**.

### Market Data
The system is **purely technical**: the only input is **OHLCV (candlestick)
price/volume data** for the Watchlist instruments, pulled from OKX. No news,
social/sentiment, fundamental, or on-chain feeds are used. (This sharply narrows
data dependencies versus the reference framework.)

### Instrument
**USDT-margined perpetual swaps** on OKX. No expiry, USDT collateral, funding
charged periodically. Chosen over dated futures (expiry overhead) and spot
margin (lower ceilings, borrow accounting).

### Leverage
Trades may use **leverage** (borrowed exposure beyond deposited capital). This is
the core reason for choosing a derivatives-capable venue. Implies liquidation
risk, funding costs, and margin math — all enforced in the Execution / Risk
Layer. **Hard ceiling: 5×**, enforced in code; no agent can request more.

### Hard Risk Limits (v1)
The deterministic limits the Execution / Risk Layer enforces (reject-outright on
violation). Expressed as % of account equity so they are balance-independent:

| Limit | Value |
|---|---|
| Max risk per trade (stop distance × size) | **1%** of equity |
| Stop-loss | **Mandatory** on every position (no stop ⇒ no order) |
| Max leverage | **5×** |
| Max concurrent positions | **3** |
| Max total notional exposure | **3× equity** |
| Daily loss limit | **−5%** equity ⇒ halt for the day |
| Max drawdown kill-switch | **−20%** from peak ⇒ halt all trading, manual restart |
| Position stacking | **One position per asset** — no averaging in v1 |

The two most safety-critical knobs are **max risk per trade** and the
**drawdown kill-switch**.

---

## Decisions

- [ADR 0001](docs/adr/0001-okx-as-venue-for-leveraged-trading.md) — OKX as the
  venue for leveraged crypto trading.
- [ADR 0002](docs/adr/0002-deterministic-risk-layer-is-final-authority.md) —
  Deterministic Execution/Risk Layer is the final authority (reject outright).
- [ADR 0003](docs/adr/0003-hybrid-deterministic-indicators-llm-judgment.md) —
  Hybrid: deterministic indicators, LLMs only at the judgment layer.
- [ADR 0004](docs/adr/0004-exchange-native-stops-and-always-on-runtime.md) —
  Exchange-native stops; always-on runtime for Live.
