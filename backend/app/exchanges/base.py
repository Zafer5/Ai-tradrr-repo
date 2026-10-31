"""Borsa bağlantıları için ortak arayüz.

Binance dışında Bitget veya Paribu eklenirken aynı arayüz uygulanır; diğer
modüller (tarayıcı, analiz, motor) borsanın hangisi olduğunu bilmez.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class SymbolInfo:
    symbol: str
    base: str
    quote: str
    status: str
    spot_allowed: bool
    step_size: float = 0.0
    tick_size: float = 0.0
    min_notional: float = 0.0
    min_qty: float = 0.0


@dataclass
class Ticker24h:
    symbol: str
    last_price: float
    price_change_pct: float
    quote_volume: float
    trade_count: int
    high: float
    low: float


@dataclass
class BookTicker:
    symbol: str
    bid: float
    ask: float

    @property
    def spread_pct(self) -> float:
        if self.bid <= 0 or self.ask <= 0:
            return 100.0
        mid = (self.bid + self.ask) / 2
        return (self.ask - self.bid) / mid * 100


@dataclass
class Candle:
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int
    closed: bool = True


@dataclass
class PriceUpdate:
    symbol: str
    price: float
    ts: float = field(default=0.0)


class ExchangeError(Exception):
    """Borsadan gelen veya bağlantı kaynaklı hata."""


class MarketDataClient(ABC):
    name: str

    @abstractmethod
    async def symbols(self) -> list[SymbolInfo]: ...

    @abstractmethod
    async def tickers_24h(self) -> list[Ticker24h]: ...

    @abstractmethod
    async def book_tickers(self) -> list[BookTicker]: ...

    @abstractmethod
    async def book_ticker(self, symbol: str) -> BookTicker: ...

    @abstractmethod
    async def klines(self, symbol: str, interval: str, limit: int = 250) -> list[Candle]: ...

    @abstractmethod
    async def close(self) -> None: ...
