"""Suggestions and quick actions: the chat always has SHOWN things to offer, each one a tap that runs
something in the house now, and the ones a household keeps using stay under the chat as quick actions.

Where a suggestion comes from, best first:

1. A routine the cloud agent suggested (the weekly run below): a real Home Assistant automation that
   Sunrise saved switched off and labelled "Suggested" (Sunrise's `routine` op=suggest).
2. What this house usually does at about this hour, from Sunrise's `usage` ("Turn on the Den lamp").
3. What is on right now ("Turn off the Kitchen lights").
4. The household's own scenes.
5. A light or switch the house uses most.
6. Something to ask Console, so there are always SHOWN.

2 to 6 are made on this box from the house as it is, with no AI: they cost nothing and are there with
the weekly run off, the cloud agent paused or Sunrise missing. They only ever switch lights, switches,
fans and helpers on or off, or run a scene, and only things exposed to Assist.

What happens to one:

- A tap runs it once, as the person who tapped, and reads back what changed. It runs at home.
- Tapped PROMOTE_TAPS times on PROMOTE_DAYS different days, it becomes a quick action: it leaves the
  suggestions and stays under the chat, at most QUICK_MAX of them.
- Seen DISCARD_SEEN times on DISCARD_DAYS different days and never tapped, it is discarded. One made at
  home rests for REST_DAYS days; a suggested routine is removed and never suggested again.
- A routine nobody taps for EXPIRE_DAYS days is removed, and an administrator can remove any of them (✕):
  never suggested again.
- A quick action nobody uses for QUICK_IDLE_DAYS days goes back to being an ordinary suggestion.
- An administrator can let a suggested routine run by itself (op=keep): from then on it is an ordinary
  routine on its own trigger, and Sunrise's `undo` still takes it back.

The weekly run (Mondays at 3 AM) is an AI feature, off unless an administrator turns it on, because each
run spends some of the month's credits; what it spent shows on the Plan tab under "Where it went".
Console keeps, per suggestion: what it is, when it was seen and tapped, and how often. Nothing a person
said. Only counts leave the box.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import hashlib
import json
import logging
from typing import Any

from homeassistant.core import Context, HomeAssistant, State, callback
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er, llm
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util

from . import wording
from .const import DOMAIN, LLM_API_SUNRISE, PATH_SUGGESTIONS, PATH_TAPS

_LOGGER = logging.getLogger(__name__)

SHOWN = 3
PROMOTE_TAPS = 3
PROMOTE_DAYS = 2
DISCARD_SEEN = 4
DISCARD_DAYS = 2
SEEN_GAP = timedelta(hours=4)  # the same chat left open, or opened five times in an hour, is one sighting
REST_DAYS = 30
QUICK_MAX = 6
QUICK_IDLE_DAYS = 30
MAX_LIVE = 3  # suggested routines waiting at a time
EXPIRE_DAYS = 7
RUN_AT = (0, 3, 0)  # Monday (weekday 0), 3:00 local time, when the house is quiet
NEVER_KEPT = 200
DAYS_KEPT = 5
USAGE_DAYS = 14
USAGE_FOR = timedelta(hours=1)
USAGE_WAIT_S = 3
READBACK_S = 3.0
SWITCHED = ("light", "switch", "fan", "input_boolean")  # what a suggestion made at home may turn on or off
DOWN = ("unavailable", "unknown")
PER_KIND = 2  # of the SHOWN, at most this many of one kind while there are others

RUN_PROMPT = (
    "Suggest up to {n} routines for this house from how it is used. Follow the routines skill (get_skill name=routines), "
    "its section “Suggesting routines”, exactly: read memory, list the routines, read usage, then save each one "
    "with routine op=suggest. Never act, try or keep anything now: nobody is here, and nothing in the house may change "
    "now. Don't suggest these again, the household didn't want them: {never}. Already suggested: {live}. If nothing "
    "has enough evidence, suggest nothing. Reply with one line: how many you suggested."
)


def fresh() -> dict[str, Any]:
    return {"on": False, "items": [], "home": {}, "rest": {}, "never": [], "kept": [], "last_run": None, "counts": {}}


def fingerprint(config: dict[str, Any]) -> str:
    """What a routine does, whatever it's called: its triggers, conditions and actions."""
    what = {k: config.get(k) or config.get(k.rstrip("s")) for k in ("triggers", "conditions", "actions")}
    return hashlib.sha256(json.dumps(what, sort_keys=True, default=str).encode()).hexdigest()[:20]


class Refused(Exception):
    """Said to the person as it is."""


# --- how one suggestion is doing: sightings and taps, the same for every kind ---------------------


def saw(row: dict[str, Any], now: datetime, day: str) -> bool:
    """Count a sighting, unless it was seen a moment ago. True when it counted."""
    last = row.get("seen_at")
    if last and now - datetime.fromisoformat(last) < SEEN_GAP:
        return False
    row["seen"] = int(row.get("seen") or 0) + 1
    row["seen_at"] = now.isoformat()
    row["seen_days"] = sorted({*(row.get("seen_days") or []), day})[-DAYS_KEPT:]
    return True


def tapped(row: dict[str, Any], now: datetime, day: str) -> None:
    row["taps"] = int(row.get("taps") or 0) + 1
    row["last_tap"] = now.isoformat()
    row["tap_days"] = sorted({*(row.get("tap_days") or []), day})[-DAYS_KEPT:]


def earned(row: dict[str, Any]) -> bool:
    """Used often enough, on enough different days, to be a quick action."""
    return int(row.get("taps") or 0) >= PROMOTE_TAPS and len(row.get("tap_days") or []) >= PROMOTE_DAYS


def ignored(row: dict[str, Any]) -> bool:
    """Seen often enough, on enough different days, and never tapped."""
    return not row.get("taps") and int(row.get("seen") or 0) >= DISCARD_SEEN and len(row.get("seen_days") or []) >= DISCARD_DAYS


def pick(candidates: list[dict[str, Any]], count: int = SHOWN) -> list[dict[str, Any]]:
    """The `count` best, best first. Of the ones made at home, at most PER_KIND of one kind while there
    are others to show; something to ask only fills the places nothing else takes."""
    ranked = sorted(candidates, key=lambda c: (-c["rank"], c["id"]))
    chosen: list[dict[str, Any]] = []

    def take(pool: list[dict[str, Any]], limit: int) -> None:
        for candidate in pool:
            if len(chosen) >= count:
                return
            same = sum(1 for c in chosen if c["sort"] == candidate["sort"])
            if candidate not in chosen and (not limit or candidate["sort"] == "routine" or same < limit):
                chosen.append(candidate)

    real = [c for c in ranked if c["sort"] != "ask"]
    take(real, PER_KIND)
    take(real, 0)
    take(ranked, 0)
    return sorted(chosen, key=lambda c: (-c["rank"], c["id"]))


class Suggestions:
    def __init__(self, hass: HomeAssistant, data) -> None:
        self.hass = hass
        self.data = data
        self._stop = None
        self.running = False
        self._usage: dict[str, dict[str, Any]] = {}
        self._usage_at: datetime | None = None
        self._usage_task: asyncio.Task | None = None

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

    def _day(self) -> str:
        """Today in the house's own time: three taps in one evening are one day."""
        return dt_util.as_local(self.data.now()).date().isoformat()

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

    def _sunrise(self) -> bool:
        return any(api.id == LLM_API_SUNRISE for api in llm.async_get_apis(self.hass))

    async def _tool(self, name: str, args: dict[str, Any], user_id: str | None = None) -> dict[str, Any]:
        """One of Sunrise's tools, as the person who tapped (or as nobody, for the weekly run)."""
        ctx = llm.LLMContext(
            platform=DOMAIN, context=Context(user_id=user_id), language=self.hass.config.language,
            assistant="conversation", device_id=None,
        )  # fmt: skip
        try:
            api = await llm.async_get_api(self.hass, LLM_API_SUNRISE, ctx)
        except Exception as error:  # noqa: BLE001 (Sunrise missing, or AI turned off)
            raise Refused(str(error) or wording.SUGGESTIONS_NO_SUNRISE) from error
        result = await api.async_call_tool(llm.ToolInput(tool_name=name, tool_args=args))
        data = getattr(result, "data", result)
        return data if isinstance(data, dict) else {}

    async def _routine(self, args: dict[str, Any], user_id: str | None = None) -> dict[str, Any]:
        return await self._tool("routine", args, user_id)

    # --- what this house does, for the suggestions made at home --------------------------------------

    async def _read_usage(self) -> None:
        try:
            got = await self._tool("usage", {"days": USAGE_DAYS})
            self._usage = {row["id"]: row for row in got.get("things") or [] if isinstance(row, dict) and row.get("id")}
        except Exception:  # noqa: BLE001 (no Sunrise, AI off, no recorder: suggest from what's on instead)
            self._usage = {}
        self._usage_at = self.data.now()

    async def _refresh_usage(self) -> None:
        """How the house was used these two weeks, read at most once an hour. A slow read doesn't hold the
        chat up: the suggestions go out without it and have it next time."""
        if self._usage_at is not None and self.data.now() - self._usage_at < USAGE_FOR:
            return
        if self._usage_task is None or self._usage_task.done():
            self._usage_task = self.hass.async_create_task(self._read_usage(), "console suggestions usage")
        try:
            await asyncio.wait_for(asyncio.shield(self._usage_task), USAGE_WAIT_S)
        except TimeoutError:
            pass

    def _things(self) -> list[dict[str, Any]]:
        """The things a suggestion may switch: exposed to Assist, reachable, with their room."""
        from homeassistant.components.homeassistant.exposed_entities import async_should_expose  # noqa: PLC0415

        entities, devices, areas = er.async_get(self.hass), dr.async_get(self.hass), ar.async_get(self.hass)
        out = []
        for state in self.hass.states.async_all((*SWITCHED, "scene")):
            try:
                if not async_should_expose(self.hass, "conversation", state.entity_id):
                    continue
            except KeyError:  # the exposure settings aren't loaded: nothing is offered
                continue
            if state.domain != "scene" and state.state in DOWN:
                continue
            entry = entities.async_get(state.entity_id)
            if entry and (entry.platform == DOMAIN or entry.entity_category is not None):
                continue  # never Console's own off switches, nor a device's settings
            area_id = entry.area_id if entry else None
            if entry and not area_id and entry.device_id and (device := devices.async_get(entry.device_id)):
                area_id = device.area_id
            area = areas.async_get_area(area_id) if area_id else None
            out.append({"id": state.entity_id, "domain": state.domain, "name": state.name, "on": state.state == "on",
                        "area_id": area.id if area else None, "area": area.name if area else None})
        return sorted(out, key=lambda t: t["id"])

    def _recipe(self, key: str, things: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
        """What a suggestion made at home is, worked out from its key and the house as it is now: its
        name, and either the action and the things it acts on, or the words it asks Console. None when the
        house no longer has what it needs."""
        things = self._things() if things is None else things
        by_id = {t["id"]: t for t in things}
        what, _, rest = key.partition(":")
        if what == "ask":
            return {"kind": "ask", "name": wording.ASKS[rest], "ask": wording.ASKS[rest]} if rest in wording.ASKS else None
        if what == "scene":
            return {"kind": "action", "name": by_id[rest]["name"], "action": "scene.turn_on", "ids": [rest]} if rest in by_id else None
        if what not in ("on", "off"):
            return None
        if rest == "lights":
            ids = [t["id"] for t in things if t["domain"] == "light"]
            name = wording.ALL_LIGHTS_OFF
        elif rest.startswith("area:"):
            ids = [t["id"] for t in things if t["domain"] == "light" and t["area_id"] == rest[5:]]
            name = wording.room_lights(what, next((t["area"] for t in things if t["area_id"] == rest[5:]), "")) if ids else ""
        else:
            thing = by_id.get(rest)
            if thing is None or thing["domain"] not in SWITCHED:
                return None
            return {"kind": "action", "name": wording.switch_thing(what, thing["name"]), "action": f"{thing['domain']}.turn_{what}", "ids": [rest]}
        return {"kind": "action", "name": name, "action": f"light.turn_{what}", "ids": ids} if ids else None

    def _candidates(self, things: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Every suggestion this house could be offered right now, made at home: its key, why, and how
        good a guess it is (rank). `sort` is its kind, for showing a mix."""
        hour = dt_util.as_local(self.data.now()).hour
        lights_on = [t for t in things if t["domain"] == "light" and t["on"]]
        out: list[dict[str, Any]] = []

        def add(key: str, sort: str, rank: float, why: str) -> None:
            if not any(c["id"] == key for c in out):
                out.append({"id": key, "sort": sort, "rank": rank, "why": why})

        # What this house usually has on at about this hour, and is off now.
        for thing in things:
            used = self._usage.get(thing["id"]) or {}
            days = int(used.get("days_used") or 0)
            near = any(abs(hour - int(h)) in (0, 1, 23) for h in used.get("common_hours") or [])
            if thing["domain"] in SWITCHED and not thing["on"] and near and days >= 3:
                add(f"on:{thing['id']}", "habit", 80 + min(days, USAGE_DAYS), wording.why_habit(hour, days, USAGE_DAYS))
        # What is on right now.
        rooms: dict[str, list[dict[str, Any]]] = {}
        for thing in lights_on:
            rooms.setdefault(thing["area_id"] or "", []).append(thing)
        if len(lights_on) >= 2 and len(rooms) >= 2:
            add("off:lights", "off", 70, wording.why_on(len(lights_on)))
        for area_id, lit in rooms.items():
            if area_id and len(lit) > 1:
                add(f"off:area:{area_id}", "off", 60 + min(len(lit), 9), wording.why_on(len(lit), lit[0]["area"]))
            else:
                for thing in lit:
                    add(f"off:{thing['id']}", "off", 58, wording.WHY_ON_ONE)
        for thing in things:
            if thing["domain"] in ("switch", "fan") and thing["on"]:
                add(f"off:{thing['id']}", "off", 55, wording.WHY_ON_ONE)
        # The household's own scenes.
        for thing in things:
            if thing["domain"] == "scene":
                add(f"scene:{thing['id']}", "scene", 40, wording.WHY_SCENE)
        # What the house switches most and is off now; with no usage to go on, its lights.
        most = sorted(
            (t for t in things if t["domain"] in SWITCHED and not t["on"]),
            key=lambda t: (-int((self._usage.get(t["id"]) or {}).get("changes") or 0), t["domain"] != "light", t["name"]),
        )
        for place, thing in enumerate(most[:6]):
            used = bool((self._usage.get(thing["id"]) or {}).get("changes"))
            add(f"on:{thing['id']}", "thing", 20 - place, wording.WHY_USED if used else wording.WHY_THING)
        # Something to ask, so there are always enough.
        for place, slug in enumerate(wording.ASKS):
            add(f"ask:{slug}", "ask", 5 - place, wording.WHY_ASK)
        return out

    # --- what the card and the page show ------------------------------------------------------------

    def _chip(self, key: str, recipe: dict[str, Any], why: str, row: dict[str, Any] | None) -> dict[str, Any]:
        row = row or {}
        chip = {"id": key, "kind": recipe["kind"], "name": recipe["name"], "why": why, "taps": int(row.get("taps") or 0),
                "quick": bool(row.get("quick"))}
        return chip | ({"ask": recipe["ask"]} if recipe["kind"] == "ask" else {})

    def _routine_chip(self, item: dict[str, Any]) -> dict[str, Any]:
        return {"id": item["id"], "kind": "routine", "name": item["name"], "why": item.get("description") or "",
                "taps": int(item.get("taps") or 0), "quick": bool(item.get("quick"))}

    async def listing(self, *, admin: bool = True, routines: bool = True) -> dict[str, Any]:
        """What the chat shows (`suggested`, always SHOWN of them, and `quick`), and what the settings page
        lists. Suggested routines change the house's setup when they are tried, which only an
        administrator may do, so they are shown to administrators only; `routines` is False when the
        tools behind them are switched off."""
        state = self.state
        self._tidy()
        await self._refresh_usage()
        things = self._things()
        home = state["home"]
        available = self._sunrise()
        items = state["items"] if routines and available and admin else []
        now = self.data.now().isoformat()
        resting = {key for key, until in state["rest"].items() if until > now}
        never = {n["fingerprint"] for n in state["never"]}

        quick = [(item.get("last_tap") or "", self._routine_chip(item)) for item in items if item.get("quick")]
        for key, row in home.items():
            if row.get("quick") and (recipe := self._recipe(key, things)):
                quick.append((row.get("last_tap") or "", self._chip(key, recipe, "", row)))

        offered = [{"id": i["id"], "sort": "routine", "rank": 100, "chip": self._routine_chip(i)} for i in items if not i.get("quick")]
        for candidate in self._candidates(things):
            key = candidate["id"]
            if key in resting or key in never or (home.get(key) or {}).get("quick"):
                continue
            if recipe := self._recipe(key, things):
                offered.append(candidate | {"chip": self._chip(key, recipe, candidate["why"], home.get(key))})
        return {
            "on": state["on"],
            "suggested": [c["chip"] for c in pick(offered)],
            "quick": [chip for _, chip in sorted(quick, key=lambda q: q[0], reverse=True)][:QUICK_MAX],
            "items": [
                {k: item.get(k) for k in ("id", "name", "description", "taps", "made", "last_tap", "seen")} | {"quick": bool(item.get("quick"))}
                for item in state["items"]
            ],
            "kept": list(state["kept"])[-20:],
            "last_run": state["last_run"],
            "available": available,
            "rules": {"shown": SHOWN, "promote_taps": PROMOTE_TAPS, "promote_days": PROMOTE_DAYS, "discard_seen": DISCARD_SEEN,
                      "rest_days": REST_DAYS, "quick_max": QUICK_MAX, "quick_idle_days": QUICK_IDLE_DAYS, "expire_days": EXPIRE_DAYS},
        }

    def _count(self, what: str) -> None:
        month = self.state["counts"].setdefault(self.data.period, {})
        month[what] = month.get(what, 0) + 1

    def _tidy(self) -> None:
        """A quick action nobody has used for QUICK_IDLE_DAYS days goes back; a rest that is over ends."""
        state = self.state
        now = self.data.now()
        cutoff = (now - timedelta(days=QUICK_IDLE_DAYS)).isoformat()
        changed = False
        for key, row in list(state["home"].items()):
            if row.get("quick") and (row.get("last_tap") or "") < cutoff:
                del state["home"][key]
                changed = True
        for item in state["items"]:
            if item.get("quick") and (item.get("last_tap") or "") < cutoff:
                item.update(quick=False, taps=0, tap_days=[], seen=0, seen_days=[], seen_at=None, made=now.isoformat())
                changed = True
        for key, until in list(state["rest"].items()):
            if until <= now.isoformat():
                del state["rest"][key]
                changed = True
        if changed:
            self.data.changed()

    # --- the weekly run --------------------------------------------------------------------------

    async def run(self, *, force: bool = False) -> dict[str, Any]:
        """Tidy up, then ask the cloud agent for new suggested routines up to MAX_LIVE."""
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
            room = MAX_LIVE - sum(1 for i in state["items"] if not i.get("quick"))
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
            waiting = sum(1 for i in state["items"] if not i.get("quick"))
            if mark in never or any(i["fingerprint"] == mark for i in state["items"]) or waiting >= MAX_LIVE:
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
        """Remove the suggested routines nobody has tapped for EXPIRE_DAYS days. A quick action isn't one
        of them: it goes back to a suggestion first, after QUICK_IDLE_DAYS."""
        cutoff = self.data.now() - timedelta(days=EXPIRE_DAYS)
        old = [i for i in self.state["items"] if not i.get("quick") and datetime.fromisoformat(i.get("last_tap") or i["made"]) < cutoff]
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
        self._never(item["fingerprint"], item["name"])
        self._count(why)
        self.data.changed()

    def _never(self, mark: str, name: str) -> None:
        state = self.state
        state["never"] = (state["never"] + [{"fingerprint": mark, "name": name}])[-NEVER_KEPT:]

    # --- what a person does -----------------------------------------------------------------------

    def _item(self, sid: str) -> dict[str, Any] | None:
        return next((i for i in self.state["items"] if i["id"] == sid), None)

    async def seen(self, ids: list[str]) -> dict[str, Any]:
        """The chat showed these suggestions. One that has been seen often enough and never tapped is
        discarded: the answer says which, so the card can ask for the next ones."""
        state = self.state
        now, day = self.data.now(), self._day()
        gone: list[str] = []
        for sid in dict.fromkeys(ids):
            item = self._item(sid)
            if item is not None:
                if not item.get("quick") and saw(item, now, day) and ignored(item):
                    await self._drop(item, None, "ignored")
                    gone.append(sid)
                continue
            if sid.startswith("ask:") or self._recipe(sid) is None:
                continue  # something to ask is the floor that keeps the chat at SHOWN: it is never discarded
            row = state["home"].setdefault(sid, {})
            if not row.get("quick") and saw(row, now, day) and ignored(row):
                del state["home"][sid]
                state["rest"][sid] = (now + timedelta(days=REST_DAYS)).isoformat()
                self._count("ignored")
                gone.append(sid)
        self.data.changed()
        return {"discarded": gone}

    def _promote(self, row: dict[str, Any]) -> bool:
        """Make it a quick action if it has earned that. When that makes too many, the one used longest
        ago goes back to being a suggestion."""
        if row.get("quick") or not earned(row):
            return False
        row["quick"] = True
        state = self.state
        quick = [r for r in [*state["items"], *state["home"].values()] if r.get("quick")]
        for extra in sorted(quick, key=lambda r: r.get("last_tap") or "")[: max(0, len(quick) - QUICK_MAX)]:
            extra.update(quick=False, taps=0, tap_days=[], seen=0, seen_days=[], seen_at=None)
        self._count("quick")
        return True

    async def _act(self, recipe: dict[str, Any], user_id: str) -> list[dict[str, Any]]:
        """Do a suggestion made at home, through Home Assistant itself as the person who tapped, then read
        each thing back: CHECKED when it shows the change, NOT CONFIRMED when it doesn't in a few seconds."""
        domain, _, service = recipe["action"].partition(".")
        ids = recipe["ids"]
        want = {"turn_on": "on", "turn_off": "off"}.get(service) if domain != "scene" else None
        try:
            await self.hass.services.async_call(domain, service, {"entity_id": ids}, blocking=True, context=Context(user_id=user_id))
        except Exception as error:  # noqa: BLE001 (Home Assistant's own reason: not allowed, or the device refused)
            raise Refused(wording.action_failed(recipe["name"], str(error))) from error
        waited = 0.0
        while want and waited < READBACK_S and any(self._now(eid) not in (want, *DOWN, None) for eid in ids):
            await asyncio.sleep(0.2)
            waited += 0.2
        rows = []
        for eid in ids:
            state: State | None = self.hass.states.get(eid)
            now = state.state if state else None
            result = "UNREACHABLE" if now in (*DOWN, None) and want else "CHECKED" if want is None or now == want else "NOT CONFIRMED"
            rows.append({"id": eid, "name": state.name if state else eid, "now": now, "result": result})
        return rows

    def _now(self, entity_id: str) -> str | None:
        state = self.hass.states.get(entity_id)
        return state.state if state else None

    async def tap(self, sid: str, user_id: str) -> dict[str, Any]:
        """Run it once. Used often enough on enough days, it becomes a quick action. Something to ask isn't
        run here: the answer carries the words, and the card asks them."""
        state = self.state
        now, day = self.data.now(), self._day()
        item = self._item(sid)
        if item is not None:
            tried = await self._routine({"op": "try", "id": sid}, user_id)
            if tried.get("error") or not tried.get("ran"):
                raise Refused(str(tried.get("error") or tried.get("why") or wording.SUGGESTION_DIDNT_RUN))
            row, name, kind = item, item["name"], "routine"
            done = wording.routine_ran(name, tried.get("things") or [])
            things = tried.get("things") or []
        else:
            recipe = self._recipe(sid)
            if recipe is None:
                raise Refused(wording.SUGGESTION_GONE)
            row, name, kind = state["home"].setdefault(sid, {}), recipe["name"], recipe["kind"]
            things = []
            if kind == "action":
                things = await self._act(recipe, user_id)
                if not any(t["result"] == "CHECKED" for t in things):
                    raise Refused(wording.action_ran(name, things))
                done = wording.action_ran(name, things)
            else:
                done = ""
            row["name"] = name
        was_quick = bool(row.get("quick"))
        tapped(row, now, day)
        self._count("tapped")
        if kind != "ask":
            self.data.count_path(PATH_TAPS)
        promoted = self._promote(row)
        self.data.changed()
        note = wording.suggestion_progress(int(row["taps"]), len(row["tap_days"]), PROMOTE_TAPS, PROMOTE_DAYS, promoted, was_quick)
        return {
            "id": sid,
            "kind": kind,
            "name": name,
            "reply": f"{done} {note}".strip(),
            "taps": row["taps"],
            "quick": bool(row.get("quick")),
            "promoted": promoted,
            "things": things,
        } | ({"ask": recipe["ask"]} if kind == "ask" else {})

    async def keep(self, sid: str, user_id: str) -> dict[str, Any]:
        """Let a suggested routine run by itself from now on (Sunrise's op=keep)."""
        item = self._item(sid)
        if item is None:
            raise Refused(wording.SUGGESTION_GONE)
        kept = await self._routine({"op": "keep", "id": sid}, user_id)
        if not kept.get("ok"):
            raise Refused(str(kept.get("error") or kept.get("why") or wording.SUGGESTION_DIDNT_RUN))
        state = self.state
        state["items"] = [i for i in state["items"] if i["id"] != sid]
        state["kept"].append({"name": item["name"], "entity_id": kept.get("entity_id"), "change_id": kept.get("change_id"),
                              "at": self.data.now().isoformat()})
        self._count("kept")
        self.data.changed()
        return {"ok": True, "reply": wording.suggestion_kept(item["name"])}

    async def dismiss(self, sid: str, user_id: str) -> dict[str, Any]:
        """Never suggest this again (an administrator's ✕), whether it is waiting or already a quick action.
        Something to ask can't be removed: it is what keeps the chat at SHOWN."""
        item = self._item(sid)
        if item is not None:
            await self._drop(item, user_id, "dismissed")
            return {"ok": True, "reply": wording.suggestion_dismissed(item["name"])}
        recipe = None if sid.startswith("ask:") else self._recipe(sid)
        row = None if sid.startswith("ask:") else self.state["home"].pop(sid, None)
        if recipe is None and row is None:
            raise Refused(wording.SUGGESTION_GONE)
        name = (recipe or {}).get("name") or (row or {}).get("name") or sid
        self._never(sid, name)
        self._count("dismissed")
        self.data.changed()
        return {"ok": True, "reply": wording.suggestion_dismissed(name)}

    async def dismiss_all(self) -> int:
        """Remove every suggested routine (the data wipe): nothing switched off is left behind in automations."""
        items = list(self.state["items"])
        for item in items:
            try:
                await self._routine({"op": "dismiss", "id": item["id"]})
            except Exception:  # noqa: BLE001 (the wipe goes on whatever happens here)
                _LOGGER.warning("Console: couldn't remove the suggestion %s during the wipe", item["id"])
        return len(items)
