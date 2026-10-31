"""Bildirimler: panel içi bildirim merkezi + (isteğe bağlı) Telegram. Sır içeren hiçbir şey yazılmaz."""
from __future__ import annotations

import logging
import time

import httpx

from .logging_setup import register_secret
from .models import Notification

log = logging.getLogger("app.notify")


class Notifier:
    def __init__(self, db, telegram_token: str = "", telegram_chat: str = "", http: httpx.AsyncClient | None = None):
        self.db = db
        self.token, self.chat = telegram_token, telegram_chat
        if self.token:
            register_secret(self.token)
        self.http = http
        self._last: dict[str, float] = {}

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.token and self.chat)

    async def send(self, kind: str, title: str, body: str = "", level: str = "info", dedupe_key: str | None = None, dedupe_sec: int = 0) -> bool:
        """dedupe_key + dedupe_sec: aynı bildirimin kısa sürede tekrarını engeller."""
        if dedupe_key and dedupe_sec:
            if time.time() - self._last.get(dedupe_key, 0) < dedupe_sec:
                return False
            self._last[dedupe_key] = time.time()
        async with self.db.session() as ses:
            ses.add(Notification(kind=kind, level=level, title=title[:120], body=body))
            await ses.commit()
        if self.telegram_enabled:
            await self._telegram(f"*{title}*\n{body}".strip())
        return True

    async def _telegram(self, text: str) -> None:
        client = self.http or httpx.AsyncClient(timeout=10)
        try:
            r = await client.post(f"https://api.telegram.org/bot{self.token}/sendMessage",
                                  json={"chat_id": self.chat, "text": text[:3900], "parse_mode": "Markdown"})
            if r.status_code != 200:
                log.warning("Telegram gönderimi başarısız (HTTP %s)", r.status_code)
        except Exception as e:  # bildirim hatası işlemi durdurmaz
            log.warning("Telegram gönderimi başarısız: %s", type(e).__name__)
        finally:
            if self.http is None:
                await client.aclose()
