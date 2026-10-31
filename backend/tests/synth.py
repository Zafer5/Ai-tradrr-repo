"""Test için SENTETİK mum üretici (yalnızca testlerde kullanılır; ürün kodunda yoktur)."""
from __future__ import annotations

import numpy as np

from app.exchange.types import INTERVAL_MS, Candles


def make_candles(n: int, interval: str = "1h", drift: float = 0.0, vol: float = 0.004, seed: int = 1,
                 start_price: float = 100.0, end_ms: int | None = None, base_volume: float = 1000.0,
                 vol_trend: float = 0.0) -> Candles:
    """Log-getirisi ~ N(drift, vol) olan rastgele yürüyüş. Son mumun KAPANIŞ zamanı ``end_ms``'dir."""
    rng = np.random.default_rng(seed)
    step = INTERVAL_MS[interval]
    end_ms = end_ms if end_ms is not None else 1_700_000_000_000
    rets = rng.normal(drift, vol, n)
    close = start_price * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[start_price], close[:-1]])
    wick = np.abs(rng.normal(0, vol / 2, n))
    high = np.maximum(open_, close) * (1 + wick)
    low = np.minimum(open_, close) * (1 - wick)
    volume = base_volume * (1 + vol_trend * np.arange(n) / n) * (1 + np.abs(rng.normal(0, 0.3, n)))
    close_time = end_ms - (n - 1 - np.arange(n)) * step
    open_time = close_time - step + 1
    return Candles(open_time.astype("int64"), open_, high, low, close, volume, close_time.astype("int64"))


def make_multi_tf(days: float, drift_per_hour: float = 0.0, vol_per_sqrt_hour: float = 0.004, seed: int = 1,
                  start_price: float = 100.0, end_ms: int = 1_700_000_000_000 // 14_400_000 * 14_400_000) -> dict[str, Candles]:
    """Tutarlı çok zaman dilimli veri: 5dk mumlar üretilip 15dk/1sa/4sa'e BİRLEŞTİRİLİR (aynı fiyat yolu)."""
    n5 = int(days * 288)
    n5 -= n5 % 48  # 4sa sınırına hizala
    c5 = make_candles(n5, "5m", drift=drift_per_hour / 12, vol=vol_per_sqrt_hour / (12 ** 0.5), seed=seed,
                      start_price=start_price, end_ms=end_ms - 1)
    out = {"5m": c5}
    for tf, k in (("15m", 3), ("1h", 12), ("4h", 48)):
        m = n5 // k
        sl = lambda a: a[: m * k].reshape(m, k)  # noqa: E731
        out[tf] = Candles(
            open_time=sl(c5.open_time)[:, 0], open=sl(c5.open)[:, 0], high=sl(c5.high).max(axis=1), low=sl(c5.low).min(axis=1),
            close=sl(c5.close)[:, -1], volume=sl(c5.volume).sum(axis=1), close_time=sl(c5.close_time)[:, -1],
        )
    return out
