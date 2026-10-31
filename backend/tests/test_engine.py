import pytest
from sqlalchemy import select

from app.db import Database, Position, Trade
from app.engine import Engine

from .helpers import FakeClient


@pytest.fixture
async def engine():
    db = Database("sqlite+aiosqlite:///:memory:")
    e = Engine(FakeClient(), db, 1000.0)
    await e.init()
    await e.refresh_universe()
    yield e
    await db.dispose()


async def open_one(e):
    await e.set_running(True)
    e.settings.risk.min_score = 0
    await e.analysis_cycle()
    async with e.db.session() as s:
        return (await s.execute(select(Position))).scalars().all()


async def test_no_trades_when_bot_stopped(engine):
    engine.settings.risk.min_score = 0
    await engine.analysis_cycle()
    assert engine.latest["AAAUSDT"].tradable
    async with engine.db.session() as s:
        assert not (await s.execute(select(Position))).scalars().all()


async def test_full_cycle_take_profit_scale_out(engine):
    e = engine
    positions = await open_one(e)
    assert len(positions) == 1
    p = positions[0]
    assert p.status == "open" and p.cost_basis > 0
    st = await e.status()
    assert abs(st["cash"] - (1000 - p.cost_basis)) < 1e-3

    # mükerrer alım engeli
    await e.analysis_cycle()
    async with e.db.session() as s:
        assert len((await s.execute(select(Position))).scalars().all()) == 1

    # fiyat hedefe çıkar -> kademeli satış
    e.client.price["AAAUSDT"] = p.take_profit * 1.01
    e.prices.clear()
    await e.manage_positions()
    async with e.db.session() as s:
        p2 = await s.get(Position, p.id)
        assert p2.scaled_out and p2.status == "open"
        assert p2.stop_loss > p2.entry_price          # stop başa başa çekildi
        sells = (await s.execute(select(Trade).where(Trade.side == "SELL"))).scalars().all()
        assert len(sells) == 1 and sells[0].pnl > 0

    # fiyat düşer -> kalan kısım stop ile kapanır
    e.client.price["AAAUSDT"] = p2.entry_price * 0.99
    e.prices.clear()
    await e.manage_positions()
    async with e.db.session() as s:
        p3 = await s.get(Position, p.id)
        assert p3.status == "closed"
    rep = await e.report()
    assert rep["closed_trades"] == 1
    assert rep["net_pnl"] > 0


async def test_stop_loss(engine):
    e = engine
    p = (await open_one(e))[0]
    e.client.price["AAAUSDT"] = p.stop_loss * 0.99
    e.prices.clear()
    await e.manage_positions()
    async with e.db.session() as s:
        p2 = await s.get(Position, p.id)
        assert p2.status == "closed" and p2.exit_reason == "Stop-loss" and p2.realized_pnl < 0


async def test_emergency_stop_blocks_and_closes(engine):
    e = engine
    await open_one(e)
    closed = await e.set_emergency(True, close_positions=True)
    assert closed == 1 and not e.running
    with pytest.raises(ValueError):
        await e.set_running(True)
    await e.analysis_cycle()
    async with e.db.session() as s:
        assert all(p.status == "closed" for p in (await s.execute(select(Position))).scalars().all())


async def test_price_error_no_order(engine):
    e = engine
    await e.set_running(True)
    e.settings.risk.min_score = 0
    e.client.fail_book = True
    await e.analysis_cycle()
    async with e.db.session() as s:
        assert not (await s.execute(select(Position))).scalars().all()


async def test_settings_validation(engine):
    with pytest.raises(ValueError):
        await engine.save_settings({"risk": {"risk_per_trade_pct": 50}})
    await engine.save_settings({"risk": {"max_open_positions": 3}})
    assert engine.settings.risk.max_open_positions == 3
