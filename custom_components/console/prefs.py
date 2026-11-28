"""Device settings: the level this household wants each speaker's volume and each light's brightness at,
learned from what people do, and used by the agent whenever someone doesn't name a level.

Owner, 2026-11-28: "maybe the user is listening to music on some speaker and they think it's too loud. They
ask to drop the volume or else do so manually. The agent should be able to see that and remember that
setting for future agent actions on that device."

Where a level comes from:

- A chat (or voice, or Assist) turn where the person asked about it ("too loud", "turn it down", "kitchen at
  20"): the level the device is at when the turn ends, updated if the device reports a new level within
  AGENT_S (a speaker can be slow to say).
- A change by hand (the app, the device's own buttons): the level it was left at once the person stopped
  adjusting it (SETTLE_S of quiet).
- Either of those within CORRECT_S of the agent setting that device is a correction: the agent got it wrong,
  so the correction replaces the levels kept in the CORRECT_S before it.

What never counts: a level the agent chose without being asked (it would only be learning from itself), and
a change made by an automation or a script.

A device's learned level is the middle of its last KEEP levels, so one loud song doesn't move it. The agent
is told each one on every turn (prompt), and the music tool starts music at it when no volume is given.
Each is listed under "What the house knows about you", where an administrator can forget it.

Console keeps per device: its id and name, and per setting its last few levels with when and how. Nothing a
person said. It isn't part of anything sent to the relay. "Learn device settings" under AI features turns it
off: nothing is recorded and nothing is used.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import logging
import re
import statistics
from typing import Any

from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later

_LOGGER = logging.getLogger(__name__)

# setting -> (domain, attribute, how to turn the attribute into a percentage)
SETTINGS: dict[str, tuple[str, str, Callable[[float], int]]] = {
    "volume": ("media_player", "volume_level", lambda v: round(float(v) * 100)),
    "brightness": ("light", "brightness", lambda v: round(float(v) * 100 / 255)),
}
# Words that make a turn about that setting: then the level it ends at is what the person asked for.
ASKED = {
    "volume": re.compile(r"\b(volume|loud\w*|quiet\w*|soft\w*|turn (it|that|this|the music) (down|up)|down a bit|up a bit|lower|mute|blast\w*|\d{1,3}\s*%?)", re.I),
    "brightness": re.compile(r"\b(bright\w*|dim\w*|dark\w*|lighter|\d{1,3}\s*%)", re.I),
}
KEEP = 5  # levels kept per device and setting; the learned one is their middle
SETTLE_S = 20  # a change by hand is the level left once the person stops adjusting for this long
AGENT_S = 30  # a change this soon after the agent touched a device is the agent's
CORRECT_S = 10 * 60  # a person's change this soon after the agent set a device corrects it
DEVICE = re.compile(r"^(media_player|light)\.[a-z0-9_]+$")


def fresh() -> dict[str, Any]:
    return {"devices": {}}


def entities_in(value: Any) -> set[str]:
    """Every speaker or light id anywhere in a tool call's arguments or result."""
    found: set[str] = set()

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list | tuple):
            for v in x:
                walk(v)
        elif isinstance(x, str) and DEVICE.match(x):
            found.add(x)

    walk(value)
    return found


class Prefs:
    def __init__(self, hass: HomeAssistant, data) -> None:
        self.hass = hass
        self.data = data
        self._stop: Callable[[], None] | None = None
        self._touched: dict[str, datetime] = {}  # device -> when the agent last changed it (memory only)
        self._before: dict[str, datetime] = {}  # device -> when an earlier turn changed it, before the latest
        self._waiting: dict[tuple[str, str], tuple[Callable[[], None], int]] = {}  # a change by hand, settling
        self._asked: dict[tuple[str, str], dict[str, Any]] = {}  # a level just asked for, while the device may still report it

    @property
    def state(self) -> dict[str, Any]:
        stored = self.data.data.setdefault("prefs", fresh())
        stored.setdefault("devices", {})
        return stored

    def on(self) -> bool:
        return self.data.feature("prefs")

    @callback
    def start(self) -> None:
        self._stop = self.hass.bus.async_listen(EVENT_STATE_CHANGED, self._changed)

    @callback
    def stop(self) -> None:
        if self._stop:
            self._stop()
            self._stop = None
        for cancel, _ in self._waiting.values():
            cancel()
        self._waiting.clear()

    def _now(self) -> datetime:
        return datetime.now(UTC)

    # --- which device a level belongs to ----------------------------------------------------------------

    def key(self, entity_id: str) -> str:
        """The device a level is kept under. A speaker that Music Assistant and its maker both show is one
        speaker: kept under Music Assistant's copy, which is the one the music tool plays on."""
        if not entity_id.startswith("media_player."):
            return entity_id
        state = self.hass.states.get(entity_id)
        if state is None:
            return entity_id
        from . import music  # noqa: PLC0415

        name = state.name.strip().lower()
        return next((p["id"] for p in music.players(self.hass) if p["name"].strip().lower() == name), entity_id)

    # --- what the agent did, and what people asked for ---------------------------------------------------

    @callback
    def agent_touched(self, entity_ids: set[str]) -> None:
        """The agent just changed these devices: their changes in the next AGENT_S are its own."""
        now = self._now()
        for entity_id in entity_ids:
            key = self.key(entity_id)
            last = self._touched.get(key)
            if last and (now - last).total_seconds() > AGENT_S:  # an earlier turn's: what a correction corrects
                self._before[key] = last
            self._touched[key] = now

    @callback
    def after_turn(self, text: str, entity_ids: set[str], *, by_person: bool) -> None:
        """A turn just ended. If a person asked about a device's level, remember the level it ends at."""
        if not self.on() or not by_person or not entity_ids:
            return
        wanted = [name for name, pattern in ASKED.items() if pattern.search(text or "")]
        if not wanted:
            return  # the agent chose any level itself: nothing to learn from that
        ended = self._now()
        for entity_id in entity_ids:
            for setting in wanted:
                level = self._level(entity_id, setting)
                if level is None:
                    continue
                last = self._before.get(self.key(entity_id))
                how = "corrected" if last and (ended - last).total_seconds() < CORRECT_S else "asked"
                row = self._record(entity_id, setting, level, how)
                if row is not None:
                    self._asked[(self.key(entity_id), setting)] = row

    def _level(self, entity_id: str, setting: str) -> int | None:
        domain, attribute, to_pct = SETTINGS[setting]
        state = self.hass.states.get(entity_id)
        if state is None or not entity_id.startswith(f"{domain}.") or state.state in ("unavailable", "unknown", "off"):
            return None
        value = state.attributes.get(attribute)
        return max(0, min(100, to_pct(value))) if isinstance(value, int | float) else None

    # --- changes by hand ---------------------------------------------------------------------------------

    @callback
    def _changed(self, event: Event) -> None:
        if not self.on():
            return
        entity_id = event.data.get("entity_id") or ""
        old, new = event.data.get("old_state"), event.data.get("new_state")
        if old is None or new is None or not DEVICE.match(entity_id):
            return
        if event.context.parent_id:  # an automation or a script made it
            return
        key = self.key(entity_id)
        touched = self._touched.get(key)
        if touched and (self._now() - touched).total_seconds() < AGENT_S:
            self._settled(key, entity_id, touched)  # the agent's own change: a level asked for may have just landed
            return
        for setting, (domain, attribute, _) in SETTINGS.items():
            if not entity_id.startswith(f"{domain}.") or new.state in ("unavailable", "unknown", "off"):
                continue
            was, now = old.attributes.get(attribute), new.attributes.get(attribute)
            if not isinstance(now, int | float) or was == now or was is None:
                continue
            level = self._level(entity_id, setting)
            if level is None:
                continue
            waiting = self._waiting.pop((entity_id, setting), None)
            if waiting:
                waiting[0]()  # still adjusting: start the quiet over

            @callback
            def settle(_now: datetime, entity_id: str = entity_id, setting: str = setting) -> None:
                _, level = self._waiting.pop((entity_id, setting), (None, None))
                if level is None:
                    return
                earlier = self._touched.get(self.key(entity_id))
                corrected = earlier and (self._now() - earlier).total_seconds() < CORRECT_S + SETTLE_S
                self._record(entity_id, setting, level, "corrected" if corrected else "by hand")

            self._waiting[(entity_id, setting)] = (async_call_later(self.hass, SETTLE_S, settle), level)

    def _settled(self, key: str, entity_id: str, touched: datetime) -> None:
        """A device the agent just set reported a new level: if a person asked for it, that is the level."""
        for setting in SETTINGS:
            row = self._asked.get((key, setting))
            if row is None:
                continue
            if datetime.fromisoformat(row["at"]) < touched or (self._now() - datetime.fromisoformat(row["at"])).total_seconds() > AGENT_S:
                self._asked.pop((key, setting), None)
                continue
            level = self._level(entity_id, setting)
            if level is not None and level != row["level"]:
                row["level"] = level
                self.data.changed()

    # --- what is kept ------------------------------------------------------------------------------------

    def _record(self, entity_id: str, setting: str, level: int, how: str) -> dict[str, Any] | None:
        if not self.on():
            return None
        key = self.key(entity_id)
        state = self.hass.states.get(key) or self.hass.states.get(entity_id)
        device = self.state["devices"].setdefault(key, {})
        device["name"] = state.name if state else key
        row = device.setdefault(setting, {"levels": []})
        kept = {"level": int(level), "at": self._now().isoformat(), "how": how}
        levels = row["levels"]
        if how == "corrected":  # what it corrects was wrong: it goes
            levels = [item for item in levels if (self._now() - datetime.fromisoformat(item["at"])).total_seconds() > CORRECT_S + SETTLE_S]
        row["levels"] = [*levels, kept][-KEEP:]
        self.data.changed()
        return kept

    def level(self, entity_id: str, setting: str) -> int | None:
        """The level this household wants for this device's setting, or None when there isn't one yet."""
        if not self.on():
            return None
        row = (self.state["devices"].get(self.key(entity_id)) or {}).get(setting)
        levels = [item["level"] for item in (row or {}).get("levels") or []]
        return round(statistics.median(levels)) if levels else None

    def listing(self) -> list[dict[str, Any]]:
        out = []
        for key, device in sorted(self.state["devices"].items(), key=lambda kv: str(kv[1].get("name") or kv[0]).lower()):
            for setting in SETTINGS:
                levels = (device.get(setting) or {}).get("levels") or []
                if levels:
                    last = levels[-1]
                    out.append({"entity_id": key, "name": device.get("name") or key, "setting": setting,
                                "level": round(statistics.median(item["level"] for item in levels)), "times": len(levels),
                                "last_at": last["at"], "last_how": last["how"]})
        return out

    def forget(self, entity_id: str, setting: str) -> bool:
        device = self.state["devices"].get(entity_id)
        if not device or setting not in device:
            return False
        del device[setting]
        if not any(name in device for name in SETTINGS):
            del self.state["devices"][entity_id]
        self.data.changed()
        return True

    def prompt(self) -> str:
        """What the agent is told on every turn: each device's learned level, for the ones it may use."""
        if not self.on():
            return ""
        from homeassistant.components.homeassistant.exposed_entities import async_should_expose  # noqa: PLC0415

        from . import wording  # noqa: PLC0415

        lines = []
        for row in self.listing():
            try:
                if not async_should_expose(self.hass, "conversation", row["entity_id"]):
                    continue
            except KeyError:
                continue
            lines.append(wording.pref_line(row))
        return wording.PREFS_HEADER + "\n".join(lines) if lines else ""
