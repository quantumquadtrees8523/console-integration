"""Usage details (metrics.py): what is used in this house, counted by day against fixed lists, with a
story in words made from the counts. Nothing a person says, no device, room or time of day is in it; the
household sees exactly what is sent and can switch it off; the data wipe erases it. The registry is the one
place a countable thing is declared, and these tests fail when a feature or a tool isn't in it."""

from __future__ import annotations

import ast
from datetime import timedelta
import json
import logging
import os
from pathlib import Path
import re

from jsonschema import Draft202012Validator
import pytest

from homeassistant.core import Context
from homeassistant.helpers import area_registry as ar, entity_registry as er, llm

from custom_components.console import conversation, features, metrics, router, tools, topics, wipe, wording
from custom_components.console.const import CATEGORIES, PATHS, ROUTES

from .conftest import ask, link

SCHEMA = json.loads((Path(__file__).parent / "metrics.schema.json").read_text())
VALID = Draft202012Validator(SCHEMA)
SECRETS = ("zanzibar", "priya", "quokka", "wombat")


def today(console) -> dict:
    return console.data["metrics"]["days"].get(metrics._today(console), {})  # noqa: SLF001


async def sent(hass, hass_client) -> str:
    """The exact text Console's relay is given."""
    answer = await (await hass_client()).get("/api/console/relay/metrics")
    assert answer.status == 200 and answer.content_type == "application/json"
    return await answer.text()


async def ws(hass, hass_ws_client, message: dict, token: str | None = None) -> dict:
    client = await hass_ws_client(hass, token) if token else await hass_ws_client(hass)
    await client.send_json({"id": 1, **message})
    return await client.receive_json()


# --- the registry: the one place a countable thing is declared ------------------------------------------


def test_every_ai_feature_is_registered():
    assert metrics.IDS["features"] == tuple(feature.key for feature in features.FEATURES)


async def test_every_tool_console_gives_an_agent_is_registered(hass, console):
    ctx = llm.LLMContext(platform="test", context=Context(), language="en", assistant="conversation", device_id=None)
    own = [tool.name for tool in (await tools.ConsoleAPI(hass).async_get_api_instance(ctx)).tools]
    own += [conversation.ESCALATE, conversation.HANDOFF]
    assert own and not [name for name in own if name not in metrics.IDS["tools"]]


def test_every_tool_console_labels_is_registered():
    """A tool that topics.py or router.py knows by name is one Console expects to see: it must be countable."""
    named = {*topics._PLAIN_TOOLS, *topics._OP_AREA, *router._TOOL_CATEGORY}  # noqa: SLF001
    assert not sorted(name for name in named if name not in metrics.IDS["tools"])


def _sunrise() -> Path:
    """Sunrise's source, to read its tools and skills from: SUNRISE_REPO, or a checkout beside this one.
    CI clones it. Without it this test fails, on purpose: a Sunrise tool with no entry must not pass unseen."""
    where = Path(os.environ.get("SUNRISE_REPO") or Path(__file__).resolve().parents[2] / "sunrise")
    api = where / "custom_components" / "sunrise" / "api.py"
    assert api.is_file(), f"Sunrise isn't at {where}: git clone https://github.com/quantumquadtrees8523/sunrise there, or set SUNRISE_REPO"
    return where


def test_every_sunrise_tool_and_shipped_skill_is_registered():
    where = _sunrise()
    tree = ast.parse((where / "custom_components" / "sunrise" / "api.py").read_text())
    specs = [
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Spec" and node.args and isinstance(node.args[0], ast.Constant)
    ]
    assert len(specs) >= 20, "Sunrise's tool table wasn't found where it used to be"
    assert not sorted(name for name in specs if name not in metrics.IDS["tools"]), "a Sunrise tool has no entry in metrics.REGISTRY"
    skills = [p.name for p in (where / "custom_components" / "sunrise" / "bundled_skills").iterdir() if p.is_dir() and not p.name.startswith("_")]
    assert len(skills) >= 10
    assert not sorted(name for name in skills if name not in metrics.IDS["skills"]), "a Sunrise skill has no entry in metrics.REGISTRY"


def test_every_path_route_and_label_a_turn_can_have_is_countable():
    assert metrics.IDS["surfaces"] == PATHS and metrics.CELLS["routes"] == ROUTES and metrics.CELLS["categories"] == CATEGORIES
    for feature in features.FEATURES:
        assert set(feature.paths) <= set(PATHS)


def test_every_entry_has_a_plain_name_and_every_name_an_entry():
    for kind in metrics.KINDS:
        assert set(wording.METRIC_NAMES[kind]) == set(metrics.IDS[kind]), kind
    assert len({(e.kind, e.id) for e in metrics.REGISTRY}) == len(metrics.REGISTRY), "an entry is registered once"


def test_a_name_that_is_not_registered_can_never_be_counted(console):
    """Whatever string arrives, what is stored is an id from the registry."""
    for api, name in (("sunrise", "open the garage for Priya"), ("console", "zanzibar"), (None, "wombat"), ("someone_elses_api", "quokka")):
        metrics.tool(console, api, name, {"name": "the quokka skill"}, {"results": [{"result": "zanzibar"}]}, False)
    metrics.tool(console, "sunrise", "get_skill", {"name": "priya's own skill"}, {}, False)
    metrics.tool(console, "assist", "HassTurnOn", {"name": "Wombat lamp"}, {}, False)
    metrics.seen(console, "the zanzibar dashboard")
    metrics.event(console, "priya tapped")
    metrics.tap(console, "wombat", "ok")
    metrics.turn(console, "a route of my own", "a label of my own", True, "a path of my own")
    day = today(console)
    assert set(day["tools"]) == {"unregistered", "other", "get_skill", "assist_intent"} and day["skills"] == {"own": {"ok": 1}}
    assert day["tools"]["unregistered"] == {"unconfirmed": 3}
    assert "screens" not in day and "routes" not in day and "categories" not in day and set(day["surfaces"]) == {"suggestion_taps"}
    assert set(day["suggestions"]) == {"tapped"} and "suggestion_kinds" not in day
    kept = json.dumps(console.data["metrics"]).lower()
    assert not [word for word in SECRETS if word in kept]


# --- counting --------------------------------------------------------------------------------------


async def test_a_request_is_counted_by_agent_surface_route_feature_and_band(hass, console, model, lights_off, hass_admin_user, freezer):
    freezer.move_to("2026-11-28T07:14:00+00:00")
    link(console)
    await ask(hass, "turn off the kitchen light", Context(user_id=hass_admin_user.id))  # at home
    model.say("Two lights are on. [[status]]")
    await ask(hass, "which lights did we leave on downstairs and should I worry", Context(user_id=hass_admin_user.id))
    model.fail(conversation.openrouter.ModelError("http 500"))
    model.say("Nothing is wrong. [[troubleshooting]]")
    await ask(hass, "why does the hallway light keep dropping off the network")  # nobody signed in: an automation
    day = console.data["metrics"]["days"]["2026-11-28"]
    assert day["turns"] == {"ok": 3}
    assert day["agents"] == {"assist_local": {"ok": 1}, "cloud_agent": {"ok": 2}}
    assert day["surfaces"] == {"assist": {"ok": 2}, "automations": {"ok": 1}}
    assert day["routes"] == {"local": {"ok": 1}, "flash": {"ok": 1}, "pro": {"ok": 1}}
    assert day["categories"] == {"control": {"ok": 1}, "status": {"ok": 1}, "troubleshooting": {"ok": 1}}
    assert day["features"] == {"agent": {"ok": 2}, "pro": {"ok": 1}}, "a request answered at home is not a use of AI"
    assert day["latency"] == {"local": {"under_1s": 1}, "flash": {"under_1s": 1}, "pro": {"under_1s": 1}}
    assert "07" not in json.dumps(day) and "14" not in json.dumps(day), "the day, never the time of day"


async def test_a_request_the_cloud_agent_could_not_take_is_counted_as_not_done(hass, console, model):
    await ask(hass, "what should I automate next in this house")  # not linked
    day = today(console)
    assert day["turns"] == {"failed": 1}
    assert day["agents"] == {"cloud_agent": {"failed": 1}} and day["routes"] == {"fallback": {"failed": 1}}


def test_how_long_a_request_took_is_kept_as_one_of_four_bands():
    assert [metrics.band(ms) for ms in (0, 999, 1000, 2999, 3000, 9999, 10000, 600000)] == [
        "under_1s", "under_1s", "1_to_3s", "1_to_3s", "3_to_10s", "3_to_10s", "over_10s", "over_10s",
    ]  # fmt: skip


async def test_each_tool_an_agent_calls_is_counted_by_name_and_how_it_went(hass, console, model, lights_off):
    link(console)
    model.call_tool("assist__intent__HassTurnOff", {"name": "Kitchen light"})
    model.say("The kitchen light is off. [[control]]")
    await ask(hass, "could you make the kitchen dark for the movie")
    model.call_tool("console__about", {})
    model.say("You're on the Free plan. [[status]]")
    await ask(hass, "what plan is this house on and what does it include")
    model.call_tool("console_handoff", {"asked": "x", "why": "y", "next": "z"})
    await ask(hass, "please log in to my router and change the wifi password")
    day = today(console)
    assert day["tools"] == {"assist_intent": {"ok": 1}, "about": {"ok": 1}, "console_handoff": {"ok": 1}}


def test_a_tool_that_did_not_see_its_change_is_not_confirmed():
    assert metrics.outcome_of({"results": [{"result": "CHECKED"}, {"result": "NOT CONFIRMED"}]}, False) == "unconfirmed"
    assert metrics.outcome_of({"results": [{"result": "UNREACHABLE"}]}, False) == "unconfirmed"
    assert metrics.outcome_of({"results": [{"result": "CHECKED"}]}, False) == "ok"
    assert metrics.outcome_of({"result": "NOT CONFIRMED"}, False) == "unconfirmed"
    assert metrics.outcome_of({"error": "no such thing"}, False) == "failed" and metrics.outcome_of({}, True) == "failed"
    assert metrics.outcome_of({"things": []}, False) == "ok" and metrics.outcome_of(None, False) == "ok"


async def test_claude_and_any_coding_agent_are_counted_through_the_same_door(hass, console):
    """An agent that comes through Home Assistant's MCP server (Claude, Claude Code) gets its tools from the
    same guarded APIs as Console's own agent, so each call it makes is counted by the tool's name. Its turn
    is counted from those calls (others.py), under the connector."""
    console.guard.apply()
    mcp = llm.LLMContext(platform="mcp_server", context=Context(), language="en", assistant="conversation", device_id=None)
    api = await llm.async_get_api(hass, "console", mcp)
    await api.async_call_tool(llm.ToolInput(tool_name="about", tool_args={}))
    merged = await llm.async_get_api(hass, ["assist", "console"], mcp)
    await merged.async_call_tool(llm.ToolInput(tool_name="console__about", tool_args={}))
    assert today(console)["tools"] == {"about": {"ok": 2}}

    console.count_turn("other_agent", "status", True, agent="other_agents", topic="help.ask", path="claude")
    console.count_turn("other_agent", "control", False, agent="other_agents", path="support")
    day = today(console)
    assert day["agents"] == {"connector": {"ok": 1}, "support": {"failed": 1}}
    assert day["surfaces"] == {"claude": {"ok": 1}, "support": {"failed": 1}}
    assert "features" not in day, "another agent's turn isn't a use of Console's cloud agent"


async def test_consoles_own_plumbing_is_not_an_agent(hass, console):
    """A tapped suggestion and the suggestions' own reads use the tools without any agent: not counted."""
    console.guard.apply()
    own = llm.LLMContext(platform="console", context=Context(), language="en", assistant="conversation", device_id=None)
    api = await llm.async_get_api(hass, "console", own)
    await api.async_call_tool(llm.ToolInput(tool_name="about", tool_args={}))
    assert "tools" not in today(console)


async def test_taps_on_suggestions_and_opened_screens_are_counted(hass, console, hass_ws_client):
    hass.states.async_set("light.kitchen", "on", {"friendly_name": "Kitchen light"})
    await ws(hass, hass_ws_client, {"type": "console/suggestions/seen", "ids": ["off:light.kitchen", "ask:whats_on"]})
    tapped = await ws(hass, hass_ws_client, {"type": "console/suggestions/tap", "suggestion_id": "ask:whats_on"})
    assert tapped["success"] is True
    gone = await ws(hass, hass_ws_client, {"type": "console/suggestions/tap", "suggestion_id": "scene:scene.not_here"})
    assert gone["success"] is False
    for screen in ("chat_card", "settings_plan", "settings_plan"):
        assert (await ws(hass, hass_ws_client, {"type": "console/metrics/seen", "screen": screen}))["success"] is True
    refused = await ws(hass, hass_ws_client, {"type": "console/metrics/seen", "screen": "the bedroom dashboard"})
    assert refused["success"] is False
    day = today(console)
    assert day["suggestions"] == {"shown": 2, "tapped": 2} and day["screens"] == {"chat_card": 1, "settings_plan": 2}
    assert day["suggestion_kinds"] == {"ask": {"ok": 1}, "scene": {"failed": 1}}
    assert day["agents"] == {"taps": {"failed": 1}} and day["features"] == {"chips": {"failed": 1}}


async def test_counts_are_by_utc_day_and_old_days_are_dropped(hass, console, freezer):
    freezer.move_to("2026-11-28T23:59:00+00:00")
    console.count_turn("local", "control", True)
    freezer.move_to("2026-11-29T00:01:00+00:00")
    console.count_turn("local", "control", True)
    console.count_turn("local", "control", True)
    days = console.data["metrics"]["days"]
    assert {day: counts["turns"]["ok"] for day, counts in days.items()} == {"2026-11-28": 1, "2026-11-29": 2}
    assert console.data["metrics"]["since"] == "2026-11-28"
    for _ in range(60):
        freezer.tick(timedelta(days=1))
        console.count_turn("local", "control", True)
    kept = list(console.data["metrics"]["days"])
    assert len(kept) == metrics.DAYS_KEPT and kept[-1] == "2027-01-28" and "2026-11-29" not in kept


# --- what was never used ------------------------------------------------------------------------------


async def test_what_was_never_used_is_what_exists_here_less_what_was_counted(hass, console, model, lights_off, hass_client):
    link(console)
    exists = metrics.available(hass)
    assert exists["features"] == ["agent", "pro", "suggestions", "style", "chips"]
    assert "act" not in exists["tools"] and exists["skills"] == [], "no Sunrise on this box: its tools don't exist here"
    assert "music" not in exists["tools"] and "music_panel" not in exists["screens"], "nor Music Assistant"
    assert exists["tools"] == ["dashboard", "about", "chat_history", "console_handoff", "console_escalate"]

    model.call_tool("console__about", {})
    model.say("You're on the Free plan. [[status]]")
    await ask(hass, "what plan is this house on and what does it include")
    await ask(hass, "turn off the kitchen light")
    made = json.loads(await sent(hass, hass_client))
    assert made["registry"] == exists
    assert made["unused"]["features"] == ["pro", "suggestions", "style", "chips"]
    assert made["unused"]["tools"] == ["dashboard", "chat_history", "console_handoff", "console_escalate"]
    assert made["unused"]["agents"] == ["connector", "support", "taps"]
    assert "automations" not in made["unused"]["surfaces"] and "chat" in made["unused"]["surfaces"]
    for kind in metrics.KINDS:
        assert set(made["unused"][kind]) <= set(made["registry"][kind])
        assert not set(made["unused"][kind]) & {"unregistered", "other", "assist_intent", "own"}, "a catch-all is never 'unused'"


def test_unused_is_worked_out_over_every_day_kept():
    exists = {kind: list(metrics.IDS[kind][:3]) for kind in metrics.KINDS}
    days = {"2026-11-01": {"tools": {"house_map": {"ok": 1}}}, "2026-11-20": {"tools": {"act": {"failed": 2}}, "screens": {"chat_card": 4}}}
    never = metrics.unused(exists, days)
    assert never["tools"] == ["audit"] and never["screens"] == ["settings_plan", "settings_knows"]
    assert never["features"] == exists["features"]
    assert metrics.unused(exists, {})["tools"] == exists["tools"]


# --- the story ---------------------------------------------------------------------------------------


def test_the_story_says_what_was_leaned_on_never_touched_and_failed():
    exists = {"features": ["agent", "pro", "chips"], "tools": ["act", "routine", "music"], "skills": ["welcome"],
              "agents": ["cloud_agent", "assist_local", "connector"], "surfaces": ["chat", "voice"], "screens": ["chat_card"]}  # fmt: skip
    days = {
        "2026-11-27": {"turns": {"ok": 30, "failed": 0}, "agents": {"assist_local": {"ok": 30}}, "surfaces": {"voice": {"ok": 30}}},
        "2026-11-28": {
            "turns": {"ok": 9, "failed": 3},
            "agents": {"cloud_agent": {"ok": 9, "failed": 3}},
            "surfaces": {"chat": {"ok": 9, "failed": 3}},
            "features": {"agent": {"ok": 9, "failed": 3}},
            "tools": {"act": {"ok": 6, "unconfirmed": 1}, "music": {"ok": 2, "failed": 3}},
            "suggestions": {"tapped": 4, "promoted": 1},
            "screens": {"chat_card": 5},
        },
    }
    told = metrics.story(exists, days, "2026-11-22", "2026-11-28")
    assert told == (
        "From 2026-11-22 to 2026-11-28 this house made 42 requests: 39 done, 3 not done. "
        "Answered by: Home Assistant's own agent at home (30), Console's cloud agent (12). "
        "Asked from: voice (30), the chat card (12). "
        "AI features used: the cloud agent (12). "
        "Tools used most: switching things (7), music (5). "
        "Screens opened: the chat card (5). "
        "Suggestions were tapped 4 times and 1 became quick actions. "
        "Never used in this window: the stronger model, suggestions and quick actions, Claude and other agents through the connector. "
        "1 of 3 tools were never used. 1 of 1 skills were never used. "
        "Failed or not confirmed more than once: the cloud agent (3 of 12), music (3 of 5), Console's cloud agent (3 of 12)."
    )
    assert metrics.scrub(told)
    assert metrics.story(exists, {}, "2026-11-22", "2026-11-28").startswith("From 2026-11-22 to 2026-11-28 this house made no requests.")


@pytest.mark.parametrize(
    "text",
    [
        "This house asked about Priya's surprise party.",
        "Tools used most: the Quokka room lamp (3).",
        "Never used: <b>music</b>",
        "From 2026-11-22 to 2026-11-28 this house made 4 requests; see http://example.test",
        "house " * 400,
        None,
    ],
)
def test_a_story_with_any_word_outside_the_vocabulary_is_refused(text):
    assert metrics.scrub(text) is False


async def test_a_report_that_fails_its_own_check_is_held_back(hass, console, hass_client, hass_ws_client, monkeypatch):
    console.count_turn("local", "control", True)
    monkeypatch.setitem(wording.METRIC_NAMES["agents"], "assist_local", "Priya's kitchen")  # as if a name leaked into the words
    monkeypatch.setattr(metrics, "vocabulary", lambda: json.loads(json.dumps(TEXT["x-story-words"])))
    assert await sent(hass, hass_client) == '{"held":true,"on":true,"v":1}'
    shown = (await ws(hass, hass_ws_client, {"type": "console/metrics"}))["result"]
    assert shown["held"] is True and shown["story"] is None and "Priya" not in shown["body"]

    monkeypatch.undo()
    monkeypatch.setattr(metrics, "story", lambda *a: 1 / 0)  # a report that can't be made at all
    assert await sent(hass, hass_client) == '{"held":true,"on":true,"v":1}'


async def test_only_registered_ids_are_read_out_of_the_store_whatever_is_in_it(hass, console, hass_client):
    console.count_turn("local", "control", True)
    day = console.data["metrics"]["days"][metrics._today(console)]  # noqa: SLF001
    day["tools"] = {"Quokka room lamp": {"ok": 1}, "about": {"ok": 2}}
    day["said"] = {"zanzibar": 1}
    day["latency"] = {"at_0714": {"under_1s": 1}}
    text = await sent(hass, hass_client)
    made = json.loads(text)
    VALID.validate(made)
    assert made["days"][metrics._today(console)]["tools"] == {"about": {"ok": 2}}  # noqa: SLF001
    assert "Quokka" not in text and "zanzibar" not in text and "0714" not in text


# --- the contract with the relay ------------------------------------------------------------------------

TEXT = SCHEMA["$defs"]["report"]["properties"]["story"]["properties"]["text"]


def test_the_lists_here_are_the_contracts():
    """tests/metrics.schema.json is a copy of console-relay protocol/schemas/metrics.schema.json. A change to
    the registry or to the story's words that the relay doesn't have yet fails here: change the contract first."""
    defs = SCHEMA["$defs"]
    for kind in metrics.KINDS:
        listed = [e.id for e in metrics.REGISTRY if e.kind == kind and e.listed]
        assert defs["lists"]["properties"][kind]["items"]["enum"] == listed, kind
    day = defs["day"]["properties"]
    for group, ids in (metrics.CELLS | metrics.PLAIN).items():
        assert tuple(day[group]["properties"]) == tuple(ids), group
    assert set(day) == {"turns", "latency", *metrics.CELLS, *metrics.PLAIN}
    assert tuple(day["latency"]["properties"]) == ROUTES
    assert tuple(day["latency"]["properties"]["local"]["properties"]) == metrics.BANDS
    assert tuple(defs["cell"]["properties"]) == metrics.OUTCOMES
    assert TEXT["x-story-words"] == metrics.vocabulary() and TEXT["maxLength"] == metrics.STORY_MAX
    assert re.fullmatch(TEXT["pattern"], "abc") and metrics._ALLOWED.pattern == TEXT["pattern"]  # noqa: SLF001
    assert SCHEMA["x-max-bytes"] == metrics.MAX_BYTES and defs["count"]["maximum"] == metrics.MOST
    assert defs["report"]["properties"]["days"]["maxProperties"] == metrics.DAYS_SENT


async def test_what_this_box_sends_is_valid_under_the_relays_schema(hass, console, model, lights_off, hass_client, hass_ws_client):
    link(console)
    assert VALID.is_valid(json.loads(await sent(hass, hass_client))), "with nothing counted yet"
    model.call_tool("assist__intent__HassTurnOff", {"name": "Kitchen light"})
    model.say("The kitchen light is off. [[control]]")
    await ask(hass, "could you make the kitchen dark for the movie")
    await ask(hass, "turn off the kitchen light")
    model.fail(conversation.openrouter.ModelError("timeout"))
    model.fail(conversation.openrouter.ModelError("timeout"))
    await ask(hass, "what should I do about the thing that nobody can answer")  # both models fail
    console.count_turn("other_agent", "control", True, agent="other_agents", path="claude")
    metrics.tool(console, "sunrise", "act", {}, {"results": [{"result": "NOT CONFIRMED"}]}, False)
    metrics.tool(console, "sunrise", "get_skill", {"name": "welcome"}, {}, False)
    metrics.tool(console, "sunrise", "a_tool_from_next_year", {}, {}, False)
    metrics.tap(console, "turn_off", "ok", True, 120.0)
    metrics.event(console, "quick")
    await ws(hass, hass_ws_client, {"type": "console/metrics/seen", "screen": "settings_knows"})
    text = await sent(hass, hass_client)
    made = json.loads(text)
    VALID.validate(made)
    assert metrics.check(made) is None and len(text.encode()) < metrics.MAX_BYTES
    assert set(made) == {"v", "on", "window", "registry", "unused", "days", "story"}
    day = made["days"][metrics._today(console)]  # noqa: SLF001
    assert set(day) == {"turns", "features", "tools", "skills", "agents", "surfaces", "routes", "categories", "suggestion_kinds",
                        "suggestions", "screens", "latency"}  # fmt: skip
    for small in ('{"on":false,"v":1}', '{"held":true,"on":true,"v":1}'):
        VALID.validate(json.loads(small))


def test_the_schema_refuses_what_the_box_must_never_send():
    good = {"v": 1, "on": True, "window": {"from": "2026-11-28", "to": "2026-11-28"}, "registry": dict.fromkeys(metrics.KINDS, []),
            "unused": dict.fromkeys(metrics.KINDS, []), "days": {"2026-11-28": {"turns": {"ok": 1, "failed": 0}}},
            "story": {"from": "2026-11-22", "to": "2026-11-28", "text": "From 2026-11-22 to 2026-11-28 this house made no requests."}}  # fmt: skip
    VALID.validate(good)
    assert metrics.check(good) is None
    for change in (
        {"said": "turn off Priya's lamp"},
        {"days": {"2026-11-28": {"tools": {"Quokka room lamp": {"ok": 1}}}}},
        {"days": {"2026-11-28": {"turns": {"ok": 1, "failed": 0, "at_0714": 1}}}},
        {"days": {"2026-11-28T07:14": {}}},
        {"registry": dict.fromkeys(metrics.KINDS, []) | {"rooms": ["kitchen"]}},
        {"story": {"from": "2026-11-22", "to": "2026-11-28", "text": "Hello <b>"}},
    ):
        assert not VALID.is_valid(good | change), change
        assert metrics.check(good | change) is not None, change


# --- privacy: nothing said, no device, no room, in anything kept, sent, told or logged -----------------------


async def test_nothing_said_and_no_device_or_room_is_in_any_count_report_story_or_log(
    hass, console, model, hass_client, hass_ws_client, hass_admin_user, caplog
):
    caplog.set_level(logging.DEBUG, logger="custom_components.console")
    link(console)
    room = ar.async_get(hass).async_create("Quokka room")
    entry = er.async_get(hass).async_get_or_create("light", "test", "wombat-1", suggested_object_id="wombat_lamp")
    er.async_get(hass).async_update_entity(entry.entity_id, area_id=room.id, name="Wombat lamp")
    hass.states.async_set(entry.entity_id, "on", {"friendly_name": "Wombat lamp"})
    from homeassistant.components.homeassistant.exposed_entities import async_expose_entity
    from pytest_homeassistant_custom_component.common import async_mock_service

    async_expose_entity(hass, "conversation", entry.entity_id, True)
    off = async_mock_service(hass, "light", "turn_off")

    # At home, by name and by room.
    await ask(hass, "turn off the Wombat lamp", Context(user_id=hass_admin_user.id))
    await ask(hass, "turn off the lights in the Quokka room", Context(user_id=hass_admin_user.id))
    assert len(off) == 2
    # Through the cloud agent, with a tool that is given the name, on the chat card.
    client = await hass_ws_client(hass)
    model.call_tool("assist__intent__HassTurnOff", {"name": "Wombat lamp", "area": "Quokka room"})
    model.say("The Wombat lamp in the Quokka room is off, ready for Priya's zanzibar surprise. [[control]]")
    await client.send_json({"id": 7, "type": "console/chat", "text": "make the Quokka room dark for Priya's zanzibar surprise, the Wombat lamp too"})
    while (await client.receive_json()).get("event", {}).get("kind") != "done":
        pass
    # A tap on the suggestion that names the lamp.
    hass.states.async_set(entry.entity_id, "on", {"friendly_name": "Wombat lamp"})
    await client.send_json({"id": 8, "type": "console/suggestions/tap", "suggestion_id": f"off:{entry.entity_id}"})
    await client.receive_json()
    # Another agent's tools, as Sunrise would record them.
    metrics.tool(console, "sunrise", "act", {"action": "light.turn_off", "entity_ids": [entry.entity_id]}, {"results": [{"name": "Wombat lamp", "result": "CHECKED"}]}, False)
    metrics.tool(console, "sunrise", "memory_write", {"name": "priya.md", "text": "the zanzibar surprise"}, {}, False)
    await console.async_save_now()

    assert console.history.total() >= 2, "the chat itself is kept in its own file on the box, as before"
    text = await sent(hass, hass_client)
    shown = (await ws(hass, hass_ws_client, {"type": "console/metrics"}))["result"]
    made = json.loads(text)
    assert made["days"] and made["story"]["text"], "there is something to look through"
    assert sum(made["days"][metrics._today(console)]["turns"].values()) == 3  # noqa: SLF001
    places = {
        "the counts kept": json.dumps(console.data["metrics"]),
        "this month's totals": json.dumps(console.data["months"]) + json.dumps(console.summary()),
        "what is sent": text,
        "the story": made["story"]["text"],
        "what the household is shown": json.dumps({k: v for k, v in shown.items() if k not in ("words", "names")}),
        "Console's log": "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("custom_components.console")),
    }
    for where, kept in places.items():
        assert not [word for word in (*SECRETS, entry.entity_id, room.id, hass_admin_user.id) if word.lower() in kept.lower()], where
    VALID.validate(made)
    assert not re.search(r"\d\d:\d\d", text), "no time of day"


# --- what the household sees, the switch, and the wipe ------------------------------------------------------


async def test_the_household_is_shown_exactly_what_is_sent_byte_for_byte(hass, console, model, lights_off, hass_client, hass_ws_client):
    link(console)
    await ask(hass, "turn off the kitchen light")
    model.say("Two lights are on. [[status]]")
    await ask(hass, "which lights did we leave on downstairs and should I worry")
    shown = (await ws(hass, hass_ws_client, {"type": "console/metrics"}))["result"]
    answer = await (await hass_client()).get("/api/console/relay/metrics")
    assert await answer.read() == shown["body"].encode(), "the same bytes"
    assert shown["on"] is True and shown["held"] is False and shown["story"] == json.loads(shown["body"])["story"]["text"]
    assert shown["words"] == wording.METRICS_PAGE and shown["names"] == wording.METRIC_NAMES
    assert shown["body"] == json.dumps(json.loads(shown["body"]), sort_keys=True, separators=(",", ":")), "one fixed form"
    # The panel shows it, with its words from wording.py.
    page = (Path(metrics.__file__).parent / "www" / "console-panel.js").read_text()
    assert 'type: "console/metrics"' in page and "esc(m.body)" in page and "switch.console_usage_details" in page


async def test_with_the_switch_off_nothing_is_counted_and_nothing_is_sent(hass, console, model, lights_off, hass_client, hass_ws_client, hass_read_only_access_token):
    link(console)
    await ask(hass, "turn off the kitchen light")
    assert hass.states.get("switch.console_usage_details").state == "on", "on unless the household turns it off"
    refused = await ws(hass, hass_ws_client, {"type": "console/metrics/set", "on": False}, hass_read_only_access_token)
    assert refused["success"] is False and metrics.on(console) is True, "administrators only"

    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.console_usage_details"}, blocking=True)
    assert await sent(hass, hass_client) == '{"on":false,"v":1}'
    before = json.dumps(console.data["metrics"])
    await ask(hass, "turn off the kitchen light")
    model.say("Hello. [[other]]")
    await ask(hass, "tell me something nice about this house")
    metrics.tool(console, "sunrise", "act", {}, {}, False)
    metrics.seen(console, "chat_card")
    metrics.tap(console, "scene", "ok")
    metrics.event(console, "shown", 3)
    assert json.dumps(console.data["metrics"]) == before
    assert console.summary()["turns"] == 3, "the month's totals are counted as before"
    shown = (await ws(hass, hass_ws_client, {"type": "console/metrics"}))["result"]
    assert shown["on"] is False and shown["body"] == '{"on":false,"v":1}' and shown["story"] is None
    status = await (await (await hass_client()).get("/api/console/relay/status")).json()
    assert status["switches"]["metrics"] is False

    assert (await ws(hass, hass_ws_client, {"type": "console/metrics/set", "on": True}))["result"] == {"on": True}
    assert json.loads(await sent(hass, hass_client))["on"] is True


async def test_usage_details_are_for_the_relay_as_an_administrator_and_not_with_cloud_access_off(
    hass, console, hass_client, hass_client_no_auth, hass_read_only_access_token
):
    assert (await (await hass_client_no_auth()).get("/api/console/relay/metrics")).status == 401
    assert (await (await hass_client(hass_read_only_access_token)).get("/api/console/relay/metrics")).status == 403
    console.set_switch("cloud", False)
    assert (await (await hass_client()).get("/api/console/relay/metrics")).status == 423


async def test_the_data_wipe_erases_the_counts_and_never_turns_the_switch_back_on(hass, console, lights_off, hass_client, hass_ws_client):
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, "persistent_notification", {})
    link(console)
    await ask(hass, "turn off the kitchen light")
    metrics.seen(console, "chat_card")
    assert console.data["metrics"]["days"] and console.data["metrics"]["since"]
    console.set_switch(metrics.SWITCH, False)

    done = await ws(hass, hass_ws_client, {"type": "console/wipe", "level": "data", "confirm": wipe.WORDS_DATA})
    assert done["success"] is True
    assert console.data["metrics"] == {"since": None, "days": {}}
    assert metrics.on(console) is False, "erasing data never turns a switch back on"
    assert (await (await hass_client()).get("/api/console/relay/metrics")).status == 409, "and the relay is refused until someone reconnects"
    assert (await (await (await hass_client()).get("/api/console/relay/status")).json())["unlinked"] is True  # the relay deletes its copy on this


async def test_the_months_summary_is_unchanged_by_all_this(hass, console, lights_off):
    await ask(hass, "turn off the kitchen light")
    assert set(console.summary()) == {"period", "spend_usd", "turns", "ok", "failed", "by_route", "by_category", "by_agent"}
