"""Mevcut coin portföyü: kayıt, Binance'ten salt okunur senkronizasyon, karar uygulama (öneri / gölge)."""
from __future__ import annotations

import logging
import time

from sqlalchemy import delete, select

from ..exchange.binance import BinanceClient
from ..exchange.types import SymbolInfo
from ..models import Holding, PortfolioAction, utcnow
from ..trading_settings import TradingSettings
from .costbasis import compute_cost_basis, history_matches
from .manager import HoldingDecision, HoldingState, MarketView, decide

log = logging.getLogger("app.portfolio")
IGNORE_ASSETS = {"USDT", "USDC", "FDUSD", "BUSD", "TUSD", "DAI", "USDP", "EUR", "TRY", "BRL"}
MIN_VALUE_USDT = 1.0  # toz bakiyeleri yok say


class PortfolioService:
    def __init__(self, db, notifier):
        self.db = db
        self.notifier = notifier
        self._last_action: dict[tuple[str, str], float] = {}

    async def holdings(self, include_zero: bool = False) -> list[Holding]:
        async with self.db.session() as ses:
            rows = list((await ses.execute(select(Holding).order_by(Holding.asset))).scalars())
        return rows if include_zero else [h for h in rows if h.quantity > 0]

    async def symbols(self) -> set[str]:
        return {h.symbol for h in await self.holdings()}

    # ------------------------------------------------------------------ elle kayıt
    async def upsert_manual(self, asset: str, quantity: float, avg_cost: float, note: str = "", quote: str = "USDT") -> Holding:
        asset = asset.upper().strip()
        async with self.db.session() as ses:
            h = (await ses.execute(select(Holding).where(Holding.asset == asset))).scalar_one_or_none()
            if h is None:
                h = Holding(asset=asset, symbol=asset + quote, quantity=quantity, avg_cost=avg_cost, cost_known=avg_cost > 0, source="manual", note=note)
                ses.add(h)
            else:
                h.quantity, h.avg_cost, h.cost_known, h.note = quantity, avg_cost, avg_cost > 0, note
                h.tp_done = False  # kullanıcı pozisyonu güncelledi: yeniden değerlendirilir
                h.updated_at = utcnow()
            await ses.commit()
        return h

    async def set_managed(self, asset: str, managed: bool) -> bool:
        async with self.db.session() as ses:
            h = (await ses.execute(select(Holding).where(Holding.asset == asset.upper()))).scalar_one_or_none()
            if not h:
                return False
            h.managed = managed
            await ses.commit()
        return True

    async def delete(self, asset: str) -> None:
        async with self.db.session() as ses:
            await ses.execute(delete(Holding).where(Holding.asset == asset.upper()))
            await ses.commit()

    # ------------------------------------------------------------------ Binance salt okunur senkronizasyon
    async def sync_from_binance(self, client: BinanceClient, symbols: dict[str, SymbolInfo], prices: dict[str, float]) -> dict:
        """Bakiyeleri okur, myTrades'ten maliyeti hesaplar. Geçmiş eksikse maliyeti 'bilinmiyor' bırakır (elle girilir).
        YALNIZCA OKUR: hiçbir emir göndermez."""
        acc = await client.account()
        report = {"found": 0, "cost_ok": 0, "cost_missing": [], "skipped": []}
        seen = set()
        for b in acc.get("balances", []):
            asset, qty = b["asset"], float(b["free"]) + float(b["locked"])
            if qty <= 0 or asset in IGNORE_ASSETS:
                continue
            sym = asset + "USDT"
            info = symbols.get(sym)
            px = prices.get(sym)
            if not info or not px:
                report["skipped"].append(asset)
                continue
            if qty * px < MIN_VALUE_USDT:
                continue
            report["found"] += 1
            seen.add(asset)
            cost_known, avg, realized, fees = False, 0.0, 0.0, 0.0
            try:
                cb = compute_cost_basis(await client.my_trades(sym), asset)
                if history_matches(cb.quantity, qty):
                    cost_known, avg, realized, fees = cb.avg_cost > 0, cb.avg_cost, cb.realized_pnl, cb.fees_usdt
            except Exception as e:  # tek coin hatası tümünü durdurmasın
                log.warning("%s geçmiş alımları okunamadı: %s", asset, e)
            async with self.db.session() as ses:
                h = (await ses.execute(select(Holding).where(Holding.asset == asset))).scalar_one_or_none()
                if h is None:
                    h = Holding(asset=asset, symbol=sym, quantity=qty, source="binance")
                    ses.add(h)
                h.quantity, h.symbol, h.source, h.updated_at = qty, sym, "binance", utcnow()
                if cost_known:
                    h.avg_cost, h.cost_known, h.realized_pnl, h.fees_paid = avg, True, realized, fees
                    report["cost_ok"] += 1
                elif not h.cost_known:
                    report["cost_missing"].append(asset)
                await ses.commit()
        async with self.db.session() as ses:  # artık hesapta olmayanlar
            for h in (await ses.execute(select(Holding).where(Holding.source == "binance"))).scalars():
                if h.asset not in seen:
                    h.quantity = 0.0
            await ses.commit()
        log.info("Portföy senkronize edildi: %d coin, %d maliyet hesaplandı, %d maliyet eksik", report["found"], report["cost_ok"], len(report["cost_missing"]))
        return report

    # ------------------------------------------------------------------ değerleme
    def valuation(self, h: Holding, price: float | None, s: TradingSettings, mv: MarketView | None = None) -> dict:
        fee, slip = s.fee_rate_pct / 100, s.slippage_pct / 100
        px = price or 0.0
        value = h.quantity * px
        invested = h.quantity * h.avg_cost if h.cost_known else None
        unreal = (value * (1 - fee) * (1 - slip) - invested) if invested is not None and px else None
        dec = decide(HoldingState(h.quantity, h.avg_cost, h.peak_price or px, h.trailing_active, h.cost_known, h.tp_done), px, mv or MarketView(), s) if px else None
        return {
            "asset": h.asset, "symbol": h.symbol, "quantity": h.quantity, "avg_cost": h.avg_cost if h.cost_known else None,
            "price": price, "value": value, "invested": invested, "unrealized_pnl": unreal,
            "unrealized_pct": (unreal / invested * 100) if unreal is not None and invested else None,
            "realized_pnl": h.realized_pnl, "fees_paid": h.fees_paid, "source": h.source, "managed": h.managed,
            "cost_known": h.cost_known, "note": h.note,
            "target_price": dec.target_price if dec else None, "trail_stop": dec.trail_stop if dec else None,
            "trailing_active": h.trailing_active, "risk": mv.risk if mv else None,
            "decision": dec.action if dec else None, "decision_text": dec.reason if dec else None,
        }

    # ------------------------------------------------------------------ yönetim döngüsü
    async def evaluate_all(self, prices: dict[str, float], views: dict[str, MarketView], s: TradingSettings) -> list[dict]:
        """Her yönetilen coin için karar üretir. watch: öneri kaydı+bildirim; manage: gölge (sanal) uygulama."""
        events = []
        if s.portfolio_mode == "off":
            return events
        for h in await self.holdings():
            px = prices.get(h.symbol)
            if not h.managed or not px:
                continue
            mv = views.get(h.symbol, MarketView())
            dec = decide(HoldingState(h.quantity, h.avg_cost, h.peak_price or px, h.trailing_active, h.cost_known, h.tp_done), px, mv, s)
            async with self.db.session() as ses:
                row = await ses.get(Holding, h.id)
                row.peak_price, row.trailing_active = dec.peak, dec.trailing_active
                row.last_decision = dec.reason
                await ses.commit()
            if dec.action in ("HOLD", "NO_COST"):
                continue
            key = (h.asset, dec.action)
            # aynı öneri/işlem 6 saat içinde tekrarlanmaz (watch: spam önleme; manage: tekrarlayan kısmi satışları önleme)
            if time.time() - self._last_action.get(key, 0) < 6 * 3600:
                continue
            self._last_action[key] = time.time()
            events.append(await self._apply(h, px, dec, s))
        return events

    async def _apply(self, h: Holding, px: float, dec: HoldingDecision, s: TradingSettings) -> dict:
        fee, slip = s.fee_rate_pct / 100, s.slippage_pct / 100
        qty = h.quantity * dec.fraction
        net = qty * px * (1 - fee) * (1 - slip) - qty * h.avg_cost
        mode = "golge" if s.portfolio_mode == "manage" else "oneri"
        async with self.db.session() as ses:
            ses.add(PortfolioAction(asset=h.asset, action=dec.action, mode=mode, fraction=dec.fraction, quantity=qty, price=px, net_pnl=net, reason=dec.reason))
            if mode == "golge":
                row = await ses.get(Holding, h.id)
                row.quantity = max(0.0, row.quantity - qty)
                if dec.action == "TAKE_PROFIT":
                    row.tp_done, row.trailing_active = True, True  # kalan miktar trailing ile korunur
                row.realized_pnl += net
                row.fees_paid += qty * px * fee
                if row.quantity <= 0:
                    row.peak_price, row.trailing_active = 0.0, False
            await ses.commit()
        label = {"TAKE_PROFIT": "Kâr realizasyonu", "TRAIL_EXIT": "Trailing stop", "REDUCE_RISK": "Risk azaltma", "STOP": "Zarar sınırı"}[dec.action]
        prefix = "GÖLGE İŞLEM (sanal)" if mode == "golge" else "ÖNERİ"
        await self.notifier.send(
            "portfolio", f"{prefix}: {h.asset} — {label}",
            f"{qty:.6g} {h.asset} @ {px:.6g} · tahmini net sonuç {net:+.2f} USDT\nNeden: {dec.reason}\n(Gerçek hesabınızda emir gönderilmedi.)",
            level="good" if net > 0 else "warn",
        )
        log.info("Portföy %s %s: %s %.6g @ %.6g (net %+.2f)", mode, dec.action, h.asset, qty, px, net)
        return {"asset": h.asset, "action": dec.action, "mode": mode}
