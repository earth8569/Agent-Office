# Agent Office

Paper-first AI crypto trading office.

Current build is dependency-light Python core:

- deterministic indicator snapshot from 4h + 1d OHLCV
- rule-based baseline over same snapshot planned for LLM agents
- deterministic risk layer as final authority
- SQLite audit/position/equity store
- paper execution adapter with simulated exchange-native stop ID
- smoke CLI and stdlib tests

## Dashboard Shortcut

Double-click `start-dashboard.bat` to start the local Pixel Agent dashboard with `config/agent-office.toml` and open the browser. Keep that window open while testing. Double-click `stop-dashboard.bat` to stop the dashboard server.
## Commands

```powershell
python -m unittest discover -s tests
python -m agent_office.cli init --config config\agent-office.toml
python -m agent_office.cli smoke-cycle --config config\agent-office.toml
python -m agent_office.cli web --config config\agent-office.toml
python -m agent_office.cli backtest --config config\agent-office.toml --start 2026-01-01 --end 2026-04-01 --cache-dir data\ohlcv_cache
```

Runtime symbols and risk settings live in `config/agent-office.toml`. To test a different coin set without editing the default file, either pass `--config path\to\other.toml` or set `$env:AGENT_OFFICE_CONFIG = "path\to\other.toml"`.

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
## Telegram alerts

Set these in `.env` to receive a Telegram alert when the dashboard agent workflow stops after a scan or fails:

```env
TELEGRAM_BOT_TOKEN=123456:your-bot-token
TELEGRAM_CHAT_ID=123456789
AGENT_OFFICE_DASHBOARD_URL=http://127.0.0.1:8787/reports/grid_pixel_dashboard.html
```

If Telegram values are empty, the alert call is recorded in SQLite but no Telegram message is sent. The Telegram restart button opens `AGENT_OFFICE_DASHBOARD_URL?autostart=1`; use a public/tunnel URL if opening from a phone.
