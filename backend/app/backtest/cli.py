"""Komut satırından backtest:   python -m app.backtest.cli BTCUSDT --days 120

Binance'ten geçmiş mumları indirir (API anahtarı GEREKMEZ), eğitim/test ayrımıyla çalıştırır ve Türkçe rapor yazar.
"""
from __future__ import annotations

import argparse
import asyncio
import time

import numpy as np

from ..config import get_config
from ..exchange.binance import BinanceClient
from ..exchange.types import INTERVAL_MS, Candles
from ..trading_settings import TradingSettings
from .engine import walk_forward


async def fetch_history(client: BinanceClient, symbol: str, interval: str, days: int, warmup_bars: int = 260) -> Candles:
    step = INTERVAL_MS[interval]
    end = int(time.time() * 1000)
    start = end - days * 86_400_000 - warmup_bars * step
    parts: list[Candles] = []
    cursor = start
    while cursor < end:
        c = await client.klines(symbol, interval, 1000, start=cursor)
        if len(c) == 0:
            break
        parts.append(c)
        cursor = int(c.close_time[-1]) + 1
        if len(c) < 1000:
            break
    cat = lambda name: np.concatenate([getattr(p, name) for p in parts])  # noqa: E731
    out = Candles(*(cat(n) for n in ("open_time", "open", "high", "low", "close", "volume", "close_time")))
    return out.closed(end)


def fmt(m: dict) -> str:
    def f(x, nd=2, suf=""):
        return "-" if x is None else f"{x:.{nd}f}{suf}"

    return (
        f"  İşlem sayısı        : {m['trades']}\n"
        f"  Net getiri          : %{f(m['net_return_pct'])}  ({f(m['net_pnl'])} USDT)\n"
        f"  Kazanç oranı        : %{f(m['win_rate'], 1)}   (tek başına başarı ölçütü değildir)\n"
        f"  Ort. kazanç/kayıp   : {f(m['avg_win'])} / {f(m['avg_loss'])}  -> risk/getiri {f(m['risk_reward'])}\n"
        f"  Profit factor       : {f(m['profit_factor'])}\n"
        f"  Beklenti (işlem başı): {f(m['expectancy'], 3)} USDT\n"
        f"  Maks. düşüş         : %{f(m['max_drawdown_pct'])}\n"
        f"  Al-tut (aynı dönem) : %{f(m['buy_and_hold_pct'])}\n"
        f"  Çıkış nedenleri     : {m['by_reason']}"
    )


async def main() -> None:
    ap = argparse.ArgumentParser(description="AI KRİPTO TRADER backtest")
    ap.add_argument("symbol", help="örn. BTCUSDT")
    ap.add_argument("--days", type=int, default=120, help="test edilecek gün sayısı (4sa EMA200 için ek ısınma verisi otomatik eklenir)")
    ap.add_argument("--split", type=float, default=0.6, help="eğitim oranı (kalanı test)")
    a = ap.parse_args()

    cfg = get_config()
    client = BinanceClient(cfg.binance_rest_url)
    try:
        # her zaman dilimi için 260 mumluk ek ısınma verisi indirilir (4sa EMA200 için gerekli)
        candles = {}
        for tf in ("5m", "15m", "1h", "4h"):
            candles[tf] = await fetch_history(client, a.symbol.upper(), tf, a.days)
            print(f"{tf}: {len(candles[tf])} mum indirildi")
    finally:
        await client.aclose()

    s = TradingSettings()
    print(f"\nBacktest çalışıyor (komisyon %{s.fee_rate_pct}, kayma %{s.slippage_pct}) ...")
    wf = walk_forward(candles, s, a.split)
    print(f"\nEĞİTİM diliminde seçilen alım eşiği: {wf.chosen_threshold}")
    print("\n=== EĞİTİM (parametre seçimi burada yapıldı) ===\n" + fmt(wf.train.metrics))
    print("\n=== TEST (hiç görülmemiş veri - asıl güvenilir sonuç) ===\n" + fmt(wf.test.metrics))
    print("\nUYARI: Geçmiş performans gelecekteki sonucu garanti etmez. İşlem sayısı azsa sonuçlar istatistiksel olarak anlamsızdır.")


if __name__ == "__main__":
    asyncio.run(main())
