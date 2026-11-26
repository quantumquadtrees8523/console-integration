"""Console: the opinionated path on top of Home Assistant and Sunrise.

A conversation agent (local first, then the household's own cloud agent), a chat card, a panel, and
the link to Console's relay. Everything that talks to the internet lives here, never in Sunrise.
"""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import CoreState, HomeAssistant, ServiceCall

from . import dashboard, relay_api, websocket_api
from .const import DOMAIN, PANEL_URL, STATIC_URL, VERSION
from .guard import AiGuard
from .learned import Learned
from .others import OtherAgents
from .state import ConsoleData
from .support import Support

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.CONVERSATION, Platform.SENSOR, Platform.SWITCH]
CARD_URL = f"{STATIC_URL}/console-chat-card.js?v={VERSION}"
PANEL_JS = f"{STATIC_URL}/console-panel.js?v={VERSION}"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = ConsoleData(hass)
    await data.async_load()
    data.learned = Learned(hass, data)
    data.others = OtherAgents(hass, data)
    data.support = Support(hass, data)
    data.guard = AiGuard(hass, data)
    hass.data[DOMAIN] = data

    if not hass.data.get(f"{DOMAIN}_served"):
        hass.data[f"{DOMAIN}_served"] = True
        www = Path(__file__).parent / "www"
        await hass.http.async_register_static_paths([StaticPathConfig(STATIC_URL, str(www), False)])
        frontend.add_extra_js_url(hass, CARD_URL)
        for view in (relay_api.ConfigView, relay_api.StatusView, relay_api.NotifyView, relay_api.SupportView):
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
    data.learned.start()
    data.others.start()
    data.support.start()
    data.guard.start()

    async def build_dashboard(_event=None) -> None:
        """Once the house's things are all loaded: make the Home dashboard, or bring it up to date."""
        try:
            await dashboard.ensure(hass, data)
        except Exception:  # noqa: BLE001 (a dashboard that can't be built mustn't stop Console)
            _LOGGER.exception("Console: the Home dashboard couldn't be built")

    if hass.state is CoreState.running:
        entry.async_create_background_task(hass, build_dashboard(), "console dashboard")
    else:
        entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, build_dashboard))

    async def rebuild(call: ServiceCall) -> None:
        await dashboard.ensure(hass, data, force=bool(call.data.get("force", True)))

    hass.services.async_register(DOMAIN, "rebuild_dashboard", rebuild)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        data = hass.data[DOMAIN]
        data.learned.stop()
        data.others.stop()
        data.support.stop()
        data.guard.stop()
        hass.services.async_remove(DOMAIN, "rebuild_dashboard")
        frontend.async_remove_panel(hass, PANEL_URL)
        await hass.data[DOMAIN].async_save_now()
    return unloaded
