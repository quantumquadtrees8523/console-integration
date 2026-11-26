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
