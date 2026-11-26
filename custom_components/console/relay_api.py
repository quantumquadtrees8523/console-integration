"""What the relay may ask of this box, over the tunnel, as a Home Assistant administrator.

- POST /api/console/relay/config: hand over the household's inference key, plan and spend. The answer
  carries this month's usage summary, so one round trip does both.
- GET  /api/console/relay/status: versions, the cloud agent's state and the usage summary.
- POST /api/console/relay/notify: show the household a notification.

The usage summary is counts and labels only (see state.ConsoleData.summary). No message, device name or
room ever goes in it.
"""

from __future__ import annotations

from typing import Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant

from .const import DOMAIN, VERSION
from .state import ConsoleData
from .status import status


def _admin(request: web.Request) -> bool:
    user = request.get("hass_user")
    return bool(user and user.is_admin)


def _report(hass: HomeAssistant, data: ConsoleData) -> dict[str, Any]:
    sunrise = hass.data.get("integrations", {}).get("sunrise")
    return {
        "console": VERSION,
        "home_assistant": HA_VERSION,
        "sunrise": str(sunrise.version) if sunrise and sunrise.version else None,
        "cloud_agent": data.cloud_state(),
        "usage": data.summary(),
        "support": {"on": bool(data.data["support"].get("on")), "until": data.data["support"].get("until")},
    }


class ConfigView(HomeAssistantView):
    url = "/api/console/relay/config"
    name = "api:console:relay:config"

    async def post(self, request: web.Request) -> web.Response:
        if not _admin(request):
            return self.json_message("Administrators only.", 403)
        hass: HomeAssistant = request.app["hass"]
        try:
            body = await request.json()
        except ValueError:
            return self.json_message("That wasn't JSON.", 400)
        if not isinstance(body, dict):
            return self.json_message("Send an object.", 400)
        inference = body.get("inference")
        if inference is not None and not (
            isinstance(inference, dict) and inference.get("key") and inference.get("base_url")
        ):
            return self.json_message("inference needs key and base_url.", 400)
        data: ConsoleData = hass.data[DOMAIN]
        data.apply_relay_config(body)
        await data.async_save_now()
        return self.json(_report(hass, data))


class StatusView(HomeAssistantView):
    url = "/api/console/relay/status"
    name = "api:console:relay:status"

    async def get(self, request: web.Request) -> web.Response:
        if not _admin(request):
            return self.json_message("Administrators only.", 403)
        hass: HomeAssistant = request.app["hass"]
        return self.json(_report(hass, hass.data[DOMAIN]) | {"detail": status(hass, hass.data[DOMAIN])})


class NotifyView(HomeAssistantView):
    url = "/api/console/relay/notify"
    name = "api:console:relay:notify"

    async def post(self, request: web.Request) -> web.Response:
        if not _admin(request):
            return self.json_message("Administrators only.", 403)
        hass: HomeAssistant = request.app["hass"]
        try:
            body = await request.json()
            title, message = str(body["title"])[:120], str(body["message"])[:1000]
        except (ValueError, KeyError, TypeError):
            return self.json_message("Send title and message.", 400)
        await hass.services.async_call(
            "persistent_notification", "create", {"title": title, "message": message}, blocking=True
        )
        pushed = 0
        for service in hass.services.async_services().get("notify", {}):
            if service.startswith("mobile_app_"):
                await hass.services.async_call("notify", service, {"title": title, "message": message})
                pushed += 1
        return self.json({"ok": True, "phones": pushed})
