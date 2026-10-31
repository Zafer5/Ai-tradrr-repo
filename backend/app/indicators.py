"""Teknik göstergeler (saf Python; dış kütüphane gerektirmez)."""
from __future__ import annotations

import math


def ema(values: list[float], period: int) -> list[float]:
    """Üssel hareketli ortalama. İlk değer ilk `period` değerin basit ortalamasıdır.
    Yeterli veri yoksa NaN döner."""
    out = [math.nan] * len(values)
    if len(values) < period:
        return out
    k = 2 / (period + 1)
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def sma(values: list[float], period: int) -> list[float]:
    out = [math.nan] * len(values)
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= period:
            s -= values[i - period]
        if i >= period - 1:
            out[i] = s / period
    return out


def rsi(closes: list[float], period: int = 14) -> list[float]:
    """Wilder RSI."""
    out = [math.nan] * len(closes)
    if len(closes) <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    avg_g, avg_l = gains / period, losses / period

    def val(g, l):
        if l == 0:
            return 100.0 if g > 0 else 50.0
        return 100 - 100 / (1 + g / l)

    out[period] = val(avg_g, avg_l)
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        avg_g = (avg_g * (period - 1) + max(d, 0)) / period
        avg_l = (avg_l * (period - 1) + max(-d, 0)) / period
        out[i] = val(avg_g, avg_l)
    return out


def macd(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9):
    ef, es = ema(closes, fast), ema(closes, slow)
    line = [f - s if not (math.isnan(f) or math.isnan(s)) else math.nan for f, s in zip(ef, es)]
    valid = [v for v in line if not math.isnan(v)]
    sig_valid = ema(valid, signal)
    sig = [math.nan] * (len(line) - len(valid)) + sig_valid
    hist = [l - s if not (math.isnan(l) or math.isnan(s)) else math.nan for l, s in zip(line, sig)]
    return line, sig, hist


def bollinger(closes: list[float], period: int = 20, mult: float = 2.0):
    mid = sma(closes, period)
    upper, lower = [math.nan] * len(closes), [math.nan] * len(closes)
    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1 : i + 1]
        m = mid[i]
        sd = math.sqrt(sum((x - m) ** 2 for x in window) / period)
        upper[i], lower[i] = m + mult * sd, m - mult * sd
    return upper, mid, lower


def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float]:
    """Wilder ATR."""
    n = len(closes)
    out = [math.nan] * n
    if n <= period:
        return out
    trs = [highs[0] - lows[0]]
    for i in range(1, n):
        trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    prev = sum(trs[1 : period + 1]) / period
    out[period] = prev
    for i in range(period + 1, n):
        prev = (prev * (period - 1) + trs[i]) / period
        out[i] = prev
    return out


def support_resistance(highs: list[float], lows: list[float], price: float, lookback: int = 100, wing: int = 3):
    """Son `lookback` mum içindeki salınım (swing) dip/tepelerinden en yakın destek ve direnci bulur."""
    h, l = highs[-lookback:], lows[-lookback:]
    supports, resistances = [], []
    for i in range(wing, len(h) - wing):
        if h[i] == max(h[i - wing : i + wing + 1]):
            resistances.append(h[i])
        if l[i] == min(l[i - wing : i + wing + 1]):
            supports.append(l[i])
    sup = max((s for s in supports if s < price), default=min(l) if l else math.nan)
    res = min((r for r in resistances if r > price), default=max(h) if h else math.nan)
    return sup, res


def last(values: list[float]) -> float:
    return values[-1] if values else math.nan
