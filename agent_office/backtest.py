from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from agent_office.config import AppConfig
from agent_office.indicators import build_indicator_snapshot
from agent_office.models import AccountState, Candle, Position, Side, TradeIntent, utc_now
from agent_office.risk import RiskLayer
from agent_office.strategy import RuleBasedBaseline


@dataclass(frozen=True)
class BacktestTrade:
    symbol: str
    side: Side
    opened_at: datetime
    closed_at: datetime
    entry_price: float
    exit_price: float
    stop_loss: float
    notional_usdt: float
    gross_pnl_usdt: float
    fees_usdt: float
    net_pnl_usdt: float
    exit_reason: str


@dataclass(frozen=True)
class BacktestResult:
    start: datetime
    end: datetime
    symbols: tuple[str, ...]
    starting_equity_usdt: float
    ending_equity_usdt: float
    return_pct: float
    max_drawdown_pct: float
    trades: tuple[BacktestTrade, ...]
    win_rate_pct: float
    gross_pnl_usdt: float
    fees_usdt: float
    net_pnl_usdt: float
    profit_factor: float | None
    risk_rejections: dict[str, int]
    cycles: int
    equity_curve: tuple[tuple[str, float], ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class _OpenPosition:
    symbol: str
    side: Side
    entry_price: float
    stop_loss: float
    notional_usdt: float
    leverage: float
    quantity: float
    opened_at: datetime


class RuleBaselineBacktester:
    def __init__(self, config: AppConfig, fee_rate: float = 0.0005) -> None:
        if fee_rate < 0:
            raise ValueError("fee_rate cannot be negative")
        self.config = config
        self.fee_rate = fee_rate
        self.strategy = RuleBasedBaseline(config)
        self.risk_layer = RiskLayer(config.risk_limits)

    def run(
        self,
        candles_4h_by_symbol: dict[str, Sequence[Candle]],
        candles_1d_by_symbol: dict[str, Sequence[Candle]],
        start: datetime,
        end: datetime,
    ) -> BacktestResult:
        symbols = tuple(candles_4h_by_symbol)
        equity = self.config.starting_equity_usdt
        peak_equity = equity
        max_drawdown = 0.0
        daily_pnl: dict[date, float] = {}
        trades: list[BacktestTrade] = []
        equity_curve: list[tuple[str, float]] = [(start.isoformat(), equity)]
        open_positions: dict[str, _OpenPosition] = {}
        risk_rejections: dict[str, int] = {}
        cycles = 0

        by_time = self._build_4h_index(candles_4h_by_symbol, start, end)
        for candle_time in sorted(by_time):
            cycle_day = candle_time.date()
            daily_value = daily_pnl.get(cycle_day, 0.0)

            for symbol, index in by_time[candle_time]:
                candles_4h = candles_4h_by_symbol[symbol]
                candle = candles_4h[index]
                cycles += 1

                if symbol in open_positions:
                    position = open_positions[symbol]
                    if self._stop_hit(position, candle):
                        trade = self._close_trade(position, candle_time, position.stop_loss, "stop_loss")
                        trades.append(trade)
                        equity += trade.net_pnl_usdt
                        daily_value += trade.net_pnl_usdt
                        peak_equity = max(peak_equity, equity)
                        max_drawdown = max(max_drawdown, _drawdown(equity, peak_equity))
                        equity_curve.append((candle_time.isoformat(), equity))
                        del open_positions[symbol]
                        daily_pnl[cycle_day] = daily_value
                        continue

                if index < 60:
                    continue

                candles_1d = _daily_window(candles_1d_by_symbol[symbol], candle.timestamp)
                if len(candles_1d) < 60:
                    continue

                snapshot = build_indicator_snapshot(symbol, candles_4h[: index + 1], candles_1d)
                signal_account = self._account(equity, peak_equity, daily_value, open_positions)
                signal = self.strategy.decide(snapshot, signal_account)

                if symbol in open_positions and signal is not None and signal.side != open_positions[symbol].side:
                    trade = self._close_trade(open_positions[symbol], candle_time, candle.close, "opposite_signal")
                    trades.append(trade)
                    equity += trade.net_pnl_usdt
                    daily_value += trade.net_pnl_usdt
                    peak_equity = max(peak_equity, equity)
                    max_drawdown = max(max_drawdown, _drawdown(equity, peak_equity))
                    equity_curve.append((candle_time.isoformat(), equity))
                    del open_positions[symbol]
                    daily_pnl[cycle_day] = daily_value
                    continue

                if symbol in open_positions or signal is None:
                    daily_pnl[cycle_day] = daily_value
                    continue

                account = self._account(equity, peak_equity, daily_value, open_positions)
                decision = self.risk_layer.validate(signal, account)
                if not decision.accepted:
                    risk_rejections[decision.reason] = risk_rejections.get(decision.reason, 0) + 1
                    daily_pnl[cycle_day] = daily_value
                    continue

                open_positions[symbol] = _position_from_intent(signal, candle_time)
                daily_pnl[cycle_day] = daily_value

        for symbol, position in list(open_positions.items()):
            candles = [candle for candle in candles_4h_by_symbol[symbol] if _close_time(candle, "4h") <= end]
            if not candles:
                continue
            final_candle = candles[-1]
            trade = self._close_trade(position, _close_time(final_candle, "4h"), final_candle.close, "period_end")
            trades.append(trade)
            equity += trade.net_pnl_usdt
            daily_pnl[final_candle.timestamp.date()] = daily_pnl.get(final_candle.timestamp.date(), 0.0) + trade.net_pnl_usdt
            peak_equity = max(peak_equity, equity)
            max_drawdown = max(max_drawdown, _drawdown(equity, peak_equity))
            equity_curve.append((_close_time(final_candle, "4h").isoformat(), equity))

        wins = [trade for trade in trades if trade.net_pnl_usdt > 0]
        losses = [trade for trade in trades if trade.net_pnl_usdt < 0]
        gross_profit = sum(trade.net_pnl_usdt for trade in wins)
        gross_loss = abs(sum(trade.net_pnl_usdt for trade in losses))
        return BacktestResult(
            start=start,
            end=end,
            symbols=symbols,
            starting_equity_usdt=self.config.starting_equity_usdt,
            ending_equity_usdt=equity,
            return_pct=((equity / self.config.starting_equity_usdt) - 1) * 100,
            max_drawdown_pct=max_drawdown * 100,
            trades=tuple(trades),
            win_rate_pct=(len(wins) / len(trades) * 100) if trades else 0.0,
            gross_pnl_usdt=sum(trade.gross_pnl_usdt for trade in trades),
            fees_usdt=sum(trade.fees_usdt for trade in trades),
            net_pnl_usdt=equity - self.config.starting_equity_usdt,
            profit_factor=(gross_profit / gross_loss) if gross_loss else None,
            risk_rejections=risk_rejections,
            cycles=cycles,
            equity_curve=tuple(equity_curve),
        )

    def _account(
        self,
        equity: float,
        peak_equity: float,
        daily_pnl: float,
        positions: dict[str, _OpenPosition],
    ) -> AccountState:
        return AccountState(
            equity_usdt=equity,
            peak_equity_usdt=peak_equity,
            daily_pnl_usdt=daily_pnl,
            positions=tuple(_to_position(position) for position in positions.values()),
        )

    def _close_trade(
        self,
        position: _OpenPosition,
        closed_at: datetime,
        exit_price: float,
        exit_reason: str,
    ) -> BacktestTrade:
        direction = 1 if position.side == Side.LONG else -1
        gross_pnl = ((exit_price - position.entry_price) / position.entry_price) * position.notional_usdt * direction
        fees = position.notional_usdt * self.fee_rate * 2
        return BacktestTrade(
            symbol=position.symbol,
            side=position.side,
            opened_at=position.opened_at,
            closed_at=closed_at,
            entry_price=position.entry_price,
            exit_price=exit_price,
            stop_loss=position.stop_loss,
            notional_usdt=position.notional_usdt,
            gross_pnl_usdt=gross_pnl,
            fees_usdt=fees,
            net_pnl_usdt=gross_pnl - fees,
            exit_reason=exit_reason,
        )

    @staticmethod
    def _build_4h_index(
        candles_by_symbol: dict[str, Sequence[Candle]],
        start: datetime,
        end: datetime,
    ) -> dict[datetime, list[tuple[str, int]]]:
        by_time: dict[datetime, list[tuple[str, int]]] = {}
        for symbol, candles in candles_by_symbol.items():
            for index, candle in enumerate(candles):
                decision_time = _close_time(candle, "4h")
                if start <= decision_time < end:
                    by_time.setdefault(decision_time, []).append((symbol, index))
        return by_time

    @staticmethod
    def _stop_hit(position: _OpenPosition, candle: Candle) -> bool:
        if position.side == Side.LONG:
            return candle.low <= position.stop_loss
        return candle.high >= position.stop_loss


def fetch_okx_public_ohlcv(
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    limit: int = 100,
) -> list[Candle]:
    try:
        import ccxt  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("ccxt not installed. Run `python -m pip install -e .`.") from exc

    exchange = ccxt.okx({"enableRateLimit": True, "options": {"defaultType": "swap"}})
    timeframe_ms = _timeframe_ms(timeframe)
    since = _to_ms(start)
    end_ms = _to_ms(end)
    rows: list[list[float]] = []

    while since < end_ms:
        batch = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=limit)
        if not batch:
            break
        rows.extend(batch)
        next_since = int(batch[-1][0]) + timeframe_ms
        if next_since <= since:
            break
        since = next_since
        if int(batch[-1][0]) >= end_ms:
            break

    deduped = {int(row[0]): row for row in rows if _to_ms(start) <= int(row[0]) < end_ms}
    return [_parse_ohlcv(row) for row in sorted(deduped.values(), key=lambda row: int(row[0]))]


def load_or_fetch_okx_public_ohlcv(
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    cache_dir: Path = Path("data/ohlcv_cache"),
) -> list[Candle]:
    path = ohlcv_cache_path(cache_dir, symbol, timeframe, start, end)
    if path.exists():
        return read_ohlcv_csv(path)

    candles = fetch_okx_public_ohlcv(symbol, timeframe, start, end)
    write_ohlcv_csv(path, candles)
    return candles


def ohlcv_cache_path(
    cache_dir: Path,
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
) -> Path:
    safe_symbol = symbol.replace("/", "-").replace(":", "-")
    filename = f"{safe_symbol}_{timeframe}_{start.date()}_{end.date()}.csv"
    return cache_dir / filename


def read_ohlcv_csv(path: Path) -> list[Candle]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [
            Candle(
                timestamp=datetime.fromisoformat(row["timestamp"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
            for row in csv.DictReader(handle)
        ]


def write_ohlcv_csv(path: Path, candles: Sequence[Candle]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        for candle in candles:
            writer.writerow(
                {
                    "timestamp": candle.timestamp.isoformat(),
                    "open": candle.open,
                    "high": candle.high,
                    "low": candle.low,
                    "close": candle.close,
                    "volume": candle.volume,
                }
            )

def parse_utc_date(value: str) -> datetime:
    parsed = date.fromisoformat(value)
    return datetime.combine(parsed, time.min, tzinfo=timezone.utc)


def warmup_start(start: datetime) -> datetime:
    return start - timedelta(days=90)


def result_summary(result: BacktestResult, trade_limit: int = 12) -> dict[str, Any]:
    return {
        "period": {
            "start": result.start.isoformat(),
            "end_exclusive": result.end.isoformat(),
        },
        "symbols": list(result.symbols),
        "starting_equity_usdt": round(result.starting_equity_usdt, 2),
        "ending_equity_usdt": round(result.ending_equity_usdt, 2),
        "return_pct": round(result.return_pct, 2),
        "max_drawdown_pct": round(result.max_drawdown_pct, 2),
        "trades": len(result.trades),
        "win_rate_pct": round(result.win_rate_pct, 2),
        "gross_pnl_usdt": round(result.gross_pnl_usdt, 2),
        "fees_usdt": round(result.fees_usdt, 2),
        "net_pnl_usdt": round(result.net_pnl_usdt, 2),
        "profit_factor": None if result.profit_factor is None else round(result.profit_factor, 2),
        "risk_rejections": result.risk_rejections,
        "cycles": result.cycles,
        "equity_curve": [{"time": point[0], "equity": round(point[1], 2)} for point in result.equity_curve],
        "sample_trades": [
            {
                "symbol": trade.symbol,
                "side": trade.side.value,
                "opened_at": trade.opened_at.isoformat(),
                "closed_at": trade.closed_at.isoformat(),
                "entry": round(trade.entry_price, 4),
                "exit": round(trade.exit_price, 4),
                "net_pnl_usdt": round(trade.net_pnl_usdt, 2),
                "exit_reason": trade.exit_reason,
            }
            for trade in result.trades[:trade_limit]
        ],
    }


def _position_from_intent(intent: TradeIntent, opened_at: datetime) -> _OpenPosition:
    return _OpenPosition(
        symbol=intent.symbol,
        side=intent.side,
        entry_price=intent.entry_price,
        stop_loss=intent.stop_loss,
        notional_usdt=intent.notional_usdt,
        leverage=intent.leverage,
        quantity=intent.notional_usdt / intent.entry_price,
        opened_at=opened_at,
    )


def _to_position(position: _OpenPosition) -> Position:
    return Position(
        symbol=position.symbol,
        side=position.side,
        entry_price=position.entry_price,
        stop_loss=position.stop_loss,
        notional_usdt=position.notional_usdt,
        leverage=position.leverage,
        quantity=position.quantity,
        opened_at=position.opened_at,
        stop_order_id="backtest-stop",
    )


def _daily_window(candles: Sequence[Candle], timestamp: datetime) -> list[Candle]:
    return [candle for candle in candles if _close_time(candle, "1d") <= timestamp]


def _close_time(candle: Candle, timeframe: str) -> datetime:
    if timeframe == "4h":
        return candle.timestamp + timedelta(hours=4)
    if timeframe == "1d":
        return candle.timestamp + timedelta(days=1)
    raise ValueError(f"unsupported timeframe: {timeframe}")


def _drawdown(equity: float, peak_equity: float) -> float:
    if peak_equity <= 0:
        return 0.0
    return max(0.0, 1 - (equity / peak_equity))


def _timeframe_ms(timeframe: str) -> int:
    if timeframe == "4h":
        return 4 * 60 * 60 * 1000
    if timeframe == "1d":
        return 24 * 60 * 60 * 1000
    raise ValueError(f"unsupported timeframe: {timeframe}")


def _to_ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def _parse_ohlcv(row: Sequence[float]) -> Candle:
    return Candle(
        timestamp=datetime.fromtimestamp(float(row[0]) / 1000, tz=timezone.utc),
        open=float(row[1]),
        high=float(row[2]),
        low=float(row[3]),
        close=float(row[4]),
        volume=float(row[5]),
    )
