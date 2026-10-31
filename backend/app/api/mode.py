"""İşlem modu (sanal / testnet / GERÇEK) ve borsa anahtarları.

Gerçek moda geçiş için ÜÇ koşul birlikte gerekir:
  1) sunucu sahibi .env içinde ALLOW_LIVE_TRADING=true yapmış olmalı,
  2) kullanıcı panelde sermaye tavanı + yazılı onay cümlesi + şifre girmeli,
  3) anahtarda alım-satım yetkisi AÇIK, para çekme yetkisi KAPALI olmalı (doğrulanır).
"""
from __future__ import annotations

import unicodedata
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..exchange.binance import ExchangeError
from ..logging_setup import register_secret
from ..models import ApiCredential, utcnow
from ..security import mask
from .routes import ctx, require_auth

router = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])

CONFIRM_PHRASE = "GERÇEK PARAYLA İŞLEM YAPMAYI ONAYLIYORUM"
MIN_LIVE_CAPITAL = 20.0


def fold(s: str) -> str:
    """Büyük/küçük harf ve Türkçe karakter farkını yok sayarak karşılaştırma."""
    s = unicodedata.normalize("NFKD", s.strip().upper())
    return "".join(ch for ch in s if not unicodedata.combining(ch)).replace("İ", "I").replace("ı", "I")


class ModeBody(BaseModel):
    mode: Literal["paper", "testnet", "live"]
    capital: float | None = None
    confirm_phrase: str = ""
    password: str = ""


async def _creds(c, env: str) -> ApiCredential | None:
    async with c.db.session() as ses:
        return await ses.get(ApiCredential, env)


@router.get("/trading-mode")
async def get_mode(request: Request):
    c = ctx(request)
    live, test = await _creds(c, "live"), await _creds(c, "testnet")
    openpos = len(await c.service.open_positions())
    return {
        "mode": c.service.mode, "label": c.service.mode_label, "capital": c.service.capital,
        "executor_ok": (c.service.exec is not None) if c.service.is_exchange else True, "executor_error": c.service.exec_error,
        "server_allows_live": c.cfg.allow_live_trading, "live_key": bool(live), "testnet_key": bool(test),
        "bot_running": c.bot.enabled, "open_positions": openpos, "confirm_phrase": CONFIRM_PHRASE, "min_live_capital": MIN_LIVE_CAPITAL,
        "halt": c.bot.halt_reason,
    }


@router.post("/trading-mode")
async def set_mode(body: ModeBody, request: Request):
    c = ctx(request)
    if body.mode == c.service.mode and body.mode == "paper":
        return await get_mode(request)
    if c.bot.enabled:
        raise HTTPException(409, "Önce botu durdurun.")
    if await c.service.open_positions():
        raise HTTPException(409, f"{c.service.mode_label} modda açık pozisyon var. Önce pozisyonları kapatın.")

    if body.mode == "paper":
        await c.service.activate_mode("paper")
        c.bot.halt_reason = None
        return await get_mode(request)

    # ---- borsa modları ortak kontroller ----
    capital = body.capital or 0.0
    if capital <= 0:
        raise HTTPException(422, "Botun kullanabileceği azami sermayeyi (USDT) girin.")
    env = body.mode
    if not await _creds(c, env):
        raise HTTPException(422, f"Önce {'Testnet' if env == 'testnet' else 'gerçek hesap'} API anahtarını kaydedin.")

    if body.mode == "live":
        if not c.cfg.allow_live_trading:
            raise HTTPException(403, "Gerçek işlem sunucu tarafında kapalı. Sunucudaki .env dosyasına ALLOW_LIVE_TRADING=true ekleyip yeniden başlatın.")
        if capital < MIN_LIVE_CAPITAL:
            raise HTTPException(422, f"Gerçek mod için azami sermaye en az {MIN_LIVE_CAPITAL:.0f} USDT olmalı.")
        if fold(body.confirm_phrase) != fold(CONFIRM_PHRASE):
            raise HTTPException(422, f"Onay cümlesi hatalı. Aynen şunu yazın: {CONFIRM_PHRASE}")
        if not c.auth.gate.verify(body.password):
            raise HTTPException(401, "Şifre hatalı.")

    # geçici yürütücü ile hesabı doğrula (henüz mod değişmedi)
    try:
        ex = await c.service.executor_factory(env)
        info = await ex.check_account()
    except (ExchangeError, ValueError) as e:
        raise HTTPException(502, f"Borsa hesabı doğrulanamadı: {e}")
    if info["can_withdraw"]:
        raise HTTPException(422, "Bu anahtarda PARA ÇEKME yetkisi açık. Güvenliğiniz için reddedildi: Binance'te anahtarın para çekme yetkisini kapatıp yeniden oluşturun.")
    if not info["can_trade"]:
        raise HTTPException(422, "Bu anahtarda alım-satım yetkisi kapalı. Binance'te 'Enable Spot & Margin Trading' (yalnızca Spot) seçili olmalı.")
    if info["usdt_free"] < capital:
        raise HTTPException(422, f"Hesapta yeterli serbest USDT yok (serbest {info['usdt_free']:.2f}, istenen sermaye {capital:.2f}).")

    await c.service.activate_mode(body.mode, capital)
    c.bot.halt_reason = None
    return await get_mode(request)


@router.post("/bot/clear-halt")
async def clear_halt(request: Request):
    problem = await ctx(request).bot.clear_halt()
    if problem:
        raise HTTPException(409, f"Hâlâ uyuşmazlık var: {problem}")
    return {"ok": True}


# ---------------------------------------------------------------------- gerçek hesap anahtarı
class KeyBody(BaseModel):
    api_key: str
    api_secret: str


@router.put("/connections/live")
async def save_live(body: KeyBody, request: Request):
    c = ctx(request)
    key, secret = body.api_key.strip(), body.api_secret.strip()
    if len(key) < 16 or len(secret) < 16 or " " in key or " " in secret:
        raise HTTPException(422, "Anahtar biçimi geçersiz görünüyor.")
    if c.service.mode == "live":
        raise HTTPException(409, "Gerçek mod aktifken anahtar değiştirilemez. Önce SANAL moda geçin.")
    register_secret(key)
    register_secret(secret)
    async with c.db.session() as ses:
        row = await ses.get(ApiCredential, "live")
        ek, es = c.auth.vault.encrypt(key), c.auth.vault.encrypt(secret)
        if row:
            row.api_key_enc, row.api_secret_enc, row.key_hint, row.updated_at = ek, es, mask(key), utcnow()
        else:
            ses.add(ApiCredential(env="live", api_key_enc=ek, api_secret_enc=es, key_hint=mask(key)))
        await ses.commit()
    return {"ok": True, "key_hint": mask(key)}


@router.delete("/connections/live")
async def delete_live(request: Request):
    c = ctx(request)
    if c.service.mode == "live":
        raise HTTPException(409, "Gerçek mod aktifken anahtar silinemez. Önce SANAL moda geçin.")
    async with c.db.session() as ses:
        row = await ses.get(ApiCredential, "live")
        if row:
            await ses.delete(row)
            await ses.commit()
    return {"ok": True}


@router.post("/connections/live/test")
async def test_live(request: Request):
    c = ctx(request)
    if not await _creds(c, "live"):
        raise HTTPException(404, "Önce gerçek hesap anahtarını kaydedin.")
    try:
        info = await (await c.service.executor_factory("live")).check_account()
    except (ExchangeError, ValueError) as e:
        raise HTTPException(502, f"Binance bağlantısı başarısız: {e}")
    problems = []
    if info["can_withdraw"]:
        problems.append("PARA ÇEKME yetkisi AÇIK: sistem bu anahtarı kullanmayı reddeder. Yetkiyi kapatın.")
    if not info["can_trade"]:
        problems.append("Alım-satım yetkisi KAPALI: emir gönderilemez.")
    return {"ok": not problems, "usdt_free": info["usdt_free"], "permissions": info["permissions"], "problems": problems,
            "can_trade": info["can_trade"], "can_withdraw": info["can_withdraw"]}
