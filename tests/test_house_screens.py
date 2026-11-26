"""The house's own screens: the Home dashboard, learned sentences, and what the house knows about you."""

from __future__ import annotations

import time

from pytest_homeassistant_custom_component.common import async_mock_service

from homeassistant.components import frontend
from homeassistant.components.homeassistant.exposed_entities import async_expose_entity
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.helpers import llm

from custom_components.console import dashboard, wording
from custom_components.console.learned import LEARN_AFTER, normalize

from .conftest import ask, link


async def test_the_home_dashboard_is_built_from_the_house_and_made_the_default(hass, console):
    hass.states.async_set("light.desk", "on", {"friendly_name": "Desk lamp"})
    hass.states.async_set("light.hidden", "on", {"friendly_name": "Not exposed"})
    hass.states.async_set("media_player.kitchen", "idle", {"friendly_name": "Kitchen speaker"})
    async_expose_entity(hass, "conversation", "light.desk", True)
    async_expose_entity(hass, "conversation", "light.hidden", False)
    async_expose_entity(hass, "conversation", "media_player.kitchen", True)
    done = await dashboard.ensure(hass, console)
    assert done["ok"] and done["did"] in ("created", "rebuilt") and done["url"] == "/console-home"
    config = await hass.data[LOVELACE_DATA].dashboards["console-home"].async_load(False)
    sections = config["views"][0]["sections"]
    assert sections[0]["cards"][1]["type"] == "custom:console-chat-card"
    assert [s["cards"][0]["heading"] for s in sections] == ["Console", "Lights", "Music and speakers"]
    tiles = [c["entity"] for s in sections for c in s["cards"] if c["type"] == "tile"]
    assert "light.desk" in tiles and "light.kitchen" in tiles and "light.hidden" not in tiles
    system = await frontend.async_system_store(hass)
    assert system.data["core"]["default_panel"] == "console-home"
    assert dashboard.build(hass) == dashboard.build(hass)  # the same house gives the same dashboard


async def test_a_hand_edited_dashboard_is_left_alone_until_asked(hass, console):
    await dashboard.ensure(hass, console)
    board = hass.data[LOVELACE_DATA].dashboards["console-home"]
    await board.async_save({"views": [{"title": "Mine", "cards": []}]})
    hass.states.async_set("light.new", "on", {"friendly_name": "New lamp"})
    async_expose_entity(hass, "conversation", "light.new", True)
    assert (await dashboard.ensure(hass, console))["did"].startswith("left alone")
    assert (await board.async_load(False))["views"][0]["title"] == "Mine"
    assert (await dashboard.ensure(hass, console, force=True))["did"] == "rebuilt"
    assert (await board.async_load(False))["views"][0]["title"] == "Home"


async def test_a_new_device_appears_on_an_untouched_dashboard(hass, console):
    await dashboard.ensure(hass, console)
    hass.states.async_set("light.new", "on", {"friendly_name": "New lamp"})
    async_expose_entity(hass, "conversation", "light.new", True)
    assert (await dashboard.ensure(hass, console))["did"] == "rebuilt"


class _Act(llm.Tool):
    """Sunrise's act, as far as the agent can tell: does the action and says CHECKED."""

    name = "act"
    description = "Do something and check it"

    async def async_call(self, hass, tool_input, llm_context):
        args = tool_input.tool_args
        domain, _, service = args["action"].partition(".")
        await hass.services.async_call(domain, service, {"entity_id": args["entity_ids"], **args.get("data", {})}, blocking=True)
        rows = [{"id": e, "name": "Kitchen light", "result": "CHECKED", "now": "off"} for e in args["entity_ids"]]
        return llm.ToolResult(data={"results": rows}, error=False) if hasattr(llm, "ToolResult") else {"results": rows}


class _Sunrise(llm.API):
    def __init__(self, hass):
        super().__init__(hass=hass, id="sunrise", name="Sunrise")

    async def async_get_api_instance(self, llm_context):
        return llm.APIInstance(api=self, api_prompt="Sunrise's rules.", llm_context=llm_context, tools=[_Act()])


async def test_a_sentence_said_three_times_is_learned_and_then_runs_at_home(hass, console, model):
    link(console)
    llm.async_register_api(hass, _Sunrise(hass))
    off = async_mock_service(hass, "light", "turn_off")
    said = "Make the kitchen go dark, please!"
    for time_said in range(1, LEARN_AFTER + 1):
        model.call_tool("act", {"action": "light.turn_off", "entity_ids": ["light.kitchen"]}, f"call_{time_said}")
        reply = await ask(hass, said)
        assert reply.startswith("Done. Kitchen light is off.")
        assert (wording.LEARNED in reply) == (time_said == LEARN_AFTER)
    assert len(model.calls) == LEARN_AFTER and len(off) == LEARN_AFTER
    assert "light.kitchen | Kitchen light" in model.calls[0]["messages"][0]["content"]  # the model had the ids
    learned = console.data["learned"]
    assert [item["sentence"] for item in learned] == [normalize(said)] == ["make the kitchen go dark please"]
    assert console.data["phrases"] == {}

    reply = await ask(hass, said)  # the fourth time: no model call
    assert len(model.calls) == LEARN_AFTER and len(off) == LEARN_AFTER + 1
    assert reply == "Done. Kitchen light."
    assert console.summary()["by_route"]["local"] == 1 and learned[0]["uses"] == 1

    assert console.learned.forget(learned[0]["id"]) is True
    model.call_tool("act", {"action": "light.turn_off", "entity_ids": ["light.kitchen"]}, "call_9")
    await ask(hass, said)
    assert len(model.calls) == LEARN_AFTER + 1  # forgotten: back to the cloud agent


async def test_only_a_hash_is_kept_until_a_sentence_is_learned(hass, console, model):
    link(console)
    llm.async_register_api(hass, _Sunrise(hass))
    async_mock_service(hass, "light", "turn_off")
    model.call_tool("act", {"action": "light.turn_off", "entity_ids": ["light.kitchen"]})
    await ask(hass, "Make the kitchen go dark, please!")
    import json

    kept = json.dumps(console.data)
    assert "go dark" not in kept and len(console.data["phrases"]) == 1


async def test_locks_are_never_learned(hass, console):
    class Call:
        tool_name = "act"
        tool_args = {"action": "lock.unlock", "entity_ids": ["lock.front_door"]}

    for _ in range(LEARN_AFTER + 1):
        assert console.learned.observe("unlock the front door", [Call()], [{"name": "Front door"}]) is None
    assert console.data["learned"] == [] and console.data["phrases"] == {}


async def test_what_the_house_knows_lists_presence_learned_and_the_summary(hass, console, hass_ws_client):
    hass.states.async_set("person.surya", "home", {"friendly_name": "Surya"})
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "console/knows"})
    result = (await ws.receive_json())["result"]
    assert result["presence"][0]["name"] == "Surya" and result["presence"][0]["state"] == "home"
    assert result["sunrise"] is False and result["memory"] == [] and result["learned"] == []
    assert result["usage"]["turns"] == 0 and result["assist_runs"] == 0


async def test_changing_what_the_house_knows_needs_an_administrator(hass, console, hass_ws_client, hass_read_only_access_token):
    ws = await hass_ws_client(hass, hass_read_only_access_token)
    for n, command in enumerate(
        (
            {"type": "console/learned/forget", "sentence_id": "x"},
            {"type": "console/memory/delete", "name": "house.md"},
            {"type": "console/assist/clear"},
            {"type": "console/dashboard/rebuild"},
        ),
        start=1,
    ):
        await ws.send_json({"id": n, **command})
        answer = await ws.receive_json()
        assert answer["success"] is False and answer["error"]["code"] == "unauthorized"


async def test_another_agents_tool_calls_are_counted_as_its_turns(hass, console):
    """Claude, through the MCP server, uses Sunrise's tools: Console counts bursts of them as turns."""
    now = time.time()
    calls = [
        {"ts": now + 1, "tool": "house_map", "args": {}, "error": False},
        {"ts": now + 5, "tool": "act", "args": {"action": "light.turn_off"}, "error": False},
        {"ts": now + 400, "tool": "diagnose_device", "args": {}, "error": True},
    ]
    console.others._calls = lambda: calls
    console.others.mark_own(now + 4.5, now + 5.5)  # the act was Console's own turn
    assert console.others.scan(now + 600) == 2
    month = console.summary()
    assert month["by_agent"] == {"other_agents": 2} and month["by_route"]["other_agent"] == 2
    assert month["by_category"]["status"] == 1 and month["by_category"]["troubleshooting"] == 1
    assert month["ok"] == 1 and month["failed"] == 1
    assert console.others.scan(now + 700) == 0
