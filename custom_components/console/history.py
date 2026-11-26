"""The chat card's history: what was said in Console's chat, kept on this box so a conversation is
still there after a reload, with earlier messages a pull away.

It is a file of its own (.storage/console_chat), apart from Console's store, and it never leaves the
box: it is in nothing the relay reads. Each signed-in Home Assistant person has their own history. They
see how much is kept, and can delete it, on the Console page under "What the house knows about you";
erasing Console's data erases all of it. Each person's history stops at the newest 400 messages.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

KEEP = 400
PAGE = 10
TEXT_MAX = 8000


class ChatHistory:
    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[dict[str, Any]] = Store(hass, 1, "console_chat", private=True)
        self.people: dict[str, list[dict[str, Any]]] = {}

    async def async_load(self) -> None:
        self.people = (await self._store.async_load() or {}).get("people", {})

    def _save(self) -> None:
        self._store.async_delay_save(lambda: {"people": self.people}, 3)

    def add(self, user_id: str, who: str, text: str, **extra: Any) -> None:
        if not user_id or not text:
            return
        mine = self.people.setdefault(user_id, [])
        mine.append({"at": datetime.now(UTC).isoformat(), "who": who, "text": text[:TEXT_MAX]} | extra)
        del mine[:-KEEP]
        self._save()

    def page(self, user_id: str, before: int | None = None, limit: int = PAGE) -> dict[str, Any]:
        """Up to `limit` messages ending just before index `before` (the newest when None), oldest first."""
        mine = self.people.get(user_id, [])
        end = len(mine) if before is None else max(0, min(before, len(mine)))
        start = max(0, end - limit)
        return {"messages": mine[start:end], "from": start, "more": start > 0, "total": len(mine)}

    def last(self, user_id: str, count: int) -> list[dict[str, Any]]:
        return self.people.get(user_id, [])[-count:] if count > 0 else []

    def count(self, user_id: str) -> int:
        return len(self.people.get(user_id, []))

    def total(self) -> int:
        return sum(len(messages) for messages in self.people.values())

    def clear(self, user_id: str) -> int:
        gone = len(self.people.pop(user_id, []))
        self._save()
        return gone

    async def async_erase(self) -> int:
        gone = self.total()
        self.people = {}
        await self._store.async_remove()
        return gone
