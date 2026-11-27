"""The usage notifications: one at 80% of the month's credits and one at 100%, each once a month, as a
Home Assistant notification and a push to each phone with the Companion app. Each says how much is used
and links to the Console page's Plan tab, which shows where the credits went. Nothing is throttled."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant, callback

from . import wording
from .const import STOP_AT, WARN_AT
from .state import next_reset

_LOGGER = logging.getLogger(__name__)
NOTIFICATION_ID = "console_usage"
LINK = "/console"


class UsageAlerts:
    def __init__(self, hass: HomeAssistant, data) -> None:
        self.hass = hass
        self.data = data
        self._unlisten = None

    @callback
    def start(self) -> None:
        self._unlisten = self.data.listen(self.check)
        self.check()

    @callback
    def stop(self) -> None:
        if self._unlisten:
            self._unlisten()
            self._unlisten = None

    @callback
    def check(self) -> None:
        sent = self.data.data.setdefault("alerts", {})
        if sent.get("period") != self.data.period:
            sent.clear()
            sent.update(period=self.data.period, levels=[])
        used = self.data.used
        level = "out" if used >= STOP_AT else "near" if used >= WARN_AT else None
        if level is None or level in sent["levels"]:
            return
        sent["levels"].append(level)
        if level == "out":
            title, message = wording.USAGE_TITLE_OUT, wording.usage_out(next_reset(self.data.now()))
        else:
            title, message = wording.USAGE_TITLE_NEAR, wording.usage_near(min(99, int(used * 100)))
        self.data.changed()
        self.hass.async_create_task(self._send(title, message))

    async def _send(self, title: str, message: str) -> None:
        services = self.hass.services.async_services()
        if "create" in services.get("persistent_notification", {}):
            await self.hass.services.async_call(
                "persistent_notification", "create",
                {"notification_id": NOTIFICATION_ID, "title": title, "message": message}, blocking=False,
            )  # fmt: skip
        plain = message.replace("[See where they went](/console)", "Tap to see where they went.").replace(
            "[See where the credits went](/console)", "Tap to see where the credits went."
        )
        for service in services.get("notify", {}):
            if service.startswith("mobile_app_"):
                try:
                    await self.hass.services.async_call(
                        "notify", service,
                        {"title": title, "message": plain, "data": {"url": LINK, "clickAction": LINK}}, blocking=False,
                    )  # fmt: skip
                except Exception:  # noqa: BLE001 (one phone that can't be reached mustn't stop the others)
                    _LOGGER.warning("Console: couldn't send the usage notification to %s", service)
