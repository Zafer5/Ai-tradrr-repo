"""Analiz motoru: çoklu zaman dilimi teknik analizi ile 0-100 fırsat puanı üretir.

ÖNEMLİ: Bu modül yalnızca öneri üretir; emir gönderemez. Her öneri ayrıca
risk.py içindeki bağımsız risk kontrolünden geçer. Puanlar kesinlik bildirmez.

Bu ilk sürüm şeffaf, açıklanabilir kurallara dayalı bir puanlama modelidir.
`Analyzer` arayüzü sayesinde ileride makine öğrenmesi veya dil modeli tabanlı
bir analizci aynı yere takılabilir.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict

from . import indicators as ind
from .exchanges.base import Candle

TIMEFRAMES = ("5m", "15m", "1h", "4h")
MIN_CANDLES = 210  # EMA200 için yeterli geçmiş


@dataclass
class TFStats:
    close: float
    ema9: float
    ema21: float
    ema50: float
    ema200: float
    rsi: float
    macd_hist: float
    macd_hist_prev: float
    bb_upper: float
    bb_mid: float
    bb_lower: float
    atr: float
    vol_ratio: float
    support: float
    resistance: float
    last_change_pct: float


@dataclass
class Analysis:
    symbol: str
    price: float
    score: int
    label: str
    trend: str
    risk_level: str
    entry: float
    take_profit: float
    stop_loss: float
    atr_pct: float
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    tradable: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


def label_for(score: int) -> str:
    if score >= 85:
        return "Çok güçlü fırsat"
    if score >= 70:
        return "Değerlendirilebilir fırsat"
    if score >= 50:
        return "Bekle"
    return "İşlem yapma"


def closed_only(candles: list[Candle]) -> list[Candle]:
    """Henüz kapanmamış son mumu çıkarır (geleceğe bakma / yeniden boyama hatasını önler)."""
    return [c for c in candles if c.closed]


def tf_stats(candles: list[Candle]) -> TFStats | None:
    c = closed_only(candles)
    if len(c) < MIN_CANDLES:
        return None
    closes = [x.close for x in c]
    highs = [x.high for x in c]
    lows = [x.low for x in c]
    vols = [x.volume for x in c]
    _, _, hist = ind.macd(closes)
    up, mid, lo = ind.bollinger(closes)
    a = ind.atr(highs, lows, closes)
    avg_vol = sum(vols[-21:-1]) / 20
    sup, res = ind.support_resistance(highs, lows, closes[-1])
    return TFStats(
        close=closes[-1],
        ema9=ind.last(ind.ema(closes, 9)),
        ema21=ind.last(ind.ema(closes, 21)),
        ema50=ind.last(ind.ema(closes, 50)),
        ema200=ind.last(ind.ema(closes, 200)),
        rsi=ind.last(ind.rsi(closes)),
        macd_hist=hist[-1],
        macd_hist_prev=hist[-2],
        bb_upper=up[-1],
        bb_mid=mid[-1],
        bb_lower=lo[-1],
        atr=a[-1],
        vol_ratio=(vols[-1] / avg_vol) if avg_vol > 0 else 0.0,
        support=sup,
        resistance=res,
        last_change_pct=(closes[-1] - c[-1].open) / c[-1].open * 100 if c[-1].open else 0.0,
    )


@dataclass
class TargetSettings:
    use_atr_targets: bool = True
    atr_tp_mult: float = 2.5
    atr_sl_mult: float = 1.5
    take_profit_pct: float = 2.0
    stop_loss_pct: float = 1.5


class Analyzer:
    """Kurallara dayalı, açıklanabilir puanlama."""

    def analyze(self, symbol: str, data: dict[str, list[Candle]], targets: TargetSettings) -> Analysis:
        stats = {tf: tf_stats(data.get(tf, [])) for tf in TIMEFRAMES}
        missing = [tf for tf, s in stats.items() if s is None]
        if missing:
            price = data["5m"][-1].close if data.get("5m") else 0.0
            return Analysis(symbol, price, 0, "İşlem yapma", "belirsiz", "yüksek", price, 0, 0, 0,
                            [], [f"Yetersiz geçmiş veri: {', '.join(missing)} (yeni listelenmiş olabilir)"], False)

        s5, s15, s1h, s4h = stats["5m"], stats["15m"], stats["1h"], stats["4h"]
        price = s5.close
        score = 0
        reasons: list[str] = []
        warnings: list[str] = []

        # 1) Ana trend - 4 saatlik (20 puan)
        if s4h.close > s4h.ema200:
            score += 10; reasons.append("4s: fiyat EMA200 üzerinde (uzun vadeli yükseliş)")
        else:
            warnings.append("4s: fiyat EMA200 altında (uzun vadeli zayıf)")
        if s4h.ema50 > s4h.ema200:
            score += 10; reasons.append("4s: EMA50 > EMA200")

        # 2) Orta vade - 1 saatlik (20 puan)
        if s1h.ema9 > s1h.ema21:
            score += 8; reasons.append("1s: EMA9 > EMA21 (kısa vadeli yükseliş)")
        if s1h.close > s1h.ema50:
            score += 6; reasons.append("1s: fiyat EMA50 üzerinde")
        if s1h.macd_hist > 0:
            score += 6; reasons.append("1s: MACD pozitif")

        # 3) Momentum - 15 dakikalık (20 puan)
        if 45 <= s15.rsi <= 65:
            score += 8; reasons.append(f"15dk: RSI sağlıklı bölgede ({s15.rsi:.0f})")
        elif s15.rsi > 75:
            score -= 8; warnings.append(f"15dk: RSI aşırı alım ({s15.rsi:.0f})")
        if s15.macd_hist > s15.macd_hist_prev:
            score += 6; reasons.append("15dk: MACD histogramı yükseliyor")
        if s15.close > s15.ema21:
            score += 6; reasons.append("15dk: fiyat EMA21 üzerinde")

        # 4) Giriş zamanlaması - 5 dakikalık (15 puan)
        if s5.rsi < 70:
            score += 5
        else:
            warnings.append(f"5dk: RSI yüksek ({s5.rsi:.0f}), giriş için geç olabilir")
        if s5.close <= s5.bb_mid and s1h.ema9 > s1h.ema21:
            score += 10; reasons.append("5dk: yükseliş trendinde geri çekilme (Bollinger orta bandı altı)")
        elif s5.close >= s5.bb_upper:
            warnings.append("5dk: fiyat üst Bollinger bandında")

        # 5) Hacim (15 puan)
        if s1h.vol_ratio >= 2:
            score += 15; reasons.append(f"1s: hacim ortalamanın {s1h.vol_ratio:.1f} katı")
        elif s1h.vol_ratio >= 1.2:
            score += 10; reasons.append(f"1s: hacim ortalamanın üzerinde ({s1h.vol_ratio:.1f}x)")
        elif s1h.vol_ratio < 0.5:
            warnings.append("1s: hacim zayıf")

        # 6) Volatilite (10 puan)
        atr_pct = s1h.atr / price * 100 if price else 0
        if 0.3 <= atr_pct <= 3:
            score += 10; reasons.append(f"Volatilite makul (1s ATR %{atr_pct:.2f})")
        elif atr_pct > 3:
            warnings.append(f"Volatilite çok yüksek (1s ATR %{atr_pct:.2f})")
        else:
            warnings.append(f"Volatilite çok düşük (1s ATR %{atr_pct:.2f}), kâr hedefi zor")

        # Cezalar
        if abs(s5.last_change_pct) >= 3:
            score -= 10; warnings.append(f"Ani fiyat hareketi: son 5dk mumda %{s5.last_change_pct:.1f}")
        if not math.isnan(s1h.resistance) and s1h.resistance > price and (s1h.resistance - price) < 0.5 * s1h.atr:
            score -= 10; warnings.append(f"Dirence çok yakın ({s1h.resistance:.6g})")

        score = int(max(0, min(100, score)))

        if s4h.close > s4h.ema200 and s1h.ema9 > s1h.ema21:
            trend = "yükseliş"
        elif s4h.close < s4h.ema200 and s1h.ema9 < s1h.ema21:
            trend = "düşüş"
        else:
            trend = "yatay/karışık"

        risk_level = "düşük" if atr_pct < 1 else ("orta" if atr_pct <= 2.5 else "yüksek")

        if targets.use_atr_targets:
            tp = price + targets.atr_tp_mult * s1h.atr
            sl = price - targets.atr_sl_mult * s1h.atr
        else:
            tp = price * (1 + targets.take_profit_pct / 100)
            sl = price * (1 - targets.stop_loss_pct / 100)

        return Analysis(symbol, price, score, label_for(score), trend, risk_level, price, tp, sl,
                        round(atr_pct, 3), reasons, warnings, True)
