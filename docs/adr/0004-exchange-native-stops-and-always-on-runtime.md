# 0004 — Exchange-native stops; always-on runtime for Live

- Status: Accepted
- Date: 2026-06-06

## Context

The decision loop runs unattended on a 4-hour cadence, on **leveraged** OKX
perpetual positions. A naive design enforces the mandatory stop-loss inside the
local Python loop (check price each cycle, close if breached). Under leverage
that is dangerous: if the process crashes, the machine sleeps/reboots, or the
network drops, the loop-enforced stop never fires and a leveraged position runs
**unprotected** — the classic way leveraged accounts get liquidated.

The runtime host is also in question: the development machine is a Windows
laptop, which sleeps, reboots, and loses connectivity — unreliable for an
unattended 4h schedule.

## Decision

1. **Stops are exchange-native.** Every position's mandatory stop-loss is placed
   as a **native stop order on OKX at entry** and lives on the exchange,
   independent of whether the local process is running. Protection does not
   depend on system uptime.
2. **Live runs on a small always-on cloud VM/VPS**, not the laptop. Local
   Windows is for **development and Paper** experimentation only.
3. **The loop is idempotent and reconcile-first** (see Reconciliation): a missed
   cycle is harmless — a closed-candle decision simply doesn't happen that bar,
   and the next cycle reconciles against OKX and catches up.

## Consequences

- Survival of an open position no longer depends on the agent being online — the
  most important operational safety property of the system.
- The Execution/Risk Layer must place (and, on exit/adjustment, cancel/replace)
  native stop orders, and reconcile their state from OKX each cycle.
- Native stop-market orders carry exchange-side behaviour (slippage on a fast
  wick, exchange downtime) that the system does not control — accepted as
  strictly safer than loop-monitored stops.
- A cloud VM adds a small fixed hosting cost and deployment/secrets-management
  surface (OKX + Anthropic keys), justified by reliable unattended operation.
- Paper can run locally; only Live requires the always-on host.
