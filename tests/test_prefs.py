"""Device settings (prefs.py): how a household wants each of its devices set (a speaker's volume, a light's
brightness, a thermostat's temperature, a blind's position, a select's option…), learned from chats and from
changes by hand, and used whenever nobody says.

Owner, 2026-11-28: "maybe the user is listening to music on some speaker and they think it's too loud. They
ask to drop the volume or else do so manually. The agent should be able to see that and remember that
setting for future agent actions on that device", and "this should be general. not just speakers and lights".
"""

from __future__ import annotations

from datetime import timedelta
import json

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, MockModule, async_fire_time_changed, mock_integration

from homeassistant.components.homeassistant.exposed_entities import async_expose_entity
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import Context, ServiceCall
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.console import features, music, prefs as P

from .conftest import ask, link


@pytest.fixture
def speaker(hass):
    """The kitchen speaker, as Music Assistant shows it and as its maker (Sonos) does: one speaker, two copies.
    Setting its volume really changes it, the way a speaker would."""
    mock_integration(hass, MockModule("music_assistant"))
    MockConfigEntry(domain="music_assistant", title="Music Assistant", state=ConfigEntryState.LOADED).add_to_hass(hass)
    registry = er.async_get(hass)
    for platform, object_id in (("music_assistant", "kitchen"), ("sonos", "kitchen_sonos")):
        made = registry.async_get_or_create("media_player", platform, object_id, suggested_object_id=object_id)
        hass.states.async_set(made.entity_id, "playing", {"friendly_name": "Kitchen", "volume_level": 0.6, "media_title": "Blue in Green"})
        async_expose_entity(hass, "conversation", made.entity_id, True)
    calls: list[ServiceCall] = []

    async def volume_set(call: ServiceCall) -> None:
        calls.append(call)
        ids = call.data["entity_id"] if isinstance(call.data["entity_id"], list) else [call.data["entity_id"]]
        for entity_id in ids:
            state = hass.states.get(entity_id)
            hass.states.async_set(entity_id, state.state, {**state.attributes, "volume_level": call.data["volume_level"]}, context=call.context)

    async def play(call: ServiceCall) -> None:
        calls.append(call)
        for entity_id in call.data.get("entity_id", []):
            state = hass.states.get(entity_id)
            hass.states.async_set(entity_id, "playing", {**state.attributes, "media_title": "So What"}, context=call.context)

    hass.services.async_register("media_player", "volume_set", volume_set)
    hass.services.async_register("music_assistant", "play_media", play)
    return calls


def by_hand(hass, entity_id: str, volume: float, context: Context | None = None) -> None:
    """Someone turns the speaker's own knob, or drags the slider in the app."""
    state = hass.states.get(entity_id)
    hass.states.async_set(entity_id, state.state, {**state.attributes, "volume_level": volume}, context=context or Context())


def settle(hass, freezer, seconds: float = P.SETTLE_S + 1) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass, dt_util.utcnow())


def levels(console, entity_id="media_player.kitchen", setting="volume_level") -> list[tuple]:
    row = console.prefs.state["devices"].get(entity_id, {}).get(setting) or {}
    return [(item["value"], item["how"]) for item in row.get("values", [])]


async def test_asking_to_turn_it_down_is_remembered_and_used_the_next_time(hass, console, model, speaker, hass_admin_user):
    link(console)
    model.call_tool("console__music", {"op": "control", "room": "kitchen", "action": "volume", "volume": 25})
    model.say("Done: the kitchen is at 25%. [[control]]")
    await ask(hass, "the music is too loud in the kitchen, turn it down", Context(user_id=hass_admin_user.id))
    await hass.async_block_till_done()
    assert levels(console) == [(0.25, "asked")]
    assert console.prefs.value("media_player.kitchen", "volume_level") == 0.25
    assert console.prefs.value("media_player.kitchen_sonos", "volume_level") == 0.25  # the maker's copy is the same speaker

    # The next turn, the agent is told; and music started without a volume plays at the learned one.
    model.call_tool("console__music", {"op": "play", "room": "kitchen", "what": "kind of blue"})
    model.say("Playing Kind of Blue in the kitchen. [[control]]")
    await ask(hass, "play some miles davis in the kitchen", Context(user_id=hass_admin_user.id))
    told = model.calls[-2]["messages"][0]["content"]
    assert "- Kitchen (media_player.kitchen): volume 25% [volume_level=0.25] (from 1 time; last asked for)" in told
    assert "What they ask for now always wins" in told
    volume_calls = [c for c in speaker if c.service == "volume_set"]
    assert volume_calls[-1].data["volume_level"] == 0.25
    result = json.loads(model.calls[-1]["messages"][-1]["content"])["data"]
    assert "learned" in result["volume_from"]
    assert levels(console) == [(0.25, "asked")]  # the agent using a level it learned doesn't count as asking for it again


async def test_a_level_the_agent_chose_itself_is_not_learned(hass, console, model, speaker, hass_admin_user):
    link(console)
    model.call_tool("console__music", {"op": "play", "room": "kitchen", "what": "kind of blue", "volume": 70})
    model.say("Playing. [[control]]")
    await ask(hass, "put on some jazz in the kitchen", Context(user_id=hass_admin_user.id))  # no level asked for
    await hass.async_block_till_done()
    assert levels(console) == []


async def test_a_change_by_hand_is_kept_once_the_person_stops_adjusting(hass, console, speaker, freezer):
    for volume in (0.5, 0.42, 0.35):  # pressing the speaker's own button three times
        by_hand(hass, "media_player.kitchen_sonos", volume)
        settle(hass, freezer, 3)
    assert levels(console) == []  # still adjusting
    settle(hass, freezer)
    assert levels(console) == [(0.35, "by hand")]  # one level, the one it was left at, on the speaker the music tool uses
    by_hand(hass, "media_player.kitchen", 0.2, Context(parent_id="automation-run"))  # a routine turned it down
    settle(hass, freezer)
    assert levels(console) == [(0.35, "by hand")]  # routines aren't people


class Clock:
    """The learner's own clock, moved by hand. The music tool really waits a moment after a change, and a
    frozen test clock would make that wait for ever, so this test moves only the learner's time."""

    def __init__(self, console, monkeypatch) -> None:
        from datetime import UTC, datetime

        self.now = datetime.now(UTC)
        monkeypatch.setattr(console.prefs, "_now", lambda: self.now)

    def tick(self, hass, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))


async def test_turning_it_down_by_hand_after_console_set_it_corrects_it(hass, console, model, speaker, hass_admin_user, monkeypatch):
    clock = Clock(console, monkeypatch)
    link(console)
    model.call_tool("console__music", {"op": "play", "room": "kitchen", "what": "kind of blue", "volume": 60})
    model.say("Playing at 60%. [[control]]")
    await ask(hass, "play kind of blue in the kitchen at 60", Context(user_id=hass_admin_user.id))
    assert levels(console) == [(0.6, "asked")]
    clock.tick(hass, 2 * 60)
    by_hand(hass, "media_player.kitchen", 0.3)  # too loud after all
    clock.tick(hass, P.SETTLE_S + 1)
    await hass.async_block_till_done()
    assert levels(console) == [(0.3, "corrected")]  # the correction replaces what it corrected
    assert console.prefs.value("media_player.kitchen", "volume_level") == 0.3

    # Asked again later, by chat, to bring it down: also a correction of what Console set.
    model.call_tool("console__music", {"op": "play", "room": "kitchen", "what": "so what"})
    model.say("Playing. [[control]]")
    await ask(hass, "play so what in the kitchen", Context(user_id=hass_admin_user.id))  # played at the learned 30%
    assert [c for c in speaker if c.service == "volume_set"][-1].data["volume_level"] == 0.3
    clock.tick(hass, 60)
    model.call_tool("console__music", {"op": "control", "room": "kitchen", "action": "volume", "volume": 20})
    model.say("Down to 20%. [[control]]")
    await ask(hass, "still too loud, lower it", Context(user_id=hass_admin_user.id))
    assert levels(console) == [(0.2, "corrected")]


async def test_the_learned_level_is_the_middle_of_the_last_few(hass, console, speaker, freezer):
    for volume in (0.3, 0.32, 0.9, 0.28, 0.31, 0.3):  # one loud song in the middle
        by_hand(hass, "media_player.kitchen", volume)
        settle(hass, freezer, P.CORRECT_S + P.SETTLE_S + 5)
    assert len(levels(console)) == P.KEEP and console.prefs.value("media_player.kitchen", "volume_level") == 0.31


async def test_a_lights_brightness_is_learned_too(hass, console, freezer):
    hass.states.async_set("light.desk", "on", {"friendly_name": "Desk lamp", "brightness": 255})
    async_expose_entity(hass, "conversation", "light.desk", True)
    hass.states.async_set("light.desk", "on", {"friendly_name": "Desk lamp", "brightness": 102}, context=Context())
    settle(hass, freezer)
    assert levels(console, "light.desk", "brightness") == [(102.0, "by hand")]
    hass.states.async_set("light.desk", "off", {"friendly_name": "Desk lamp"}, context=Context())  # off isn't a brightness
    settle(hass, freezer)
    assert "brightness 40%" in console.prefs.prompt()


async def test_switched_off_it_learns_nothing_and_uses_nothing(hass, console, model, speaker, hass_admin_user, freezer):
    link(console)
    by_hand(hass, "media_player.kitchen", 0.3)
    settle(hass, freezer)
    features.set_on(console, features.PREFS, False)
    assert console.prefs.prompt() == "" and console.prefs.value("media_player.kitchen", "volume_level") is None
    by_hand(hass, "media_player.kitchen", 0.1)
    settle(hass, freezer)
    assert levels(console) == [(0.3, "by hand")]  # kept, not added to
    await music.run(hass, {"op": "play", "room": "kitchen", "what": "kind of blue"})
    assert not [c for c in speaker if c.service == "volume_set"]  # not used
    features.set_on(console, features.PREFS, True)
    assert console.prefs.value("media_player.kitchen", "volume_level") == 0.3  # back when it's on again


async def test_it_is_listed_and_only_an_administrator_forgets_it(hass, console, speaker, freezer, hass_ws_client, hass_read_only_access_token):
    by_hand(hass, "media_player.kitchen", 0.3)
    settle(hass, freezer)
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "console/knows"})
    knows = (await client.receive_json())["result"]
    assert knows["prefs_on"] is True
    [row] = knows["prefs"]
    assert row["name"] == "Kitchen" and row["setting"] == "volume_level" and row["label"] == "volume" and row["shown"] == "30%"
    assert row["value"] == 0.3 and row["last_how"] == "by hand"
    reader = await hass_ws_client(hass, hass_read_only_access_token)
    await reader.send_json({"id": 1, "type": "console/prefs/forget", "entity_id": "media_player.kitchen", "setting": "volume_level"})
    assert (await reader.receive_json())["success"] is False
    await client.send_json({"id": 2, "type": "console/prefs/forget", "entity_id": "media_player.kitchen", "setting": "volume_level"})
    done = (await client.receive_json())["result"]
    assert done["ok"] is True and "Kitchen" in done["message"] and console.prefs.listing() == []


async def test_nothing_a_person_said_is_kept_and_nothing_goes_to_the_relay(hass, console, model, speaker, hass_admin_user):
    link(console)
    model.call_tool("console__music", {"op": "control", "room": "kitchen", "action": "volume", "volume": 25})
    model.say("Done. [[control]]")
    await ask(hass, "the music is too loud for the baby, turn it down", Context(user_id=hass_admin_user.id))
    await console.async_save_now()
    assert console.prefs.listing()
    assert "baby" not in json.dumps(console.data)
    assert "prefs" not in json.dumps(console.summary()) and "kitchen" not in json.dumps(console.summary()).lower()


async def test_it_is_general_a_thermostat_a_blind_and_a_select_are_learned_too(hass, console, freezer, hass_admin_user):
    person = Context(user_id=hass_admin_user.id)
    hass.states.async_set("climate.living_room", "heat", {"friendly_name": "Living room", "temperature": 19, "preset_mode": "home"})
    hass.states.async_set("cover.bedroom_blind", "open", {"friendly_name": "Bedroom blind", "current_position": 100})
    hass.states.async_set("select.tv_picture", "standard", {"friendly_name": "TV picture", "options": ["standard", "movie", "vivid"]})
    for entity_id in ("climate.living_room", "cover.bedroom_blind", "select.tv_picture"):
        async_expose_entity(hass, "conversation", entity_id, True)

    hass.states.async_set("climate.living_room", "heat", {"friendly_name": "Living room", "temperature": 21.5, "preset_mode": "home"}, context=person)
    hass.states.async_set("cover.bedroom_blind", "open", {"friendly_name": "Bedroom blind", "current_position": 40}, context=Context())
    hass.states.async_set("select.tv_picture", "movie", {"friendly_name": "TV picture", "options": ["standard", "movie", "vivid"]}, context=person)
    settle(hass, freezer)
    assert levels(console, "climate.living_room", "temperature") == [(21.5, "by hand")]
    assert levels(console, "cover.bedroom_blind", "current_position") == [(40.0, "by hand")]
    assert levels(console, "select.tv_picture", "state") == [("movie", "by hand")]

    # A thermostat changes its own target on a schedule: with nobody signed in behind it, that isn't a choice.
    hass.states.async_set("climate.living_room", "heat", {"friendly_name": "Living room", "temperature": 17, "preset_mode": "home"}, context=Context())
    settle(hass, freezer)
    assert levels(console, "climate.living_room", "temperature") == [(21.5, "by hand")]

    told = console.prefs.prompt()
    assert "- Living room (climate.living_room): target temperature 21.5 °C [temperature=21.5]" in told
    assert "- Bedroom blind (cover.bedroom_blind): position 40% [current_position=40]" in told
    assert "- TV picture (select.tv_picture): option movie [state='movie']" in told


async def test_a_choice_is_the_one_made_most_often(hass, console, freezer):
    hass.states.async_set("select.tv_picture", "standard", {"friendly_name": "TV picture"})
    for option in ("movie", "vivid", "movie", "standard", "vivid"):
        hass.states.async_set("select.tv_picture", option, {"friendly_name": "TV picture"}, context=Context())
        settle(hass, freezer, P.CORRECT_S + P.SETTLE_S + 5)
    assert console.prefs.value("select.tv_picture", "state") == "vivid"  # movie and vivid twice each: the latest wins


def test_the_persons_own_words_say_whether_they_asked_for_it():
    volume, mode, colour = P.setting("media_player.x", "volume_level"), P.setting("climate.x", "state"), P.setting("light.x", "rgb_color")
    assert P.person_asked("the music is too loud, turn it down", volume, 0.25)
    assert P.person_asked("kitchen at 20", volume, 0.2) and P.person_asked("a bit louder please", volume, 0.5)
    assert not P.person_asked("put on some jazz in the kitchen", volume, 0.7)  # the agent chose that one
    assert P.person_asked("switch the heating to heat", mode, "heat") and not P.person_asked("warm the house up", mode, "heat_cool")
    assert P.person_asked("make the desk lamp amber", colour, [255, 191, 0]) and not P.person_asked("turn on the desk lamp", colour, [255, 191, 0])


def test_a_call_counts_as_asked_only_when_it_set_that_setting_on_purpose():
    lamp, speaker, heat = {"light.desk"}, {"media_player.kitchen"}, {"climate.living_room"}
    assert P.asked("act", {"action": "light.turn_on", "entity_ids": ["light.desk"], "data": {"brightness_pct": 40}}, lamp) == {("light.desk", "brightness")}
    assert P.asked("act", {"action": "light.turn_on", "entity_ids": ["light.desk"]}, lamp) == set()  # just on: nothing chosen
    assert P.asked("act", {"action": "light.turn_on", "data": {"color_name": "amber"}}, lamp) == {("light.desk", "rgb_color")}
    assert P.asked("act", {"action": "media_player.volume_down"}, speaker) == {("media_player.kitchen", "volume_level")}  # turned down
    assert P.asked("act", {"action": "climate.set_temperature", "data": {"temperature": 21}}, heat) == {("climate.living_room", "temperature")}
    assert P.asked("act", {"action": "climate.set_hvac_mode", "data": {"hvac_mode": "cool"}}, heat) == {("climate.living_room", "state")}
    assert P.asked("act", {"action": "light.turn_on", "data": {"brightness_pct": 40}}, speaker) == set()  # another kind of device
    assert P.asked("music", {"op": "play", "room": "kitchen", "what": "jazz"}, speaker) == set()
    assert P.asked("music", {"op": "control", "action": "volume", "volume": 20}, speaker) == {("media_player.kitchen", "volume_level")}
    assert P.asked("HassClimateSetTemperature", {"temperature": 21}, heat) == {("climate.living_room", "temperature")}
    assert P.asked("act", {"action": "lock.unlock"}, {"lock.front_door"}) == set()  # locks are never a setting
