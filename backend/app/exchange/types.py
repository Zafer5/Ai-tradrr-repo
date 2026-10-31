from __future__ import annotations

from dataclasses import dataclass

import numpy as np

INTERVAL_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


@dataclass(frozen=True)
class SymbolInfo:
    symbol: str
    base: str
    quote: str
    status: str
    spot_allowed: bool
    tick_size: float = 0.0
    step_size: float = 0.0
    min_qty: float = 0.0
    min_notional: float = 0.0


@dataclass(frozen=True)
class Ticker:
    symbol: str
    last: float
    bid: float
    ask: float
    quote_volume: float
    change_pct: float
    trades: int

    @property
    def spread_pct(self) -> float | None:
        if self.bid <= 0 or self.ask <= 0 or self.ask < self.bid:
            return None
        mid = (self.bid + self.ask) / 2
        return (self.ask - self.bid) / mid * 100


@dataclass
class Candles:
    """Mum verisi (sütun dizileri). Zamanlar milisaniye cinsindendir."""

    open_time: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    close_time: np.ndarray

    def __len__(self) -> int:
        return len(self.close)

    def closed(self, now_ms: int) -> "Candles":
        """Henüz kapanmamış (oluşmakta olan) mumu çıkarır. Analiz yalnızca kapanmış mumlarla yapılır."""
        mask = self.close_time < now_ms
        return Candles(*(a[mask] for a in (self.open_time, self.open, self.high, self.low, self.close, self.volume, self.close_time)))

    @classmethod
    def from_klines(cls, rows: list[list]) -> "Candles":
        if not rows:
            e = np.array([], dtype=float)
            return cls(e.astype("int64"), e, e, e, e, e, e.astype("int64"))
        return cls(
            open_time=np.array([int(r[0]) for r in rows], dtype="int64"),
            open=np.array([float(r[1]) for r in rows]),
            high=np.array([float(r[2]) for r in rows]),
            low=np.array([float(r[3]) for r in rows]),
            close=np.array([float(r[4]) for r in rows]),
            volume=np.array([float(r[5]) for r in rows]),
            close_time=np.array([int(r[6]) for r in rows], dtype="int64"),
        )
