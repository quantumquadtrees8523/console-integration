"""One coarse label for each request: what kind of thing it was ("lights.on_off", "automations.create").

The label comes from what was done (the intent Home Assistant matched, or the tool the agent called and
its action), never from the person's words, and only from the fixed lists below. The counts go to
Console's relay in batches, where they are added to one total for all houses together and kept for no
single house. The lists and the batch are a contract with the relay: console-relay `protocol/topics.md`.
"""

from __future__ import annotations

from typing import Any

AREAS = (
    "lights", "switches", "climate", "covers", "locks", "security", "music", "fans", "vacuum", "scenes",
    "timers", "lists", "weather", "sensors", "house", "automations", "dashboards", "devices", "network",
    "memory", "skills", "backups", "plan", "help", "handoff", "learned", "chat", "other",
)  # fmt: skip
ACTIONS = (
    "on_off", "adjust", "play", "control", "run", "create", "change", "remove", "fix", "diagnose", "ask",
    "other",
)  # fmt: skip
NOTHING = "other.other"

_DOMAIN_AREA = {
    "light": "lights",
    "switch": "switches",
    "input_boolean": "switches",
    "climate": "climate",
    "water_heater": "climate",
    "humidifier": "climate",
    "cover": "covers",
    "valve": "covers",
    "lock": "locks",
    "alarm_control_panel": "security",
    "media_player": "music",
    "fan": "fans",
    "vacuum": "vacuum",
    "lawn_mower": "vacuum",
    "scene": "scenes",
    "script": "scenes",
    "timer": "timers",
    "todo": "lists",
    "shopping_list": "lists",
    "weather": "weather",
    "sensor": "sensors",
    "binary_sensor": "sensors",
    "automation": "automations",
}
_ON_OFF = {
    "turn_on", "turn_off", "toggle", "open_cover", "close_cover", "stop_cover", "open_valve", "close_valve",
    "lock", "unlock", "open", "start", "stop", "pause", "return_to_base", "start_mowing", "dock", "press",
    "alarm_disarm",
}  # fmt: skip
_PLAYS = {"play_media", "media_play", "select_source"}
# When a request did several things, the one that changed the most names it.
_WEIGHT = {
    "create": 5, "change": 5, "remove": 5, "fix": 5, "on_off": 4, "adjust": 4, "play": 4, "control": 4,
    "run": 4, "diagnose": 3, "ask": 2, "other": 1,
}  # fmt: skip


def label(area: str, action: str) -> str:
    return f"{area}.{action}" if area in AREAS and action in ACTIONS else NOTHING


def _area(domain: Any) -> str:
    if isinstance(domain, list | tuple | set):
        domain = next(iter(domain), None)
    return _DOMAIN_AREA.get(str(domain or ""), "other")


def for_action(action: Any, data: Any = None) -> str:
    """A Home Assistant action ("light.turn_on", with or without data) as a label."""
    domain, _, service = str(action or "").partition(".")
    area = _area(domain)
    if area == "scenes":
        return label(area, "run")
    if area == "automations":
        return label(area, "run" if service == "trigger" else "change")
    if area == "music":
        if service in _PLAYS:
            return label(area, "play")
        return label(area, "on_off" if service in ("turn_on", "turn_off", "toggle") else "control")
    if service in _ON_OFF or service.startswith("alarm_arm"):
        return label(area, "adjust" if service == "turn_on" and data and area in ("lights", "fans") else "on_off")
    if "set" in service or service in ("increase_speed", "decrease_speed"):
        return label(area, "adjust")
    return label(area, "other")


def for_intent(name: str | None, domains: Any = None) -> str:
    """A Home Assistant intent ("HassTurnOn") and the kinds of thing it matched, as a label."""
    name = name or ""
    area = _area(domains) if domains else "other"
    if "LightSet" in name:
        return "lights.adjust"
    if "Climate" in name or "Temperature" in name or "Humidifier" in name:
        return "climate.ask" if "Get" in name else "climate.adjust"
    if "MediaSearchAndPlay" in name:
        return "music.play"
    if "Media" in name or "Volume" in name:
        return "music.control"
    if "Timer" in name:
        return "timers.ask" if "Status" in name else "timers.create" if "Start" in name else "timers.control"
    if "Weather" in name:
        return "weather.ask"
    if "GetCurrent" in name:
        return "house.ask"
    if "GetState" in name:
        return label("house" if area == "other" else area, "ask")
    if "List" in name:
        return "lists.change"
    if "Vacuum" in name or "LawnMower" in name:
        return "vacuum.on_off"
    if "SetPosition" in name:
        return label("covers" if area == "other" else area, "adjust")
    if "FanSetSpeed" in name:
        return "fans.adjust"
    if any(part in name for part in ("TurnOn", "TurnOff", "Toggle", "OpenCover", "CloseCover")):
        if area == "scenes":
            return "scenes.run"
        return label("covers" if area == "other" and "Cover" in name else area, "on_off")
    if "Nevermind" in name or "Respond" in name:
        return "chat.other"
    return NOTHING


_PLAIN_TOOLS = {
    "diagnose_device": "devices.diagnose",
    "fix_device": "devices.fix",
    "network_check": "network.diagnose",
    "audit": "house.diagnose",
    "discovered": "devices.ask",
    "house_map": "house.ask",
    "changes": "house.ask",
    "behavior_log": "house.ask",
    "undo": "house.change",
    "behavior_revert": "house.change",
    "memory_write": "memory.change",
    "memory_delete": "memory.remove",
    "memory_read": "memory.ask",
    "memory_list": "memory.ask",
    "skill_update": "skills.change",
    "usage": "plan.ask",
    "about": "help.ask",
    "console_handoff": "handoff.other",
}
_BY_OP = {
    "routine": {"list": "ask", "get": "ask", "try": "run", "delete": "remove"},
    "dashboard": {"create": "create", "remove": "remove", "list": "ask"},
    "music": {"play": "play", "control": "control", "move": "control", "queue": "control", "search": "ask",
              "library": "ask", "speakers": "ask"},
    "registry_edit": {"remove_entity": "remove"},
    "backup": {"list": "ask", "status": "ask", "get": "ask"},
}  # fmt: skip
_OP_AREA = {"routine": "automations", "dashboard": "dashboards", "music": "music", "registry_edit": "devices",
            "backup": "backups"}  # fmt: skip
_OP_DEFAULT = {"routine": None, "dashboard": "other", "music": "other", "registry_edit": "change", "backup": "create"}


def for_tool(name: str, args: dict | None) -> str | None:
    """One tool call as a label, or None for a call that says nothing about what was asked (reading a
    skill's instructions, asking the time, logging the run)."""
    name = (name or "").rsplit("__", 1)[-1]
    args = args if isinstance(args, dict) else {}
    if name.startswith("Hass"):
        return for_intent(name, args.get("domain"))
    if name == "act":
        return for_action(args.get("action"), args.get("data"))
    if name in _OP_AREA:
        op = str(args.get("op") or "")
        action = _BY_OP[name].get(op) or _OP_DEFAULT[name]
        if action is None:  # a routine being checked or saved: new unless it names one that exists
            action = "change" if args.get("id") else "create"
        return label(_OP_AREA[name], action)
    return _PLAIN_TOOLS.get(name)


def for_turn(calls: list[tuple[str, dict]], category: str = "other") -> str:
    """The one label for a request, from the tools it used. No tools: it was talk."""
    found = [topic for topic in (for_tool(name, args) for name, args in calls) if topic]
    if not found:
        return "chat.ask" if category == "status" else "chat.other"
    return max(found, key=lambda topic: _WEIGHT.get(topic.partition(".")[2], 0))
