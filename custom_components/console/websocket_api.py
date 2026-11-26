"""What the chat card and the Console page ask over Home Assistant's WebSocket.

Reading is for anyone signed in to Home Assistant. Changing or deleting anything is for administrators.
"""

from __future__ import annotations

from typing import Any

import probatio as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from . import dashboard, knows
from .const import DOMAIN
from .status import status


@callback
def async_setup(hass: HomeAssistant) -> None:
    for command in (
        ws_status,
        ws_knows,
        ws_memory_read,
        ws_memory_write,
        ws_memory_delete,
        ws_learned_forget,
        ws_assist_clear,
        ws_dashboard_rebuild,
    ):
        websocket_api.async_register_command(hass, command)


@websocket_api.websocket_command({vol.Required("type"): "console/status"})
@callback
def ws_status(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    connection.send_result(msg["id"], status(hass, hass.data[DOMAIN]) | {"is_admin": connection.user.is_admin})


@websocket_api.websocket_command({vol.Required("type"): "console/knows"})
@websocket_api.async_response
async def ws_knows(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """What the house knows about the people in it."""
    connection.send_result(msg["id"], await knows.everything(hass, hass.data[DOMAIN]))


@websocket_api.websocket_command({vol.Required("type"): "console/memory/read", vol.Required("name"): str})
@websocket_api.async_response
async def ws_memory_read(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    text = await knows.memory_read(hass, msg["name"])
    if text is None:
        connection.send_error(msg["id"], "not_found", "There's no memory file with that name.")
        return
    connection.send_result(msg["id"], {"name": msg["name"], "text": text})


@websocket_api.websocket_command(
    {vol.Required("type"): "console/memory/write", vol.Required("name"): str, vol.Required("text"): str}
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_memory_write(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    try:
        await knows.memory_write(hass, msg["name"], msg["text"])
    except Exception as error:  # noqa: BLE001 (Sunrise's own refusals are worded for the person)
        connection.send_error(msg["id"], "refused", str(error))
        return
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command({vol.Required("type"): "console/memory/delete", vol.Required("name"): str})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_memory_delete(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    try:
        await knows.memory_delete(hass, msg["name"])
    except Exception as error:  # noqa: BLE001
        connection.send_error(msg["id"], "refused", str(error))
        return
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command({vol.Required("type"): "console/learned/forget", vol.Required("sentence_id"): str})
@websocket_api.require_admin
@callback
def ws_learned_forget(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    connection.send_result(msg["id"], {"ok": hass.data[DOMAIN].learned.forget(msg["sentence_id"])})


@websocket_api.websocket_command({vol.Required("type"): "console/assist/clear"})
@websocket_api.require_admin
@callback
def ws_assist_clear(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    connection.send_result(msg["id"], {"cleared": knows.clear_assist_runs(hass)})


@websocket_api.websocket_command({vol.Required("type"): "console/dashboard/rebuild"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_dashboard_rebuild(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    connection.send_result(msg["id"], await dashboard.ensure(hass, hass.data[DOMAIN], force=True))
