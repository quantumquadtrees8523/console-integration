"""Reply style: once a week, Console re-learns how each person writes to it, so its replies keep matching
them (short when they're short, casual when they're casual).

The work is Sunrise's `match-my-style` skill. This module only fires it: on Sunday morning, for each
signed-in person with enough chat to go on, one turn of Console's own agent *as that person*, so the
`chat_history` tool (tools.py) hands it that person's own messages and nobody else's. The skill writes
the result to Sunrise's memory (`reply-style.md`), whose first line every later turn sees.

What a person said stays where it always was: the chat card's history file on this box, read in that
person's own turn exactly as the earlier messages on their screen already are. Console's store keeps
only when this last ran and for how many people. The run is skipped when the cloud agent can't be used
or the month's allowance is nearly spent.
"""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change

from .const import PATH_STYLE

_LOGGER = logging.getLogger(__name__)

RUN_AT = (6, 10, 23)  # Sunday (weekday 6), 10:23 local time
MIN_MESSAGES = 15  # the skill won't write a style from fewer of a person's own messages
SKILL = "match-my-style"

RUN_PROMPT = (
    f"Weekly run of the {SKILL} skill for me. Follow it exactly (get_skill name={SKILL}), its section "
    "\"Weekly run\" included: read my own messages with the chat_history tool (Console's), compare with "
    "reply-style.md and update it only if my style really moved, then add a dated line to log.md. Nobody is "
    "waiting on this: don't change anything in the house. Reply with one line: what changed, or \"no change\"."
)


def fresh() -> dict[str, Any]:
    return {"on": True, "last_run": None}


class Style:
    def __init__(self, hass: HomeAssistant, data) -> None:
        self.hass = hass
        self.data = data
        self._stop = None
        self.running = False

    @property
    def state(self) -> dict[str, Any]:
        stored = self.data.data.setdefault("style", fresh())
        for key, value in fresh().items():
            stored.setdefault(key, value)
        return stored

    @callback
    def start(self) -> None:
        self._stop = async_track_time_change(self.hass, self._tick, hour=RUN_AT[1], minute=RUN_AT[2], second=0)

    @callback
    def stop(self) -> None:
        if self._stop:
            self._stop()
            self._stop = None

    async def _tick(self, now: datetime) -> None:
        if now.weekday() != RUN_AT[0]:
            return
        try:
            await self.run()
        except Exception:  # noqa: BLE001 (a failed week mustn't stop the next one)
            _LOGGER.exception("Console: the weekly reply-style run failed")

    def people(self) -> list[str]:
        """Signed-in people with enough of their own messages for the skill to work from."""
        history = self.data.history
        return [
            user_id
            for user_id in history.people
            if sum(1 for m in history.everything(user_id) if m.get("who") == "you") >= MIN_MESSAGES
        ]

    async def run(self, *, force: bool = False) -> dict[str, Any]:
        """One turn per person, as that person."""
        if not self.state["on"] and not force:
            return {"ran": False, "why": "off"}
        if self.running:
            return {"ran": False, "why": "already running"}
        cloud = self.data.cloud_state()
        if cloud != "ok":
            return self._ran(False, f"cloud agent {cloud}")
        who = self.people()
        if not who:
            return self._ran(False, "not enough chat yet")
        from homeassistant.components import conversation  # noqa: PLC0415

        self.running = True
        done = 0
        try:
            for user_id in who:
                context = Context(user_id=user_id)
                self.data.via[context.id] = PATH_STYLE
                try:
                    await conversation.async_converse(
                        self.hass, RUN_PROMPT, None, context, self.hass.config.language, agent_id="conversation.console"
                    )
                    done += 1
                except Exception:  # noqa: BLE001 (one person's run mustn't stop the next person's)
                    _LOGGER.exception("Console: a reply-style run failed")
                finally:
                    self.data.via.pop(context.id, None)
            return self._ran(True, None, people=done)
        finally:
            self.running = False

    def _ran(self, ran: bool, why: str | None, people: int = 0) -> dict[str, Any]:
        self.state["last_run"] = {"at": self.data.now().isoformat(), "ran": ran, "why": why, "people": people}
        self.data.changed()
        return {"ran": ran, "why": why, "people": people}
