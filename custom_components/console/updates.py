"""Update this house: install the latest release of every integration HACS manages that has one waiting
(Console, Sunrise, any other), then restart Home Assistant once so they load. Owner, 2026-11-28: "can we
get to a point where i simply just click update on the cloud or local machine and it updates with
whatever is most up to date on the integrations?"

Two buttons reach this: Update now in Console settings (an administrator at the house), and the relay's
admin page (POST /api/console/relay/update), which the household allows with switch.console_updates (on
unless they turn it off). Each run goes in the log the household reads. HACS downloads the releases;
Home Assistant itself and its built-in integrations are not touched.
"""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from . import wording

INSTALL_WAIT_S = 120.0  # one integration
RESTART_AFTER_S = 3.0  # so the answer gets out before Home Assistant goes down


def hacs_updates(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Every update entity HACS made: what's installed, what's latest, whether one is waiting."""
    out = []
    for entry in er.async_get(hass).entities.values():
        if entry.platform != "hacs" or entry.domain != "update":
            continue
        st = hass.states.get(entry.entity_id)
        a = st.attributes if st else {}
        out.append({"id": entry.entity_id, "name": a.get("title") or (st.name if st else entry.entity_id),
                    "version": a.get("installed_version"), "latest": a.get("latest_version"),
                    "waiting": bool(st and st.state == "on")})
    return sorted(out, key=lambda r: str(r["name"]).lower())


async def refresh(hass: HomeAssistant) -> None:
    """Ask HACS to look again, so a release published minutes ago is seen."""
    ids = [r["id"] for r in hacs_updates(hass)]
    if ids and hass.services.has_service("homeassistant", "update_entity"):
        try:
            await hass.services.async_call("homeassistant", "update_entity", {"entity_id": ids}, blocking=True)
        except HomeAssistantError:
            pass


async def update_all(hass: HomeAssistant, data, by: str, restart: bool = True) -> dict[str, Any]:
    """Install every waiting HACS release, one at a time, reading each version back; restart once if any landed."""
    await refresh(hass)
    waiting = [r for r in hacs_updates(hass) if r["waiting"]]
    updated, failed = [], []
    for row in waiting:
        try:
            async with asyncio.timeout(INSTALL_WAIT_S):
                await hass.services.async_call("update", "install", {"entity_id": row["id"]}, blocking=True, context=Context())
        except TimeoutError:
            failed.append({"name": row["name"], "why": "HACS didn't finish in time"})
            continue
        except (HomeAssistantError, ValueError) as exc:
            failed.append({"name": row["name"], "why": str(exc)[:200]})
            continue
        now = next((r for r in hacs_updates(hass) if r["id"] == row["id"]), row)
        if now["version"] and str(now["version"]) == str(row["latest"]):
            updated.append({"name": row["name"], "from": row["version"], "to": now["version"]})
        else:
            failed.append({"name": row["name"], "why": f"HACS finished, but it reads {now['version']}, not {row['latest']}"})
    restarting = bool(restart and updated)
    data.support.log(wording.updated(by, updated, failed, restarting))
    if restarting:
        hass.loop.call_later(RESTART_AFTER_S, lambda: hass.async_create_task(
            hass.services.async_call("homeassistant", "restart", {}, context=Context())))
    return {"ok": not failed, "updated": updated, "failed": failed,
            "up_to_date": [r["name"] for r in hacs_updates(hass) if not r["waiting"] and r["name"] not in {u["name"] for u in updated}],
            "restarting": restarting}
