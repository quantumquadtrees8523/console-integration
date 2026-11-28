"""AI features: each thing Console does with AI, with a switch of its own.

The page in Console settings lists them: what each one is for, how expensive it tends to be, what this
house actually spent on it this month, and what turning it off means. The words are in wording.py; the
numbers are this box's own counts (state.py), in credits.

These are not the off switches (switch.py): those cut the house off from the relay, or from every AI
agent at once. A feature that is off stops one use of Console's own cloud agent and nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.core import HomeAssistant

from . import wording
from .const import MODEL_PRO, PATH_ASSIST, PATH_AUTOMATIONS, PATH_CHAT, PATH_STYLE, PATH_SUGGESTIONS, PATH_TAPS, PATH_VOICE, ROUTE_PRO
from .credits import credits


@dataclass(frozen=True)
class Feature:
    key: str
    default: bool
    level: str  # how expensive it tends to be: none, low, medium or high
    paths: tuple[str, ...] = ()  # where its requests are counted (the Plan tab's "Where it went")


AGENT, PRO, WEEKLY, STYLE, CHIPS = "agent", "pro", "suggestions", "style", "chips"
FEATURES = (
    Feature(AGENT, True, "low", (PATH_CHAT, PATH_VOICE, PATH_ASSIST, PATH_AUTOMATIONS)),
    Feature(PRO, True, "high"),
    Feature(WEEKLY, False, "medium", (PATH_SUGGESTIONS,)),
    Feature(STYLE, True, "medium", (PATH_STYLE,)),
    Feature(CHIPS, True, "none", (PATH_TAPS,)),
)
BY_KEY = {feature.key: feature for feature in FEATURES}
# Requests that are a feature of their own: the cloud-agent switch doesn't stop them, their own does.
OWN_SWITCH = (PATH_SUGGESTIONS, PATH_STYLE)


def is_on(data, key: str) -> bool:
    if key == WEEKLY:
        return bool(data.suggestions.state["on"])
    if key == STYLE:
        return bool(data.style.state["on"])
    return bool((data.data.get("features") or {}).get(key, BY_KEY[key].default))


def set_on(data, key: str, on: bool) -> bool:
    if key == WEEKLY:
        data.suggestions.set_on(on)
    elif key == STYLE:
        data.style.state["on"] = bool(on)
        data.changed()
    else:
        data.data.setdefault("features", {})[key] = bool(on)
        data.changed()
    return is_on(data, key)


def _spent(data, feature: Feature) -> dict[str, Any]:
    """What this house's own counts say the feature used this month."""
    month = data.month()
    if feature.key == PRO:
        requests = int(month["by_route"].get(ROUTE_PRO) or 0)
        usd = float(((month.get("by_model") or {}).get(MODEL_PRO) or {}).get("spend_usd") or 0.0)
    else:
        rows = [data.paths().get(path) or {} for path in feature.paths]
        requests = sum(int(row.get("turns") or 0) for row in rows)
        usd = sum(float(row.get("spend_usd") or 0.0) for row in rows)
    return {"requests": requests, "credits": credits(usd), "each": credits(usd / requests) if requests and usd else None}


def listing(hass: HomeAssistant, data) -> dict[str, Any]:
    rows = []
    for feature in FEATURES:
        words = wording.FEATURES[feature.key]
        row = {"key": feature.key, "on": is_on(data, feature.key), "default": feature.default, "level": feature.level,
               "level_name": wording.COST_LEVELS[feature.level], "this_month": _spent(data, feature)} | words
        if feature.key == WEEKLY:
            last = data.suggestions.state.get("last_run") or {}
            row["last_run"] = {"at": last.get("at"), "ran": last.get("ran"), "why": last.get("why"), "made": last.get("made"),
                               "credits": credits(last.get("cost_usd") or 0.0)} if last else None
        if feature.key == STYLE:
            row["last_run"] = data.style.state.get("last_run")
        rows.append(row)
    return {"features": rows, "period": data.period, "credits": {"used": credits(data.spend_usd), "allowed": credits(data.cap_usd)},
            "about": wording.FEATURES_ABOUT}
