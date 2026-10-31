"""Tek seferlik canlı tarama ve analiz testi.

Kullanım (sunucuda):  docker compose run --rm trader python -m app.scan_once
Binance'e bağlanır, uygun coinleri listeler ve ilk 5 coini analiz eder. Emir göndermez.
"""
import asyncio

from .analysis import TIMEFRAMES, Analyzer, TargetSettings
from .config import settings
from .exchanges.binance import BinanceClient
from .scanner import ScanFilters, scan


async def main() -> None:
    c = BinanceClient(settings.binance_rest_url)
    try:
        await c.ping()
        print("✓ Binance bağlantısı başarılı")
        symbols, tickers, books = await asyncio.gather(c.symbols(), c.tickers_24h(), c.book_tickers())
        ok, rejected = scan(symbols, tickers, books, ScanFilters())
        print(f"✓ {len(ok)} coin seçildi, {len(rejected)} coin elendi\n")
        for i, r in enumerate(ok, 1):
            print(f"{i:>2}. {r.symbol:<14} fiyat {r.price:<12.6g} hacim {r.quote_volume/1e6:>8.1f} M$  spread %{r.spread_pct:.3f}")
        print("\nİlk 5 coin analiz ediliyor...\n")
        an = Analyzer()
        for r in ok[:5]:
            data = dict(zip(TIMEFRAMES, await asyncio.gather(*(c.klines(r.symbol, tf, 250) for tf in TIMEFRAMES))))
            a = an.analyze(r.symbol, data, TargetSettings())
            print(f"{a.symbol}: puan {a.score} ({a.label}), trend {a.trend}, risk {a.risk_level}")
            for x in a.reasons:
                print("   +", x)
            for x in a.warnings:
                print("   !", x)
    finally:
        await c.close()


if __name__ == "__main__":
    asyncio.run(main())
