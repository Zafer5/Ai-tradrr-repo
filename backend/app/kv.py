"""KV tablosu için küçük yardımcılar."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from .models import KV


async def kv_get(session, key: str, default: Any = None) -> Any:
    row = (await session.execute(select(KV).where(KV.key == key))).scalar_one_or_none()
    return json.loads(row.value) if row else default


async def kv_set(session, key: str, value: Any) -> None:
    row = (await session.execute(select(KV).where(KV.key == key))).scalar_one_or_none()
    payload = json.dumps(value)
    if row:
        row.value = payload
    else:
        session.add(KV(key=key, value=payload))
