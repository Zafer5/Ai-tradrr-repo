"""Günlük özet raporu (Türkçe)."""
from __future__ import annotations

from sqlalchemy import func, select

from .models import Order, Position
from .trading.exits import REASON_TR
from .trading.service import TZ, as_utc, day_start_utc


async def build_daily_report(db, service, prices: dict[str, float]) -> tuple[str, str]:
    equity, cash, open_value = await service.equity(prices)
    start = await service.roll_day(equity)
    async with db.session() as ses:
        closed = list((await ses.execute(select(Position).where(Position.closed_at >= day_start_utc()))).scalars())
        opened = (await ses.execute(select(func.count(Position.id)).where(Position.opened_at >= day_start_utc()))).scalar_one()
        fees = (await ses.execute(select(func.coalesce(func.sum(Order.fee), 0.0)).where(Order.created_at >= day_start_utc()))).scalar_one()
    realized = sum(p.realized_pnl for p in closed)
    wins = sum(1 for p in closed if p.realized_pnl > 0)
    day = equity - start
    lines = [
        f"Özkaynak: {equity:.2f} USDT ({day:+.2f} bugün, %{(day / start * 100 if start else 0):+.2f})",
        f"Bugün açılan: {opened} · kapanan: {len(closed)} ({wins} kâr / {len(closed) - wins} zarar)",
        f"Gerçekleşen net: {realized:+.3f} USDT · komisyon {fees:.3f} USDT",
        f"Açık pozisyon değeri: {open_value:.2f} USDT",
    ]
    for p in closed[-5:]:
        lines.append(f"• {p.symbol.replace('USDT', '')}: {p.realized_pnl:+.3f} USDT ({REASON_TR.get(p.close_reason or '', p.close_reason)})")
    return "Günlük rapor (sanal işlemler)", "\n".join(lines)
