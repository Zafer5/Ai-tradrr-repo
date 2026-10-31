"""Panelden değiştirilebilir alım-satım / risk ayarları.

Varsayılanlar, proje talimatındaki "ilk test ayarları"dır. Tüm alanlar sınır kontrolünden geçer.
Her alanın Türkçe etiketi, birimi ve grubu panelde form üretmek için kullanılır.
"""
from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import select

from .models import KV


def F(default, label: str, group: str, unit: str = "", help: str = "", **kw):
    return Field(default, json_schema_extra={"label": label, "group": group, "unit": unit, "help": help}, **kw)


PROFILES: dict[str, dict] = {
    "dusuk": dict(risk_per_trade_pct=0.5, daily_loss_limit_pct=1.0, max_open_positions=3, max_symbol_alloc_pct=3.0,
                  max_total_exposure_pct=10.0, buy_score_threshold=80.0, allow_high_risk=False, max_chase_change_pct=10.0, market_shock_pct=2.0),
    "dengeli": dict(risk_per_trade_pct=1.0, daily_loss_limit_pct=2.0, max_open_positions=5, max_symbol_alloc_pct=5.0,
                    max_total_exposure_pct=20.0, buy_score_threshold=70.0, allow_high_risk=False, max_chase_change_pct=15.0, market_shock_pct=2.5),
    "yuksek": dict(risk_per_trade_pct=1.5, daily_loss_limit_pct=3.0, max_open_positions=7, max_symbol_alloc_pct=7.0,
                   max_total_exposure_pct=30.0, buy_score_threshold=65.0, allow_high_risk=False, max_chase_change_pct=20.0, market_shock_pct=3.0),
}
PROFILE_LABELS = {"dusuk": "Düşük risk", "dengeli": "Dengeli", "yuksek": "Yüksek risk", "ozel": "Özel"}
# Not: "Yüksek risk" bile kaldıraç/vadeli işlem açmaz; yalnızca limitleri biraz genişletir.


class TradingSettings(BaseModel):
    risk_profile: Literal["dusuk", "dengeli", "yuksek", "ozel"] = F("dengeli", "Risk profili", "Genel", "", "Profil seçmek ilgili risk limitlerini topluca ayarlar.")

    # ---- Paper trading hesabı ----
    initial_balance: float = F(1000.0, "Başlangıç sanal bakiye", "Genel", "USDT",
                               "Yalnızca 'Sanal hesabı sıfırla' işleminde kullanılır.", ge=10, le=10_000_000)

    # ---- Tarayıcı ----
    scan_interval_sec: int = F(120, "Tarama aralığı", "Tarayıcı", "sn", "Coin listesi ve analizler ne sıklıkla yenilensin.", ge=30, le=3600)
    scan_top_n: int = F(50, "Takip edilecek coin sayısı", "Tarayıcı", "adet", "Hacme göre en iyi N uygun coin.", ge=5, le=100)
    min_quote_volume_usdt: float = F(5_000_000.0, "Asgari 24s hacim", "Tarayıcı", "USDT", "Altındaki coinler elenir.", ge=100_000)
    max_spread_pct: float = F(0.15, "Azami spread", "Tarayıcı", "%", "Alış-satış farkı bundan büyükse coin elenir.", ge=0.01, le=2)
    min_trades_24h: int = F(5000, "Asgari 24s işlem sayısı", "Tarayıcı", "adet", "", ge=0)
    max_abs_change_pct: float = F(25.0, "Azami 24s fiyat değişimi", "Tarayıcı", "%", "Aşırı pompa/dump yaşayan coinler elenir.", ge=5, le=200)
    exclude_stablecoins: bool = F(True, "Stablecoinleri dışarıda bırak", "Tarayıcı")

    # ---- Alım kararı ----
    buy_score_threshold: float = F(70.0, "Alım için asgari AI puanı", "Alım", "puan", "70-84 değerlendirilebilir, 85+ çok güçlü.", ge=50, le=100)
    allow_high_risk: bool = F(False, "Yüksek riskli coinlere izin ver", "Alım")

    max_chase_change_pct: float = F(15.0, "Kovalama sınırı (24s yükseliş)", "Alım", "%", "24 saatte bundan fazla yükselmiş coinin peşinden alım yapılmaz; geri çekilme beklenir.", ge=3, le=100)
    btc_filter_enabled: bool = F(True, "BTC yön filtresi", "Alım", "", "BTC düşüş trendindeyken alım eşiği +10 puan yükselir.")
    market_shock_pct: float = F(2.5, "Ani düşüş koruması (BTC 1 saatlik düşüş)", "Alım", "%", "BTC bu kadar düşerse yeni alımlar bir süre durdurulur.", ge=0.5, le=15)

    # ---- Mevcut portföy yönetimi ----
    portfolio_mode: Literal["off", "watch", "manage"] = F("watch", "Mevcut coin yönetimi", "Portföy", "", "off: kapalı | watch: izle ve öner | manage: gölge (sanal) yönetim. Gerçek hesapta emir GÖNDERİLMEZ.")
    holding_target_pct: float = F(5.0, "Mevcut coin hedef kâr (temel)", "Portföy", "%", "Piyasaya göre otomatik ayarlanır.", ge=1, le=100)
    holding_sell_fraction: float = F(0.5, "Hedefte satılacak oran", "Portföy", "0-1", "", ge=0.1, le=1.0)
    holding_trail_activation_pct: float = F(4.0, "Mevcut coin trailing başlangıç kârı", "Portföy", "%", "", ge=1, le=100)
    holding_trail_distance_pct: float = F(1.5, "Mevcut coin trailing mesafesi", "Portföy", "%", "", ge=0.3, le=50)
    holding_stop_pct: float = F(0.0, "Mevcut coin zarar sınırı (0 = kapalı)", "Portföy", "%", "0 ise zarardaki coin otomatik satılmaz, yalnızca uyarılır.", ge=0, le=60)

    # ---- Hedef / çıkış ----
    target_mode: Literal["rr", "percent"] = F("rr", "Hedef yöntemi", "Hedefler", "", "rr: risk katı | percent: sabit yüzde")
    tp1_rr: float = F(2.0, "1. hedef (risk katı)", "Hedefler", "R", "", ge=0.5, le=10)
    tp2_rr: float = F(3.5, "2. hedef (risk katı)", "Hedefler", "R", "", ge=0.8, le=20)
    tp1_pct: float = F(2.0, "1. hedef (yüzde)", "Hedefler", "%", "", ge=0.3, le=50)
    tp2_pct: float = F(4.0, "2. hedef (yüzde)", "Hedefler", "%", "", ge=0.5, le=100)
    tp1_sell_fraction: float = F(0.5, "1. hedefte satılacak oran", "Hedefler", "0-1", "Kademeli satış: 0.5 = pozisyonun yarısı.", ge=0.1, le=1.0)
    stop_mode: Literal["atr", "percent"] = F("atr", "Stop-loss yöntemi", "Hedefler", "", "atr: ATR katı | percent: sabit yüzde")
    stop_atr_mult: float = F(1.5, "Stop mesafesi (ATR katı)", "Hedefler", "xATR", "", ge=0.5, le=6)
    stop_pct: float = F(1.5, "Stop mesafesi (yüzde)", "Hedefler", "%", "", ge=0.2, le=20)
    trailing_enabled: bool = F(True, "Trailing stop kullan", "Hedefler")
    trailing_activation_pct: float = F(1.5, "Trailing stop devreye giriş kârı", "Hedefler", "%", "Fiyat girişin bu kadar üstüne çıkınca başlar.", ge=0.3, le=50)
    trailing_distance_pct: float = F(0.8, "Trailing stop mesafesi", "Hedefler", "%", "Zirveden bu kadar düşünce satar (başa baş seviyesinin altına inmez).", ge=0.1, le=20)

    # ---- Maliyet simülasyonu ----
    fee_rate_pct: float = F(0.10, "Komisyon (işlem başına)", "Maliyet", "%", "Binance Spot varsayılanı %0.10.", ge=0, le=1)
    slippage_pct: float = F(0.05, "Fiyat kayması (slippage)", "Maliyet", "%", "Piyasa emirlerinde simüle edilir.", ge=0, le=2)

    # ---- Risk yönetimi ----
    risk_per_trade_pct: float = F(1.0, "İşlem başına azami risk", "Risk", "% sermaye", "", ge=0.05, le=5)
    daily_loss_limit_pct: float = F(2.0, "Günlük zarar limiti", "Risk", "% sermaye", "Aşılırsa gün sonuna kadar yeni alım yapılmaz.", ge=0.2, le=20)
    max_open_positions: int = F(5, "Aynı anda azami pozisyon", "Risk", "adet", "", ge=1, le=20)
    max_symbol_alloc_pct: float = F(5.0, "Tek coine azami sermaye", "Risk", "% sermaye", "", ge=0.5, le=50)
    max_total_exposure_pct: float = F(20.0, "Toplam açık maruziyet", "Risk", "% sermaye", "", ge=1, le=100)
    min_net_profit_pct: float = F(0.3, "1. hedefte asgari net kâr", "Risk", "%", "Komisyon+kayma sonrası; altındaysa alım yapılmaz.", ge=0.05, le=10)
    min_risk_reward: float = F(1.2, "Asgari risk/getiri (1. hedef, net)", "Risk", "R", "", ge=0.3, le=10)
    cooldown_minutes: int = F(60, "Çıkış sonrası aynı coine bekleme", "Risk", "dk", "", ge=0, le=1440)
    max_trades_per_day: int = F(20, "Günlük azami işlem sayısı", "Risk", "adet", "", ge=1, le=500)

    @model_validator(mode="after")
    def _check(self):
        if self.tp2_rr <= self.tp1_rr:
            raise ValueError("2. hedef (risk katı), 1. hedeften büyük olmalıdır.")
        if self.tp2_pct <= self.tp1_pct:
            raise ValueError("2. hedef (yüzde), 1. hedeften büyük olmalıdır.")
        if self.max_symbol_alloc_pct > self.max_total_exposure_pct:
            raise ValueError("Tek coin limiti, toplam maruziyet limitinden büyük olamaz.")
        return self


def settings_meta() -> list[dict[str, Any]]:
    meta = []
    for key, f in TradingSettings.model_fields.items():
        extra = f.json_schema_extra or {}
        ann = f.annotation
        kind = "bool" if ann is bool else "int" if ann is int else "float" if ann is float else "select"
        item: dict[str, Any] = {"key": key, "kind": kind, **extra}
        for m in f.metadata:
            if hasattr(m, "ge"):
                item["min"] = m.ge
            if hasattr(m, "le"):
                item["max"] = m.le
        if kind == "select":
            item["options"] = list(getattr(ann, "__args__", ()))
        meta.append(item)
    return meta


class SettingsStore:
    """Ayarları veritabanında saklar; bellekte önbellekler."""

    KEY = "trading_settings"

    def __init__(self, db):
        self.db = db
        self._cache: TradingSettings | None = None

    async def get(self) -> TradingSettings:
        if self._cache is None:
            async with self.db.session() as s:
                row = (await s.execute(select(KV).where(KV.key == self.KEY))).scalar_one_or_none()
            try:
                self._cache = TradingSettings(**json.loads(row.value)) if row else TradingSettings()
            except (ValidationError, ValueError):
                self._cache = TradingSettings()
        return self._cache

    async def update(self, values: dict[str, Any]) -> TradingSettings:
        current = (await self.get()).model_dump()
        current.update(values)
        if "risk_profile" not in values and any(k in values for k in PROFILES["dengeli"]):
            # profil alanları elle değiştirildi: adlı bir profille birebir eşleşiyorsa o profil, değilse "özel"
            current["risk_profile"] = next((n for n, p in PROFILES.items() if all(current[k] == v for k, v in p.items())), "ozel")
        new = TradingSettings(**current)  # ValidationError yukarıya fırlar
        async with self.db.session() as s:
            row = (await s.execute(select(KV).where(KV.key == self.KEY))).scalar_one_or_none()
            if row:
                row.value = new.model_dump_json()
            else:
                s.add(KV(key=self.KEY, value=new.model_dump_json()))
            await s.commit()
        self._cache = new
        return new

    async def apply_profile(self, name: str) -> TradingSettings:
        if name not in PROFILES:
            raise ValueError("Geçersiz risk profili")
        return await self.update({**PROFILES[name], "risk_profile": name})

    async def reset(self) -> TradingSettings:
        return await self.update(TradingSettings().model_dump())
