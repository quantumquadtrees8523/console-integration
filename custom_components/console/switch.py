"""The kill switches as Home Assistant switches, so they can sit on a dashboard or in an automation.

- switch.console_cloud_agent: Console's cloud agent. Off: requests are answered at home only.
- switch.console_ai: AI in this house. Off: no AI agent (Console's, Claude, any other) can use the
  house's tools.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .state import ConsoleData


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    data: ConsoleData = hass.data[DOMAIN]
    async_add_entities(
        [
            KillSwitch(data, entry, "cloud", "switch.console_cloud_agent", "Console cloud agent", "mdi:cloud-outline"),
            KillSwitch(data, entry, "ai", "switch.console_ai", "AI in this house", "mdi:robot-outline"),
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
        self._attr_unique_id = f"{entry.entry_id}_switch_{key}"

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
