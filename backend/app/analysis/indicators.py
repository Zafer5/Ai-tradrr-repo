"""Teknik göstergeler (yalnızca numpy). Hepsi 'nedensel'dir: i. mumdaki değer yalnızca i ve öncesine bağlıdır
(gelecek veri sızıntısı yoktur - backtest için kritik)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..exchange.types import Candles


def ema(values: np.ndarray, n: int) -> np.ndarray:
    v = np.asarray(values, dtype=float)
    out = np.full(v.shape, np.nan)
    if len(v) < n:
        return out
    a = 2.0 / (n + 1)
    out[n - 1] = v[:n].mean()
    for i in range(n, len(v)):
        out[i] = a * v[i] + (1 - a) * out[i - 1]
    return out


def _ema_valid(values: np.ndarray, n: int) -> np.ndarray:
    """Başında NaN bulunan diziler için EMA."""
    out = np.full(values.shape, np.nan)
    valid = np.flatnonzero(~np.isnan(values))
    if len(valid):
        s = valid[0]
        out[s:] = ema(values[s:], n)
    return out


def rsi(close: np.ndarray, n: int = 14) -> np.ndarray:
    out = np.full(close.shape, np.nan)
    if len(close) <= n:
        return out
    d = np.diff(close)
    gain = np.where(d > 0, d, 0.0)
    loss = np.where(d < 0, -d, 0.0)
    ag, al = gain[:n].mean(), loss[:n].mean()

    def val(ag, al):
        return 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)

    out[n] = val(ag, al)
    for i in range(n, len(d)):
        ag = (ag * (n - 1) + gain[i]) / n
        al = (al * (n - 1) + loss[i]) / n
        out[i + 1] = val(ag, al)
    return out


def macd(close: np.ndarray, fast=12, slow=26, sig=9):
    line = ema(close, fast) - ema(close, slow)
    signal = _ema_valid(line, sig)
    return line, signal, line - signal


def bollinger(close: np.ndarray, n: int = 20, k: float = 2.0):
    mid = np.full(close.shape, np.nan)
    sd = np.full(close.shape, np.nan)
    if len(close) >= n:
        w = np.lib.stride_tricks.sliding_window_view(close, n)
        mid[n - 1 :] = w.mean(axis=1)
        sd[n - 1 :] = w.std(axis=1)
    return mid, mid + k * sd, mid - k * sd


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int = 14) -> np.ndarray:
    out = np.full(close.shape, np.nan)
    if len(close) <= n:
        return out
    pc = close[:-1]
    tr = np.maximum.reduce([high[1:] - low[1:], np.abs(high[1:] - pc), np.abs(low[1:] - pc)])
    a = tr[:n].mean()
    out[n] = a
    for i in range(n, len(tr)):
        a = (a * (n - 1) + tr[i]) / n
        out[i + 1] = a
    return out


def volume_ratio(volume: np.ndarray, n: int = 20) -> np.ndarray:
    """Mum hacminin, kendisinden ÖNCEKİ n mumun ortalamasına oranı."""
    out = np.full(volume.shape, np.nan)
    if len(volume) > n:
        w = np.lib.stride_tricks.sliding_window_view(volume, n).mean(axis=1)  # w[j] = mean(volume[j:j+n])
        prev_mean = w[: len(volume) - n]  # i = n+j için mean(volume[j:j+n])
        with np.errstate(divide="ignore", invalid="ignore"):
            out[n:] = np.where(prev_mean > 0, volume[n:] / prev_mean, np.nan)
    return out


def support_resistance(high: np.ndarray, low: np.ndarray, close: np.ndarray, i: int, window: int = 5, lookback: int = 120):
    """Yalnızca i'ye kadar OLUŞMUŞ ve onaylanmış pivotlardan en yakın destek/direnç.
    Pivot, sağında 'window' mum onaylanınca geçerli olur => gelecek verisi kullanılmaz."""
    px = close[i]
    start = max(window, i - lookback)
    res_levels, sup_levels = [], []
    for k in range(start, i - window + 1):
        if high[k] >= high[k - window : k + window + 1].max():
            res_levels.append(high[k])
        if low[k] <= low[k - window : k + window + 1].min():
            sup_levels.append(low[k])
    above = [r for r in res_levels if r > px]
    below = [s for s in sup_levels if s < px]
    resistance = min(above) if above else None
    support = max(below) if below else None
    if resistance is None:
        hh = high[max(0, i - lookback) : i + 1].max()
        resistance = hh if hh > px else None
    if support is None:
        ll = low[max(0, i - lookback) : i + 1].min()
        support = ll if ll < px else None
    return support, resistance


@dataclass
class IndicatorSet:
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    close_time: np.ndarray
    ema9: np.ndarray
    ema21: np.ndarray
    ema50: np.ndarray
    ema200: np.ndarray
    rsi: np.ndarray
    macd: np.ndarray
    macd_signal: np.ndarray
    macd_hist: np.ndarray
    bb_mid: np.ndarray
    bb_up: np.ndarray
    bb_low: np.ndarray
    atr: np.ndarray
    vol_ratio: np.ndarray


def compute_indicators(c: Candles) -> IndicatorSet:
    m, s, h = macd(c.close)
    bm, bu, bl = bollinger(c.close)
    return IndicatorSet(
        open=c.open, high=c.high, low=c.low, close=c.close, volume=c.volume, close_time=c.close_time,
        ema9=ema(c.close, 9), ema21=ema(c.close, 21), ema50=ema(c.close, 50), ema200=ema(c.close, 200),
        rsi=rsi(c.close), macd=m, macd_signal=s, macd_hist=h,
        bb_mid=bm, bb_up=bu, bb_low=bl,
        atr=atr(c.high, c.low, c.close), vol_ratio=volume_ratio(c.volume),
    )
