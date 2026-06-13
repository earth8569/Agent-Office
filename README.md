# Agent Office

Paper-first AI crypto trading office.

Current build is dependency-light Python core:

- deterministic indicator snapshot from 4h + 1d OHLCV
- rule-based baseline over same snapshot planned for LLM agents
- deterministic risk layer as final authority
- SQLite audit/position/equity store
- paper execution adapter with simulated exchange-native stop ID
- smoke CLI and stdlib tests

## Commands

```powershell
python -m unittest discover -s tests
python -m agent_office.cli init --db data\paper.sqlite
python -m agent_office.cli smoke-cycle --db data\paper.sqlite
python -m agent_office.cli web --db data\paper.sqlite
python -m agent_office.cli backtest --start 2026-01-01 --end 2026-04-01 --cache-dir data\ohlcv_cache
```

Backtest OHLCV CSV files are cached in `data/ohlcv_cache` so repeat runs do not refetch candles. SQLite runtime databases stay local under `data/*.sqlite`.

Open `http://127.0.0.1:8787` for the operator console. It shows each recorded
agent/runtime/risk/execution action from the SQLite audit log and refreshes
every 5 seconds.

## OKX Demo Integration

Install deps first:

```powershell
python -m pip install -e .
```

Set rotated demo credentials in your shell or a local `.env` loader. `.env` is
gitignored.

Run read-only OKX demo tests:

```powershell
$env:RUN_OKX_DEMO_TESTS = "1"
$env:OKX_DEMO = "1"
python -m unittest tests.test_okx_demo_integration -v
```

These tests fetch closed candles, balance, positions, open stop/algo orders, and
run reconciliation. They do not place orders.

## Current Boundary

`OkxDemoAdapter` is read-only for now. `OkxExecutionAdapter` still does not place
orders. LangGraph/LLM agents should plug in above `RiskLayer`; no agent should
call an execution adapter directly.
