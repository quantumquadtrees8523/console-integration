"""Suggested routines. The house uses Console, and Console is guided by Sunrise (owner, 2026-11-28): each run is
one ordinary turn of Console's agent that follows Sunrise's `routines` skill. Console decides when it runs, on
which model, and what happens to the result; how to find a habit and write its routine is the skill's.

- **Every hour** (LISTEN_MINUTE past) the agent is asked what the house heard, and follows the skill's
  "Listening": Sunrise's `usage` lists what followed what (a door, motion sensor or person changed, and someone
  switched a thing by hand right after, often enough), and the agent saves those routines, or changes nothing.
- **Every Monday at 3 AM** the agent follows the skill's "Suggesting routines" in full: habits by the clock too.
- The house can ask for either itself: the `console.suggest_routines` service (an automation, a button).
- Every run is **Flash with thinking off, never the stronger model** (conversation.py; "made using the flash
  model never reasoning").
- A suggestion is a real automation Sunrise saved **running** and labelled "Suggested" (`routine` op=suggest
  on=true; "once its on its on and should be running"). It shows as buttons at the top of the Home dashboard,
  in the chat card: **Keep** (op=keep: an ordinary routine, off the card) or **Undo** (op=dismiss: removed, and
  never suggested again). Nothing is put in notifications.
- One nobody answers for EXPIRE_DAYS days is pruned: removed like Undo, and never suggested again.
- At most MAX_LIVE wait for an answer at a time; when they do, no run is made (and nothing is spent).

It's a setting, off unless an administrator turns it on, because every run spends some of the month's
allowance, the hourly ones too; what they spent shows on the Plan tab under "Where it went".
Console keeps, per suggestion: its automation id and name, a fingerprint of what it does and when it was
made. Nothing a person said. Only counts leave the box.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import logging
from typing import Any

from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.helpers import llm
from homeassistant.helpers.event import async_track_time_change

from . import wording
from .const import DOMAIN, LLM_API_SUNRISE, PATH_SUGGESTIONS

_LOGGER = logging.getLogger(__name__)

MAX_LIVE = 3
EXPIRE_DAYS = 7  # unanswered this long: pruned
RUN_AT = (0, 3, 0)  # Monday (weekday 0), 3:00 local time, when the house is quiet
LISTEN_MINUTE = 17  # every hour at this minute: what did the house hear?
NEVER_KEPT = 200

RUN_PROMPT = (
    "Suggest up to {n} routines for this house from how it is used. Follow the routines skill (get_skill name=routines), "
    "its section “Suggesting routines”, exactly: read memory, list the routines, read usage, then save each one "
    "with routine op=suggest and on=true: the owner wants suggestions live, running from the moment they're saved. "
    "Never act, try or keep anything now. Don't suggest these again, the household didn't want them: {never}. Already suggested: {live}. If nothing "
    "has enough evidence, suggest nothing. Reply with one line: how many you suggested."
)


LISTEN_PROMPT = (
    "What did the house hear? Follow the routines skill (get_skill name=routines), its part “Listening”, exactly. "
    "The owner wants suggestions live (on=true). Save up to {n}. Never act, try or keep anything now. "
    "Reply with one line: how many you saved."
)


def fresh() -> dict[str, Any]:
    return {"on": False, "items": [], "never": [], "kept": [], "last_run": None, "counts": {}}


def fingerprint(config: dict[str, Any]) -> str:
    """What a routine does, whatever it's called: its triggers, conditions and actions."""
    what = {k: config.get(k) or config.get(k.rstrip("s")) for k in ("triggers", "conditions", "actions")}
    return hashlib.sha256(json.dumps(what, sort_keys=True, default=str).encode()).hexdigest()[:20]


class Refused(Exception):
    """Said to the person as it is."""


class Suggestions:
    def __init__(self, hass: HomeAssistant, data) -> None:
        self.hass = hass
        self.data = data
        self._stop = None
        self.running = False

    @property
    def state(self) -> dict[str, Any]:
        stored = self.data.data.setdefault("suggestions", fresh())
        for key, value in fresh().items():
            stored.setdefault(key, value)
        return stored

    @callback
    def start(self) -> None:
        self._stop = [
            async_track_time_change(self.hass, self._weekly, hour=RUN_AT[1], minute=RUN_AT[2], second=0),
            async_track_time_change(self.hass, self._hourly, minute=LISTEN_MINUTE, second=0),
        ]

    @callback
    def stop(self) -> None:
        for stop in self._stop or []:
            stop()
        self._stop = None

    async def _hourly(self, now: datetime) -> None:
        try:
            await self.run(heard=True)
        except Exception:  # noqa: BLE001 (a failed hour mustn't stop the next one)
            _LOGGER.exception("Console: the hourly listen failed")

    async def _weekly(self, now: datetime) -> None:
        if now.weekday() != RUN_AT[0]:
            return
        try:
            await self.run()
        except Exception:  # noqa: BLE001 (a failed week mustn't stop the next one)
            _LOGGER.exception("Console: the weekly suggestions run failed")

    # --- the setting ------------------------------------------------------------------------------

    def set_on(self, on: bool) -> dict[str, Any]:
        self.state["on"] = bool(on)
        self.data.changed()
        if on:
            self.hass.async_create_task(
                self.hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {"notification_id": "console_suggestions", "title": wording.SUGGESTIONS_ON_TITLE, "message": wording.SUGGESTIONS_ON},
                    blocking=False,
                )
            )
        return {"on": self.state["on"]}

    # --- talking to Sunrise -----------------------------------------------------------------------

    async def _routine(self, args: dict[str, Any], user_id: str | None = None) -> dict[str, Any]:
        """Sunrise's routine tool, as the person who pressed (or as nobody, for a run's bookkeeping)."""
        ctx = llm.LLMContext(
            platform=DOMAIN, context=Context(user_id=user_id), language=self.hass.config.language,
            assistant="conversation", device_id=None,
        )  # fmt: skip
        try:
            api = await llm.async_get_api(self.hass, LLM_API_SUNRISE, ctx)
        except Exception as error:  # noqa: BLE001 (Sunrise missing, or AI turned off)
            raise Refused(str(error) or wording.SUGGESTIONS_NO_SUNRISE) from error
        result = await api.async_call_tool(llm.ToolInput(tool_name="routine", tool_args=args))
        data = getattr(result, "data", result)
        return data if isinstance(data, dict) else {}

    # --- what the card and the page show ------------------------------------------------------------

    def listing(self) -> dict[str, Any]:
        state = self.state
        return {
            "on": state["on"],
            "items": [
                {k: item.get(k) for k in ("id", "name", "description", "made")}
                for item in state["items"]
            ],
            "kept": list(state["kept"])[-20:],
            "last_run": state["last_run"],
            "available": any(api.id == LLM_API_SUNRISE for api in llm.async_get_apis(self.hass)),
        }

    def _count(self, what: str) -> None:
        month = self.state["counts"].setdefault(self.data.period, {})
        month[what] = month.get(what, 0) + 1

    # --- the runs --------------------------------------------------------------------------------

    async def run(self, *, force: bool = False, heard: bool = False) -> dict[str, Any]:
        """Prune, then one turn of the cloud agent, guided by Sunrise's routines skill: what the house heard
        (`heard`, the hourly run) or how the house is used as a whole (Monday's)."""
        state = self.state
        if not state["on"] and not force:
            return {"ran": False, "why": "off"}
        if self.running:
            return {"ran": False, "why": "already running"}
        cloud = self.data.cloud_state()
        if cloud not in ("ok", "near_limit"):
            return self._ran(False, f"cloud agent {cloud}")
        self.running = True
        try:
            await self.reconcile()
            await self.expire()
            room = MAX_LIVE - len(state["items"])
            if room <= 0:
                return self._ran(False, "full")
            from homeassistant.components import conversation  # noqa: PLC0415

            before = self.data.spend_usd
            text = LISTEN_PROMPT.format(n=room) if heard else RUN_PROMPT.format(
                n=room,
                never=", ".join(f"“{n['name']}”" for n in state["never"][-30:]) or "none",
                live=", ".join(f"“{i['name']}”" for i in state["items"]) or "none",
            )
            context = Context()
            self.data.via[context.id] = PATH_SUGGESTIONS
            try:
                await conversation.async_converse(self.hass, text, None, context, self.hass.config.language, agent_id="conversation.console")
            finally:
                self.data.via.pop(context.id, None)
            made = await self.reconcile()
            return self._ran(True, None, made=made, cost=round(self.data.spend_usd - before, 6))
        finally:
            self.running = False

    def _ran(self, ran: bool, why: str | None, made: int = 0, cost: float = 0.0) -> dict[str, Any]:
        self.state["last_run"] = {"at": self.data.now().isoformat(), "ran": ran, "why": why, "made": made, "cost_usd": cost}
        self.data.changed()
        return {"ran": ran, "why": why, "made": made, "cost_usd": cost}

    async def reconcile(self) -> int:
        """Line Console's records up with the automations: pick up new suggestions, drop the ones that are
        gone, remove any the household turned down before or that go over MAX_LIVE. Returns how many are new."""
        state = self.state
        listed = await self._routine({"op": "list"})
        live = {r["id"]: r for r in listed.get("routines") or [] if r.get("suggestion")}
        state["items"] = [item for item in state["items"] if item["id"] in live]
        known = {item["id"] for item in state["items"]}
        never = {n["fingerprint"] for n in state["never"]}
        new = 0
        for rid, row in live.items():
            if rid in known:
                continue
            got = await self._routine({"op": "get", "id": rid})
            config = got.get("config") or {}
            mark = fingerprint(config)
            if mark in never or any(i["fingerprint"] == mark for i in state["items"]) or len(state["items"]) >= MAX_LIVE:
                await self._routine({"op": "dismiss", "id": rid})
                continue
            state["items"].append(
                {
                    "id": rid,
                    "entity_id": row.get("entity_id"),
                    "name": config.get("alias") or row.get("name") or rid,
                    "description": config.get("description") or "",
                    "fingerprint": mark,
                    "made": self.data.now().isoformat(),
                }
            )
            self._count("suggested")
            new += 1
        self.data.changed()
        return new

    async def expire(self) -> int:
        """Prune: remove the suggestions nobody has answered for EXPIRE_DAYS days. Each stops running, and is
        never suggested again."""
        cutoff = self.data.now() - timedelta(days=EXPIRE_DAYS)
        old = [i for i in self.state["items"] if datetime.fromisoformat(i["made"]) < cutoff]
        for item in old:
            await self._drop(item, None, "expired")
        return len(old)

    async def _drop(self, item: dict[str, Any], user_id: str | None, why: str) -> None:
        try:
            await self._routine({"op": "dismiss", "id": item["id"]}, user_id)
        except Refused:
            pass  # Sunrise isn't there to remove it: forget it here all the same
        state = self.state
        state["items"] = [i for i in state["items"] if i["id"] != item["id"]]
        state["never"] = (state["never"] + [{"fingerprint": item["fingerprint"], "name": item["name"]}])[-NEVER_KEPT:]
        self._count(why)
        self.data.changed()

    # --- what a person does -----------------------------------------------------------------------

    def _item(self, sid: str) -> dict[str, Any]:
        item = next((i for i in self.state["items"] if i["id"] == sid), None)
        if item is None:
            raise Refused(wording.SUGGESTION_GONE)
        return item

    async def keep(self, sid: str, user_id: str) -> dict[str, Any]:
        """Keep: it's an ordinary routine from here on, and leaves the card."""
        item = self._item(sid)
        kept = await self._routine({"op": "keep", "id": sid}, user_id)
        if kept.get("error") or not kept.get("ok"):
            raise Refused(str(kept.get("error") or kept.get("why") or wording.SUGGESTION_NOT_KEPT))
        state = self.state
        state["items"] = [i for i in state["items"] if i["id"] != sid]
        state["kept"].append({"name": item["name"], "entity_id": kept.get("entity_id"), "change_id": kept.get("change_id"),
                              "at": self.data.now().isoformat()})
        self._count("kept")
        self.data.changed()
        return {"ok": True, "name": item["name"], "reply": wording.suggestion_kept(item["name"])}

    async def dismiss(self, sid: str, user_id: str) -> dict[str, Any]:
        item = self._item(sid)
        await self._drop(item, user_id, "dismissed")
        return {"ok": True, "reply": wording.suggestion_dismissed(item["name"])}

    async def dismiss_all(self) -> int:
        """Remove every suggestion still waiting for an answer (the data wipe): none is left running in automations."""
        items = list(self.state["items"])
        for item in items:
            try:
                await self._routine({"op": "dismiss", "id": item["id"]})
            except Exception:  # noqa: BLE001 (the wipe goes on whatever happens here)
                _LOGGER.warning("Console: couldn't remove the suggestion %s during the wipe", item["id"])
        return len(items)
