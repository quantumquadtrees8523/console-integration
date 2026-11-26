"""Music by chat, through Music Assistant: one speaker per room, search, play by name, the queue."""

from __future__ import annotations

import json

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, MockModule, async_mock_service, mock_integration

from homeassistant.components.homeassistant.exposed_entities import async_expose_entity
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import ServiceCall, SupportsResponse
from homeassistant.helpers import entity_registry as er

from custom_components.console import conversation as agent, music

from .conftest import ask, link


@pytest.fixture
def speakers(hass):
    """A kitchen speaker that two integrations both show, as on a real house: Music Assistant's and Sonos's."""
    mock_integration(hass, MockModule("music_assistant"))  # a stand-in: the real one needs Music Assistant's client
    entry = MockConfigEntry(domain="music_assistant", title="Music Assistant", state=ConfigEntryState.LOADED)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    for platform, object_id, name in (
        ("music_assistant", "kitchen", "Kitchen"),
        ("music_assistant", "living_room", "Living Room"),
        ("sonos", "kitchen_kitchen", "Kitchen"),
        ("spotify", "spotify", "Spotify"),
    ):
        made = registry.async_get_or_create("media_player", platform, object_id, suggested_object_id=object_id)
        hass.states.async_set(made.entity_id, "idle", {"friendly_name": name, "volume_level": 0.3})
        async_expose_entity(hass, "conversation", made.entity_id, True)

    asked: list[ServiceCall] = []

    async def search(call: ServiceCall) -> dict:
        asked.append(call)
        return {"tracks": [{"name": "redrum", "uri": "spotify://track/1", "artists": [{"name": "21 Savage"}], "album": {"name": "american dream"}}],
                "albums": [], "playlists": [{"name": "This Is 21 Savage", "uri": "spotify://playlist/2"}]}  # fmt: skip

    async def library(call: ServiceCall) -> dict:
        asked.append(call)
        return {"items": [{"name": "Protect This House", "uri": "library://playlist/7"}, {"name": "Sunday", "uri": "library://playlist/8"}]}

    async def play(call: ServiceCall) -> None:
        asked.append(call)
        for entity_id in call.data.get("entity_id", []):
            hass.states.async_set(entity_id, "playing", {"friendly_name": "Kitchen", "media_title": "redrum", "media_artist": "21 Savage", "volume_level": 0.6})

    hass.services.async_register("music_assistant", "search", search, supports_response=SupportsResponse.ONLY)
    hass.services.async_register("music_assistant", "get_library", library, supports_response=SupportsResponse.ONLY)
    hass.services.async_register("music_assistant", "play_media", play)
    return entry, asked


async def test_a_room_has_one_speaker_and_it_is_music_assistants(hass, console, speakers):
    assert [(p["name"], p["id"]) for p in music.players(hass)] == [("Kitchen", "media_player.kitchen"), ("Living Room", "media_player.living_room")]
    told = agent.devices_block(hass)
    assert "media_player." not in told  # no twin from Sonos, no playback-only Spotify entity
    assert "Speakers, through the music tool only: Kitchen (idle), Living Room (idle)." in told


async def test_search_gives_names_and_what_to_play_them_by(hass, console, speakers):
    entry, asked = speakers
    found = await music.run(hass, {"op": "search", "query": "redrum", "artist": "21 Savage"})
    assert found["found"]["tracks"] == [{"name": "redrum", "uri": "spotify://track/1", "artists": "21 Savage", "album": "american dream"}]
    assert found["found"]["playlists"][0]["name"] == "This Is 21 Savage" and "albums" not in found["found"]
    assert asked[0].data == {"config_entry_id": entry.entry_id, "name": "redrum", "artist": "21 Savage"}


async def test_the_households_own_playlists_can_be_read(hass, console, speakers):
    got = await music.run(hass, {"op": "library", "kind": "playlist"})
    assert [p["name"] for p in got["library"]["items"]] == ["Protect This House", "Sunday"]


async def test_play_sets_the_volume_plays_on_the_rooms_speaker_and_reads_it_back(hass, console, speakers):
    _, asked = speakers
    volume = async_mock_service(hass, "media_player", "volume_set")
    now = await music.run(hass, {"op": "play", "what": "redrum", "artist": "21 Savage", "room": "kitchen speaker", "volume": 60})
    assert volume[0].data == {"entity_id": "media_player.kitchen", "volume_level": 0.6}
    assert asked[-1].data["media_id"] == "redrum" and asked[-1].data["artist"] == "21 Savage"
    assert asked[-1].data["entity_id"] == ["media_player.kitchen"]
    assert now["result"] == "CHECKED" and now["title"] == "redrum" and now["artist"] == "21 Savage" and now["volume"] == 60


async def test_controls_go_to_the_same_speaker(hass, console, speakers):
    paused = async_mock_service(hass, "media_player", "media_pause")
    skipped = async_mock_service(hass, "media_player", "media_next_track")
    await music.run(hass, {"op": "control", "room": "Kitchen", "action": "pause"})
    await music.run(hass, {"op": "control", "room": "Kitchen", "action": "next"})
    assert paused[0].data["entity_id"] == "media_player.kitchen" and skipped[0].data["entity_id"] == "media_player.kitchen"


async def test_what_cannot_be_done_is_said_in_words(hass, console, speakers):
    with pytest.raises(music.Refused, match="The speakers are: Kitchen, Living Room"):
        await music.run(hass, {"op": "play", "what": "jazz", "room": "garage"})
    with pytest.raises(music.Refused, match="Which speaker"):
        await music.run(hass, {"op": "queue"})


async def test_without_music_assistant_the_tool_says_so(hass, console):
    with pytest.raises(music.Refused, match="Music Assistant isn't set up"):
        await music.run(hass, {"op": "search", "query": "jazz"})
    assert await music.run(hass, {"op": "speakers"}) == {"speakers": []}


async def test_the_chat_plays_a_song_by_name_in_one_tool_call(hass, console, model, speakers):
    link(console)
    async_mock_service(hass, "media_player", "volume_set")
    model.call_tool("console__music", {"op": "play", "what": "redrum", "artist": "21 Savage", "room": "kitchen", "volume": 60})
    model.say("Playing redrum by 21 Savage in the Kitchen at 60%. [[control]]")
    reply = await ask(hass, "play redrum by 21 savage on the kitchen speaker at 60 percent")
    assert reply == "Playing redrum by 21 Savage in the Kitchen at 60%."
    offered = {tool["function"]["name"]: tool["function"] for tool in model.calls[0]["tools"]}
    assert "console__music" in offered and "console__about" in offered and "console_handoff" in offered
    assert "use the music tool" in model.calls[0]["messages"][0]["content"]
    result = json.loads(model.calls[1]["messages"][-1]["content"])["data"]
    assert result["result"] == "CHECKED" and result["title"] == "redrum"
    assert console.summary()["by_category"]["control"] == 1


async def test_about_gives_console_its_own_facts(hass, console):
    from custom_components.console import about

    link(console, cap=1.0)
    console.add_spend(0.12)
    facts = await about.facts(hass)
    assert facts["plan"]["credits_a_month"] == 100 and facts["plan"]["credits_used"] == 12
    assert facts["off_switches"]["Cloud access"]["on"] is True and facts["versions"]["console"]
    assert any("music" in line for line in facts["this_chat_can"]) and "console_handoff" in facts["when_it_cannot"]
    assert "$" not in json.dumps(facts["plan"]["credits_a_month"])


async def test_when_music_assistant_cannot_stream_it_the_speakers_own_spotify_link_plays_it(hass, console, speakers):
    """Music Assistant can search Spotify but its engine can't always play it. The same speaker through
    its maker's integration, with Home Assistant's own Spotify link, can."""
    from homeassistant.exceptions import HomeAssistantError

    entry, asked = speakers
    mock_integration(hass, MockModule("spotify"))
    spotify = MockConfigEntry(domain="spotify", title="Spotify", state=ConfigEntryState.LOADED, entry_id="01M5JA6N4MZRBJBV6QBSD3SG67")
    spotify.add_to_hass(hass)

    async def cannot_stream(call: ServiceCall) -> None:
        raise HomeAssistantError("The requested media item could not be found.")

    hass.services.async_register("music_assistant", "play_media", cannot_stream)
    played = []

    async def sonos_plays(call: ServiceCall) -> None:
        played.append(call.data)
        hass.states.async_set("media_player.kitchen_kitchen", "playing", {"friendly_name": "Kitchen", "media_title": "redrum", "media_artist": "21 Savage", "volume_level": 0.15})

    hass.services.async_register("media_player", "play_media", sonos_plays)
    async_mock_service(hass, "media_player", "volume_set")
    now = await music.run(hass, {"op": "play", "what": "redrum", "artist": "21 Savage", "room": "kitchen", "volume": 15})
    assert played[0]["entity_id"] == "media_player.kitchen_kitchen"
    assert played[0]["media_content_id"] == "spotify://01m5ja6n4mzrbjbv6qbsd3sg67/spotify:track:1"
    assert played[0]["media_content_type"] == "spotify://track"
    assert now["result"] == "CHECKED" and now["title"] == "redrum" and "own Spotify link" in now["note"]

    # Pause and skip now go to the copy of the speaker that has the music.
    paused = async_mock_service(hass, "media_player", "media_pause")
    await music.run(hass, {"op": "control", "room": "Kitchen", "action": "pause"})
    assert paused[0].data["entity_id"] == "media_player.kitchen_kitchen"
    assert [p["state"] for p in music.players(hass) if p["name"] == "Kitchen"] == ["playing"]


async def test_with_no_other_link_a_stream_failure_is_said_plainly(hass, console, speakers):
    from homeassistant.exceptions import HomeAssistantError

    async def cannot_stream(call: ServiceCall) -> None:
        raise HomeAssistantError("The requested media item could not be found.")

    hass.services.async_register("music_assistant", "play_media", cannot_stream)
    with pytest.raises(music.Refused, match="didn't let it stream"):
        await music.run(hass, {"op": "play", "what": "redrum", "room": "living room"})
