"""The chat card's history: every chat a person has had with Console, each one a thread of its own.

A thread holds what was said and, with each of Console's replies, the work behind it (where the request
went, the thinking, each tool and what came back), so opening a chat again shows the whole of it.

It is a file of its own (.storage/console_chat), apart from Console's store, and it never leaves the
box: it is in nothing the relay reads. Each signed-in Home Assistant person has their own threads. They
see how much is kept, and can delete a thread or all of it, in Console settings under "What the house
knows about you"; erasing Console's data erases all of it. Each person keeps their newest THREADS chats,
and each chat its newest KEEP messages.
"""

from __future__ import annotations

from datetime import UTC, datetime
import secrets
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

KEEP = 200  # messages in one thread
THREADS = 40  # threads per person
PAGE = 10
TEXT_MAX = 8000
TITLE_MAX = 60
EARLIER = "Earlier messages"  # the thread a history from before threads is moved into


def new_id() -> str:
    """A thread's id, which is also its conversation id in Home Assistant. Not a ULID on purpose: Home
    Assistant keeps an id it didn't make itself, so a thread keeps one id for as long as it lives."""
    return f"console-{secrets.token_hex(8)}"


def _title(text: str) -> str:
    line = " ".join(str(text or "").split())
    return line if len(line) <= TITLE_MAX else line[: TITLE_MAX - 1].rstrip() + "…"


class ChatHistory:
    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[dict[str, Any]] = Store(hass, 1, "console_chat", private=True)
        self.people: dict[str, list[dict[str, Any]]] = {}  # user id -> threads, oldest first

    async def async_load(self) -> None:
        stored = (await self._store.async_load() or {}).get("people", {})
        self.people = {user_id: self._threads(kept) for user_id, kept in stored.items()}

    @staticmethod
    def _threads(kept: Any) -> list[dict[str, Any]]:
        """A person's threads as stored. A history from before threads (one flat list of messages) becomes
        one thread, so nothing a person had is lost."""
        if not isinstance(kept, list) or not kept:
            return []
        if "messages" in kept[0]:
            return kept
        return [{"id": new_id(), "title": EARLIER, "made": kept[0].get("at"), "at": kept[-1].get("at"), "messages": kept[-KEEP:]}]

    def _save(self) -> None:
        self._store.async_delay_save(lambda: {"people": self.people}, 3)

    # --- threads ----------------------------------------------------------------------------------

    def _thread(self, user_id: str, thread_id: str | None) -> dict[str, Any] | None:
        return next((t for t in self.people.get(user_id, []) if t["id"] == thread_id), None)

    def newest(self, user_id: str) -> dict[str, Any] | None:
        mine = self.people.get(user_id, [])
        return max(mine, key=lambda t: t.get("at") or "") if mine else None

    def threads(self, user_id: str) -> list[dict[str, Any]]:
        """This person's chats, the one used last first: id, title, when, how many messages, the last line."""
        rows = []
        for thread in self.people.get(user_id, []):
            last = thread["messages"][-1] if thread["messages"] else {}
            rows.append({"id": thread["id"], "title": thread["title"], "at": thread.get("at"), "made": thread.get("made"),
                         "count": len(thread["messages"]), "last": _title(last.get("text") or "")})
        return sorted(rows, key=lambda row: row["at"] or "", reverse=True)

    def add(self, user_id: str, who: str, text: str, thread_id: str | None = None, **extra: Any) -> str | None:
        """Add one message to a thread (a new thread when it names none, or one that isn't there).
        Returns the thread's id."""
        if not user_id or not text:
            return thread_id
        now = datetime.now(UTC).isoformat()
        thread = self._thread(user_id, thread_id) if thread_id else None
        if thread is None:
            thread = {"id": thread_id or new_id(), "title": _title(text) if who == "you" else "", "made": now, "at": now, "messages": []}
            mine = self.people.setdefault(user_id, [])
            mine.append(thread)
            if len(mine) > THREADS:  # the chats used longest ago go first
                mine.sort(key=lambda t: t.get("at") or "")
                del mine[:-THREADS]
        if not thread["title"] and who == "you":
            thread["title"] = _title(text)
        thread["messages"].append({"at": now, "who": who, "text": text[:TEXT_MAX]} | {k: v for k, v in extra.items() if v})
        del thread["messages"][:-KEEP]
        thread["at"] = now
        self._save()
        return thread["id"]

    def page(self, user_id: str, thread_id: str | None = None, before: int | None = None, limit: int = PAGE) -> dict[str, Any]:
        """Up to `limit` messages of one thread ending just before index `before` (the newest when None),
        oldest first. With no thread named: the one this person used last."""
        thread = self._thread(user_id, thread_id) if thread_id else self.newest(user_id)
        if thread is None:
            return {"thread_id": thread_id, "title": "", "messages": [], "from": 0, "more": False, "total": 0}
        messages = thread["messages"]
        end = len(messages) if before is None else max(0, min(before, len(messages)))
        start = max(0, end - limit)
        return {"thread_id": thread["id"], "title": thread["title"], "at": thread.get("at"), "messages": messages[start:end],
                "from": start, "more": start > 0, "total": len(messages)}

    def context(self, user_id: str, thread_id: str, count: int) -> list[dict[str, Any]]:
        """The last `count` messages of a thread, for the model to pick the conversation up from."""
        thread = self._thread(user_id, thread_id)
        return thread["messages"][-count:] if thread and count > 0 else []

    def last(self, user_id: str, count: int) -> list[dict[str, Any]]:
        """This person's newest `count` messages across all their chats, oldest first."""
        return self.everything(user_id)[-count:] if count > 0 else []

    def everything(self, user_id: str) -> list[dict[str, Any]]:
        messages = [m for thread in self.people.get(user_id, []) for m in thread["messages"]]
        return sorted(messages, key=lambda m: m.get("at") or "")

    def count(self, user_id: str) -> int:
        return sum(len(thread["messages"]) for thread in self.people.get(user_id, []))

    def total(self) -> int:
        return sum(self.count(user_id) for user_id in self.people)

    def delete(self, user_id: str, thread_id: str) -> int:
        """Delete one of this person's chats. Returns how many messages went with it."""
        thread = self._thread(user_id, thread_id)
        if thread is None:
            return 0
        self.people[user_id] = [t for t in self.people[user_id] if t["id"] != thread_id]
        self._save()
        return len(thread["messages"])

    def clear(self, user_id: str) -> int:
        gone = self.count(user_id)
        self.people.pop(user_id, None)
        self._save()
        return gone

    async def async_erase(self) -> int:
        gone = self.total()
        self.people = {}
        await self._store.async_remove()
        return gone
