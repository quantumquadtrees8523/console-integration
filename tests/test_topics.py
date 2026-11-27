"""What kind of thing each request was: one label from a fixed list, worked out from what was done.
The counts leave the box in batches that are sent unchanged until the relay says they were counted."""

from __future__ import annotations

import pytest

from custom_components.console import topics

from .test_agent import ask, link
from .test_relay_api import HANDOVER


@pytest.mark.parametrize(
    ("action", "data", "topic"),
    [
        ("light.turn_on", None, "lights.on_off"),
        ("light.turn_on", {"brightness_pct": 40}, "lights.adjust"),
        ("light.turn_off", None, "lights.on_off"),
        ("switch.toggle", None, "switches.on_off"),
        ("climate.set_temperature", {"temperature": 20}, "climate.adjust"),
        ("cover.open_cover", None, "covers.on_off"),
        ("cover.set_cover_position", {"position": 30}, "covers.adjust"),
        ("lock.unlock", None, "locks.on_off"),
        ("alarm_control_panel.alarm_arm_away", None, "security.on_off"),
        ("media_player.play_media", {"media_content_id": "x"}, "music.play"),
        ("media_player.volume_set", {"volume_level": 0.3}, "music.control"),
        ("scene.turn_on", None, "scenes.run"),
        ("automation.trigger", None, "automations.run"),
        ("automation.turn_off", None, "automations.change"),
        ("fan.set_percentage", {"percentage": 50}, "fans.adjust"),
        ("made_up.do_a_thing", None, "other.other"),
        (None, None, "other.other"),
    ],
)
def test_a_home_assistant_action_has_a_label(action, data, topic):
    assert topics.for_action(action, data) == topic


@pytest.mark.parametrize(
    ("intent", "kinds", "topic"),
    [
        ("HassTurnOn", ["light"], "lights.on_off"),
        ("HassTurnOff", "switch", "switches.on_off"),
        ("HassTurnOn", ["scene"], "scenes.run"),
        ("HassTurnOn", None, "other.on_off"),
        ("HassLightSet", ["light"], "lights.adjust"),
        ("HassClimateSetTemperature", None, "climate.adjust"),
        ("HassClimateGetTemperature", None, "climate.ask"),
        ("HassMediaPause", ["media_player"], "music.control"),
        ("HassMediaSearchAndPlay", None, "music.play"),
        ("HassSetVolume", None, "music.control"),
        ("HassStartTimer", None, "timers.create"),
        ("HassCancelTimer", None, "timers.control"),
        ("HassTimerStatus", None, "timers.ask"),
        ("HassGetWeather", None, "weather.ask"),
        ("HassGetCurrentTime", None, "house.ask"),
        ("HassGetState", ["binary_sensor"], "sensors.ask"),
        ("HassGetState", None, "house.ask"),
        ("HassShoppingListAddItem", None, "lists.change"),
        ("HassVacuumStart", None, "vacuum.on_off"),
        ("HassNevermind", None, "chat.other"),
        ("SomethingNew", None, "other.other"),
        (None, None, "other.other"),
    ],
)
def test_an_intent_has_a_label(intent, kinds, topic):
    assert topics.for_intent(intent, kinds) == topic


@pytest.mark.parametrize(
    ("tool", "args", "topic"),
    [
        ("sunrise__act", {"action": "light.turn_off", "entity_ids": ["light.desk"]}, "lights.on_off"),
        ("sunrise__routine", {"op": "save", "config": {}}, "automations.create"),
        ("sunrise__routine", {"op": "save", "id": "abc", "config": {}}, "automations.change"),
        ("sunrise__routine", {"op": "delete", "id": "abc"}, "automations.remove"),
        ("sunrise__routine", {"op": "list"}, "automations.ask"),
        ("sunrise__routine", {"op": "try", "id": "abc"}, "automations.run"),
        ("console__dashboard", {"op": "create", "title": "Office"}, "dashboards.create"),
        ("console__music", {"op": "play", "query": "anything at all"}, "music.play"),
        ("console__music", {"op": "search", "query": "anything at all"}, "music.ask"),
        ("sunrise__diagnose_device", {}, "devices.diagnose"),
        ("sunrise__fix_device", {"op": "reload_entry"}, "devices.fix"),
        ("sunrise__registry_edit", {"op": "rename", "value": "a private name"}, "devices.change"),
        ("sunrise__registry_edit", {"op": "remove_entity"}, "devices.remove"),
        ("sunrise__memory_write", {"text": "something private"}, "memory.change"),
        ("sunrise__house_map", {}, "house.ask"),
        ("sunrise__usage", {}, "plan.ask"),
        ("assist__intent__HassTurnOn", {"name": "Desk lamp", "domain": ["light"]}, "lights.on_off"),
        ("sunrise__get_skill", {"name": "routines"}, None),
        ("llm__GetDateTime", {}, None),
        ("something_else", {}, None),
    ],
)
def test_a_tool_call_has_a_label_or_says_nothing(tool, args, topic):
    assert topics.for_tool(tool, args) == topic


def test_a_request_gets_one_label_the_one_that_changed_the_most():
    looked_then_built = [("sunrise__house_map", {}), ("sunrise__routine", {"op": "save"}), ("sunrise__act", {"action": "light.turn_on"})]
    assert topics.for_turn(looked_then_built) == "automations.create"
    assert topics.for_turn([("sunrise__house_map", {}), ("sunrise__act", {"action": "light.turn_on"})]) == "lights.on_off"
    assert topics.for_turn([("sunrise__get_skill", {"name": "x"})], "status") == "chat.ask"
    assert topics.for_turn([]) == "chat.other"


def test_every_label_is_from_the_lists_whatever_goes_in():
    made = {topics.for_action(f"{d}.{s}", {"x": 1}) for d in ("light", "garage code 4411", "") for s in ("turn_on", "set_x", "say my name")}
    made |= {topics.for_tool("sunrise__act", {"action": "my secret.plan"}), topics.for_intent("Hass My Secret", ["my secret"])}
    for topic in made:
        area, _, action = topic.partition(".")
        assert area in topics.AREAS and action in topics.ACTIONS, topic


async def test_a_local_command_is_counted_by_what_it_did(hass, console, model, lights_off):
    link(console)
    await ask(hass, "turn off the kitchen light")
    assert console.topics_waiting() == {console.period: {"lights.on_off": 1}}


async def test_a_model_turn_is_counted_by_the_tool_it_used_not_by_its_words(hass, console, model, lights_off):
    link(console)
    model.call_tool("assist__intent__HassTurnOff", {"name": "Kitchen light"})
    model.say("The kitchen light is off. [[control]]")
    await ask(hass, "could you make the kitchen dark for the movie about the Hendersons")
    model.say("Two lights are on. [[status]]")
    await ask(hass, "which lights did we leave on downstairs and should I worry")
    waiting = console.topics_waiting()[console.period]
    assert waiting == {"lights.on_off": 1, "chat.ask": 1}
    assert "movie" not in str(console.data["topics"]) and "Henderson" not in str(console.data["topics"])


async def test_a_batch_goes_out_unchanged_until_the_relay_says_it_was_counted(hass, console, hass_client):
    client = await hass_client()
    assert "topics" not in await (await client.get("/api/console/relay/status")).json(), "nothing to send yet"

    console.count_turn("local", "control", True, topic="lights.on_off")
    console.count_turn("local", "control", True, topic="lights.on_off")
    first = (await (await client.get("/api/console/relay/status")).json())["topics"]
    assert first["counts"] == {console.period: {"lights.on_off": 2}} and len(first["batch"]) >= 8

    console.count_turn("flash", "customization", True, topic="automations.create")
    again = (await (await client.get("/api/console/relay/status")).json())["topics"]
    assert again == first, "the relay didn't answer: the same batch, with nothing added to it"
    assert console.topics_waiting() == {console.period: {"lights.on_off": 2, "automations.create": 1}}

    await client.post("/api/console/relay/config", json=HANDOVER | {"topics_applied": "some-other-batch"})
    assert (await (await client.get("/api/console/relay/status")).json())["topics"] == first

    await client.post("/api/console/relay/config", json=HANDOVER | {"topics_applied": first["batch"]})
    second = (await (await client.get("/api/console/relay/status")).json())["topics"]
    assert second["batch"] != first["batch"] and second["counts"] == {console.period: {"automations.create": 1}}

    await client.post("/api/console/relay/config", json=HANDOVER | {"topics_applied": second["batch"]})
    assert "topics" not in await (await client.get("/api/console/relay/status")).json()
    assert console.topics_waiting() == {}


async def test_the_monthly_summary_still_has_no_topics_in_it(hass, console):
    console.count_turn("local", "control", True, topic="lights.on_off")
    assert "lights.on_off" not in str(console.summary()), "topics are not part of this house's own totals"
    assert console.summary()["turns"] == 1


async def test_erasing_console_data_erases_the_counts_that_were_waiting(hass, console):
    console.count_turn("local", "control", True, topic="lights.on_off")
    console.topics_batch()
    console.count_turn("local", "control", True, topic="music.play")
    await console.async_erase()
    assert console.topics_waiting() == {} and console.topics_batch() is None


async def test_the_household_is_shown_the_counts_that_are_waiting(hass, console, hass_ws_client):
    console.count_turn("local", "control", True, topic="lights.on_off")
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "console/knows"})
    shown = (await client.receive_json())["result"]
    assert shown["topics"] == {console.period: {"lights.on_off": 1}}
