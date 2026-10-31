"""Yapay zekâ analiz motoru (emir göndermez; yalnızca puan, gerekçe ve plan üretir).

Dürüst not: Bu motor kural tabanlı çok göstergeli bir puanlama modelidir (makine öğrenmesi modeli DEĞİLDİR).
Puanlar kâr garantisi vermez; her işlem ayrıca bağımsız risk yöneticisinden geçer.
Analiz yalnızca KAPANMIŞ mumlarla yapılır (oluşmakta olan mum kullanılmaz).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from ..exchange.types import Candles
from .indicators import IndicatorSet, compute_indicators, support_resistance

TIMEFRAMES = ("5m", "15m", "1h", "4h", "1d")
TF_WEIGHTS = {"5m": 0.10, "15m": 0.20, "1h": 0.25, "4h": 0.25, "1d": 0.20}
TF_LABEL = {"5m": "5dk", "15m": "15dk", "1h": "1sa", "4h": "4sa", "1d": "1g"}
MIN_4H_BARS = 200  # ~33 gün: daha yeni listelenen coinler elenir
MIN_BARS = 60
VOL_LIMIT_PCT = {"5m": 1.5, "15m": 2.5, "1h": 4.0, "4h": 7.0, "1d": 14.0}  # ATR/fiyat % üstü => aşırı oynak


def label_for(score: float) -> str:
    if score >= 85:
        return "Çok güçlü fırsat"
    if score >= 70:
        return "Değerlendirilebilir fırsat"
    if score >= 50:
        return "Bekle"
    return "İşlem yapma"


@dataclass
class TFSignal:
    interval: str
    score: float
    trend: str
    trend_ratio: float
    close: float
    rsi: float
    macd_hist: float
    macd_rising: bool
    atr: float
    atr_pct: float
    vol_ratio: float | None
    bb_pct: float | None
    support: float | None
    resistance: float | None
    spike: str | None  # "up" | "down" | None
    flags: list[str] = field(default_factory=list)  # uyarılar

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        for k, v in d.items():
            if isinstance(v, (float, np.floating)):
                d[k] = None if np.isnan(v) else round(float(v), 6)
        return d


def _ok(*vals) -> bool:
    return not any(np.isnan(v) for v in vals)


def evaluate_tf(ind: IndicatorSet, i: int, interval: str) -> TFSignal | None:
    """i. mumdaki durumu puanlar (0-100). i'den sonraki veriye bakmaz."""
    if i < 1 or not _ok(ind.ema9[i], ind.ema21[i], ind.ema50[i], ind.rsi[i], ind.macd_hist[i], ind.bb_mid[i], ind.atr[i]):
        return None
    close, opn = ind.close[i], ind.open[i]
    atr_v = ind.atr[i]
    flags: list[str] = []

    # ---- Trend (0-35) ----
    conds = [
        close > ind.ema50[i],
        ind.ema9[i] > ind.ema21[i],
        ind.ema21[i] > ind.ema50[i],
        (i >= 5 and _ok(ind.ema50[i - 5]) and ind.ema50[i] > ind.ema50[i - 5]),
    ]
    if _ok(ind.ema200[i]):
        conds += [close > ind.ema200[i], ind.ema50[i] > ind.ema200[i]]
    ratio = sum(bool(c) for c in conds) / len(conds)
    trend = "Yükseliş" if ratio >= 0.8 else "Zayıf yükseliş" if ratio >= 0.5 else "Yatay" if ratio >= 0.34 else "Düşüş"
    trend_pts = ratio * 35

    # ---- Momentum: MACD + RSI (-10..25) ----
    hist, hist_prev = ind.macd_hist[i], ind.macd_hist[i - 1]
    rising = bool(_ok(hist_prev) and hist > hist_prev)
    mom = 0.0
    if hist > 0:
        mom += 8
    if rising:
        mom += 5
    r = ind.rsi[i]
    if 50 <= r <= 65:
        mom += 12
    elif 65 < r <= 72:
        mom += 6
    elif 40 <= r < 50:
        mom += 4
    elif r > 72:
        mom -= 10
        flags.append(f"{TF_LABEL[interval]}: RSI {r:.0f} aşırı alım bölgesinde")
    mom = float(np.clip(mom, -10, 25))

    # ---- Hacim (0-15) ----
    vr = ind.vol_ratio[i]
    bullish = close > opn
    vol_pts = 0.0
    if _ok(vr):
        if vr >= 1.5:
            vol_pts = 15 if bullish else 4
        elif vr >= 1.0:
            vol_pts = 9 if bullish else 4
        elif vr >= 0.6:
            vol_pts = 4

    # ---- Bollinger (0-10) ----
    bb_pct = None
    bb_pts = 0.0
    width = ind.bb_up[i] - ind.bb_low[i]
    if _ok(width) and width > 0:
        bb_pct = float((close - ind.bb_low[i]) / width)
        if bb_pct > 1:
            bb_pts = 2
            flags.append(f"{TF_LABEL[interval]}: fiyat Bollinger üst bandının dışında (aşırı uzamış)")
        elif bb_pct > 0.85:
            bb_pts = 5
        elif bb_pct >= 0.5:
            bb_pts = 10
        elif bb_pct >= 0.2:
            bb_pts = 6 if ratio >= 0.5 else 3
        else:
            bb_pts = 3 if ratio >= 0.5 else 0

    # ---- Destek / direnç alanı (0-10) ----
    support, resistance = support_resistance(ind.high, ind.low, ind.close, i)
    room = (resistance - close) / atr_v if resistance else 5.0
    room_pts = 10 if room >= 3 else 7 if room >= 2 else 3 if room >= 1 else 0
    if resistance and room < 1:
        flags.append(f"{TF_LABEL[interval]}: yakında direnç ({resistance:.6g})")

    # ---- Cezalar: ani hareket & aşırı volatilite ----
    pen = 0.0
    spike = None
    body = close - opn
    if abs(body) > 3 * atr_v:
        spike = "up" if body > 0 else "down"
        pen -= 10 if spike == "up" else 15
        flags.append(f"{TF_LABEL[interval]}: ani {'yükseliş' if spike == 'up' else 'düşüş'} (>3xATR)")
    atr_pct = float(atr_v / close * 100)
    if atr_pct > VOL_LIMIT_PCT[interval]:
        pen -= 8
        flags.append(f"{TF_LABEL[interval]}: aşırı volatilite (ATR %{atr_pct:.2f})")

    raw = trend_pts + mom + vol_pts + bb_pts + room_pts + pen
    score = float(np.clip(raw / 95 * 100, 0, 100))
    return TFSignal(
        interval=interval, score=round(score, 1), trend=trend, trend_ratio=ratio, close=float(close),
        rsi=float(r), macd_hist=float(hist), macd_rising=rising, atr=float(atr_v), atr_pct=atr_pct,
        vol_ratio=float(vr) if _ok(vr) else None, bb_pct=bb_pct,
        support=float(support) if support else None, resistance=float(resistance) if resistance else None,
        spike=spike, flags=flags,
    )


@dataclass
class Composite:
    score: float
    label: str
    trend: str
    risk: str
    rationale: list[str]
    warnings: list[str]


def _is_up(sig: TFSignal | None) -> bool:
    return sig is not None and sig.trend in ("Yükseliş", "Zayıf yükseliş")


def compose(signals: dict[str, TFSignal], spread_pct: float | None = None) -> Composite:
    """Zaman dilimi puanlarını birleştirir. Üst zaman dilimi düşüşteyse puan tavanlanır."""
    wsum = sum(TF_WEIGHTS[tf] for tf in signals)
    base = sum(TF_WEIGHTS[tf] * s.score for tf, s in signals.items()) / wsum
    s5, s15, s1h, s4h, s1d = (signals.get(k) for k in TIMEFRAMES)
    warnings: list[str] = []
    for s in signals.values():
        warnings += s.flags

    score = base
    if _is_up(s15) and _is_up(s1h) and _is_up(s4h):
        score += 5
    if s4h and s4h.trend == "Düşüş":
        warnings.append("4sa grafik düşüş trendinde: puan en fazla 55 olabilir (trende karşı alım yapılmaz)")
        score = min(score, 55)
    if s1h and s1h.trend == "Düşüş":
        warnings.append("1sa grafik düşüş trendinde: puan en fazla 60 olabilir")
        score = min(score, 60)
    if s1d and s1d.trend == "Düşüş":
        warnings.append("Günlük grafik düşüş trendinde: puan en fazla 65 olabilir")
        score = min(score, 65)
    if s1h and s1h.rsi > 75:
        score -= 8
    score = float(np.clip(score, 0, 100))

    # Genel trend: 1sa ve 4sa baz alınır
    if _is_up(s4h) and _is_up(s1h):
        trend = "Yükseliş"
    elif (s4h and s4h.trend == "Düşüş") or (s1h and s1h.trend == "Düşüş"):
        trend = "Düşüş"
    else:
        trend = "Yatay"

    # Risk seviyesi
    rp = 0
    ref = s1h or s15
    if ref:
        rp += 2 if ref.atr_pct > 3 else 1 if ref.atr_pct > 1.5 else 0
    if any(s.spike for s in signals.values()):
        rp += 2
    if spread_pct is not None and spread_pct > 0.08:
        rp += 1
    if s4h and s4h.trend == "Düşüş":
        rp += 1
    if s1h and s1h.rsi > 75:
        rp += 1
    risk = "Düşük" if rp <= 1 else "Orta" if rp <= 3 else "Yüksek"

    # Türkçe gerekçe
    why: list[str] = [f"Genel trend: {trend}."]
    for tf in ("1d", "4h", "1h", "15m"):
        s = signals.get(tf)
        if s:
            macd_txt = ("pozitif" if s.macd_hist > 0 else "negatif") + (" ve güçleniyor" if s.macd_rising else " ve zayıflıyor")
            why.append(f"{TF_LABEL[tf]}: {s.trend} trendi, RSI {s.rsi:.0f}, MACD {macd_txt}, puan {s.score:.0f}.")
    if s1h and s1h.vol_ratio is not None:
        why.append(f"Hacim (1sa): son 20 mum ortalamasının {s1h.vol_ratio:.1f} katı.")
    if s1h and s1h.resistance:
        why.append(f"En yakın direnç {s1h.resistance:.6g}; destek {s1h.support:.6g}." if s1h.support else f"En yakın direnç {s1h.resistance:.6g}.")
    return Composite(round(score, 1), label_for(score), trend, risk, why, warnings)


@dataclass(frozen=True)
class PlanParams:
    stop_mode: str = "atr"
    stop_atr_mult: float = 1.5
    stop_pct: float = 1.5
    target_mode: str = "rr"
    tp1_rr: float = 2.0
    tp2_rr: float = 3.5
    tp1_pct: float = 2.0
    tp2_pct: float = 4.0
    min_stop_pct: float = 0.5
    max_stop_pct: float = 6.0

    @classmethod
    def from_settings(cls, s) -> "PlanParams":
        return cls(s.stop_mode, s.stop_atr_mult, s.stop_pct, s.target_mode, s.tp1_rr, s.tp2_rr, s.tp1_pct, s.tp2_pct)


def build_plan(entry: float, atr_abs: float, p: PlanParams) -> tuple[float, float, float]:
    """(stop, hedef1, hedef2) döndürür."""
    if p.stop_mode == "atr":
        dist = float(np.clip(p.stop_atr_mult * atr_abs, entry * p.min_stop_pct / 100, entry * p.max_stop_pct / 100))
    else:
        dist = entry * p.stop_pct / 100
    stop = entry - dist
    if p.target_mode == "rr":
        return stop, entry + p.tp1_rr * dist, entry + p.tp2_rr * dist
    return stop, entry * (1 + p.tp1_pct / 100), entry * (1 + p.tp2_pct / 100)


@dataclass
class Analysis:
    symbol: str
    ts: float
    eligible: bool
    skip_reason: str | None = None
    price: float = 0.0
    score: float = 0.0
    label: str = "İşlem yapma"
    trend: str = "-"
    risk: str = "-"
    entry: float = 0.0
    stop: float = 0.0
    tp1: float = 0.0
    tp2: float = 0.0
    atr_pct: float = 0.0
    spread_pct: float | None = None
    quote_volume: float | None = None
    rationale: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    tf: dict[str, dict] = field(default_factory=dict)
    change_pct: float | None = None
    tags: list[str] = field(default_factory=list)
    sell_fit: float = 0.0  # satış uygunluğu 0-100
    downside_risk: float = 0.0  # düşüş riski 0-100
    expected_rr: float = 0.0  # brüt beklenen risk/getiri (1. hedef)
    held: bool = False

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        for k in ("price", "entry", "stop", "tp1", "tp2"):
            d[k] = float(f"{d[k]:.8g}")
        return d


CHASE_CHANGE_PCT = 15.0


def sell_fitness(signals: dict[str, TFSignal]) -> float:
    """Satış uygunluğu (0-100): aşırı alım, zayıflayan momentum, bozulan trend."""
    s1h, s4h = signals.get("1h"), signals.get("4h")
    if not s1h:
        return 0.0
    v = (1 - s1h.trend_ratio) * 40 + max(0.0, s1h.rsi - 65) * 2.5
    if s1h.macd_hist < 0 and not s1h.macd_rising:
        v += 15
    if s1h.bb_pct is not None and s1h.bb_pct > 1:
        v += 10
    if s4h and s4h.trend == "Düşüş":
        v += 10
    return float(np.clip(v, 0, 100))


def downside_risk(signals: dict[str, TFSignal]) -> float:
    """Düşüşün devam etme riski (0-100)."""
    v = 0.0
    weights = {"1d": 20, "4h": 25, "1h": 20}
    for tf, w in weights.items():
        s = signals.get(tf)
        if s:
            v += w * (1 - s.trend_ratio)
    if any(s.spike == "down" for s in signals.values()):
        v += 20
    s1h = signals.get("1h")
    if s1h and s1h.macd_hist < 0 and not s1h.macd_rising:
        v += 10
    return float(np.clip(v, 0, 100))


def classify(signals: dict[str, TFSignal], change_pct: float | None) -> list[str]:
    """Fırsat etiketleri (tarayıcı kategorileri)."""
    tags: list[str] = []
    s15, s1h, s4h = signals.get("15m"), signals.get("1h"), signals.get("4h")
    if change_pct is not None:
        if change_pct >= 5:
            tags.append("Günün yükseleni")
        if change_pct <= -5:
            tags.append("Günün düşeni")
        if change_pct >= CHASE_CHANGE_PCT:
            tags.append("Aşırı yükselmiş")
    if (s1h and s1h.vol_ratio and s1h.vol_ratio >= 2.0) or (s15 and s15.vol_ratio and s15.vol_ratio >= 2.5):
        tags.append("Hacim artışı")
    if s1h and s15 and s1h.rsi < 48 and s15.macd_rising and s15.macd_hist > 0 and not (s4h and s4h.trend == "Düşüş"):
        tags.append("Toparlanma")
    if s1h and s1h.support and (s1h.close - s1h.support) / s1h.atr <= 1.0:
        tags.append("Desteğe yakın")
    if s1h and s15 and s4h and _is_up(s15) and _is_up(s1h) and s4h.trend in ("Yatay", "Zayıf yükseliş") and (s15.vol_ratio or 0) >= 1.3:
        tags.append("Yeni trend")
    if s1h and (s1h.rsi > 75 or (s1h.bb_pct is not None and s1h.bb_pct > 1)) and "Aşırı yükselmiş" not in tags:
        tags.append("Aşırı yükselmiş")
    return tags


def analyze_symbol(
    symbol: str,
    candles: dict[str, Candles],
    now_ms: int | None = None,
    plan: PlanParams | None = None,
    spread_pct: float | None = None,
    quote_volume: float | None = None,
    change_pct: float | None = None,
) -> Analysis:
    now_ms = now_ms or int(time.time() * 1000)
    plan = plan or PlanParams()
    base = Analysis(symbol=symbol, ts=time.time(), eligible=False, spread_pct=spread_pct, quote_volume=quote_volume, change_pct=change_pct)
    closed = {tf: c.closed(now_ms) for tf, c in candles.items()}

    if len(closed.get("4h", [])) < MIN_4H_BARS:
        base.skip_reason = f"Yeni listelenmiş / yetersiz geçmiş (4sa mum sayısı {len(closed.get('4h', []))} < {MIN_4H_BARS})"
        return base

    signals: dict[str, TFSignal] = {}
    for tf in TIMEFRAMES:
        c = closed.get(tf)
        if c is None or len(c) < MIN_BARS:
            continue
        sig = evaluate_tf(compute_indicators(c), len(c) - 1, tf)
        if sig:
            signals[tf] = sig
    if "1h" not in signals or "4h" not in signals:
        base.skip_reason = "Gösterge hesabı için yeterli veri yok"
        return base

    comp = compose(signals, spread_pct)
    price = float(closed["5m"].close[-1]) if "5m" in closed and len(closed["5m"]) else signals["1h"].close
    stop, tp1, tp2 = build_plan(price, signals["1h"].atr, plan)
    base.eligible = True
    base.price, base.entry, base.stop, base.tp1, base.tp2 = price, price, stop, tp1, tp2
    base.score, base.label, base.trend, base.risk = comp.score, comp.label, comp.trend, comp.risk
    base.atr_pct = signals["1h"].atr_pct
    base.rationale, base.warnings = comp.rationale, comp.warnings
    base.tags = classify(signals, change_pct)
    base.sell_fit = round(sell_fitness(signals), 1)
    base.downside_risk = round(downside_risk(signals), 1)
    base.expected_rr = round((tp1 - price) / (price - stop), 2) if price > stop else 0.0
    if "Aşırı yükselmiş" in base.tags:
        base.warnings.append("Aşırı yükselmiş: yükselişin peşinden koşulmaz, geri çekilme beklenir")
    base.tf = {tf: s.to_dict() for tf, s in signals.items()}
    return base
