"""Where a turn goes, and what it's counted as.

1. Home Assistant's own agent (built-in and learned sentences): free, on the home network.
2. Flash with thinking off, for a plain device command.
3. Flash with a little thinking, for everything else.
4. Pro, only after Flash fails or hands a hard case up.
"""

from __future__ import annotations

import re

from .const import CATEGORIES, EFFORT_FAST, EFFORT_FULL, ROUTE_FAST, ROUTE_FULL

_COMMAND = re.compile(
    r"^(please\s+)?(turn|switch|set|dim|brighten|raise|lower|open|close|play|pause|resume|stop|skip|mute|"
    r"unmute|start|lock|unlock|activate|run|toggle|make|put)\b",
    re.IGNORECASE,
)
_NOT_PLAIN = re.compile(
    r"\b(dashboard|automation|routine|schedule|every|whenever|when|if|why|how|what|which|rename|create|add|"
    r"remove|delete|set up|setup|install|fix|diagnose|remember|forget|help|explain|tomorrow|tonight at|"
    r"minutes?|hours?|sunset|sunrise)\b",
    re.IGNORECASE,
)


def plain_command(text: str) -> bool:
    """A short imperative about a device ("turn off the desk lamp", "play jazz in the kitchen")."""
    text = text.strip()
    return len(text.split()) <= 12 and bool(_COMMAND.match(text)) and not _NOT_PLAIN.search(text)


def first_route(text: str) -> tuple[str, str]:
    """The route and thinking effort for a turn the local agent didn't take."""
    return (ROUTE_FAST, EFFORT_FAST) if plain_command(text) else (ROUTE_FULL, EFFORT_FULL)


# --- labels ----------------------------------------------------------------------------------------

_CONTROL_INTENTS = ("TurnOn", "TurnOff", "Toggle", "Set", "Media", "Vacuum", "Open", "Close", "Lock", "Unlock",
                    "StartTimer", "CancelTimer", "Pause", "Unpause", "Volume", "Lawn", "Fan", "Climate")  # fmt: skip
_STATUS_INTENTS = ("GetState", "GetWeather", "GetCurrent", "GetTemperature", "TimerStatus", "Nevermind")


def category_for_intent(intent_name: str | None) -> str:
    """A local turn's label, from the intent Home Assistant matched."""
    name = intent_name or ""
    if any(part in name for part in _STATUS_INTENTS):
        return "status"
    if any(part in name for part in _CONTROL_INTENTS):
        return "control"
    return "other"


_TOOL_CATEGORY = {
    "act": "control",
    "routine": "customization",
    "dashboard": "customization",
    "registry_edit": "customization",
    "skill_update": "customization",
    "memory_write": "customization",
    "diagnose_device": "troubleshooting",
    "fix_device": "troubleshooting",
    "network_check": "troubleshooting",
    "audit": "troubleshooting",
    "house_map": "status",
    "changes": "status",
    "usage": "status",
    "memory_read": "status",
    "memory_list": "status",
}
_ORDER = ("setup", "troubleshooting", "customization", "control", "status", "other")
_SETUP_SKILLS = ("welcome", "add-a-device", "learn-the-house", "install", "onboard")


def category_for_tools(calls: list[tuple[str, dict]]) -> str:
    """A label from the tools a turn used (name, arguments): the strongest one wins."""
    found = set()
    for name, args in calls:
        name = name.rsplit("__", 1)[-1]
        if name == "get_skill":
            skill = str((args or {}).get("name") or "")
            found.add("setup" if any(s in skill for s in _SETUP_SKILLS) else "other")
        elif name.startswith("Hass"):
            found.add(category_for_intent(name))
        else:
            found.add(_TOOL_CATEGORY.get(name, "other"))
    return next((c for c in _ORDER if c in found), "other")


_LABEL = re.compile(r"\s*\[\[(" + "|".join(CATEGORIES) + r")\]\]\s*$", re.IGNORECASE)


def split_label(reply: str) -> tuple[str, str | None]:
    """The reply without its trailing [[label]], and the label if the model gave one."""
    found = _LABEL.search(reply or "")
    if not found:
        return (reply or "").strip(), None
    return reply[: found.start()].strip(), found.group(1).lower()
