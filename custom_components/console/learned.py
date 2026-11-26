"""Learned sentences: phrasings this household says often, promoted to Home Assistant's local agent.

When the cloud agent has answered the same plain command the same way three times (one confirmed
action on the same things), Console teaches the sentence to Home Assistant's own agent as a sentence
trigger. From then on it runs at home: no model, no internet, no cost. Each learned sentence is listed
on the Console page and can be removed there.

Until a sentence is learned, Console keeps only a hash of it and a count, never the words.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import hashlib
import json
import logging
import re
from typing import Any
import uuid

from homeassistant.core import Context, HomeAssistant, callback

LEARN_AFTER = 3
SAFE_DOMAINS = ("light", "switch", "fan", "scene", "input_boolean", "media_player")
MAX_PHRASES = 400
_LOGGER = logging.getLogger(__name__)
_STRIP = re.compile(r"[^\w\s'%-]")


def normalize(text: str) -> str:
    """The sentence as Home Assistant's matcher wants it: lower case, no punctuation, single spaces."""
    return re.sub(r"\s+", " ", _STRIP.sub(" ", (text or "").lower())).strip()


def _signature(action: str, entity_ids: list[str], data: dict[str, Any]) -> str:
    return json.dumps([action, sorted(entity_ids), data], sort_keys=True)


class Learned:
    def __init__(self, hass: HomeAssistant, data) -> None:
        self.hass = hass
        self.data = data
        self._unregister: dict[str, Callable[[], None]] = {}

    @property
    def items(self) -> list[dict[str, Any]]:
        return self.data.data["learned"]

    @callback
    def start(self) -> None:
        for item in self.items:
            self._register(item)

    @callback
    def stop(self) -> None:
        for unregister in self._unregister.values():
            unregister()
        self._unregister.clear()

    def _register(self, item: dict[str, Any]) -> None:
        from homeassistant.components.conversation.agent_manager import get_agent_manager  # noqa: PLC0415

        async def run(user_input, result) -> str | None:
            return await self._run(item, user_input.context)

        try:
            self._unregister[item["id"]] = get_agent_manager(self.hass).register_trigger([item["sentence"]], run)
        except Exception:  # noqa: BLE001 (a sentence the matcher can't parse is skipped, not fatal)
            _LOGGER.warning("Console: a learned sentence couldn't be registered and was skipped")

    async def _run(self, item: dict[str, Any], context: Context | None) -> str:
        domain, _, service = item["action"].partition(".")
        await self.hass.services.async_call(
            domain, service, {**item.get("data", {}), "entity_id": item["entity_ids"]}, blocking=True, context=context
        )
        item["uses"] = int(item.get("uses", 0)) + 1
        self.data.changed()
        return f"Done. {item.get('names') or 'That'}."

    @callback
    def observe(self, text: str, calls: list, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        """A plain command the cloud agent just did and confirmed. Counts it; returns the new learned
        sentence when this was the time that tipped it."""
        if len(calls) != 1 or calls[0].tool_name.rsplit("__", 1)[-1] != "act":
            return None
        args = calls[0].tool_args or {}
        action, entity_ids, extra = str(args.get("action") or ""), list(args.get("entity_ids") or []), dict(args.get("data") or {})
        sentence = normalize(text)
        if (
            not sentence
            or len(sentence.split()) < 2
            or action.partition(".")[0] not in SAFE_DOMAINS
            or not entity_ids
            or any(eid.partition(".")[0] not in SAFE_DOMAINS for eid in entity_ids)
            or any(item["sentence"] == sentence for item in self.items)
        ):
            return None
        key = hashlib.sha256(sentence.encode()).hexdigest()[:24]
        phrases = self.data.data["phrases"]
        signature = _signature(action, entity_ids, extra)
        seen = phrases.get(key)
        if not seen or seen.get("sig") != signature:
            seen = phrases[key] = {"sig": signature, "count": 0}
        seen["count"] += 1
        seen["last"] = datetime.now(UTC).isoformat()
        if len(phrases) > MAX_PHRASES:
            for old in sorted(phrases, key=lambda k: phrases[k].get("last", ""))[: len(phrases) - MAX_PHRASES]:
                del phrases[old]
        self.data.changed()
        if seen["count"] < LEARN_AFTER:
            return None
        del phrases[key]
        item = {
            "id": uuid.uuid4().hex[:12],
            "sentence": sentence,
            "action": action,
            "entity_ids": entity_ids,
            "data": extra,
            "names": ", ".join(str(row.get("name") or row.get("id")) for row in rows[:4]),
            "learned_at": datetime.now(UTC).isoformat(),
            "uses": 0,
        }
        self.items.append(item)
        self._register(item)
        self.data.changed()
        return item

    @callback
    def forget(self, item_id: str) -> bool:
        for item in list(self.items):
            if item["id"] == item_id:
                self.items.remove(item)
                if unregister := self._unregister.pop(item_id, None):
                    unregister()
                self.data.changed()
                return True
        return False
