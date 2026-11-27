"""The settings page: support mode and the two wipes."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from homeassistant.const import EVENT_HOMEASSISTANT_CLOSE
from homeassistant.setup import async_setup_component

from custom_components.console import wipe, wording
from custom_components.console.const import OPENROUTER_URL

from .conftest import ask, link


async def ws(hass, hass_ws_client, command: dict, token=None) -> dict:
    client = await hass_ws_client(hass, token) if token else await hass_ws_client(hass)
    await client.send_json({"id": 1, **command})
    return await client.receive_json()


async def test_support_mode_is_off_until_someone_turns_it_on(hass, console, hass_ws_client, freezer):
    assert await async_setup_component(hass, "persistent_notification", {})
    assert console.support.on() is False
    answer = await ws(hass, hass_ws_client, {"type": "console/support/set", "on": True})
    assert answer["result"]["on"] is True
    await hass.async_block_till_done()
    sensor = hass.states.get("sensor.console_cloud_agent")
    assert sensor.attributes["support"] is True and sensor.attributes["banner_kind"] == "support"
    assert sensor.attributes["banner"].startswith("Support mode is on until ")
    assert "Console's operator can open this house" in sensor.attributes["banner"]
    notices = hass.states.async_entity_ids("persistent_notification") or hass.data["persistent_notification"]
    assert "console_support" in str(notices)
    log = console.data["support"]["log"]
    assert log[-1]["what"].startswith("Turned on by ") and "7 days" in log[-1]["what"]

    freezer.tick(timedelta(days=7, minutes=1))
    console.support.check()
    assert console.support.on() is False
    assert console.data["support"]["log"][-1]["what"] == wording.SUPPORT_EXPIRED


async def test_the_operator_is_refused_unless_support_mode_is_on_and_is_logged_when_it_is(hass, console, hass_client):
    assert await async_setup_component(hass, "persistent_notification", {})
    client = await hass_client()
    refused = await client.post("/api/console/relay/support", json={"event": "opened"})
    assert refused.status == 409
    turned_on = await client.post("/api/console/relay/support", json={"set": True})
    assert (await turned_on.json())["on"] is True
    opened = await client.post("/api/console/relay/support", json={"event": "opened"})
    assert opened.status == 200
    await client.post("/api/console/relay/support", json={"event": "closed"})
    said = [line["what"] for line in console.data["support"]["log"]]
    assert said[-2:] == ["Console's operator opened this house.", "Console's operator closed this house."]
    status = await (await client.get("/api/console/relay/status")).json()
    assert status["support"]["on"] is True and status["detail"]["support"]["log"][-1]["what"] == said[-1]
    off = await client.post("/api/console/relay/support", json={"set": False})
    assert (await off.json())["on"] is False


async def test_only_an_administrator_changes_support_mode_or_wipes(hass, console, hass_ws_client, hass_read_only_access_token):
    for command in (
        {"type": "console/support/set", "on": True},
        {"type": "console/wipe", "level": "data", "confirm": wipe.WORDS_DATA},
        {"type": "console/wipe", "level": "factory", "confirm": wipe.WORDS_FACTORY},
        {"type": "console/relink"},
    ):
        answer = await ws(hass, hass_ws_client, command, hass_read_only_access_token)
        assert answer["success"] is False and answer["error"]["code"] == "unauthorized"
    assert console.support.on() is False


async def test_a_wipe_needs_its_words_typed_exactly(hass, console, hass_ws_client):
    link(console)
    for level, typed in (("data", "erase"), ("data", "factory reset"), ("factory", "erase my data"), ("factory", "")):
        answer = await ws(hass, hass_ws_client, {"type": "console/wipe", "level": level, "confirm": typed})
        assert answer["success"] is False and answer["error"]["code"] == "not_confirmed"
        assert "Nothing was erased" in answer["error"]["message"]
    assert console.key() is not None


async def test_erasing_data_forgets_everything_and_cuts_the_link_to_the_relay(hass, console, hass_ws_client, hass_client, model):
    assert await async_setup_component(hass, "persistent_notification", {})
    link(console)
    console.add_spend(0.25)
    console.count_turn("flash", "status", True)
    console.data["learned"].append({"id": "a1", "sentence": "movie time", "action": "light.turn_off", "entity_ids": ["light.kitchen"], "data": {}})
    console.learned.start()
    console.history.add("someone", "you", "remember the surprise party")
    console.history.add("someone", "console", "I will.")
    sunrise = Path(hass.config.path("sunrise"))
    (sunrise / "memory").mkdir(parents=True)
    (sunrise / "memory" / "owner.md").write_text("# Owner\nLikes it dim.\n")

    answer = await ws(hass, hass_ws_client, {"type": "console/wipe", "level": "data", "confirm": "Erase my data "})
    assert answer["success"] is True, answer
    assert answer["result"]["erased"] == {"console_store": True, "learned_sentences": 1, "chat_messages": 2, "sunrise_data": True, "suggestions": 0}
    assert not sunrise.exists()
    assert console.key() is None and console.data["learned"] == [] and console.summary()["turns"] == 0
    assert console.history.total() == 0
    assert console.summary()["spend_usd"] == 0 and console.cloud_state() == "not_linked"
    assert hass.states.get("sensor.console_cloud_agent").attributes["banner"] == wording.UNLINKED
    assert await ask(hass, "what should I automate next in this house") == wording.NOT_LINKED_REPLY
    assert model.calls == []

    client = await hass_client()
    handover = {"inference": {"base_url": OPENROUTER_URL, "key": "new-key", "expires_at": "2099-01-01T00:00:00+00:00"}}
    assert (await client.post("/api/console/relay/config", json=handover)).status == 409  # the relay is refused
    assert (await (await client.get("/api/console/relay/status")).json())["unlinked"] is True

    assert (await ws(hass, hass_ws_client, {"type": "console/relink"}))["success"] is True
    assert (await client.post("/api/console/relay/config", json=handover)).status == 200
    assert console.key()["key"] == "new-key"


async def test_a_factory_reset_removes_everything_but_integrations_and_backups(hass, console, tmp_path):
    """The removal itself, on a stand-in configuration folder (a real restart is tested on a throwaway
    Home Assistant, never here)."""
    for name in (".storage", "sunrise", "custom_components/console", "backups", "www"):
        (tmp_path / name).mkdir(parents=True)
    for name in (".storage/auth", "configuration.yaml", "home-assistant_v2.db", "secrets.yaml", "backups/keep.tar", "custom_components/console/manifest.json"):
        (tmp_path / name).write_text("x")
    gone = wipe._factory_wipe(tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["backups", "custom_components"]
    assert (tmp_path / "backups/keep.tar").exists() and (tmp_path / "custom_components/console/manifest.json").exists()
    assert set(gone) == {".storage", "sunrise", "www", "configuration.yaml", "home-assistant_v2.db", "secrets.yaml"}


async def test_a_factory_reset_wipes_only_as_home_assistant_closes(hass, console, hass_ws_client, monkeypatch):
    wiped, restarted = [], []
    monkeypatch.setattr(wipe, "_factory_wipe", lambda folder: wiped.append(folder) or [])
    hass.services.async_register("homeassistant", "restart", lambda call: restarted.append(True))
    answer = await ws(hass, hass_ws_client, {"type": "console/wipe", "level": "factory", "confirm": "factory reset"})
    assert answer["result"] == {"ok": True, "restarting": True, "kept": ["custom_components", "backups"]}
    await hass.async_block_till_done()
    assert restarted == [True] and wiped == []  # nothing is removed while Home Assistant is still running
    hass.bus.async_fire(EVENT_HOMEASSISTANT_CLOSE)
    await hass.async_block_till_done()
    assert wiped == [Path(hass.config.config_dir)]
