# 0003 — Hybrid: deterministic indicators, LLMs only at the judgment layer

- Status: Accepted
- Date: 2026-06-06

## Context

The system was scoped to be **purely technical** — its only input is OHLCV price
data (ADR-adjacent decision; no news/sentiment/fundamental/on-chain feeds). That
choice removed the main thing LLMs are uniquely good at: synthesising ambiguous,
unstructured information (narrative, news, sentiment). Technical analysis on
price data is numeric and rule-expressible — work that deterministic code does
more cheaply, exactly, and reproducibly than an LLM.

At the same time, cost analysis (verified 2026-06-06) showed running LLMs over
raw charts for every cycle is ~$360/mo for live Paper and ~$4.4K per full-year
backtest on Opus — and Opus 4.8's Jan-2026 knowledge cutoff makes pre-cutoff
backtests unreliable (lookahead/memorisation bias). Spending heavily to have an
LLM re-derive RSI/MACD/levels it can't compute reliably anyway is poor value.

Three options were weighed: **pure Python** (no LLM — a classic quant TA bot),
**full LLM office** (LLM sub-analysts read raw charts), and a **hybrid**.

## Decision

Build the **hybrid**:

- A deterministic **Indicator Engine** (Python; e.g. pandas-ta/TA-Lib) computes
  all technical features (trend, momentum, support/resistance, volume/
  volatility) on 4h + 1D into a structured **indicator snapshot**. No LLM, no
  token cost, exact and reproducible.
- The **LLM judgment layer** (Bull/Bear debate → Research Manager → Trader →
  Risk Manager → Portfolio Manager) operates **on the indicator snapshot**, not
  on raw charts. This is the only place tokens are spent.
- The deterministic **Execution/Risk Layer** (ADR 0002) remains the final
  authority below the Portfolio Manager.

## Consequences

- Token cost drops sharply versus full-LLM, because the LLMs reason over a
  compact structured snapshot rather than raw OHLCV, and do no numeric work.
- Indicators are deterministic and free, so the **Indicator Engine alone is
  fully, cheaply backtestable over real history with no lookahead bias** — only
  the LLM judgment layer carries the bias/cost caveats.
- This gives a natural baseline: a **pure-rule strategy over the same indicator
  snapshot** can be A/B'd against the LLM judgment layer. If the LLMs don't beat
  plain rules, that is a clear, cheap signal.
- The "office" keeps its identity (debate + judgment by LLMs) while the numeric
  analyst pool is now deterministic code — a future reader should expect the
  analysts to be Python, not LLMs.
- LLM agents still decide *what* and *whether*; deterministic code computes the
  evidence and enforces the limits.
