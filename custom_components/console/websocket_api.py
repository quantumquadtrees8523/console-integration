"""What the chat card and the Console panel ask over Home Assistant's WebSocket."""

from __future__ import annotations

from typing import Any

import probatio as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN
from .status import status


@callback
def async_setup(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_status)


@websocket_api.websocket_command({vol.Required("type"): "console/status"})
@callback
def ws_status(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    connection.send_result(msg["id"], status(hass, hass.data[DOMAIN]))
