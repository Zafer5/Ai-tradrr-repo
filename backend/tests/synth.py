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
