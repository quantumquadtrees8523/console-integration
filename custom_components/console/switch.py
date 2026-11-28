"""The two off switches as Home Assistant switches, so they can sit on a dashboard or in an automation.

- switch.console_cloud_access: cloud access. Off: the house is off Console's relay. The hub drops its
  tunnel and doesn't dial again, so nothing reaches the house from outside (no opening it away from home,
  no Claude through the connector, no operator), and Console sends nothing out: its cloud agent is off,
  no key is renewed, no usage is reported. It can only be turned back on from inside the house.
- switch.console_ai: AI in this house. Off: no AI agent (Console's, Claude, any other) can use the
  house's tools. Only Home Assistant's own sentence matching answers.

- switch.console_updates: updates from Console's site. On: Console's operator can install the latest release of
  each integration HACS manages here, then restart Home Assistant (updates.py). Off: only someone at the house can.

Neither of the first two is a firewall: other things on the box that use the internet by themselves (Home Assistant
Cloud, a music service, HACS) are not affected by them.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .state import ConsoleData

OLD_CLOUD_SWITCH = "switch.console_cloud_agent"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    data: ConsoleData = hass.data[DOMAIN]
    registry = er.async_get(hass)
    if registry.async_get(OLD_CLOUD_SWITCH):  # 0.3 to 0.5 called it the cloud agent switch
        registry.async_remove(OLD_CLOUD_SWITCH)
    async_add_entities(
        [
            KillSwitch(data, entry, "cloud", "switch.console_cloud_access", "Cloud access", "mdi:cloud-outline"),
            KillSwitch(data, entry, "ai", "switch.console_ai", "AI in this house", "mdi:robot-outline"),
            KillSwitch(data, entry, "updates", "switch.console_updates", "Updates from Console's site", "mdi:update"),
        ]
    )


class KillSwitch(SwitchEntity):
    _attr_has_entity_name = False
    _attr_should_poll = False

    def __init__(self, data: ConsoleData, entry: ConfigEntry, key: str, entity_id: str, name: str, icon: str) -> None:
        self.data = data
        self.key = key
        self.entity_id = entity_id
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{entry.entry_id}_switch_{'cloud_access' if key == 'cloud' else key}"

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.data.listen(self._changed))

    @callback
    def _changed(self) -> None:
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return self.data.switch(self.key)

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.data.set_switch(self.key, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.data.set_switch(self.key, False)
