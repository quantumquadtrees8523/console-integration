"""Console: the opinionated path on top of Home Assistant and Sunrise.

A conversation agent (local first, then the household's own cloud agent), a chat card, a panel, and
the link to Console's relay. Everything that talks to the internet lives here, never in Sunrise.
"""

from __future__ import annotations

from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from . import relay_api, websocket_api
from .const import DOMAIN, PANEL_URL, STATIC_URL, VERSION
from .state import ConsoleData

PLATFORMS = [Platform.CONVERSATION, Platform.SENSOR]
CARD_URL = f"{STATIC_URL}/console-chat-card.js?v={VERSION}"
PANEL_JS = f"{STATIC_URL}/console-panel.js?v={VERSION}"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = ConsoleData(hass)
    await data.async_load()
    hass.data[DOMAIN] = data

    if not hass.data.get(f"{DOMAIN}_served"):
        hass.data[f"{DOMAIN}_served"] = True
        www = Path(__file__).parent / "www"
        await hass.http.async_register_static_paths([StaticPathConfig(STATIC_URL, str(www), False)])
        frontend.add_extra_js_url(hass, CARD_URL)
        for view in (relay_api.ConfigView, relay_api.StatusView, relay_api.NotifyView):
            hass.http.register_view(view())
        websocket_api.async_setup(hass)

    if PANEL_URL not in hass.data.get(frontend.DATA_PANELS, {}):
        await panel_custom.async_register_panel(
            hass,
            frontend_url_path=PANEL_URL,
            webcomponent_name="console-panel",
            sidebar_title="Console",
            sidebar_icon="mdi:home-heart",
            module_url=PANEL_JS,
            require_admin=False,
            config={},
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        frontend.async_remove_panel(hass, PANEL_URL)
        await hass.data[DOMAIN].async_save_now()
    return unloaded
