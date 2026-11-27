"""Console's own facts, read live, for an agent that is asked about Console (the `about` tool, and the
Console half of Sunrise's self-knowledge skill). Product facts that can't be read are written here once."""

from __future__ import annotations

from typing import Any

from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant

from . import music
from .const import DOMAIN, MODEL_FLASH, MODEL_PRO, VERSION
from .credits import credits
from .state import next_reset


async def facts(hass: HomeAssistant) -> dict[str, Any]:
    data = hass.data[DOMAIN]
    sunrise = hass.data.get("integrations", {}).get("sunrise")
    plan = data.plan
    return {
        "what_console_is": (
            "Console is the opinionated layer on Home Assistant and Sunrise: this chat's agent, the Home "
            "dashboard, the Console page (plan and usage, what the house knows about you, settings), and the "
            "link to Console's relay, which lets the household open the house away from home and connect Claude."
        ),
        "versions": {"console": VERSION, "sunrise": str(sunrise.version) if sunrise and sunrise.version else None, "home_assistant": HA_VERSION},
        "plan": {
            "name": plan.get("tier_name"),
            "credits_a_month": credits(data.cap_usd),
            "credits_used": credits(data.spend_usd),
            "percent_used": int(data.used * 100),
            "starts_again": next_reset(data.now()).date().isoformat(),
            "one_credit_is": "one US cent of AI use by Console's cloud agent",
            "next_plan": plan.get("next"),
            "to_change_plan": f"contact {plan.get('contact')}",
        },
        "cloud_agent": data.cloud_state(),
        "off_switches": {
            "AI in this house": {"on": data.switch("ai"), "off_means": "no AI agent can use this house's tools; plain commands still work"},
            "Cloud access": {"on": data.switch("cloud"), "off_means": "the house is off Console's relay: no access from outside, no Claude through the connector, no cloud agent; it can only be turned back on from inside the house"},
            "where": "Home dashboard tiles, or the Console page > Settings",
        },
        "support_mode": {"on": data.support.on(), "until": data.data["support"].get("until")},
        "relay_site": data.data.get("site"),
        "how_a_request_is_answered": [
            "1. Home Assistant's own agent, at home: built-in sentences and sentences this house learned.",
            f"2. {MODEL_FLASH} with thinking off, for a plain command.",
            f"3. {MODEL_FLASH} with a little thinking, for everything else.",
            f"4. {MODEL_PRO}, when the first model fails or asks for help.",
        ],
        "music": {"music_assistant": music.entry_id(hass) is not None, "speakers": [p["name"] for p in music.players(hass)]},
        "this_chat_can": [
            "switch and set anything exposed to Assist, with a read-back",
            "answer questions about the house",
            "search and play music, playlists and radio on a room's speaker; queue, move, pause, skip, volume",
            "make and change routines, rename things and rooms, add devices Home Assistant found",
            "make and remove dashboards",
            "diagnose unreachable devices and the network, and undo its own changes",
            "run Sunrise's skills (list_skills), including welcome for first-time setup",
        ],
        "this_chat_cannot": [
            "use a web browser, open the router's pages, or sign in anywhere",
            "run commands on the box or install software",
            "see or handle passwords, keys or tokens",
            "turn the off switches or support mode on or off",
        ],
        "when_it_cannot": "call console_handoff: the person gets steps and a block to paste into Claude Code",
        "what_is_kept": (
            "Chat history is kept on this box only, per signed-in person, and is listed and deletable on the "
            "Console page under What the house knows about you. Monthly totals (counts by kind and route, and "
            "credits used) go to Console's relay, and so do counts of what kind of thing each request was, as "
            "labels from a fixed list such as lights.on_off, which the relay adds to one total for all houses "
            "and does not keep for this house; no message, device name or room does."
        ),
    }
