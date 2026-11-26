"""Asking the chat for a dashboard: Console's own `dashboard` tool."""

from __future__ import annotations

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
