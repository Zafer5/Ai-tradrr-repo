"""Testler için yardımcılar. Buradaki sahte istemci YALNIZCA otomatik testlerde kullanılır;
uygulama her zaman gerçek Binance verisiyle çalışır."""
import math
import time

from app.exchanges.base import BookTicker, Candle, MarketDataClient, SymbolInfo, Ticker24h

TF_MS = {"5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}


def make_candles(n: int, start: float, drift: float, tf: str = "1h", wave: float = 0.004, vol_last: float = 1.0):
    """Hafif dalgalı, belirli eğilimli mum dizisi üretir. Son mum kapanmış sayılır."""
    ms = TF_MS[tf]
    now = int(time.time() * 1000) - ms  # tüm mumlar geçmişte kapanmış
    out, price = [], start
    for i in range(n):
        o = price
        c = o * (1 + drift + wave * math.sin(i / 3))
        h, l = max(o, c) * 1.002, min(o, c) * 0.998
        t0 = now - (n - i) * ms
        vol = 100.0 * (vol_last if i == n - 1 else 1.0)
        out.append(Candle(t0, o, h, l, c, vol, t0 + ms - 1, True))
        price = c
    return out


class FakeClient(MarketDataClient):
    name = "fake"

    def __init__(self):
        self.price = {"AAAUSDT": 10.0}
        self.drift = 0.001
        self.fail_book = False

    async def symbols(self):
        return [SymbolInfo("AAAUSDT", "AAA", "USDT", "TRADING", True, step_size=0.001, tick_size=0.0001, min_notional=5, min_qty=0.001)]

    async def tickers_24h(self):
        return [Ticker24h("AAAUSDT", self.price["AAAUSDT"], 2.0, 50_000_000, 100_000, 11, 9)]

    async def book_tickers(self):
        return [await self.book_ticker("AAAUSDT")]

    async def book_ticker(self, symbol):
        if self.fail_book:
            from app.exchanges.base import ExchangeError
            raise ExchangeError("test bağlantı hatası")
        p = self.price[symbol]
        return BookTicker(symbol, p * 0.9999, p * 1.0001)

    async def klines(self, symbol, interval, limit=250):
        c = make_candles(limit, 5.0, self.drift, interval, vol_last=2.5)
        k = self.price[symbol] / c[-1].close  # son kapanış güncel fiyata eşit olsun
        for x in c:
            x.open, x.high, x.low, x.close = x.open * k, x.high * k, x.low * k, x.close * k
        return c

    async def close(self):
        pass
