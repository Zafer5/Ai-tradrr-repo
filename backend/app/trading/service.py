"""Paper Trading: sanal hesap, sanal dolumlar ve pozisyon kayıtları.

Dolum modeli (gerçekçi ama basitleştirilmiş):
* Alım: piyasa emri => en iyi satış fiyatı (ask) + kayma; komisyon USDT olarak düşülür.
* Hedef satışı: limit emri => hedef fiyattan dolar (daha iyi fiyat varsayılmaz), komisyon düşülür.
* Stop satışı: piyasa emri => gözlenen fiyat - kayma; komisyon düşülür.
Not: Gerçek Binance'te komisyon çoğunlukla alınan coinden kesilir; burada sadeleştirme için USDT kabul edilmiştir.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from ..kv import kv_get, kv_set
from ..models import EquitySnapshot, Order, Position, utcnow
from ..risk.manager import AccountSnapshot, RiskDecision
from ..trading_settings import TradingSettings
from .exits import ExitAction

log = logging.getLogger("app.trading")
TZ = ZoneInfo("Europe/Istanbul")
ACCOUNT_KEY = "paper_account"
DAY_KEY = "day_state"


@dataclass
class Fill:
    price: float
    qty: float
    fee: float


class PaperBroker:
    mode = "paper"

    @staticmethod
    def buy(ref_ask: float, qty: float, s: TradingSettings) -> Fill:
        price = ref_ask * (1 + s.slippage_pct / 100)
        return Fill(price, qty, price * qty * s.fee_rate_pct / 100)

    @staticmethod
    def sell(order_type: str, ref_price: float, qty: float, s: TradingSettings) -> Fill:
        price = ref_price * (1 - s.slippage_pct / 100) if order_type == "MARKET" else ref_price
        return Fill(price, qty, price * qty * s.fee_rate_pct / 100)


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

    # ------------------------------------------------------------------ hesap
    async def ensure_account(self) -> None:
        async with self.db.session() as ses:
            if await kv_get(ses, ACCOUNT_KEY) is None:
                s = await self.store.get()
                await kv_set(ses, ACCOUNT_KEY, {"cash": s.initial_balance, "initial": s.initial_balance})
                await kv_set(ses, DAY_KEY, {"date": today_str(), "start_equity": s.initial_balance})
                await ses.commit()

    async def account(self) -> dict:
        async with self.db.session() as ses:
            acc = await kv_get(ses, ACCOUNT_KEY)
        if acc is None:
            await self.ensure_account()
            return await self.account()
        return acc

    async def open_positions(self) -> list[Position]:
        async with self.db.session() as ses:
            return list((await ses.execute(select(Position).where(Position.status == "OPEN").order_by(Position.id))).scalars())

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
            trades_today = (
                await ses.execute(select(func.count(Position.id)).where(Position.opened_at >= day_start_utc()))
            ).scalar_one()
            cool = set()
            if cooldown_minutes > 0:
                since = utcnow() - timedelta(minutes=cooldown_minutes)
                rows = await ses.execute(select(Position.symbol).where(Position.status == "CLOSED", Position.closed_at >= since))
                cool = {r[0] for r in rows}
        day_pnl_pct = (equity - start) / start * 100 if start > 0 else 0.0
        return AccountSnapshot(equity, cash, open_pos, day_pnl_pct, trades_today, cool, in_flight)

    # ------------------------------------------------------------------ alım
    async def open_position(self, symbol: str, ask: float, dec: RiskDecision, stop: float, tp1: float, tp2: float,
                            score: float, risk_level: str, rationale: str, s: TradingSettings) -> Position | None:
        fill = self.broker.buy(ask, dec.quantity, s)
        cost = fill.price * fill.qty + fill.fee
        async with self.db.session() as ses:
            acc = await kv_get(ses, ACCOUNT_KEY)
            if cost > acc["cash"]:
                log.warning("%s alımı iptal: nakit yetersiz (%.2f > %.2f)", symbol, cost, acc["cash"])
                return None
            pos = Position(
                symbol=symbol, mode="paper", status="OPEN", entry_price=fill.price, quantity=fill.qty,
                initial_quantity=fill.qty, cost_total=cost, stop_price=stop, tp1_price=tp1, tp2_price=tp2,
                peak_price=fill.price, est_fees=fill.fee + fill.qty * tp1 * s.fee_rate_pct / 100, fees_total=fill.fee,
                score=score, risk_level=risk_level, rationale=rationale,
            )
            ses.add(pos)
            await ses.flush()
            ses.add(Order(position_id=pos.id, symbol=symbol, mode="paper", side="BUY", order_type="MARKET",
                          quantity=fill.qty, price=fill.price, fee=fill.fee, reason="ENTRY"))
            acc["cash"] -= cost
            await kv_set(ses, ACCOUNT_KEY, acc)
            await ses.commit()
        log.info("ALIM %s: %.6g adet @ %.8g (stop %.8g, hedef1 %.8g, hedef2 %.8g, puan %.0f)",
                 symbol, fill.qty, fill.price, stop, tp1, tp2, score)
        return pos

    # ------------------------------------------------------------------ satım
    async def execute_exit(self, position_id: int, action: ExitAction, s: TradingSettings) -> Position | None:
        async with self.db.session() as ses:
            pos = await ses.get(Position, position_id)
            if pos is None or pos.status != "OPEN":
                return None
            qty = pos.quantity if action.fraction >= 0.999 else pos.quantity * action.fraction
            fill = self.broker.sell(action.order_type, action.ref_price, qty, s)
            proceeds = fill.price * fill.qty - fill.fee
            cost_part = pos.cost_total * (qty / pos.initial_quantity)
            pnl = proceeds - cost_part

            pos.quantity -= qty
            pos.proceeds_total += proceeds
            pos.fees_total += fill.fee
            pos.realized_pnl += pnl
            if action.reason == "TAKE_PROFIT_1":
                pos.tp1_done = True
            if action.fraction >= 0.999 or pos.quantity <= pos.initial_quantity * 1e-9:
                pos.quantity = 0.0
                pos.status = "CLOSED"
                pos.closed_at = utcnow()
                pos.close_reason = action.reason
            ses.add(Order(position_id=pos.id, symbol=pos.symbol, mode="paper", side="SELL", order_type=action.order_type,
                          quantity=fill.qty, price=fill.price, fee=fill.fee, reason=action.reason))
            acc = await kv_get(ses, ACCOUNT_KEY)
            acc["cash"] += proceeds
            await kv_set(ses, ACCOUNT_KEY, acc)
            await ses.commit()
        log.info("SATIŞ %s [%s]: %.6g adet @ %.8g, bu satışın net sonucu %+.4f USDT", pos.symbol, action.reason, fill.qty, fill.price, pnl)
        return pos

    async def update_position_state(self, position_id: int, peak: float, trailing_active: bool) -> None:
        async with self.db.session() as ses:
            pos = await ses.get(Position, position_id)
            if pos and pos.status == "OPEN" and (pos.peak_price != peak or pos.trailing_active != trailing_active):
                pos.peak_price, pos.trailing_active = peak, trailing_active
                await ses.commit()

    async def close_all(self, prices: dict[str, float], reason: str, s: TradingSettings) -> int:
        n = 0
        for p in await self.open_positions():
            price = prices.get(p.symbol)
            if price:
                await self.execute_exit(p.id, ExitAction(1.0, reason, "MARKET", price), s)
                n += 1
        return n

    async def reset_account(self, s: TradingSettings) -> None:
        """Sanal hesabı sıfırlar: tüm pozisyon/emir kayıtları silinir (yalnızca paper modunda)."""
        from sqlalchemy import delete

        async with self.db.session() as ses:
            await ses.execute(delete(Order))
            await ses.execute(delete(Position))
            await ses.execute(delete(EquitySnapshot))
            await kv_set(ses, ACCOUNT_KEY, {"cash": s.initial_balance, "initial": s.initial_balance})
            await kv_set(ses, DAY_KEY, {"date": today_str(), "start_equity": s.initial_balance})
            await ses.commit()
        log.warning("Sanal hesap sıfırlandı: bakiye %.2f USDT", s.initial_balance)
