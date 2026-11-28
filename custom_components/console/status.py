"""Console's state in one dict: what the sensor, the chat card, the panel and the relay all read."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant

from . import dashboard, updates, wording
from .const import VERSION
from .credits import credits
from .state import ConsoleData, next_reset


def banner(data: ConsoleData) -> dict[str, Any] | None:
    """The banner over the chat card, or None when there's nothing to say."""
    state = data.cloud_state()
    support = getattr(data, "support", None)
    if support is not None and support.on():
        return {"kind": "support", "text": wording.support_on(datetime.fromisoformat(support.state["until"]))}
    if state == "ai_off":
        return {"kind": "off", "text": wording.AI_OFF}
    if state == "cloud_off":
        return {"kind": "off", "text": wording.CLOUD_OFF}
    if data.data.get("unlinked"):
        return {"kind": "offline", "text": wording.UNLINKED}
    if state == "near_limit":
        return {"kind": "warn", "text": wording.near_limit(min(99, int(data.used * 100)), data.plan)}
    if state == "over_limit":
        return {"kind": "stop", "text": wording.over_limit(next_reset(data.now()), data.plan)}
    if state == "not_linked":
        return {"kind": "offline", "text": wording.NOT_LINKED}
    if not data.feature("agent"):
        return {"kind": "off", "text": wording.AGENT_OFF}
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
        "support": {"on": data.support.on(), "until": data.data["support"].get("until"), "log": list(data.data["support"].get("log") or [])[-30:]},
        "unlinked": bool(data.data.get("unlinked")),
        "switches": {"cloud": data.switch("cloud"), "ai": data.switch("ai"), "updates": data.switch("updates")},
        "updates": updates.hacs_updates(hass),
        "agent": data.feature("agent"),
        "credits": {"used": credits(data.spend_usd), "allowed": credits(data.cap_usd)},
        "site": data.data.get("site"),
        "onboarding": dict(data.data["onboarding"]),
        "learned": len(data.data["learned"]),
        "dashboard": {"url": f"/{dashboard.URL_PATH}", "written": bool((data.data.get("dashboard") or {}).get("written"))},
    }
