"""Usage details: how often each feature, tool, skill, agent and screen is used in this house, by day.

This is the one way usage is counted and reported. Everything that can be counted is an entry in REGISTRY
below; a count for anything else lands on a fixed catch-all ("unregistered"), so a word that isn't in the
registry can never be stored or sent. A new AI feature (features.py), a new tool (tools.py, or Sunrise's) and
a new screen each need an entry here and a name in wording.METRIC_NAMES: tests/test_metrics.py fails without.

What is kept, in Console's store under "metrics": for each UTC day, counts by registry id, with done, failed
and not confirmed (a read-back that didn't show the change), by router tier, and by how long a request took
in four bands. No time of day, no message, no device, room or person. What is sent to Console's relay is
`body()`: those days, what exists on this box, what was never used, and a short story in words built from
the counts alone by a fixed template (`story`). `check` walks the whole report against the fixed lists and
`scrub` reads the story word by word; if either fails nothing is sent. The household sees the same bytes
in Console settings, has a switch for it (switch.console_usage_details), and the data wipe erases it.

The contract with the relay is console-relay `protocol/metrics.md`; tests/metrics.schema.json is a copy of
its schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
import re
from typing import Any

from homeassistant.core import HomeAssistant

from . import features as ai_features, wording
from .const import (
    CATEGORIES,
    DOMAIN,
    LLM_API_ASSIST,
    LLM_API_SUNRISE,
    PATH_SUPPORT,
    PATH_TAPS,
    PATHS,
    ROUTE_LOCAL,
    ROUTE_OTHER,
    ROUTE_PRO,
    ROUTES,
)

V = 1
SWITCH = "metrics"
DAYS_KEPT = 35  # on this box
DAYS_SENT = 14  # in one report: the relay replaces each day it is sent
STORY_DAYS = 7
MOST = 1_000_000  # the most one count can say
MAX_BYTES = 64 * 1024
STORY_MAX = 1500

OUTCOMES = ("ok", "failed", "unconfirmed")
BANDS = ("under_1s", "1_to_3s", "3_to_10s", "over_10s")
EVENTS = ("shown", "tapped", "quick_tapped", "promoted", "ignored", "dismissed", "kept", "suggested", "expired")
SUGGESTION_KINDS = ("routine", "ask", "scene", "turn_on", "turn_off")
OTHER, UNREGISTERED, ASSIST, OWN_SKILL = "other", "unregistered", "assist_intent", "own"


@dataclass(frozen=True)
class Entry:
    """One thing that can be counted. `needs` is what must be installed for it to exist on a box; an entry
    that isn't `listed` is a catch-all, left out of what exists and what was never used."""

    kind: str
    id: str
    needs: str | None = None
    listed: bool = True


_SUNRISE_TOOLS = (
    "house_map", "act", "audit", "diagnose_device", "fix_device", "registry_edit", "discovered", "changes",
    "routine", "undo", "backup", "update", "network_check", "usage", "list_skills", "get_skill", "skill_update",
    "memory_list", "memory_read", "memory_write", "memory_delete", "behavior_log", "behavior_revert", "log_run",
)  # fmt: skip
_CONSOLE_TOOLS = ("music", "dashboard", "about", "chat_history", "console_handoff", "console_escalate")
_SKILLS = (
    "add-a-device", "build-a-skill", "custom-cards", "device-diagnosis", "explain", "improve-home",
    "learn-the-house", "match-my-style", "music-assistant", "routines", "self-knowledge", "undo", "welcome",
    "wifi-diagnosis",
)  # fmt: skip
_AGENTS = ("cloud_agent", "assist_local", "connector", "support", "taps")
_SCREENS = ("chat_card", "settings_plan", "settings_knows", "settings_features", "settings_general", "music_panel")

# The single registration point. Kinds: features, tools, skills, agents, surfaces, screens.
REGISTRY: tuple[Entry, ...] = (
    *(Entry("features", feature.key) for feature in ai_features.FEATURES),
    *(Entry("tools", name, needs="sunrise") for name in _SUNRISE_TOOLS),
    *(Entry("tools", name, needs="music" if name == "music" else None) for name in _CONSOLE_TOOLS),
    Entry("tools", ASSIST, listed=False),
    Entry("tools", OTHER, listed=False),
    Entry("tools", UNREGISTERED, listed=False),
    *(Entry("skills", name, needs="sunrise") for name in _SKILLS),
    Entry("skills", OWN_SKILL, listed=False),
    *(Entry("agents", name) for name in _AGENTS),
    *(Entry("surfaces", path) for path in PATHS),
    *(Entry("screens", name, needs="music" if name == "music_panel" else None) for name in _SCREENS),
)
KINDS = ("features", "tools", "skills", "agents", "surfaces", "screens")
IDS: dict[str, tuple[str, ...]] = {kind: tuple(e.id for e in REGISTRY if e.kind == kind) for kind in KINDS}
# Every group of counts a day can have, and the ids each may use. `cells` count done/failed/not confirmed;
# `plain` count how many.
CELLS: dict[str, tuple[str, ...]] = {
    "features": IDS["features"],
    "tools": IDS["tools"],
    "skills": IDS["skills"],
    "agents": IDS["agents"],
    "surfaces": IDS["surfaces"],
    "routes": ROUTES,
    "categories": CATEGORIES,
    "suggestion_kinds": SUGGESTION_KINDS,
}
PLAIN: dict[str, tuple[str, ...]] = {"suggestions": EVENTS, "screens": IDS["screens"]}


def fresh() -> dict[str, Any]:
    return {"since": None, "days": {}}


def on(data) -> bool:
    return data.switch(SWITCH)


# --- counting -------------------------------------------------------------------------------------


def _today(data) -> str:
    return data.now().astimezone(UTC).date().isoformat()


def _day(data) -> dict[str, Any]:
    kept = data.data.get("metrics")
    if not isinstance(kept, dict) or "days" not in kept:
        kept = data.data["metrics"] = fresh()
    today = _today(data)
    if today not in kept["days"]:
        kept["days"][today] = {}
        kept["since"] = kept["since"] or today
        for old in sorted(kept["days"])[:-DAYS_KEPT]:
            del kept["days"][old]
    return kept["days"][today]


def _cell(day: dict[str, Any], group: str, item: str, outcome: str) -> None:
    if item not in CELLS[group] or outcome not in OUTCOMES:
        return
    cell = day.setdefault(group, {}).setdefault(item, {})
    cell[outcome] = min(int(cell.get(outcome) or 0) + 1, MOST)


def _plain(day: dict[str, Any], group: str, item: str, by: int = 1) -> None:
    if item in PLAIN[group] and by > 0:
        counts = day.setdefault(group, {})
        counts[item] = min(int(counts.get(item) or 0) + by, MOST)


def band(ms: float) -> str:
    return BANDS[0] if ms < 1000 else BANDS[1] if ms < 3000 else BANDS[2] if ms < 10000 else BANDS[3]


def agent_of(route: str, path: str | None) -> str:
    if route == ROUTE_LOCAL:
        return "assist_local"
    if route == ROUTE_OTHER:
        return "support" if path == PATH_SUPPORT else "connector"
    return "cloud_agent"


def turn(data, route: str, category: str, ok: bool, path: str | None = None, ms: float | None = None) -> None:
    """One request, whoever answered it (state.ConsoleData.count_turn calls this for every one)."""
    if not on(data):
        return
    day, outcome = _day(data), "ok" if ok else "failed"
    cell = day.setdefault("turns", {})
    cell[outcome] = min(int(cell.get(outcome) or 0) + 1, MOST)
    _cell(day, "routes", route, outcome)
    _cell(day, "categories", category, outcome)
    _cell(day, "agents", agent_of(route, path), outcome)
    if path:
        _cell(day, "surfaces", path, outcome)
    if route not in (ROUTE_LOCAL, ROUTE_OTHER):  # a use of Console's cloud agent: the AI feature it belongs to
        for feature in ai_features.FEATURES:
            if path in feature.paths:
                _cell(day, "features", feature.key, outcome)
        if route == ROUTE_PRO:
            _cell(day, "features", ai_features.PRO, outcome)
    if ms is not None and route in ROUTES:
        bands = day.setdefault("latency", {}).setdefault(route, {})
        bands[band(ms)] = min(int(bands.get(band(ms)) or 0) + 1, MOST)


def tool_id(api_id: str | None, name: str) -> str:
    """The registry id for a tool call: its own name when it is registered, else a fixed catch-all."""
    name = (name or "").rsplit("__", 1)[-1]
    if api_id == LLM_API_ASSIST:
        return ASSIST
    if api_id in (LLM_API_SUNRISE, DOMAIN, None):
        return name if name in IDS["tools"] else UNREGISTERED
    return OTHER


def outcome_of(result: Any, error: bool) -> str:
    """Done, failed, or not confirmed: a tool that read its change back and didn't see it on every thing."""
    if error or (isinstance(result, dict) and result.get("error")):
        return "failed"
    if isinstance(result, dict):
        rows = result.get("results")
        said = [row.get("result") for row in rows if isinstance(row, dict)] if isinstance(rows, list) else [result.get("result")]
        if any(isinstance(word, str) and word != "CHECKED" for word in said):
            return "unconfirmed"
    return "ok"


def tool(data, api_id: str | None, name: str, args: Any, result: Any, error: bool) -> None:
    """One tool call by any agent (guard.CountedTool calls this for every one). Only the tool's registered
    name and how it went are kept; of its arguments, only which shipped skill was read."""
    if not on(data):
        return
    day, found, outcome = _day(data), tool_id(api_id, name), outcome_of(result, error)
    _cell(day, "tools", found, outcome)
    if found == "get_skill":
        skill = str((args or {}).get("name") or "") if isinstance(args, dict) else ""
        _cell(day, "skills", skill if skill in _SKILLS else OWN_SKILL, outcome)
    data.changed()


def suggestion_kind(sid: str, routine: bool) -> str:
    if routine:
        return "routine"
    head = sid.partition(":")[0]
    return {"ask": "ask", "scene": "scene", "on": "turn_on", "off": "turn_off"}.get(head, "turn_on")


def tap(data, kind: str, outcome: str, was_quick: bool = False, ms: float | None = None) -> None:
    """A tap on a suggestion or quick action. Something to ask is counted as a tap only: its request follows."""
    if not on(data):
        return
    day = _day(data)
    _cell(day, "suggestion_kinds", kind, outcome)
    _plain(day, "suggestions", "quick_tapped" if was_quick else "tapped")
    if kind == "ask":
        return
    _cell(day, "agents", "taps", outcome)
    _cell(day, "surfaces", PATH_TAPS, outcome)
    _cell(day, "features", ai_features.CHIPS, outcome)
    if ms is not None:
        bands = day.setdefault("latency", {}).setdefault(ROUTE_LOCAL, {})
        bands[band(ms)] = min(int(bands.get(band(ms)) or 0) + 1, MOST)


def event(data, what: str, by: int = 1) -> None:
    """Something that happened to a suggestion (suggestions.py): shown, promoted, ignored and so on."""
    if on(data):
        _plain(_day(data), "suggestions", {"quick": "promoted"}.get(what, what), by)


def seen(data, screen: str) -> None:
    """Someone opened one of Console's screens."""
    if on(data) and screen in PLAIN["screens"]:
        _plain(_day(data), "screens", screen)
        data.changed()


# --- what exists here, and what was never used ---------------------------------------------------------


def available(hass: HomeAssistant) -> dict[str, list[str]]:
    """What exists on this box, by kind: the registry, less what needs something that isn't installed."""
    from . import music  # noqa: PLC0415

    have = {"sunrise": bool(hass.config_entries.async_entries("sunrise")), "music": music.entry_id(hass) is not None}
    return {kind: [e.id for e in REGISTRY if e.kind == kind and e.listed and (e.needs is None or have[e.needs])] for kind in KINDS}


def _used(days: dict[str, dict[str, Any]], kind: str) -> set[str]:
    return {item for day in days.values() for item, count in (day.get(kind) or {}).items() if count}


def unused(exists: dict[str, list[str]], days: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    """What exists here and has no count on any of these days."""
    return {kind: [item for item in exists[kind] if item not in _used(days, kind)] for kind in KINDS}


# --- the story: counts in words, from a fixed template ----------------------------------------------


def _sum(cell: Any) -> int:
    return sum(int(n or 0) for n in cell.values()) if isinstance(cell, dict) else int(cell or 0)


def _totals(days: dict[str, dict[str, Any]], group: str) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for day in days.values():
        for item, cell in (day.get(group) or {}).items():
            total = out.setdefault(item, dict.fromkeys(OUTCOMES, 0))
            for outcome, n in (cell if isinstance(cell, dict) else {"ok": cell}).items():
                total[outcome] += int(n or 0)
    return out


def _top(totals: dict[str, dict[str, int]], kind: str, most: int) -> str:
    names = wording.METRIC_NAMES[kind]
    ranked = sorted(totals.items(), key=lambda row: (-_sum(row[1]), row[0]))
    return ", ".join(wording.STORY["item"].format(name=names[item], count=_sum(cell)) for item, cell in ranked[:most] if _sum(cell))


def story(exists: dict[str, list[str]], days: dict[str, dict[str, Any]], start: str, end: str) -> str:
    """What the house leaned on, what it never touched and what failed repeatedly, in a few plain sentences.
    Made from the counts and the names in wording.py alone."""
    words = wording.STORY
    turns = {o: sum(int((day.get("turns") or {}).get(o) or 0) for day in days.values()) for o in ("ok", "failed")}
    made = turns["ok"] + turns["failed"]
    said = [words["requests"].format(start=start, end=end, turns=made, ok=turns["ok"], failed=turns["failed"]) if made
            else words["nothing"].format(start=start, end=end)]  # fmt: skip
    for kind, most in (("agents", 3), ("surfaces", 3), ("features", 5), ("tools", 5), ("skills", 3)):
        if listed := _top(_totals(days, kind), kind, most):
            said.append(words[kind].format(list=listed))
    if listed := _top(_totals(days, "screens"), "screens", 3):
        said.append(words["screens"].format(list=listed))
    events = {e: sum(int((day.get("suggestions") or {}).get(e) or 0) for day in days.values()) for e in EVENTS}
    if taps := events["tapped"] + events["quick_tapped"]:
        said.append(words["taps"].format(taps=taps, promoted=events["promoted"]))
    never = unused(exists, days)
    named = [wording.METRIC_NAMES[kind][item] for kind in ("features", "agents", "surfaces") for item in never[kind]]
    if named:
        said.append(words["never"].format(list=", ".join(named)))
    for kind in ("tools", "skills"):
        if never[kind]:
            said.append(words["never_count"].format(unused=len(never[kind]), all=len(exists[kind]), kind=words["kinds"][kind]))
    bad = []
    for kind in ("features", "tools", "skills", "agents"):
        for item, cell in sorted(_totals(days, kind).items()):
            if cell["failed"] + cell["unconfirmed"] >= 2:
                bad.append(words["failed_item"].format(name=wording.METRIC_NAMES[kind][item], bad=cell["failed"] + cell["unconfirmed"], all=_sum(cell)))
    if bad:
        said.append(words["failed"].format(list=", ".join(bad[:6])))
    return " ".join(said)


_WORD = re.compile(r"[A-Za-z][A-Za-z']*")
_ALLOWED = re.compile(r"^[A-Za-z0-9 '.,:()\-]*$")


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for inner in value.values():
            yield from _strings(inner)


def vocabulary() -> list[str]:
    """Every word a story can have: the template's and the names', nothing else. The relay holds the same
    list (protocol/metrics.md) and refuses a story with any other word."""
    text = " ".join([*_strings(wording.STORY), *_strings(wording.METRIC_NAMES)])
    return sorted({word.casefold() for word in _WORD.findall(re.sub(r"\{\w+\}", " ", text))})


def scrub(text: Any, words: frozenset[str] | None = None) -> bool:
    """Whether a story is safe to send: short, plain characters, and every word from the fixed vocabulary."""
    if not isinstance(text, str) or len(text) > STORY_MAX or not _ALLOWED.match(text):
        return False
    allowed = words if words is not None else frozenset(vocabulary())
    return all(word.casefold() in allowed for word in _WORD.findall(text))


# --- the report: exactly what is sent ---------------------------------------------------------------


def _clean_day(day: dict[str, Any]) -> dict[str, Any]:
    """A day's counts in the order and shape they are sent, with nothing empty."""
    out: dict[str, Any] = {}
    if any((day.get("turns") or {}).values()):
        out["turns"] = {o: int(day["turns"].get(o) or 0) for o in ("ok", "failed")}
    # Only ids from the lists are read out of the store, whatever is in it.
    for group, ids in (CELLS | PLAIN).items():
        if found := {item: (day.get(group) or {})[item] for item in ids if (day.get(group) or {}).get(item)}:
            out[group] = found
    if found := {route: bands for route in ROUTES if (bands := (day.get("latency") or {}).get(route))}:
        out["latency"] = found
    return out


def report(hass: HomeAssistant, data) -> dict[str, Any]:
    if not on(data):
        return {"v": V, "on": False}
    kept = data.data.get("metrics") or fresh()
    days = {day: cleaned for day in sorted(kept["days"]) if (cleaned := _clean_day(kept["days"][day]))}
    today = datetime.fromisoformat(_today(data)).date()
    week_start = (today - timedelta(days=STORY_DAYS - 1)).isoformat()
    exists = available(hass)
    made = {
        "v": V,
        "on": True,
        "window": {"from": max(kept.get("since") or today.isoformat(), (today - timedelta(days=DAYS_KEPT - 1)).isoformat()), "to": today.isoformat()},
        "registry": exists,
        "unused": unused(exists, days),
        "days": {day: days[day] for day in sorted(days)[-DAYS_SENT:]},
        "story": {
            "from": week_start,
            "to": today.isoformat(),
            "text": story(exists, {day: counts for day, counts in days.items() if day >= week_start}, week_start, today.isoformat()),
        },
    }
    return made


_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= MOST


def check(made: Any) -> str | None:
    """Why a report may not be sent, or None when it may. Walks every key and value against the fixed
    lists: an unknown key, an id that isn't registered, a count that isn't a number, a story with a word
    outside the vocabulary. The relay does the same on arrival."""
    if not isinstance(made, dict) or made.get("v") != V or not isinstance(made.get("on"), bool):
        return "version"
    if not made["on"]:
        return None if set(made) == {"v", "on"} else "schema"
    if set(made) != {"v", "on", "window", "registry", "unused", "days", "story"}:
        return "schema"
    window, told = made["window"], made["story"]
    if not (isinstance(window, dict) and set(window) == {"from", "to"} and all(isinstance(d, str) and _DAY.match(d) for d in window.values())):
        return "schema"
    for lists in (made["registry"], made["unused"]):
        if not isinstance(lists, dict) or set(lists) != set(KINDS):
            return "schema"
        for kind, items in lists.items():
            if not isinstance(items, list) or len(set(items)) != len(items) or any(item not in IDS[kind] for item in items):
                return "schema"
    days = made["days"]
    if not isinstance(days, dict) or len(days) > DAYS_SENT:
        return "schema"
    for day, groups in days.items():
        if not (isinstance(day, str) and _DAY.match(day) and isinstance(groups, dict)):
            return "schema"
        for group, counts in groups.items():
            if not isinstance(counts, dict):
                return "schema"
            if group == "turns":
                good = set(counts) == {"ok", "failed"} and all(_count(n) for n in counts.values())
            elif group in CELLS:
                good = all(
                    item in CELLS[group] and isinstance(cell, dict) and cell and set(cell) <= set(OUTCOMES) and all(_count(n) for n in cell.values())
                    for item, cell in counts.items()
                )
            elif group in PLAIN:
                good = all(item in PLAIN[group] and _count(n) for item, n in counts.items())
            elif group == "latency":
                good = all(
                    route in ROUTES and isinstance(bands, dict) and all(b in BANDS and _count(n) for b, n in bands.items())
                    for route, bands in counts.items()
                )
            else:
                good = False
            if not good:
                return "schema"
    if not (isinstance(told, dict) and set(told) == {"from", "to", "text"} and all(isinstance(told[k], str) and _DAY.match(told[k]) for k in ("from", "to"))):
        return "schema"
    if not scrub(told["text"]):
        return "story"
    return None


def body(hass: HomeAssistant, data) -> str:
    """The report as the exact text that is sent, and that the household is shown. A report that fails
    its own check, or is too big, is held back: what goes out then says only that."""
    held = json.dumps({"held": True, "on": True, "v": V}, sort_keys=True, separators=(",", ":"))
    try:
        made = report(hass, data)
        text = json.dumps(made, sort_keys=True, separators=(",", ":"))
    except Exception:  # noqa: BLE001 (a report that can't be made is one that isn't sent)
        return held
    return held if check(made) is not None or len(text.encode()) > MAX_BYTES else text


def shown(hass: HomeAssistant, data) -> dict[str, Any]:
    """What Console settings shows a household: the switch, the exact text that is sent, and its words."""
    text = body(hass, data)
    sent = json.loads(text)
    return {
        "on": on(data),
        "body": text,
        "held": bool(sent.get("held")),
        "story": (sent.get("story") or {}).get("text"),
        "words": wording.METRICS_PAGE,
        "names": wording.METRIC_NAMES,
        "days_kept": DAYS_KEPT,
    }
