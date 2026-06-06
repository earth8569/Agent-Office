from __future__ import annotations

from collections.abc import Sequence

from agent_office.models import Candle, IndicatorSnapshot, utc_now


def build_indicator_snapshot(
    symbol: str,
    candles_4h: Sequence[Candle],
    candles_1d: Sequence[Candle],
) -> IndicatorSnapshot:
    if len(candles_4h) < 60:
        raise ValueError("need at least 60 closed 4h candles")
    if len(candles_1d) < 60:
        raise ValueError("need at least 60 closed 1d candles")

    closes_4h = [candle.close for candle in candles_4h]
    closes_1d = [candle.close for candle in candles_1d]
    last = candles_4h[-1]

    sma_fast = _sma(closes_4h, 20)
    sma_slow = _sma(closes_4h, 50)
    daily_sma_fast = _sma(closes_1d, 20)
    daily_sma_slow = _sma(closes_1d, 50)
    macd, macd_signal, macd_hist = _macd(closes_4h)
    atr = _atr(candles_4h, 14)
    support = min(candle.low for candle in candles_4h[-20:])
    resistance = max(candle.high for candle in candles_4h[-20:])
    avg_volume = sum(candle.volume for candle in candles_4h[-20:]) / 20
    volume_ratio = last.volume / avg_volume if avg_volume else 0.0

    return IndicatorSnapshot(
        symbol=symbol,
        generated_at=utc_now(),
        close=last.close,
        trend=_trend(last.close, sma_fast, sma_slow),
        daily_trend=_trend(candles_1d[-1].close, daily_sma_fast, daily_sma_slow),
        sma_fast=sma_fast,
        sma_slow=sma_slow,
        rsi=_rsi(closes_4h, 14),
        macd=macd,
        macd_signal=macd_signal,
        macd_hist=macd_hist,
        atr=atr,
        support=support,
        resistance=resistance,
        volume_ratio=volume_ratio,
        volatility_pct=(atr / last.close) if last.close else 0.0,
    )


def _sma(values: Sequence[float], period: int) -> float:
    if len(values) < period:
        raise ValueError(f"need at least {period} values")
    return sum(values[-period:]) / period


def _ema_values(values: Sequence[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2 / (period + 1)
    ema = [values[0]]
    for value in values[1:]:
        ema.append((value * alpha) + (ema[-1] * (1 - alpha)))
    return ema


def _macd(values: Sequence[float]) -> tuple[float, float, float]:
    fast = _ema_values(values, 12)
    slow = _ema_values(values, 26)
    macd_series = [fast_value - slow_value for fast_value, slow_value in zip(fast, slow)]
    signal_series = _ema_values(macd_series, 9)
    macd = macd_series[-1]
    signal = signal_series[-1]
    return macd, signal, macd - signal


def _rsi(values: Sequence[float], period: int) -> float:
    if len(values) <= period:
        raise ValueError(f"need more than {period} values")
    deltas = [values[index] - values[index - 1] for index in range(1, len(values))]
    recent = deltas[-period:]
    gains = [max(delta, 0.0) for delta in recent]
    losses = [abs(min(delta, 0.0)) for delta in recent]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _atr(candles: Sequence[Candle], period: int) -> float:
    if len(candles) <= period:
        raise ValueError(f"need more than {period} candles")
    true_ranges: list[float] = []
    for index in range(1, len(candles)):
        candle = candles[index]
        previous_close = candles[index - 1].close
        true_ranges.append(
            max(
                candle.high - candle.low,
                abs(candle.high - previous_close),
                abs(candle.low - previous_close),
            )
        )
    return sum(true_ranges[-period:]) / period


def _trend(close: float, sma_fast: float, sma_slow: float) -> str:
    if close > sma_fast > sma_slow:
        return "bullish"
    if close < sma_fast < sma_slow:
        return "bearish"
    return "mixed"
