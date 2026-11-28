"""Every sentence Console shows a household, in one place."""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any


def _more(plan: dict[str, Any]) -> str:
    contact = plan.get("contact") or "Surya"
    nxt = plan.get("next")
    if nxt:
        return f"Need more? {nxt['name']} is {nxt['price']}: contact {contact}."
    return f"Need more? Contact {contact}."


def near_limit(percent: int, plan: dict[str, Any]) -> str:
    return f"You've used {percent}% of this month's Console agent allowance. {_more(plan)}"


def over_limit(reset: datetime, plan: dict[str, Any]) -> str:
    day = f"{reset.strftime('%B')} {reset.day}"
    return (
        f"Console's cloud agent is paused until {day}: this month's allowance is used up. Your house still "
        f"works. Lights, routines and plain commands run at home, and Claude is unaffected. {_more(plan)}"
    )


NOT_LINKED = (
    "Console's cloud agent isn't connected right now. Your house still works: plain commands like "
    "“turn off the kitchen lights” run at home."
)

OVER_LIMIT_REPLY = (
    "I couldn't do that one: Console's cloud agent is paused because this month's allowance is used up. "
    "Plain commands like “turn off the kitchen lights” still work, and so does Claude."
)

NOT_LINKED_REPLY = (
    "I couldn't do that one: I can't reach Console's cloud agent right now. Plain commands like "
    "“turn off the kitchen lights” still work."
)

MODEL_FAILED_REPLY = (
    "Something went wrong on my side and I didn't finish that. Nothing else changed. Try again in a moment."
)

LEARNED = "I've learned that one: from now on it runs at home, without the cloud."


SUPPORT_TITLE = "Support mode is on"
SUPPORT_EXPIRED = "Turned itself off after 7 days."


def support_on(until: datetime) -> str:
    day = f"{until.strftime('%B')} {until.day}"
    return (
        f"Support mode is on until {day}. Console's operator can open this house and see what's in it. "
        "Turn it off any time on the Console page, under Settings."
    )


UNLINKED = (
    "This house isn't connected to Console. Its data was erased here. Connect it again on the Console "
    "page, under Settings."
)


CLOUD_OFF = (
    "Cloud access is turned off for this house: it is off Console's relay, so nothing reaches it from "
    "outside and Console's cloud agent is off. Plain commands still run at home. It can only be turned back "
    "on from inside the house, on the Console page under Settings."
)
AI_OFF = (
    "AI is turned off for this house: Console's cloud agent, Claude and any other AI agent can't read or "
    "change anything here. Plain commands still run at home. Turn it back on on the Console page, under Settings."
)
CLOUD_OFF_REPLY = (
    "I couldn't do that one: cloud access is turned off for this house, so I can only do plain commands "
    "like \u201cturn off the kitchen lights\u201d."
)
AI_OFF_REPLY = (
    "I couldn't do that one: AI is turned off for this house, so I can only do plain commands like "
    "\u201cturn off the kitchen lights\u201d."
)
AI_OFF_TOOLS = "AI is turned off for this house, on the Console page in Home Assistant. No AI agent can use its tools until someone there turns it back on."


_SECRET = re.compile(r"(eyJ[\w-]{8,}\.[\w-]+\.[\w-]+|sk-[\w-]{16,}|\b[A-Za-z0-9_-]{40,}\b)")


def _clean(text: Any) -> str:
    """A field of a handoff, with anything that looks like a key or token taken out."""
    return _SECRET.sub("[removed]", str(text or "").strip())


def handoff(args: dict[str, Any]) -> str:
    """The reply when the chat hands a request to Claude Code: plain steps, then one block to paste."""
    asked, why = _clean(args.get("asked")), _clean(args.get("why"))
    found, nxt = _clean(args.get("found")), _clean(args.get("next"))
    block = [
        "I'm working on my Home Assistant house, which runs Console and Sunrise.",
        f"What I asked Console's chat: {asked}",
    ]
    if found:
        block.append(f"What Console's chat found: {found}")
    block += [
        f"What I need you to do: {nxt}",
        "Use the Sunrise tools (the MCP server named console or sunrise) for anything inside Home Assistant.",
        "Tell me what you're about to change before you change it, and never ask me to paste a password or a key: if a sign-in is needed, open the page and let me type it.",
    ]
    reason = f" ({why})" if why else ""
    return (
        f"I can't do that from this chat{reason}. Claude Code can.\n\n"
        "1. Open Claude Code on a computer on your home network.\n"
        "2. Paste this, as it is:\n\n"
        "```text\n" + "\n".join(block) + "\n```\n\n"
        "If Claude Code isn't connected to this house yet, the Console page has the steps under Settings."
    )


# --- suggested routines --------------------------------------------------------------------------

SUGGESTIONS_ON_TITLE = "Suggested routines are on"
SUGGESTIONS_ON = (
    "Console now listens to the house. Every hour its agent checks what the house heard (a door opened, then "
    "someone switched a light), and every Monday at 3 AM it looks at how the house is used. When something is "
    "clearly a habit it makes the routine, running at once, and shows it at the top of Home with Keep and Undo. "
    "One nobody answers in 7 days is removed. Every run uses some of this month's credits, the hourly ones too: "
    "see what they used on the [Console page](/console), under Where it went. Turn it off any time under Settings."
)
SUGGESTIONS_COST = (
    "Every run uses some of this month's credits: a little each hour, more on Mondays. None runs while three "
    "routines are waiting for an answer. The Plan tab shows what they used, under Where it went."
)
SUGGESTIONS_NO_SUNRISE = "Suggested routines need Sunrise, and it isn't installed."
SUGGESTION_GONE = "That suggestion isn't here any more."
SUGGESTION_NOT_KEPT = "That one couldn't be kept just now. It's still running; try again."


def suggestion_kept(name: str) -> str:
    return f"Kept “{name}”. It's an ordinary routine now: change or remove it under Settings → Automations."


def suggestion_dismissed(name: str) -> str:
    return f"Undone: “{name}” is removed. I won't suggest it again."


# --- usage notifications (alerts.py) --------------------------------------------------------------

USAGE_TITLE_NEAR = "80% of this month's Console credits used"
USAGE_TITLE_OUT = "This month's Console credits are used up"


def usage_near(percent: int) -> str:
    return f"You've used {percent}% of this month's Console credits. [See where they went](/console)."


def usage_out(reset: datetime) -> str:
    day = f"{reset.strftime('%B')} {reset.day}"
    return (
        f"Console's cloud agent is paused until {day}. Your house still works at home. "
        "[See where the credits went](/console)."
    )


# --- Music Assistant in the sidebar (music_app.py, www/console-music-panel.js) ---------------------

MUSIC_PANEL_TITLE = "Music Assistant"
MUSIC_PANEL_WORDS = {
    "opening": "Opening Music Assistant…",
    "down": "Music Assistant isn't answering right now.",
    "failed": "Couldn't open Music Assistant:",
    "retry": "Try again",
    "link": "Music Assistant still has its own password. Sign in below once, then use your Home Assistant login from now on.",
    "link_button": "Use my Home Assistant login",
    "linking": "Connecting…",
    "sign_in_first": "Sign in to Music Assistant below first, then press this again.",
}
MUSIC_ADMINS_ONLY = "Only admins can open Music Assistant."
MUSIC_OPEN_FROM_SIDEBAR = "Open Music Assistant from Home Assistant's sidebar."
MUSIC_NOT_ANSWERING = "Music Assistant isn't answering."
MUSIC_NO_SETUP = "Music Assistant didn't start its Home Assistant setup."
MUSIC_SETUP_REFUSED = "Music Assistant didn't accept Home Assistant."
MUSIC_LOGIN_OFF = "Music Assistant connected to Home Assistant, but its Home Assistant login didn't turn on."
