"""Radar: yeni listelenen ve ilgi gören / yükselme ivmesi olan coinleri bulur.

ÖNEMLİ DÜRÜSTLÜK NOTU: Bu bir "fiyat tahmini" DEĞİLDİR. Radar yalnızca hacmi ve fiyatı
olağan dışı hareket eden coinleri listeler. Yeni listelenen ve ani yükselen coinler
en çok para kaybettiren coinlerdir (aşırı oynaklık, ani çöküş, düşük likidite).
Radar'daki coinlere bot otomatik girmez; yalnızca izleme içindir.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field

import httpx

from .exchanges.base import BookTicker, Candle, ExchangeError, MarketDataClient, SymbolInfo, Ticker24h
from .scanner import FIAT, GOLD_PEGGED, STABLECOINS, is_leveraged

COINGECKO_TRENDING = "https://api.coingecko.com/api/v3/search/trending"


@dataclass
class RadarItem:
    symbol: str
    base: str
    price: float
    change_24h: float
    change_7d: float | None
    quote_volume: float
    vol_ratio: float
    age_days: int | None          # None: 60 günden eski
    breakout: bool
    trending: bool
    score: int
    tags: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def evaluate(symbol: str, base: str, candles: list[Candle], t: Ticker24h, spread_pct: float, trending: bool) -> RadarItem | None:
    """1 günlük mumlardan ivme puanı üretir. Son (açık) gün mumu hariç tutulur."""
    closed = [c for c in candles if c.closed]
    if len(closed) < 3:
        return None
    age = len(closed) if len(candles) < 60 else None
    closes = [c.close for c in closed]
    vols = [c.quote_volume if hasattr(c, "quote_volume") else c.volume * c.close for c in closed]
    # bugünün (açık) hacmi 24s ticker'dan; ortalama kapanmış günlerden
    base_vols = vols[-8:-1] if len(vols) > 8 else vols[:-1] or vols
    avg_vol = sum(base_vols) / len(base_vols) if base_vols else 0.0
    vol_ratio = t.quote_volume / avg_vol if avg_vol > 0 else 0.0
    prior_high = max((c.high for c in closed[-21:]), default=0.0)
    breakout = t.last_price > prior_high > 0 and len(closed) >= 10
    ch7 = (t.last_price / closes[-7] - 1) * 100 if len(closes) >= 7 and closes[-7] > 0 else None
    sma20 = sum(closes[-20:]) / min(20, len(closes))
    sma20_prev = sum(closes[-21:-1]) / min(20, len(closes[-21:-1])) if len(closes) > 10 else sma20

    score = 0
    tags: list[str] = []
    warn: list[str] = []
    ch = t.price_change_pct
    if 3 <= ch <= 25:
        score += 25
        tags.append("yükseliyor")
    elif ch > 25:
        tags.append("sert yükseldi")
        warn.append(f"24 saatte %{ch:.0f} yükselmiş: geri çekilme riski çok yüksek, geç kalınmış olabilir")
    if vol_ratio >= 2:
        score += 25
        tags.append("hacim patlaması")
    elif vol_ratio >= 1.5:
        score += 15
        tags.append("hacim artıyor")
    if breakout:
        score += 20
        tags.append("20 günlük tepeyi aştı")
    if t.last_price > sma20 and sma20 > sma20_prev:
        score += 15
    if trending:
        score += 10
        tags.append("CoinGecko'da trend")
    if age is not None and age < 30:
        tags.append(f"yeni listelendi ({age} gün)")
        if vol_ratio >= 1.5:
            score += 5
        warn.append("Yeni listelenen coin: aşırı oynak, ani çöküş ve düşük likidite riski")
    if age is not None and age < 7:
        warn.append("7 günden bile yeni: fiyat geçmişi çok kısa, analiz güvenilmez")
    if spread_pct > 0.3:
        score -= 10
        warn.append(f"Alış-satış farkı yüksek (%{spread_pct:.2f})")
    return RadarItem(symbol, base, t.last_price, ch, ch7, t.quote_volume, round(vol_ratio, 2), age, breakout,
                     trending, max(0, min(100, score)), tags, warn)


async def fetch_trending(timeout: float = 10.0) -> set[str]:
    """CoinGecko ücretsiz 'trend' listesi (anahtarsız). Ulaşılamazsa boş küme döner."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.get(COINGECKO_TRENDING)
            if r.status_code != 200:
                return set()
            return {x["item"]["symbol"].upper() for x in r.json().get("coins", [])}
    except (httpx.HTTPError, ValueError, KeyError):
        return set()


async def scan_radar(client: MarketDataClient, symbols: list[SymbolInfo], tickers: list[Ticker24h],
                     books: list[BookTicker], trending: set[str], max_symbols: int = 120,
                     min_quote_volume: float = 1_000_000.0, max_spread_pct: float = 0.5) -> list[RadarItem]:
    tmap = {t.symbol: t for t in tickers}
    bmap = {b.symbol: b for b in books}
    bases = {s.base for s in symbols}
    pool = []
    for s in symbols:
        if s.quote != "USDT" or s.status != "TRADING" or not s.spot_allowed:
            continue
        if s.base in STABLECOINS or s.base in FIAT or s.base in GOLD_PEGGED or is_leveraged(s.base, bases):
            continue
        t, b = tmap.get(s.symbol), bmap.get(s.symbol)
        if not t or not b or t.last_price <= 0 or t.quote_volume < min_quote_volume or b.spread_pct > max_spread_pct:
            continue
        pool.append((s, t, b))
    # en hacimlilerden + 24s değişimi en yüksek olanlardan oluşan aday havuzu
    by_vol = sorted(pool, key=lambda x: x[1].quote_volume, reverse=True)[: max_symbols // 2]
    by_chg = sorted(pool, key=lambda x: x[1].price_change_pct, reverse=True)[: max_symbols // 2]
    chosen = {x[0].symbol: x for x in by_vol + by_chg}.values()

    async def one(x):
        s, t, b = x
        try:
            candles = await client.klines(s.symbol, "1d", 60)
        except ExchangeError:
            return None
        return evaluate(s.symbol, s.base, candles, t, b.spread_pct, s.base in trending)

    results = await asyncio.gather(*(one(x) for x in chosen))
    items = [r for r in results if r]
    items.sort(key=lambda r: r.score, reverse=True)
    return items
