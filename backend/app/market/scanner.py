"""Coin tarayıcı: Binance'teki USDT paritelerinden alım-satıma uygun olanları seçer."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..exchange.types import SymbolInfo, Ticker
from ..trading_settings import TradingSettings

STABLE_BASES = {
    "USDT", "USDC", "BUSD", "FDUSD", "TUSD", "USDP", "DAI", "USDD", "AEUR", "EUR", "EURI", "UST", "USTC",
    "PYUSD", "USDE", "USD1", "XUSD", "BFUSD", "RLUSD", "USDS", "GUSD", "SUSD", "LUSD", "FRAX", "GBP", "TRY", "BRL",
}
LEVERAGED_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR")

REASON_LABELS = {
    "not_trading": "İşlem durumu TRADING değil / spot kapalı",
    "stable": "Stablecoin",
    "leveraged": "Kaldıraçlı token",
    "no_quote": "Fiyat / alış-satış verisi yok",
    "low_volume": "24s hacim düşük",
    "low_trades": "24s işlem sayısı düşük",
    "wide_spread": "Spread yüksek",
    "extreme_move": "Aşırı fiyat hareketi",
}


@dataclass
class Candidate:
    symbol: str
    base: str
    price: float
    quote_volume: float
    change_pct: float
    spread_pct: float
    trades: int

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class ScanResult:
    candidates: list[Candidate] = field(default_factory=list)
    rejected: dict[str, int] = field(default_factory=dict)
    total_pairs: int = 0
    passed_filters: int = 0
    scanned_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "candidates": [c.to_dict() for c in self.candidates],
            "rejected": {REASON_LABELS.get(k, k): v for k, v in self.rejected.items()},
            "total_pairs": self.total_pairs,
            "passed_filters": self.passed_filters,
            "scanned_at": self.scanned_at,
        }


def is_leveraged(base: str, known_bases: set[str]) -> bool:
    """BTCUP / ETHDOWN gibi kaldıraçlı tokenlar. 'JUP' gibi gerçek coinler yanlışlıkla elenmesin diye
    ek sözcüğü çıkarınca kalan kısmın ayrı bir coin olması aranır."""
    for suf in LEVERAGED_SUFFIXES:
        if base.endswith(suf) and len(base) > len(suf) and base[: -len(suf)] in known_bases:
            return True
    return False


def scan(symbols: dict[str, SymbolInfo], tickers: dict[str, Ticker], cfg: TradingSettings, quote: str = "USDT") -> ScanResult:
    res = ScanResult()
    pairs = [s for s in symbols.values() if s.quote == quote]
    known_bases = {s.base for s in pairs}
    res.total_pairs = len(pairs)

    def reject(reason: str) -> None:
        res.rejected[reason] = res.rejected.get(reason, 0) + 1

    passed: list[Candidate] = []
    for s in pairs:
        if s.status != "TRADING" or not s.spot_allowed:
            reject("not_trading")
            continue
        if cfg.exclude_stablecoins and s.base in STABLE_BASES:
            reject("stable")
            continue
        if is_leveraged(s.base, known_bases):
            reject("leveraged")
            continue
        t = tickers.get(s.symbol)
        spread = t.spread_pct if t else None
        if t is None or t.last <= 0 or spread is None:
            reject("no_quote")
            continue
        if t.quote_volume < cfg.min_quote_volume_usdt:
            reject("low_volume")
            continue
        if t.trades < cfg.min_trades_24h:
            reject("low_trades")
            continue
        if spread > cfg.max_spread_pct:
            reject("wide_spread")
            continue
        if abs(t.change_pct) > cfg.max_abs_change_pct:
            reject("extreme_move")
            continue
        passed.append(Candidate(s.symbol, s.base, t.last, t.quote_volume, t.change_pct, spread, t.trades))

    res.passed_filters = len(passed)
    passed.sort(key=lambda c: c.quote_volume, reverse=True)
    res.candidates = passed[: cfg.scan_top_n]
    return res
