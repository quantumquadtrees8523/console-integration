"""Backups and the recovery code."""

from __future__ import annotations

import re

from homeassistant.setup import async_setup_component

from custom_components.console import backups


async def ws(hass, hass_ws_client, command: dict, token=None) -> dict:
    client = await hass_ws_client(hass, token) if token else await hass_ws_client(hass)
    await client.send_json({"id": 1, **command})
    return await client.receive_json()


def test_a_recovery_code_is_long_and_typeable():
    code = backups.new_code()
    assert re.fullmatch(r"([A-HJ-NP-Z2-9]{4}-){6}[A-HJ-NP-Z2-9]{4}", code)
    assert backups.new_code() != code


async def test_the_first_ask_makes_the_code_and_sets_it_as_the_backup_key(hass, console, hass_ws_client):
    assert await async_setup_component(hass, "backup", {})
    await hass.async_block_till_done()
    before = (await ws(hass, hass_ws_client, {"type": "console/backup/status"}))["result"]
    assert before["available"] is True and before["encrypted"] is False and before["copies_go_to"] == ["backup.local"]

    made = (await ws(hass, hass_ws_client, {"type": "console/backup/recovery_code"}))["result"]
    assert made["created"] is True and len(made["code"]) == 34
    again = (await ws(hass, hass_ws_client, {"type": "console/backup/recovery_code"}))["result"]
    assert again == {"code": made["code"], "created": False}  # the same code every time after
    assert (await ws(hass, hass_ws_client, {"type": "console/backup/status"}))["result"]["encrypted"] is True
    info = (await ws(hass, hass_ws_client, {"type": "backup/config/info"}))["result"]
    assert info["config"]["create_backup"]["password"] == made["code"]  # Home Assistant's own setting


async def test_a_key_the_household_already_has_is_their_recovery_code(hass, console, hass_ws_client):
    assert await async_setup_component(hass, "backup", {})
    await hass.async_block_till_done()
    await ws(hass, hass_ws_client, {"type": "backup/config/update", "create_backup": {"password": "their-own-key"}})
    got = (await ws(hass, hass_ws_client, {"type": "console/backup/recovery_code"}))["result"]
    assert got == {"code": "their-own-key", "created": False}


async def test_only_an_administrator_sees_the_code_or_starts_a_backup(hass, console, hass_ws_client, hass_read_only_access_token):
    assert await async_setup_component(hass, "backup", {})
    for command in ({"type": "console/backup/recovery_code"}, {"type": "console/backup/now"}):
        answer = await ws(hass, hass_ws_client, command, hass_read_only_access_token)
        assert answer["success"] is False and answer["error"]["code"] == "unauthorized"


async def test_back_up_now_encrypts_with_the_code(hass, console, hass_ws_client, monkeypatch):
    assert await async_setup_component(hass, "backup", {})
    await hass.async_block_till_done()
    asked = {}

    class Started:
        backup_job_id = "job1"

    async def create(**kwargs):
        asked.update(kwargs)
        return Started()

    monkeypatch.setattr(backups._manager(hass), "async_create_backup", create)
    done = (await ws(hass, hass_ws_client, {"type": "console/backup/now"}))["result"]
    code = (await backups.recovery_code(hass))["code"]
    assert done["ok"] and done["job"] == "job1" and done["copies_go_to"] == ["backup.local"]
    assert asked["password"] == code and asked["agent_ids"] == ["backup.local"] and asked["include_database"] is True


async def test_the_code_is_never_in_what_the_relay_reads(hass, console, hass_client):
    assert await async_setup_component(hass, "backup", {})
    await hass.async_block_till_done()
    code = (await backups.recovery_code(hass))["code"]
    client = await hass_client()
    seen = await (await client.get("/api/console/relay/status")).text()
    assert code not in seen


async def test_the_new_key_is_on_disk_at_once(hass, console, hass_storage):
    """A backup started straight after the code is made must already carry it."""
    assert await async_setup_component(hass, "backup", {})
    await hass.async_block_till_done()
    code = (await backups.recovery_code(hass))["code"]
    assert hass_storage["backup"]["data"]["config"]["create_backup"]["password"] == code
