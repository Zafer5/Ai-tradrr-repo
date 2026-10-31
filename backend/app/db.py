"""Asenkron veritabanı bağlantısı (SQLite ilk aşamada, PostgreSQL üretimde)."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import event, inspect, literal, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models import Base


class Database:
    def __init__(self, url: str):
        if url.startswith("sqlite"):
            path = url.split("///", 1)[-1]
            if path and path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_async_engine(url, future=True)
        if url.startswith("sqlite"):

            @event.listens_for(self.engine.sync_engine, "connect")
            def _pragmas(dbapi_conn, _):  # pragma: no cover - sürücü düzeyi
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA busy_timeout=15000")
                cur.close()

        self._maker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def create_all(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(self._add_missing_columns)

    @staticmethod
    def _add_missing_columns(conn) -> None:
        """Basit şema geçişi: mevcut tablolara sonradan eklenen sütunları ekler (veri silinmez).
        Yalnızca YENİ ve boş bırakılabilir sütunlar için tasarlanmıştır; sütun silme/yeniden adlandırma yapmaz."""
        insp = inspect(conn)
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                ddl = f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(dialect=conn.dialect)}'
                if col.default is not None and getattr(col.default, "is_scalar", False):
                    lit = literal(col.default.arg).compile(dialect=conn.dialect, compile_kwargs={"literal_binds": True})
                    ddl += f" DEFAULT {lit}"
                conn.execute(text(ddl))

    @asynccontextmanager
    async def session(self):
        async with self._maker() as s:
            yield s

    async def dispose(self) -> None:
        await self.engine.dispose()
