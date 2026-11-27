"""Asking the chat for a dashboard: Console's own `dashboard` tool."""

from __future__ import annotations

import json

import pytest

from homeassistant.components.homeassistant.exposed_entities import async_expose_entity
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.core import Context
from homeassistant.helpers import area_registry as ar, entity_registry as er

from .conftest import ask, link


def kids_room(hass):
    area = ar.async_get(hass).async_create("Kids' room")
    registry = er.async_get(hass)
    for object_id, name in (("kids_lamp", "Kids lamp"), ("kids_night", "Night light")):
        entry = registry.async_get_or_create("light", "test", object_id, suggested_object_id=object_id)
        registry.async_update_entity(entry.entity_id, area_id=area.id)
        hass.states.async_set(entry.entity_id, "on", {"friendly_name": name})
        async_expose_entity(hass, "conversation", entry.entity_id, True)
    hidden = registry.async_get_or_create("light", "test", "kids_closet", suggested_object_id="kids_closet")
    registry.async_update_entity(hidden.entity_id, area_id=area.id)
    hass.states.async_set(hidden.entity_id, "off", {"friendly_name": "Closet"})
    async_expose_entity(hass, "conversation", hidden.entity_id, False)


async def test_the_chat_can_make_a_dashboard_for_a_room_and_remove_it(hass, console, model, hass_admin_user):
    link(console)
    kids_room(hass)
    context = Context(user_id=hass_admin_user.id)
    names = None

    model.call_tool("console__dashboard", {"op": "create", "title": "Kids' room", "rooms": ["Kids' room"]})
    model.say("I made a dashboard called Kids' room. It's in the sidebar. [[customization]]")
    reply = await ask(hass, "add a dashboard for the kids' room", context)
    assert reply == "I made a dashboard called Kids' room. It's in the sidebar."
    names = [tool["function"]["name"] for tool in model.calls[0]["tools"]]
    assert "dashboard" in [n.rsplit("__", 1)[-1] for n in names]
    board = hass.data[LOVELACE_DATA].dashboards["console-kids-room"]
    config = await board.async_load(False)
    tiles = [c["entity"] for s in config["views"][0]["sections"] for c in s["cards"] if c["type"] == "tile"]
    assert tiles == ["light.kids_lamp", "light.kids_night"]  # the unexposed closet light isn't shown
    assert config["views"][0]["title"] == "Kids' room"
    assert console.summary()["by_category"]["customization"] == 1
    tool_result = model.calls[1]["messages"][-1]["content"]
    assert '"url":"/console-kids-room"' in tool_result.replace(" ", "")

    model.call_tool("console__dashboard", {"op": "remove", "title": "Kids' room"})
    model.say("Removed. [[customization]]")
    await ask(hass, "remove the kids' room dashboard", context)
    assert "console-kids-room" not in hass.data[LOVELACE_DATA].dashboards
    assert console.data["made"] == {}


async def test_a_dashboard_is_refused_in_words_the_model_can_pass_on(hass, console, model, hass_admin_user):
    link(console)
    context = Context(user_id=hass_admin_user.id)
    model.call_tool("console__dashboard", {"op": "create", "title": "Garage", "rooms": ["Garage"]})
    model.say("There's no room called Garage here. [[customization]]")
    await ask(hass, "add a dashboard for the garage", context)
    assert "There's no room called garage" in model.calls[1]["messages"][-1]["content"]
    assert "console-garage" not in hass.data[LOVELACE_DATA].dashboards


async def test_only_an_administrators_agent_makes_dashboards(hass, console, model):
    link(console)
    kids_room(hass)
    model.call_tool("console__dashboard", {"op": "create", "title": "Kids' room", "rooms": ["Kids' room"]})
    model.say("I can't change dashboards for you. [[customization]]")
    await ask(hass, "add a dashboard for the kids' room")  # no signed-in person: a voice satellite
    assert "administrator" in model.calls[1]["messages"][-1]["content"]
    assert "console-kids-room" not in hass.data[LOVELACE_DATA].dashboards


async def test_the_tool_never_removes_a_dashboard_it_did_not_make(hass, console):
    from custom_components.console import dashboard

    await dashboard.ensure(hass, console)
    try:
        await dashboard.unmake(hass, console, "Home")
        raise AssertionError("it removed the Home dashboard")
    except dashboard.Refused as error:
        assert "didn't make a dashboard called Home" in str(error)
    assert "console-home" in hass.data[LOVELACE_DATA].dashboards


def family(hass):
    hass.states.async_set("person.sam", "home", {"friendly_name": "Sam", "latitude": 40.7, "longitude": -74.0})
    hass.states.async_set("device_tracker.sams_phone", "home", {"friendly_name": "Sam's phone", "latitude": 40.7, "longitude": -74.0})
    hass.states.async_set("device_tracker.old_tablet", "unknown", {"friendly_name": "Old tablet"})
    hass.states.async_set("sensor.living_temp", "21.5", {"friendly_name": "Living room temperature", "unit_of_measurement": "°C"})


WHERE = {
    "views": [
        {
            "type": "sections",
            "title": "Where everyone is",
            "sections": [
                {
                    "type": "grid",
                    "cards": [
                        {"type": "map", "entities": ["person.sam", {"entity": "device_tracker.sams_phone"}], "hours_to_show": 24},
                        {"type": "history-graph", "entities": ["sensor.living_temp"], "hours_to_show": 48},
                        {
                            "type": "conditional",
                            "conditions": [{"condition": "state", "entity": "person.sam", "state_not": "home"}],
                            "card": {"type": "markdown", "content": "Sam is out."},
                        },
                    ],
                }
            ],
        }
    ]
}


async def test_the_chat_writes_a_map_dashboard_itself_and_can_undo_it(hass, console, model, hass_admin_user):
    link(console)
    family(hass)
    context = Context(user_id=hass_admin_user.id)

    model.call_tool("console__dashboard", {"op": "save", "title": "Where everyone is", "config": WHERE})
    model.say("Done: a map of where everyone is, in the sidebar. [[customization]]")
    await ask(hass, "make me a dashboard with a map of where everyone is", context)
    board = hass.data[LOVELACE_DATA].dashboards["console-where-everyone-is"]
    assert await board.async_load(False) == WHERE
    result = json.loads(model.calls[1]["messages"][-1]["content"])["data"]
    assert result["created"] is True and result["cards"] == 4 and result["warnings"] == []

    model.call_tool("console__dashboard", {"op": "undo", "change_id": result["change_id"]})
    model.say("Taken away again. [[customization]]")
    await ask(hass, "undo that", context)
    assert "console-where-everyone-is" not in hass.data[LOVELACE_DATA].dashboards
    assert "console-where-everyone-is" not in console.data["made"]


async def test_an_edit_to_the_home_dashboard_sticks_and_undo_puts_it_back(hass, console):
    from custom_components.console import dashboard

    await dashboard.ensure(hass, console)
    got = await dashboard.get(hass, console, "/console-home", "")
    original = got["config"]
    edited = json.loads(json.dumps(original))
    edited["views"][0]["sections"].append({"type": "grid", "cards": [{"type": "markdown", "content": "Hello"}]})

    saved = await dashboard.save(hass, console, "/console-home", "", edited)
    assert saved["created"] is False
    board = hass.data[LOVELACE_DATA].dashboards["console-home"]
    assert await board.async_load(False) == edited
    assert (await dashboard.ensure(hass, console))["did"] == "left alone: it has been edited by hand"

    await dashboard.undo(hass, console, saved["change_id"])
    assert await board.async_load(False) == original
    with pytest.raises(dashboard.Refused, match="no dashboard change"):
        await dashboard.undo(hass, console, saved["change_id"])


async def test_a_config_with_problems_is_refused_and_nothing_is_saved(hass, console):
    from custom_components.console import dashboard

    family(hass)
    bad = {"views": [{"cards": [{"type": "map", "entities": ["person.nobody", "device_tracker.old_tablet"]}, {"type": "custom:fancy-card"}]}]}
    report = dashboard.check(hass, bad)
    assert report["ok"] is False
    assert any("person.nobody" in p for p in report["problems"])
    assert any("custom:fancy-card isn't installed" in p for p in report["problems"])
    assert any("old_tablet has no location" in w for w in report["warnings"])
    with pytest.raises(dashboard.Refused, match="Nothing was saved"):
        await dashboard.save(hass, console, "", "Broken", bad)
    assert "console-broken" not in hass.data[LOVELACE_DATA].dashboards
    assert dashboard.check(hass, {"views": []})["ok"] is False


async def test_an_installed_custom_card_passes_the_check(hass, console):
    from custom_components.console import dashboard

    await dashboard.ensure_resource(hass, "/hacsfiles/mushroom/mushroom.js?v=4")
    config = {"views": [{"cards": [{"type": "custom:mushroom-light-card", "entity": "light.kitchen"}]}]}
    assert dashboard.check(hass, config)["ok"] is True


async def test_only_an_administrators_agent_reads_a_dashboards_config(hass, console, model):
    link(console)
    model.call_tool("console__dashboard", {"op": "get", "url": "/console-home"})
    model.say("I can't. [[customization]]")
    await ask(hass, "show me the home dashboard's config")
    assert "administrator" in model.calls[1]["messages"][-1]["content"]
