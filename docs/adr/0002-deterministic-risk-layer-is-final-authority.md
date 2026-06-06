# 0002 — Deterministic Execution/Risk Layer is the final authority

- Status: Accepted
- Date: 2026-06-06

## Context

The office of LLM agents is modelled on the **TradingAgents** framework, whose
top of pipeline is a **Portfolio Manager** that makes the "final execution
decision." However, that reference framework is **analysis-only**: it has no
real order execution and no hard-enforced risk limits.

This system trades for real (Paper now, Live later) on OKX with up to **5×
leverage**. Under leverage, a single oversized or over-leveraged order can cause
liquidation. Trusting an LLM — which is non-deterministic, can hallucinate, and
can be prompt-injected via the news/social data it ingests — as the final word
on order placement is unacceptable.

Three behaviours were considered for when an intended trade violates a hard
limit: **reject outright**, **clamp to the limit**, or **reject-hard /
clamp-soft**.

## Decision

Insert a **deterministic, non-LLM Execution/Risk Layer beneath the Portfolio
Manager**. The PM produces an *intended* trade; this layer validates it against
hard limits (≤5× leverage, max position size, max total exposure, max drawdown,
kill-switch state, etc.) and is the **final authority** — it can override any
LLM, including the PM.

On any hard-limit violation, the trade is **rejected outright** (dropped and
logged), never silently modified. The PM must propose a compliant trade or no
order is placed.

## Consequences

- LLM agents decide *what* and *whether*; this layer alone decides whether an
  order actually reaches the exchange. No agent can place an order directly.
- Rejected trades are logged for later review — a feedback signal on whether the
  agents are routinely proposing non-compliant trades.
- "Reject" can cost trades the agents wanted (vs. clamping), accepted as the
  price of predictability and safety.
- Limits live in deterministic code/config, not prompts, so they cannot be
  argued away or injected away by the LLMs.
- This is the primary architectural addition over the reference framework and
  the foundation for graduating from Paper to Live.
