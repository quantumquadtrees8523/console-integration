"""Device settings: how this household wants each of its devices set, learned from what people do, and used
by the agent whenever someone doesn't say.

Owner, 2026-11-28: "maybe the user is listening to music on some speaker and they think it's too loud. They
ask to drop the volume or else do so manually. The agent should be able to see that and remember that
setting for future agent actions on that device", and "this should be general. not just speakers and lights".

A setting is anything a person can adjust on a device and Home Assistant has an action for (SETTINGS): a
light's brightness, colour temperature, colour or effect; a speaker's volume, source or sound mode; a
thermostat's target temperature, mode, fan, preset, swing or humidity; a fan's speed, preset, direction or
oscillation; a cover's or valve's position and tilt; a humidifier's target and mode; a water heater's
temperature and mode; a vacuum's fan speed; the value of a number or a select (helpers too). Never a lock,
an alarm or a garage door.

Where a value comes from:

- A chat (or voice, or Assist) turn in which the agent set that setting on that device on purpose (its call
  named a value, or turned it up or down) and the person asked for it: for a number they gave a number or
  said which way ("too loud", "turn it down", "a bit warmer"), for a choice they named it ("movie mode").
  Their words are only looked at, never kept. The value is the one the device is at when the turn ends,
  updated if it reports a new one within AGENT_S (a speaker can be slow to say). A value the agent chose
  without being asked never counts, and nor does the agent using a value it already learned.
- A change by hand (the device itself, the app): the value it was left at once the person stopped adjusting
  it (SETTLE_S of quiet). For settings a device also changes by itself (a thermostat's schedule, a TV's
  source), only a change someone made signed in to Home Assistant counts (PERSON_ONLY).
- Either one within CORRECT_S of the agent setting that device is a correction: the agent got it wrong, so
  it replaces the values kept in the CORRECT_S before it.
- Never a change made by an automation or a script.

A setting's learned value is the middle of its last KEEP numbers, or the choice made most often among its last
KEEP (the latest wins a tie), so one odd evening doesn't move it. The agent is told each one on every turn,
and the music tool starts music at a speaker's learned volume when no volume is given. Each is listed under
"What the house knows about you", where an administrator can forget it.

Console keeps per device: its id and name, and per setting its last few values with when and how. Nothing a
person said. It isn't part of anything sent to the relay. "Learn device settings" under AI features turns it
off: nothing is recorded and nothing is used.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
import logging
import re
import statistics
from typing import Any

from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later

_LOGGER = logging.getLogger(__name__)

STATE = "state"  # a setting that is the entity's state itself (a number's value, a select's option, a thermostat's mode)


@dataclass(frozen=True)
class Setting:
    attribute: str  # the attribute that holds it, or STATE
    label: str  # how a person says it
    numeric: bool
    # The actions that set it: action -> the data keys that name a value (empty: the action itself changes it,
    # like volume_down). An action listed with keys sets it only when one of those keys is in its data.
    actions: dict[str, tuple[str, ...]] = field(default_factory=dict)
    person_only: bool = False  # devices change it by themselves too: by hand counts only from someone signed in
    unit: str = ""  # "%" or "%255" (0-255 shown as a percentage) or "temp"


def _s(attribute: str, label: str, numeric: bool, actions: dict[str, tuple[str, ...]], **kw: Any) -> Setting:
    return Setting(attribute, label, numeric, actions, **kw)


SETTINGS: dict[str, tuple[Setting, ...]] = {
    "light": (
        _s("brightness", "brightness", True, {"turn_on": ("brightness", "brightness_pct", "brightness_step", "brightness_step_pct")}, unit="%255"),
        _s("color_temp_kelvin", "colour temperature", True, {"turn_on": ("color_temp_kelvin", "kelvin", "color_temp")}, unit="K"),
        _s("rgb_color", "colour", False, {"turn_on": ("rgb_color", "rgbw_color", "rgbww_color", "hs_color", "xy_color", "color_name")}),
        _s("effect", "effect", False, {"turn_on": ("effect",)}),
    ),
    "media_player": (
        _s("volume_level", "volume", True, {"volume_set": ("volume_level",), "volume_up": (), "volume_down": ()}, unit="%1"),
        _s("source", "source", False, {"select_source": ("source",)}, person_only=True),
        _s("sound_mode", "sound mode", False, {"select_sound_mode": ("sound_mode",)}, person_only=True),
    ),
    "climate": (
        _s("temperature", "target temperature", True, {"set_temperature": ("temperature",)}, person_only=True, unit="temp"),
        _s("target_temp_low", "lowest temperature", True, {"set_temperature": ("target_temp_low",)}, person_only=True, unit="temp"),
        _s("target_temp_high", "highest temperature", True, {"set_temperature": ("target_temp_high",)}, person_only=True, unit="temp"),
        _s(STATE, "mode", False, {"set_hvac_mode": ("hvac_mode",), "set_temperature": ("hvac_mode",)}, person_only=True),
        _s("fan_mode", "fan mode", False, {"set_fan_mode": ("fan_mode",)}, person_only=True),
        _s("preset_mode", "preset", False, {"set_preset_mode": ("preset_mode",)}, person_only=True),
        _s("swing_mode", "swing", False, {"set_swing_mode": ("swing_mode",)}, person_only=True),
        _s("humidity", "target humidity", True, {"set_humidity": ("humidity",)}, person_only=True, unit="%"),
    ),
    "fan": (
        _s("percentage", "speed", True, {"set_percentage": ("percentage",), "turn_on": ("percentage",), "increase_speed": (), "decrease_speed": ()}, unit="%"),
        _s("preset_mode", "preset", False, {"set_preset_mode": ("preset_mode",), "turn_on": ("preset_mode",)}),
        _s("direction", "direction", False, {"set_direction": ("direction",)}),
        _s("oscillating", "oscillation", False, {"oscillate": ("oscillating",)}),
    ),
    "cover": (
        _s("current_position", "position", True, {"set_cover_position": ("position",)}, unit="%"),
        _s("current_tilt_position", "tilt", True, {"set_cover_tilt_position": ("tilt_position",)}, unit="%"),
    ),
    "valve": (_s("current_position", "position", True, {"set_valve_position": ("position",)}, unit="%"),),
    "humidifier": (
        _s("humidity", "target humidity", True, {"set_humidity": ("humidity",)}, unit="%"),
        _s("mode", "mode", False, {"set_mode": ("mode",)}),
    ),
    "water_heater": (
        _s("temperature", "temperature", True, {"set_temperature": ("temperature",)}, person_only=True, unit="temp"),
        _s("operation_mode", "mode", False, {"set_operation_mode": ("operation_mode",)}, person_only=True),
    ),
    "vacuum": (_s("fan_speed", "fan speed", False, {"set_fan_speed": ("fan_speed",)}),),
    "number": (_s(STATE, "value", True, {"set_value": ("value",)}),),
    "input_number": (_s(STATE, "value", True, {"set_value": ("value",), "increment": (), "decrement": ()}),),
    "select": (_s(STATE, "option", False, {"select_option": ("option",), "select_next": (), "select_previous": ()}),),
    "input_select": (_s(STATE, "option", False, {"select_option": ("option",), "select_next": (), "select_previous": ()}),),
}
# Home Assistant's own intents (Assist, and the agent through them) that set a setting: intent -> (domain, attribute).
INTENTS: dict[str, tuple[tuple[str, str], ...]] = {
    "HassLightSet": (("light", "brightness"), ("light", "rgb_color"), ("light", "color_temp_kelvin")),
    "HassSetVolume": (("media_player", "volume_level"),),
    "HassMediaPlayerSetVolume": (("media_player", "volume_level"),),
    "HassClimateSetTemperature": (("climate", "temperature"),),
    "HassSetPosition": (("cover", "current_position"), ("valve", "current_position")),
    "HassFanSetSpeed": (("fan", "percentage"),),
}
NOT_A_SETTING = ("unavailable", "unknown")
OFF = ("off", "closed")  # a light that is off has no brightness to learn; a closed cover's position is 0, not a choice
KEEP = 5  # values kept per device and setting
SETTLE_S = 20  # a change by hand is the value left once the person stops adjusting for this long
AGENT_S = 30  # a change this soon after the agent touched a device is the agent's
CORRECT_S = 10 * 60  # a person's change this soon after the agent set a device corrects it
DEVICE = re.compile(rf"^({'|'.join(SETTINGS)})\.[a-z0-9_]+$")
# A person asking for a level, whatever the device: a number, or which way.
ADJUST = re.compile(
    r"\d|\b(up|down|more|less|lower|higher|raise|reduce|increase|decrease|too|bit|little|max|maximum|min|minimum|half|full|"
    r"louder|quieter|softer|brighter|dimmer|darker|lighter|warmer|cooler|colder|hotter|faster|slower|wider|narrower)\b",
    re.IGNORECASE,
)
COLOURS = re.compile(r"\b(colou?r|red|orange|amber|yellow|green|blue|purple|violet|pink|white|warm|cool|daylight)\b", re.IGNORECASE)


def person_asked(text: str, s: Setting, value: Any) -> bool:
    """Whether the person's own words asked for this setting's value (they are looked at, never kept)."""
    text = text or ""
    if s.numeric:
        return bool(ADJUST.search(text))
    if s.attribute == "rgb_color":
        return bool(COLOURS.search(text))
    said = re.sub(r"[_\s]+", " ", str(value)).strip().lower()
    return bool(said) and said in re.sub(r"[_\s]+", " ", text.lower())


def fresh() -> dict[str, Any]:
    return {"devices": {}}


def setting(entity_id: str, attribute: str) -> Setting | None:
    return next((s for s in SETTINGS.get(entity_id.partition(".")[0], ()) if s.attribute == attribute), None)


def entities_in(value: Any) -> set[str]:
    """Every device id anywhere in a tool call's arguments or result."""
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


def asked(tool: str, args: dict[str, Any], entity_ids: set[str]) -> set[tuple[str, str]]:
    """The (device, setting) pairs a tool call set on purpose: it named a value, or turned it up or down.
    `tool` is the tool's own name (act, music, HassLightSet…)."""
    out: set[tuple[str, str]] = set()
    if tool == "act":
        domain, _, action = str(args.get("action") or "").partition(".")
        keys = set((args.get("data") or {}).keys())
        for entity_id in entity_ids:
            if entity_id.partition(".")[0] != domain:
                continue
            for s in SETTINGS.get(domain, ()):
                wanted = s.actions.get(action)
                if wanted is not None and (not wanted or keys & set(wanted)):
                    out.add((entity_id, s.attribute))
    elif tool == "music":
        if args.get("volume") is not None and args.get("op") in ("play", "control"):
            out |= {(e, "volume_level") for e in entity_ids if e.startswith("media_player.")}
    elif tool in INTENTS:
        for entity_id in entity_ids:
            out |= {(entity_id, attr) for domain, attr in INTENTS[tool] if entity_id.startswith(f"{domain}.")}
    return out


def value_of(state, s: Setting) -> Any:
    """The setting's value as Home Assistant shows it, or None when the device has none to learn right now."""
    if state is None or state.state in NOT_A_SETTING:
        return None
    if s.attribute != STATE and state.state in OFF and state.domain in ("light", "media_player", "fan"):
        return None
    raw = state.state if s.attribute == STATE else state.attributes.get(s.attribute)
    if raw is None or raw == "":
        return None
    if s.numeric:
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
    return list(raw) if isinstance(raw, list | tuple) else raw


def learned_value(values: list[Any], numeric: bool) -> Any:
    if not values:
        return None
    if numeric:
        middle = statistics.median(values)
        return round(middle) if all(float(v).is_integer() for v in values) else round(middle, 2)
    counts = Counter(repr(v) for v in values)
    best = max(counts.values())
    return next(v for v in reversed(values) if counts[repr(v)] == best)  # the latest of the most chosen


class Prefs:
    def __init__(self, hass: HomeAssistant, data) -> None:
        self.hass = hass
        self.data = data
        self._stop: Callable[[], None] | None = None
        self._touched: dict[str, datetime] = {}  # device -> when the agent last changed it (memory only)
        self._before: dict[str, datetime] = {}  # device -> when an earlier turn changed it, before the latest
        self._waiting: dict[tuple[str, str], tuple[Callable[[], None], Any]] = {}  # a change by hand, settling
        self._asked: dict[tuple[str, str], dict[str, Any]] = {}  # a value just asked for, while the device may still report it

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

    # --- which device a value belongs to ----------------------------------------------------------------

    def key(self, entity_id: str) -> str:
        """The device a value is kept under. A speaker that Music Assistant and its maker both show is one
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
    def after_turn(self, text: str, wanted: set[tuple[str, str]], *, by_person: bool) -> None:
        """A turn just ended. Each (device, setting) its calls set on purpose that the person asked for: remember
        the value it ends at, unless that is just the value already learned (the agent using it isn't new)."""
        if not self.on() or not by_person:
            return
        ended = self._now()
        for entity_id, attribute in wanted:
            s = setting(entity_id, attribute)
            value = value_of(self.hass.states.get(entity_id), s) if s else None
            if value is None:
                continue
            if not person_asked(text, s, value) or self.value(entity_id, attribute) == learned_value([value], s.numeric):
                continue
            last = self._before.get(self.key(entity_id))
            how = "corrected" if last and (ended - last).total_seconds() < CORRECT_S else "asked"
            row = self._record(entity_id, s, value, how)
            if row is not None:
                self._asked[(self.key(entity_id), attribute)] = row

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
            self._settled(key, entity_id, touched)  # the agent's own change: a value asked for may have just landed
            return
        for s in SETTINGS[entity_id.partition(".")[0]]:
            was, now = value_of(old, s), value_of(new, s)
            if now is None or was is None or was == now:
                continue
            if s.person_only and not event.context.user_id:
                continue  # the device may have done it by itself (a schedule, a TV switching input)
            waiting = self._waiting.pop((entity_id, s.attribute), None)
            if waiting:
                waiting[0]()  # still adjusting: start the quiet over

            @callback
            def settle(_now: datetime, entity_id: str = entity_id, s: Setting = s) -> None:
                _, value = self._waiting.pop((entity_id, s.attribute), (None, None))
                if value is None:
                    return
                earlier = self._touched.get(self.key(entity_id))
                corrected = earlier and (self._now() - earlier).total_seconds() < CORRECT_S + SETTLE_S
                self._record(entity_id, s, value, "corrected" if corrected else "by hand")

            self._waiting[(entity_id, s.attribute)] = (async_call_later(self.hass, SETTLE_S, settle), now)

    def _settled(self, key: str, entity_id: str, touched: datetime) -> None:
        """A device the agent just set reported a new value: if a person asked for it, that is the value."""
        for s in SETTINGS[entity_id.partition(".")[0]]:
            row = self._asked.get((key, s.attribute))
            if row is None:
                continue
            at = datetime.fromisoformat(row["at"])
            if at < touched or (self._now() - at).total_seconds() > AGENT_S:
                self._asked.pop((key, s.attribute), None)
                continue
            value = value_of(self.hass.states.get(entity_id), s)
            if value is not None and value != row["value"]:
                row["value"] = value
                self.data.changed()

    # --- what is kept ------------------------------------------------------------------------------------

    def _record(self, entity_id: str, s: Setting, value: Any, how: str) -> dict[str, Any] | None:
        if not self.on():
            return None
        key = self.key(entity_id)
        state = self.hass.states.get(key) or self.hass.states.get(entity_id)
        device = self.state["devices"].setdefault(key, {})
        device["name"] = state.name if state else key
        row = device.setdefault(s.attribute, {"values": []})
        kept = {"value": value, "at": self._now().isoformat(), "how": how}
        values = row["values"]
        if how == "corrected":  # what it corrects was wrong: it goes
            values = [item for item in values if (self._now() - datetime.fromisoformat(item["at"])).total_seconds() > CORRECT_S + SETTLE_S]
        row["values"] = [*values, kept][-KEEP:]
        self.data.changed()
        return kept

    def value(self, entity_id: str, attribute: str) -> Any:
        """How this household wants this device's setting, or None when there isn't one yet."""
        s = setting(entity_id, attribute)
        if not self.on() or s is None:
            return None
        row = (self.state["devices"].get(self.key(entity_id)) or {}).get(attribute) or {}
        return learned_value([item["value"] for item in row.get("values") or []], s.numeric)

    def listing(self) -> list[dict[str, Any]]:
        from . import wording  # noqa: PLC0415

        out = []
        for key, device in sorted(self.state["devices"].items(), key=lambda kv: str(kv[1].get("name") or kv[0]).lower()):
            for s in SETTINGS.get(key.partition(".")[0], ()):
                values = (device.get(s.attribute) or {}).get("values") or []
                if not values:
                    continue
                value = learned_value([item["value"] for item in values], s.numeric)
                out.append({"entity_id": key, "name": device.get("name") or key, "setting": s.attribute, "label": s.label,
                            "value": value, "shown": wording.setting_value(s, value, self.hass.config.units.temperature_unit),
                            "times": len(values), "last_at": values[-1]["at"], "last_how": values[-1]["how"]})
        return out

    def forget(self, entity_id: str, attribute: str) -> bool:
        device = self.state["devices"].get(entity_id)
        if not device or attribute not in device:
            return False
        del device[attribute]
        if not any(k != "name" for k in device):
            del self.state["devices"][entity_id]
        self.data.changed()
        return True

    def prompt(self) -> str:
        """What the agent is told on every turn: each device's learned settings, for the devices it may use."""
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
