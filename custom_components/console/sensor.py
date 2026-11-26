"""sensor.console_cloud_agent: ok, near_limit, over_limit or not_linked, with the banner's words."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .state import ConsoleData
from .status import banner


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([CloudAgentSensor(hass.data[DOMAIN], entry)])


class CloudAgentSensor(SensorEntity):
    _attr_has_entity_name = False
    _attr_name = "Console cloud agent"
    _attr_icon = "mdi:cloud-check-outline"
    _attr_should_poll = False

    def __init__(self, data: ConsoleData, entry: ConfigEntry) -> None:
        self.data = data
        self._attr_unique_id = f"{entry.entry_id}_cloud_agent"
        self.entity_id = "sensor.console_cloud_agent"

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.data.listen(self._changed))

    @callback
    def _changed(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        return self.data.cloud_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        shown = banner(self.data)
        plan = self.data.plan
        return {
            "percent_used": int(self.data.used * 100),
            "tier": plan.get("tier_name"),
            "banner": shown["text"] if shown else None,
            "banner_kind": shown["kind"] if shown else None,
        }
