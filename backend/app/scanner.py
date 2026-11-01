"""Coin tarayıcı: işlem yapılabilir, likit USDT paritelerini seçer."""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict

from .exchanges.base import BookTicker, SymbolInfo, Ticker24h

STABLECOINS = {
    "USDT", "USDC", "BUSD", "TUSD", "FDUSD", "DAI", "USDP", "PAX", "USDD", "UST", "USTC",
    "PYUSD", "USDE", "USD1", "AEUR", "EURI", "XUSD", "BFUSD", "RLUSD", "USDS", "FRAX", "GUSD",
}
FIAT = {"EUR", "TRY", "GBP", "BRL", "AUD", "RUB", "UAH", "NGN", "ZAR", "IDRT", "BIDR", "ARS", "JPY", "MXN", "PLN", "RON", "COP", "CZK"}
GOLD_PEGGED = {"PAXG", "XAUT"}
LEVERAGED_RE = re.compile(r"^([A-Z0-9]+)(UP|DOWN|BULL|BEAR)$")


@dataclass
class ScanFilters:
    quote: str = "USDT"
    max_coins: int = 50
    min_quote_volume: float = 5_000_000.0   # 24 saatlik USDT hacmi
    max_spread_pct: float = 0.15            # alış-satış farkı yüzdesi
    min_trade_count: int = 5_000            # 24 saatte en az işlem sayısı
    exclude_stablecoins: bool = True
    exclude_leveraged: bool = True
    include_radar: bool = False             # Radar'daki en iyi birkaç eski coini de analiz et (yeni listelenenler hariç)
    radar_extra: int = 5


@dataclass
class ScanResult:
    symbol: str
    base: str
    price: float
    change_pct: float
    quote_volume: float
    spread_pct: float
    trade_count: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Rejection:
    symbol: str
    reason: str


def is_leveraged(base: str, all_bases: set[str]) -> bool:
    m = LEVERAGED_RE.match(base)
    return bool(m and m.group(1) in all_bases and len(m.group(1)) >= 2)


def scan(
    symbols: list[SymbolInfo],
    tickers: list[Ticker24h],
    books: list[BookTicker],
    f: ScanFilters,
) -> tuple[list[ScanResult], list[Rejection]]:
    tmap = {t.symbol: t for t in tickers}
    bmap = {b.symbol: b for b in books}
    all_bases = {s.base for s in symbols}
    ok: list[ScanResult] = []
    rejected: list[Rejection] = []
    for s in symbols:
        if s.quote != f.quote:
            continue
        if s.status != "TRADING" or not s.spot_allowed:
            rejected.append(Rejection(s.symbol, "İşleme kapalı veya kısıtlı"))
            continue
        if f.exclude_stablecoins and (s.base in STABLECOINS or s.base in FIAT or s.base in GOLD_PEGGED):
            rejected.append(Rejection(s.symbol, "Stablecoin / sabit değerli varlık"))
            continue
        if f.exclude_leveraged and is_leveraged(s.base, all_bases):
            rejected.append(Rejection(s.symbol, "Kaldıraçlı token"))
            continue
        t, b = tmap.get(s.symbol), bmap.get(s.symbol)
        if t is None or b is None or t.last_price <= 0:
            rejected.append(Rejection(s.symbol, "Güvenilir fiyat verisi yok"))
            continue
        if t.quote_volume < f.min_quote_volume:
            rejected.append(Rejection(s.symbol, f"Düşük hacim ({t.quote_volume:,.0f} USDT)"))
            continue
        if t.trade_count < f.min_trade_count:
            rejected.append(Rejection(s.symbol, f"Az işlem ({t.trade_count})"))
            continue
        if b.spread_pct > f.max_spread_pct:
            rejected.append(Rejection(s.symbol, f"Yüksek spread (%{b.spread_pct:.3f})"))
            continue
        ok.append(ScanResult(s.symbol, s.base, t.last_price, t.price_change_pct, t.quote_volume, b.spread_pct, t.trade_count))
    ok.sort(key=lambda r: r.quote_volume, reverse=True)
    return ok[: f.max_coins], rejected
