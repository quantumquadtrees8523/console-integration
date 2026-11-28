"""Console's own facts, read live, for an agent that is asked about Console (the `about` tool, and the
Console half of Sunrise's self-knowledge skill). Product facts that can't be read are written here once."""

from __future__ import annotations

from typing import Any

from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant

from . import features, music, wording
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
            "dashboard, Console settings in the sidebar (plan and usage, what the house knows about you, AI "
            "features, general), and the "
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
            "where": "Home dashboard tiles, or Console settings > General",
        },
        "ai_features": {
            "what": "each use of Console's cloud agent has its own switch, with what it tends to cost and what it used this month",
            "now": {wording.FEATURES[row.key]["name"]: "on" if data.feature(row.key) else "off" for row in features.FEATURES},
            "where": "Console settings > AI features; only an administrator can switch one, and this chat can't",
        },
        "chat_suggestions": (
            "The chat always shows three suggestions to tap, made on this box with no AI from what's on and how the "
            "house is used; a tap runs one at home. Tapped 3 times on 2 different days, one becomes a quick action "
            "under the chat. Seen 4 times and never tapped, it's put away for 30 days."
        ),
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
            "make, change and remove dashboards, including maps, graphs and conditional cards (undoable)",
            "diagnose unreachable devices and the network, and undo its own changes",
            "run Sunrise's skills (list_skills), including welcome for first-time setup",
        ],
        "this_chat_cannot": [
            "use a web browser, open the router's pages, or sign in anywhere",
            "run commands on the box or install software",
            "see or handle passwords, keys or tokens",
            "turn the off switches, an AI feature or support mode on or off",
        ],
        "when_it_cannot": "call console_handoff: the person gets steps and a block to paste into Claude Code",
        "what_is_kept": (
            "Chats are kept on this box only, per signed-in person, as conversations listed like collapsed comment "
            "threads and opened whole in a drawer, with the steps behind each reply. Several can run at once, each "
            "with a dot: working, didn't finish, or a new reply not yet opened. A reply stays inside its conversation; a new conversation is "
            "given a short digest of the person's other recent ones. Each can be copied or deleted in the chat "
            "card, and all of them deleted in Console settings under What the house knows about you. Monthly totals (counts by kind and route, and "
            "credits used) go to Console's relay, and so do counts of what kind of thing each request was, as "
            "labels from a fixed list such as lights.on_off, which the relay adds to one total for all houses "
            "and does not keep for this house; no message, device name or room does."
        ),
    }
