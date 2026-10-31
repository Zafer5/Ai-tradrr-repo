"""İşlem servisi: pozisyon/emir kayıtları ve hesap muhasebesi. Üç mod:

* paper   : sanal hesap + simüle dolum (gerçek piyasa fiyatı, komisyon ve kayma simülasyonu)
* testnet : Binance Spot Testnet'e GERÇEK emir (sanal paralı test borsası)
* live    : Binance Spot GERÇEK hesap — yalnızca iki kilit (sunucu + panel onayı) açıksa

Borsa modlarında:
* Dolum fiyatı, miktar ve komisyon borsanın döndürdüğü gerçek dolumlardan alınır.
* Botun kullanabileceği sermaye, kullanıcının belirlediği TAVANLA sınırlıdır (hesabın tamamı kullanılmaz).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select

from ..exchange.types import SymbolInfo
from ..kv import kv_get, kv_set
from ..models import EquitySnapshot, Order, Position, utcnow
from ..risk.manager import AccountSnapshot, RiskDecision
from ..trading_settings import TradingSettings
from .exits import ExitAction
from .live import ExchangeExecutor, Fill, OrderRejected

log = logging.getLogger("app.trading")
TZ = ZoneInfo("Europe/Istanbul")
ACCOUNT_KEY = "paper_account"
DAY_KEY = "day_state"
EXEC_KEY = "exec_config"
MODE_LABEL = {"paper": "sanal", "testnet": "TESTNET", "live": "GERÇEK"}


class PaperBroker:
    mode = "paper"

    @staticmethod
    def buy(ref_ask: float, qty: float, s: TradingSettings) -> Fill:
        price = ref_ask * (1 + s.slippage_pct / 100)
        fee = price * qty * s.fee_rate_pct / 100
        return Fill(price, qty, fee, price * qty + fee)

    @staticmethod
    def sell(order_type: str, ref_price: float, qty: float, s: TradingSettings) -> Fill:
        price = ref_price * (1 - s.slippage_pct / 100) if order_type == "MARKET" else ref_price
        fee = price * qty * s.fee_rate_pct / 100
        return Fill(price, qty, fee, price * qty - fee)


def today_str() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d")


def day_start_utc() -> datetime:
    return datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


class TradingService:
    def __init__(self, db, store):
        self.db = db
        self.store = store
        self.broker = PaperBroker()
        self.mode = "paper"
        self.capital = 0.0  # borsa modlarında botun kullanabileceği azami sermaye (USDT)
        self.armed_at: datetime | None = None
        self.exec: ExchangeExecutor | None = None
        self.exec_error: str | None = None
        self.exchange_free_usdt: float | None = None
        self.executor_factory: Callable[[str], Awaitable[ExchangeExecutor]] | None = None
        self.live_allowed = False  # sunucu kilidi (ALLOW_LIVE_TRADING); main.py ayarlar

    # ------------------------------------------------------------------ mod yönetimi
    @property
    def mode_label(self) -> str:
        return MODE_LABEL[self.mode]

    @property
    def is_exchange(self) -> bool:
        return self.mode != "paper"

    async def load_mode(self) -> None:
        async with self.db.session() as ses:
            cfg = await kv_get(ses, EXEC_KEY, {})
        self.mode = cfg.get("mode", "paper")
        self.capital = float(cfg.get("capital", 0.0))
        self.armed_at = datetime.fromisoformat(cfg["armed_at"]) if cfg.get("armed_at") else None
        self.exec, self.exec_error = None, None
        if self.is_exchange:
            await self._connect_executor()

    async def _connect_executor(self) -> None:
        try:
            if self.executor_factory is None:
                raise ValueError("Borsa bağlantısı yapılandırılmamış")
            if self.mode == "live" and not self.live_allowed:
                raise ValueError("Sunucuda gerçek işlem kilitli (ALLOW_LIVE_TRADING=false); emir gönderilmeyecek")
            self.exec = await self.executor_factory(self.mode)
            self.exec_error = None
        except Exception as e:
            self.exec, self.exec_error = None, f"{type(e).__name__}: {e}"[:200]
            log.error("%s modu için borsa bağlantısı kurulamadı: %s", self.mode.upper(), self.exec_error)

    async def activate_mode(self, mode: str, capital: float = 0.0) -> None:
        """Mod değiştirir. Çağıran, botun kapalı ve açık pozisyon olmadığını önceden doğrulamış olmalıdır."""
        async with self.db.session() as ses:
            armed = utcnow()
            await kv_set(ses, EXEC_KEY, {"mode": mode, "capital": capital, "armed_at": armed.isoformat() if mode != "paper" else None})
            await ses.commit()
        await self.load_mode()
        self.exchange_free_usdt = None
        await self.refresh_exchange_cash()
        equity, _, _ = await self.equity({})
        async with self.db.session() as ses:
            await kv_set(ses, DAY_KEY, {"date": today_str(), "start_equity": equity})
            await ses.commit()
        log.warning("İşlem modu değişti: %s (sermaye tavanı %.2f USDT)", self.mode.upper(), self.capital)

    async def refresh_exchange_cash(self) -> None:
        if not self.is_exchange or self.exec is None:
            return
        try:
            self.exchange_free_usdt = (await self.exec.balances()).get("USDT", (0.0, 0.0))[0]
        except Exception as e:
            self.exchange_free_usdt = None
            log.warning("Borsa bakiyesi okunamadı: %s", e)

    # ------------------------------------------------------------------ hesap
    async def ensure_account(self) -> None:
        async with self.db.session() as ses:
            if await kv_get(ses, ACCOUNT_KEY) is None:
                s = await self.store.get()
                await kv_set(ses, ACCOUNT_KEY, {"cash": s.initial_balance, "initial": s.initial_balance})
                await kv_set(ses, DAY_KEY, {"date": today_str(), "start_equity": s.initial_balance})
                await ses.commit()

    async def _exchange_account(self) -> dict:
        async with self.db.session() as ses:
            q = select(Position).where(Position.mode == self.mode)
            if self.armed_at:
                q = q.where(Position.opened_at >= self.armed_at)
            rows = list((await ses.execute(q)).scalars())
        realized = sum(p.realized_pnl for p in rows)
        open_cost = sum(p.cost_total * (p.quantity / p.initial_quantity) for p in rows if p.status == "OPEN")
        budget = max(0.0, self.capital + realized - open_cost)
        free = self.exchange_free_usdt if self.exchange_free_usdt is not None else 0.0  # bilinmiyorsa 0: alım yapılmaz
        return {"cash": min(free, budget), "initial": self.capital, "budget": budget, "free_on_exchange": free}

    async def account(self) -> dict:
        if self.is_exchange:
            return await self._exchange_account()
        async with self.db.session() as ses:
            acc = await kv_get(ses, ACCOUNT_KEY)
        if acc is None:
            await self.ensure_account()
            return await self.account()
        return acc

    async def open_positions(self) -> list[Position]:
        async with self.db.session() as ses:
            return list((await ses.execute(select(Position).where(Position.status == "OPEN", Position.mode == self.mode).order_by(Position.id))).scalars())

    async def equity(self, prices: dict[str, float]) -> tuple[float, float, float]:
        """(özkaynak, nakit, açık pozisyon değeri)"""
        acc = await self.account()
        value = 0.0
        for p in await self.open_positions():
            value += p.quantity * prices.get(p.symbol, p.entry_price)
        return acc["cash"] + value, acc["cash"], value

    async def roll_day(self, equity: float) -> float:
        """Gün başı özkaynağı (Europe/Istanbul gün sınırı). Yeni gün başlarsa sıfırlar."""
        async with self.db.session() as ses:
            st = await kv_get(ses, DAY_KEY)
            if not st or st.get("date") != today_str():
                st = {"date": today_str(), "start_equity": equity}
                await kv_set(ses, DAY_KEY, st)
                await ses.commit()
                log.info("Yeni gün başladı; gün başı özkaynak %.2f USDT", equity)
            return st["start_equity"]

    async def snapshot(self, prices: dict[str, float], in_flight: set[str], cooldown_minutes: int) -> AccountSnapshot:
        equity, cash, _ = await self.equity(prices)
        start = await self.roll_day(equity)
        open_pos = {p.symbol: p.quantity * prices.get(p.symbol, p.entry_price) for p in await self.open_positions()}
        async with self.db.session() as ses:
            trades_today = (await ses.execute(select(func.count(Position.id)).where(Position.opened_at >= day_start_utc(), Position.mode == self.mode))).scalar_one()
            cool = set()
            if cooldown_minutes > 0:
                since = utcnow() - timedelta(minutes=cooldown_minutes)
                rows = await ses.execute(select(Position.symbol).where(Position.status == "CLOSED", Position.closed_at >= since, Position.mode == self.mode))
                cool = {r[0] for r in rows}
        day_pnl_pct = (equity - start) / start * 100 if start > 0 else 0.0
        return AccountSnapshot(equity, cash, open_pos, day_pnl_pct, trades_today, cool, in_flight)

    # ------------------------------------------------------------------ alım
    async def open_position(self, symbol: str, ask: float, dec: RiskDecision, stop: float, tp1: float, tp2: float,
                            score: float, risk_level: str, rationale: str, s: TradingSettings, info: SymbolInfo | None = None) -> Position | None:
        if self.is_exchange:
            if self.exec is None:
                raise OrderRejected(f"Borsa bağlantısı yok: {self.exec_error or 'bilinmiyor'}")
            acct = await self._exchange_account()
            fill = await self.exec.buy(symbol, dec.quantity, ask, info, capital_free=acct["budget"])
            cost = fill.cost
        else:
            fill = self.broker.buy(ask, dec.quantity, s)
            cost = fill.cost
        async with self.db.session() as ses:
            if not self.is_exchange:
                acc = await kv_get(ses, ACCOUNT_KEY)
                if cost > acc["cash"]:
                    log.warning("%s alımı iptal: nakit yetersiz (%.2f > %.2f)", symbol, cost, acc["cash"])
                    return None
            pos = Position(
                symbol=symbol, mode=self.mode, status="OPEN", entry_price=fill.price, quantity=fill.qty,
                initial_quantity=fill.qty, cost_total=cost, stop_price=stop, tp1_price=tp1, tp2_price=tp2,
                peak_price=fill.price, est_fees=fill.fee + fill.qty * tp1 * s.fee_rate_pct / 100, fees_total=fill.fee,
                score=score, risk_level=risk_level, rationale=rationale,
            )
            ses.add(pos)
            await ses.flush()
            ses.add(Order(position_id=pos.id, symbol=symbol, mode=self.mode, side="BUY", order_type="MARKET",
                          quantity=fill.qty, price=fill.price, fee=fill.fee, reason="ENTRY", exchange_order_id=fill.order_id or None))
            if not self.is_exchange:
                acc["cash"] -= cost
                await kv_set(ses, ACCOUNT_KEY, acc)
            await ses.commit()
        if self.is_exchange:
            await self.refresh_exchange_cash()
        log.info("ALIM [%s] %s: %.6g adet @ %.8g (stop %.8g, hedef1 %.8g, hedef2 %.8g, puan %.0f)",
                 self.mode_label, symbol, fill.qty, fill.price, stop, tp1, tp2, score)
        return pos

    # ------------------------------------------------------------------ satım
    async def execute_exit(self, position_id: int, action: ExitAction, s: TradingSettings, info: SymbolInfo | None = None) -> Position | None:
        async with self.db.session() as ses:
            pos = await ses.get(Position, position_id)
            if pos is None or pos.status != "OPEN":
                return None
            full = action.fraction >= 0.999
            qty = pos.quantity if full else pos.quantity * action.fraction
            if self.is_exchange:
                if self.exec is None:
                    raise OrderRejected(f"Borsa bağlantısı yok: {self.exec_error or 'bilinmiyor'}")
                # kalan miktar veya satılacak miktar asgari tutarın altında kalacaksa pozisyonun tamamı kapatılır
                if not full and info and info.min_notional > 0:
                    px = action.ref_price
                    if qty * px < info.min_notional * 1.05 or (pos.quantity - qty) * px < info.min_notional * 1.05:
                        full, qty = True, pos.quantity
                fill = await self.exec.sell(pos.symbol, qty, action.ref_price, info, full)
            else:
                fill = self.broker.sell(action.order_type, action.ref_price, qty, s)
            proceeds = fill.cost
            sold = fill.qty
            closing = full or pos.quantity - sold <= pos.initial_quantity * 1e-9
            if closing:
                # kapanışta kalan maliyetin TAMAMI bu satışa yazılır (adım büyüklüğü tozu dahil) => kayıtlar borsadaki nakit akışıyla birebir eşleşir
                cost_part = pos.cost_total - (pos.proceeds_total - pos.realized_pnl)
            else:
                cost_part = pos.cost_total * (sold / pos.initial_quantity)
            pnl = proceeds - cost_part

            pos.quantity -= sold
            pos.proceeds_total += proceeds
            pos.fees_total += fill.fee
            pos.realized_pnl += pnl
            if action.reason == "TAKE_PROFIT_1" and not full:
                pos.tp1_done = True
            dust = pos.quantity <= pos.initial_quantity * 1e-9 or (self.is_exchange and full)
            if full or dust:
                pos.quantity = 0.0
                pos.status = "CLOSED"
                pos.closed_at = utcnow()
                pos.close_reason = action.reason
            ses.add(Order(position_id=pos.id, symbol=pos.symbol, mode=self.mode, side="SELL", order_type="MARKET" if self.is_exchange else action.order_type,
                          quantity=fill.qty, price=fill.price, fee=fill.fee, reason=action.reason, exchange_order_id=fill.order_id or None))
            if not self.is_exchange:
                acc = await kv_get(ses, ACCOUNT_KEY)
                acc["cash"] += proceeds
                await kv_set(ses, ACCOUNT_KEY, acc)
            await ses.commit()
        if self.is_exchange:
            await self.refresh_exchange_cash()
        log.info("SATIŞ [%s] %s [%s]: %.6g adet @ %.8g, bu satışın net sonucu %+.4f USDT", self.mode_label, pos.symbol, action.reason, fill.qty, fill.price, pnl)
        return pos

    async def update_position_state(self, position_id: int, peak: float, trailing_active: bool) -> None:
        async with self.db.session() as ses:
            pos = await ses.get(Position, position_id)
            if pos and pos.status == "OPEN" and (pos.peak_price != peak or pos.trailing_active != trailing_active):
                pos.peak_price, pos.trailing_active = peak, trailing_active
                await ses.commit()

    async def close_all(self, prices: dict[str, float], reason: str, s: TradingSettings, symbols: dict | None = None) -> int:
        n = 0
        for p in await self.open_positions():
            price = prices.get(p.symbol)
            if not price:
                continue
            try:
                await self.execute_exit(p.id, ExitAction(1.0, reason, "MARKET", price), s, (symbols or {}).get(p.symbol))
                n += 1
            except (OrderRejected, Exception) as e:  # bir pozisyon kapanamazsa diğerlerini kapatmayı sürdür
                log.error("%s kapatılamadı: %s", p.symbol, e)
        return n

    async def reset_account(self, s: TradingSettings) -> None:
        """Sanal hesabı sıfırlar: yalnızca paper modunda ve yalnızca paper kayıtlarını siler."""
        if self.is_exchange:
            raise ValueError("Borsa modunda sıfırlama yapılamaz")
        async with self.db.session() as ses:
            ids = [r[0] for r in await ses.execute(select(Position.id).where(Position.mode == "paper"))]
            if ids:
                await ses.execute(delete(Order).where(Order.position_id.in_(ids)))
            await ses.execute(delete(Position).where(Position.mode == "paper"))
            await ses.execute(delete(EquitySnapshot).where(EquitySnapshot.mode == "paper"))
            await kv_set(ses, ACCOUNT_KEY, {"cash": s.initial_balance, "initial": s.initial_balance})
            await kv_set(ses, DAY_KEY, {"date": today_str(), "start_equity": s.initial_balance})
            await ses.commit()
        log.warning("Sanal hesap sıfırlandı: bakiye %.2f USDT", s.initial_balance)
