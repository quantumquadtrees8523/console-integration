"""Suggested routines: once a week (Mondays at 3 AM), Console's cloud agent looks at how the house is used and tees up a
few routines in the chat card. Each one is a real Home Assistant automation that Sunrise saved switched
off and labelled "Suggested" (Sunrise's `routine` op=suggest), so it can't fire on its own.

- A tap runs it once (Sunrise's op=try, with read-back), as the person who tapped.
- The fifth tap keeps it (op=keep): from then on it is an ordinary routine that runs on its own trigger,
  and Sunrise's `undo` still takes it back.
- No tap for EXPIRE_DAYS days, or a tap on ✕: it is removed (op=dismiss) and never suggested again.
- At most MAX_LIVE suggestions exist at a time.

The weekly run is a setting, off unless an administrator turns it on, because each run spends some of
the month's allowance; what it spent shows on the Plan tab under "Where it went". It isn't throttled: it
runs whenever the cloud agent can be used, and is skipped only when it can't (switched off, unlinked, or
the month's allowance used up).
Console keeps, per suggestion: its automation id and name, a fingerprint of what it does, when it was
made, and the taps. Nothing a person said. Only counts leave the box.
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
from .const import DOMAIN, LLM_API_SUNRISE, PATH_SUGGESTIONS, PATH_TAPS

_LOGGER = logging.getLogger(__name__)

MAX_LIVE = 3
KEEP_AFTER = 5
EXPIRE_DAYS = 7
RUN_AT = (0, 3, 0)  # Monday (weekday 0), 3:00 local time, when the house is quiet
NEVER_KEPT = 200

RUN_PROMPT = (
    "Suggest up to {n} routines for this house from how it is used. Follow the routines skill (get_skill name=routines), "
    "its section “Suggesting routines”, exactly: read memory, list the routines, read usage, then save each one "
    "with routine op=suggest. Never act, try or keep anything now: nobody is here, and nothing in the house may change "
    "now. Don't suggest these again, the household didn't want them: {never}. Already suggested: {live}. If nothing "
    "has enough evidence, suggest nothing. Reply with one line: how many you suggested."
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
        self._stop = async_track_time_change(self.hass, self._weekly, hour=RUN_AT[1], minute=RUN_AT[2], second=0)

    @callback
    def stop(self) -> None:
        if self._stop:
            self._stop()
            self._stop = None

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
        """Sunrise's routine tool, as the person who tapped (or as nobody, for the weekly run)."""
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
                {k: item.get(k) for k in ("id", "name", "description", "taps", "made", "last_tap")} | {"keep_after": KEEP_AFTER}
                for item in state["items"]
            ],
            "kept": list(state["kept"])[-20:],
            "last_run": state["last_run"],
            "available": any(api.id == LLM_API_SUNRISE for api in llm.async_get_apis(self.hass)),
        }

    def _count(self, what: str) -> None:
        month = self.state["counts"].setdefault(self.data.period, {})
        month[what] = month.get(what, 0) + 1

    # --- the weekly run --------------------------------------------------------------------------

    async def run(self, *, force: bool = False) -> dict[str, Any]:
        """Tidy up, then ask the cloud agent for new suggestions up to MAX_LIVE."""
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
            text = RUN_PROMPT.format(
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
                    "taps": 0,
                    "last_tap": None,
                }
            )
            self._count("suggested")
            new += 1
        self.data.changed()
        return new

    async def expire(self) -> int:
        """Remove the suggestions nobody has tapped for EXPIRE_DAYS days."""
        cutoff = self.data.now() - timedelta(days=EXPIRE_DAYS)
        old = [i for i in self.state["items"] if datetime.fromisoformat(i.get("last_tap") or i["made"]) < cutoff]
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

    async def tap(self, sid: str, user_id: str) -> dict[str, Any]:
        """Run it once; on the KEEP_AFTER-th tap, keep it."""
        item = self._item(sid)
        tried = await self._routine({"op": "try", "id": sid}, user_id)
        if tried.get("error") or not tried.get("ran"):
            raise Refused(str(tried.get("error") or tried.get("why") or wording.SUGGESTION_DIDNT_RUN))
        item["taps"] = int(item.get("taps") or 0) + 1
        item["last_tap"] = self.data.now().isoformat()
        self._count("tapped")
        self.data.count_path(PATH_TAPS)
        things = tried.get("things") or []
        kept = None
        if item["taps"] >= KEEP_AFTER:
            kept = await self._routine({"op": "keep", "id": sid}, user_id)
            if kept.get("ok"):
                state = self.state
                state["items"] = [i for i in state["items"] if i["id"] != sid]
                state["kept"].append({"name": item["name"], "entity_id": kept.get("entity_id"), "change_id": kept.get("change_id"),
                                      "at": self.data.now().isoformat()})
                self._count("kept")
        self.data.changed()
        return {
            "name": item["name"],
            "reply": wording.suggestion_ran(item["name"], things, item["taps"], KEEP_AFTER, bool(kept and kept.get("ok"))),
            "taps": item["taps"],
            "kept": bool(kept and kept.get("ok")),
            "things": things,
        }

    async def dismiss(self, sid: str, user_id: str) -> dict[str, Any]:
        item = self._item(sid)
        await self._drop(item, user_id, "dismissed")
        return {"ok": True, "reply": wording.suggestion_dismissed(item["name"])}

    async def dismiss_all(self) -> int:
        """Remove every live suggestion (the data wipe): nothing switched off is left behind in automations."""
        items = list(self.state["items"])
        for item in items:
            try:
                await self._routine({"op": "dismiss", "id": item["id"]})
            except Exception:  # noqa: BLE001 (the wipe goes on whatever happens here)
                _LOGGER.warning("Console: couldn't remove the suggestion %s during the wipe", item["id"])
        return len(items)
