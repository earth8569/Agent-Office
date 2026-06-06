# 0001 — OKX as the venue for leveraged crypto trading

- Status: Accepted
- Date: 2026-06-06

## Context

The system trades crypto on a swing-trading horizon and requires **leverage**.
The operator is based in Thailand, so the obvious first candidate was **Binance
Thailand (Gulf Binance)**. Investigation surfaced a three-way conflict between
*venue*, *leverage*, and *clean API/tooling*:

- **Binance Thailand** is a separate, Thai-SEC-licensed entity, effectively
  **spot only** — Thai SEC restricts retail crypto derivatives, so the required
  leverage is not offered. CCXT support for it was only *proposed* (Aug 2025),
  the Thai API differs from global, and completion is unconfirmed.
- **Global Binance Futures** offers the leverage but is **geo-restricted for
  Thai residents**, with public Thai SEC warnings against its use.
- The requirement that actually anchors the design is **leverage**, not the
  specific venue.

## Decision

Use **OKX** as the trading venue. OKX provides leveraged perpetual products, a
**demo-trading** environment (used as Paper mode), and mature **CCXT** support,
preserving the Paper→Live "adapter swap" story.

The legality/jurisdiction of accessing OKX is the **operator's responsibility**,
not a concern the system encodes or enforces.

## Consequences

- The Execution / Risk Layer must handle derivatives concerns: leverage,
  liquidation, funding rates, and margin — more surface area than spot.
- Paper mode maps to OKX demo trading; Live mode to OKX live, ideally a CCXT
  adapter swap.
- If OKX becomes unavailable to the operator, the venue must be re-chosen; the
  CCXT abstraction limits but does not eliminate that cost (derivatives symbol
  conventions and margin semantics vary by exchange).
- We are knowingly outside the Thai-regulated path; this is an operator-accepted
  risk, revisited if a licensed Thai venue ever offers the required leverage.
