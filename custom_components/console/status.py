"""Console's state in one dict: what the sensor, the chat card, the panel and the relay all read."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import dashboard, wording
from .const import VERSION
from .state import ConsoleData, next_reset


def banner(data: ConsoleData) -> dict[str, Any] | None:
    """The banner over the chat card, or None when there's nothing to say."""
    state = data.cloud_state()
    if state == "near_limit":
        return {"kind": "warn", "text": wording.near_limit(min(99, int(data.used * 100)), data.plan)}
    if state == "over_limit":
        return {"kind": "stop", "text": wording.over_limit(next_reset(data.now()), data.plan)}
    if state == "not_linked":
        return {"kind": "offline", "text": wording.NOT_LINKED}
    return None


def status(hass: HomeAssistant, data: ConsoleData) -> dict[str, Any]:
    sunrise = hass.config_entries.async_entries("sunrise")
    return {
        "version": VERSION,
        "cloud_agent": data.cloud_state(),
        "percent": int(data.used * 100),
        "banner": banner(data),
        "plan": {k: data.plan.get(k) for k in ("tier", "tier_name", "cap_usd", "next", "contact")},
        "resets": next_reset(data.now()).isoformat(),
        "usage": data.summary(),
        "key_expires": (data.data.get("inference") or {}).get("expires_at"),
        "linked_at": data.data.get("linked_at"),
        "sunrise": bool(sunrise),
        "support": {k: data.data["support"].get(k) for k in ("on", "until")},
        "onboarding": dict(data.data["onboarding"]),
        "learned": len(data.data["learned"]),
        "dashboard": {"url": f"/{dashboard.URL_PATH}", "written": bool((data.data.get("dashboard") or {}).get("written"))},
    }
