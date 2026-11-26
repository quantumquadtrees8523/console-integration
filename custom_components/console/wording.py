"""Every sentence Console shows a household, in one place."""

from __future__ import annotations

from datetime import datetime
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
    "Console's cloud agent is turned off for this house. Plain commands still run at home. Turn it back on "
    "on the Console page, under Settings."
)
AI_OFF = (
    "AI is turned off for this house: Console's cloud agent, Claude and any other AI agent can't read or "
    "change anything here. Plain commands still run at home. Turn it back on on the Console page, under Settings."
)
CLOUD_OFF_REPLY = (
    "I couldn't do that one: Console's cloud agent is turned off for this house, so I can only do plain "
    "commands like \u201cturn off the kitchen lights\u201d."
)
AI_OFF_REPLY = (
    "I couldn't do that one: AI is turned off for this house, so I can only do plain commands like "
    "\u201cturn off the kitchen lights\u201d."
)
AI_OFF_TOOLS = "AI is turned off for this house, on the Console page in Home Assistant. No AI agent can use its tools until someone there turns it back on."
