"""Günlükleme: gizli bilgileri maskeler, önemli kayıtları veritabanına yazar (Sistem Günlükleri ekranı)."""
from __future__ import annotations

import asyncio
import logging
import re
from collections import deque

from .models import LogEntry

_PATTERNS = [
    (re.compile(r"(signature=)[0-9a-fA-F]{16,}"), r"\1***"),
    (re.compile(r"(X-MBX-APIKEY['\"]?\s*[:=]\s*['\"]?)[A-Za-z0-9]{10,}", re.I), r"\1***"),
    (re.compile(r"(api[_-]?key|api[_-]?secret|secret|password|şifre)(['\"]?\s*[:=]\s*['\"]?)[^\s,'\"&]+", re.I), r"\1\2***"),
]
_known_secrets: set[str] = set()


def register_secret(value: str) -> None:
    if value and len(value) >= 8:
        _known_secrets.add(value)


def redact(text: str) -> str:
    for pat, repl in _PATTERNS:
        text = pat.sub(repl, text)
    for s in _known_secrets:
        text = text.replace(s, "***")
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact(record.getMessage())
            record.args = ()
        except Exception:  # pragma: no cover
            pass
        return True


class DBLogHandler(logging.Handler):
    """Kayıtları kuyruğa alır; arka plan görevi toplu olarak veritabanına yazar."""

    def __init__(self, level=logging.INFO):
        super().__init__(level)
        self.queue: asyncio.Queue | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.recent: deque = deque(maxlen=300)

    def emit(self, record: logging.LogRecord) -> None:
        if not record.name.startswith("app"):
            return
        item = (record.levelname, record.name.removeprefix("app.") or "app", record.getMessage())
        self.recent.append(item)
        if self.queue is not None and self.loop is not None:
            try:
                self.loop.call_soon_threadsafe(self.queue.put_nowait, item)
            except RuntimeError:  # döngü kapanmış
                pass

    async def run_writer(self, db) -> None:
        self.loop = asyncio.get_running_loop()
        self.queue = asyncio.Queue(maxsize=5000)
        while True:
            batch = [await self.queue.get()]
            while not self.queue.empty() and len(batch) < 200:
                batch.append(self.queue.get_nowait())
            try:
                async with db.session() as s:
                    s.add_all(LogEntry(level=lv, source=src, message=msg[:2000]) for lv, src, msg in batch)
                    await s.commit()
            except Exception:  # pragma: no cover - günlük hatası uygulamayı durdurmasın
                pass
            await asyncio.sleep(1)


def setup_logging(level: str = "INFO") -> DBLogHandler:
    root = logging.getLogger()
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    for h in list(root.handlers):
        root.removeHandler(h)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    console.addFilter(RedactingFilter())
    root.addHandler(console)
    dbh = DBLogHandler()
    dbh.addFilter(RedactingFilter())
    root.addHandler(dbh)
    # İstek adreslerinde imza/parametre sızmasın
    for noisy in ("httpx", "httpcore", "websockets", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return dbh
