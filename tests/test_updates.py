"""Updates (updates.py): one button, at the house (Console settings) or on Console's site (the relay asks
/api/console/relay/update), installs the latest release of every HACS integration that has one waiting and
restarts Home Assistant once. The household allows the site's button with switch.console_updates; every run
is in the log the household reads."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import async_fire_time_changed, async_mock_service

LATEST = {"update.sunrise_update": ("Sunrise", "0.4.0", "0.6.0"), "update.console_update": ("Console", "0.14.0", "0.15.0"),
          "update.mushroom_update": ("Mushroom", "4.0.0", "4.0.0")}


def _hacs(hass: HomeAssistant, refuse: str | None = None) -> list[ServiceCall]:
    reg = er.async_get(hass)
    for eid, (name, now, latest) in LATEST.items():
        reg.async_get_or_create("update", "hacs", name, suggested_object_id=eid.split(".")[1])
        hass.states.async_set(eid, "on" if now != latest else "off",
                              {"title": name, "installed_version": now, "latest_version": latest})
    reg.async_get_or_create("update", "esphome", "fw", suggested_object_id="voice_firmware")
    hass.states.async_set("update.voice_firmware", "on", {"title": "Voice PE", "installed_version": "1", "latest_version": "2"})
    calls: list[ServiceCall] = []

    async def install(c: ServiceCall) -> None:
        calls.append(c)
        eid = c.data["entity_id"]
        if eid == refuse:
            raise __import__("homeassistant.exceptions", fromlist=["x"]).HomeAssistantError("GitHub said no")
        st = hass.states.get(eid)
        hass.states.async_set(eid, "off", {**st.attributes, "installed_version": st.attributes["latest_version"]})

    hass.services.async_register("update", "install", install)
    async_mock_service(hass, "homeassistant", "update_entity")
    return calls


async def _restarted(hass: HomeAssistant, restarts: list) -> int:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=5))
    await hass.async_block_till_done()
    return len(restarts)


async def test_the_sites_button_updates_every_waiting_hacs_integration_and_restarts_once(hass, console, hass_client):
    calls = _hacs(hass)
    restarts = async_mock_service(hass, "homeassistant", "restart")
    client = await hass_client()
    status = await (await client.get("/api/console/relay/status")).json()
    assert {u["name"]: u["waiting"] for u in status["updates"]} == {"Console": True, "Mushroom": False, "Sunrise": True}
    assert status["switches"]["updates"] is True and hass.states.get("switch.console_updates").state == "on"

    answer = await client.post("/api/console/relay/update", json={})
    assert answer.status == 200
    done = await answer.json()
    assert done["ok"] and done["restarting"] and done["up_to_date"] == ["Mushroom"]
    assert {(u["name"], u["from"], u["to"]) for u in done["updated"]} == {("Sunrise", "0.4.0", "0.6.0"), ("Console", "0.14.0", "0.15.0")}
    assert sorted(c.data["entity_id"] for c in calls) == ["update.console_update", "update.sunrise_update"]  # never the firmware
    assert not restarts and await _restarted(hass, restarts) == 1  # once, after answering
    line = console.data["support"]["log"][-1]["what"]
    assert line.startswith("Console's operator updated") and "Sunrise 0.4.0 → 0.6.0" in line and "restarted" in line

    again = await (await client.post("/api/console/relay/update", json={})).json()
    assert again["updated"] == [] and not again["restarting"]
    assert await _restarted(hass, restarts) == 1  # nothing new: no restart


async def test_the_household_can_turn_the_sites_button_off_and_only_admins_get_in(hass, console, hass_client, hass_read_only_access_token):
    _hacs(hass)
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.console_updates"}, blocking=True)
    client = await hass_client()
    refused = await client.post("/api/console/relay/update", json={})
    assert refused.status == 423 and "turned off" in (await refused.json())["message"]
    reader = await hass_client(hass_read_only_access_token)
    assert (await reader.post("/api/console/relay/update", json={})).status == 403
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.console_cloud_access"}, blocking=True)
    await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.console_updates"}, blocking=True)
    assert (await client.post("/api/console/relay/update", json={})).status == 423  # off the relay: nothing from outside


async def test_update_now_at_the_house_reports_what_failed_and_restarts_for_the_rest(hass, console, hass_ws_client):
    _hacs(hass, refuse="update.console_update")
    restarts = async_mock_service(hass, "homeassistant", "restart")
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "console/update/now"})
    done = (await ws.receive_json())["result"]
    assert [u["name"] for u in done["updated"]] == ["Sunrise"]
    assert done["failed"] == [{"name": "Console", "why": "GitHub said no"}] and done["restarting"]
    assert await _restarted(hass, restarts) == 1
    assert "Not updated: Console (GitHub said no)" in console.data["support"]["log"][-1]["what"]
