"""Console's Home dashboard: built from the house itself, the same way every time.

One view of sections: the chat card with Console's two off switches under it, then lights (on/off first, room by room), then speakers, then
everything else the owner exposed to Assist. Nothing is guessed and no model is involved: the same
house gives the same dashboard. A dashboard the household has edited by hand is left alone unless they
ask for it to be rebuilt.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from homeassistant.components import frontend
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er

URL_PATH = "console-home"
TITLE = "Home"
ICON = "mdi:home-heart"
_LOGGER = logging.getLogger(__name__)

OWN = ("switch.console_cloud_agent", "switch.console_ai")
# (section title, icon, domains), in the order they appear after the chat card.
GROUPS = (
    ("Lights", "mdi:lightbulb-group", ("light",)),
    ("Music and speakers", "mdi:speaker", ("media_player",)),
    ("Climate", "mdi:thermostat", ("climate", "humidifier", "fan")),
    ("Doors, shades and switches", "mdi:toggle-switch", ("cover", "lock", "switch", "input_boolean")),
    ("Scenes", "mdi:palette", ("scene", "script")),
)


def _exposed(hass: HomeAssistant, entity_id: str) -> bool:
    from homeassistant.components.homeassistant.exposed_entities import async_should_expose  # noqa: PLC0415

    return async_should_expose(hass, "conversation", entity_id)


def _area_name(hass: HomeAssistant, entity_id: str) -> str:
    entities, devices, areas = er.async_get(hass), dr.async_get(hass), ar.async_get(hass)
    entry = entities.async_get(entity_id)
    area_id = entry.area_id if entry else None
    if entry and not area_id and entry.device_id and (device := devices.async_get(entry.device_id)):
        area_id = device.area_id
    area = areas.async_get_area(area_id) if area_id else None
    return area.name if area else ""


def _tile(entity_id: str, domain: str) -> dict[str, Any]:
    tile: dict[str, Any] = {"type": "tile", "entity": entity_id}
    if domain in ("light", "switch", "input_boolean", "fan"):
        tile["tap_action"] = {"action": "toggle"}
        tile["icon_tap_action"] = {"action": "toggle"}
    if domain == "light":
        tile["features"] = [{"type": "light-brightness"}]
        tile["features_position"] = "inline"
    if domain == "media_player":
        tile["features"] = [{"type": "media-player-playback"}]
        tile["features_position"] = "inline"
    return tile


def build(hass: HomeAssistant) -> dict[str, Any]:
    """The dashboard's config for this house right now."""
    sections: list[dict[str, Any]] = [
        {
            "type": "grid",
            "cards": [
                {"type": "heading", "heading": "Console", "heading_style": "title", "icon": ICON},
                {"type": "custom:console-chat-card", "title": "", "grid_options": {"columns": "full", "rows": 7}},
                {"type": "tile", "entity": "switch.console_cloud_agent", "name": "Cloud agent"},
                {"type": "tile", "entity": "switch.console_ai", "name": "AI in this house"},
            ],
        }
    ]
    for title, icon, domains in GROUPS:
        found = []
        for state in hass.states.async_all(domains):
            if state.entity_id in OWN:
                continue  # Console's own switches sit under the chat card
            if _exposed(hass, state.entity_id):
                found.append((_area_name(hass, state.entity_id) or "~", state.name.lower(), state.entity_id))
        if not found:
            continue
        cards: list[dict[str, Any]] = [{"type": "heading", "heading": title, "heading_style": "title", "icon": icon}]
        room = None
        for area, _, entity_id in sorted(found):
            if area != room and len({a for a, _, _ in found}) > 1:
                room = area
                cards.append({"type": "heading", "heading": "No room yet" if area == "~" else area, "heading_style": "subtitle"})
            cards.append(_tile(entity_id, entity_id.partition(".")[0]))
        sections.append({"type": "grid", "cards": cards})
    return {"views": [{"type": "sections", "title": TITLE, "path": "home", "icon": ICON, "max_columns": 3, "sections": sections}]}


def digest(config: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:16]


def _collection(hass: HomeAssistant):
    """Home Assistant's own list of dashboards. It's reachable only through its WebSocket command, so
    this goes in through that command's handler."""
    handler = hass.data["websocket_api"]["lovelace/dashboards/create"][0]
    for _ in range(8):
        if hasattr(handler, "__self__"):
            return handler.__self__.storage_collection
        handler = getattr(handler, "__wrapped__", None)
        if handler is None:
            break
    raise RuntimeError("Home Assistant's dashboard list wasn't found where this version keeps it")


async def ensure(hass: HomeAssistant, data, *, force: bool = False, make_default: bool = True) -> dict[str, Any]:
    """Create Console's Home dashboard, or bring it up to date with the house. A dashboard someone has
    edited since Console last wrote it is left alone unless `force`. Returns what was done."""
    from homeassistant.components.lovelace.const import LOVELACE_DATA  # noqa: PLC0415

    kept = data.data.setdefault("dashboard", {})
    lovelace = hass.data.get(LOVELACE_DATA)
    if lovelace is None:
        return {"ok": False, "why": "Home Assistant's dashboards aren't loaded."}
    created = False
    if URL_PATH not in lovelace.dashboards:
        await _collection(hass).async_create_item(
            {"url_path": URL_PATH, "title": TITLE, "icon": ICON, "show_in_sidebar": True, "require_admin": False, "mode": "storage"}
        )
        created = True
    board = lovelace.dashboards[URL_PATH]
    config = build(hass)
    try:
        current = await board.async_load(False)
    except Exception:  # noqa: BLE001 (no config saved yet)
        current = None
    did = "unchanged"
    if current is None or created:
        await board.async_save(config)
        did = "created"
    elif digest(current) == digest(config):
        did = "unchanged"
    elif force or digest(current) == kept.get("written"):
        await board.async_save(config)
        did = "rebuilt"
    else:
        did = "left alone: it has been edited by hand"
    if did in ("created", "rebuilt") or (did == "unchanged" and not kept.get("written")):
        kept["written"] = digest(config)

    if make_default and not kept.get("default_set"):
        system = await frontend.async_system_store(hass)
        core = system.data.get("core") or {}
        if core.get("default_panel") != URL_PATH:
            kept["default_before"] = core.get("default_panel")
            await system.async_set_item("core", {**core, "default_panel": URL_PATH})
        kept["default_set"] = True
    data.changed()
    return {"ok": True, "did": did, "url": f"/{URL_PATH}", "sections": len(config["views"][0]["sections"])}


async def remove(hass: HomeAssistant, data) -> None:
    """Take Console's dashboard away and put the default dashboard back as it was."""
    from homeassistant.components.lovelace.const import LOVELACE_DATA  # noqa: PLC0415

    kept = data.data.get("dashboard") or {}
    system = await frontend.async_system_store(hass)
    core = system.data.get("core") or {}
    if core.get("default_panel") == URL_PATH:
        before = kept.get("default_before")
        await system.async_set_item("core", {**core, "default_panel": before} if before else {k: v for k, v in core.items() if k != "default_panel"})
    lovelace = hass.data.get(LOVELACE_DATA)
    if lovelace and URL_PATH in lovelace.dashboards:
        collection = _collection(hass)
        for item in list(collection.async_items()):
            if item.get("url_path") == URL_PATH:
                await collection.async_delete_item(item["id"])
