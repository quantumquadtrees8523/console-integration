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

SUGGESTIONS_ON_TITLE = "Nightly suggestions are on"
SUGGESTIONS_ON = (
    "Each night Console's cloud agent looks at how your house is used and suggests a few routines in the chat. "
    "This uses some of this month's credits every night, so your allowance runs down faster. Turn it off any "
    "time on the Console page, under Settings."
)
SUGGESTIONS_COST = (
    "Each night's run uses some of this month's credits, so the allowance runs down faster. It's skipped once "
    "80% of the month's allowance is used, and whenever the cloud agent is off."
)
SUGGESTIONS_NO_SUNRISE = "Suggested routines need Sunrise, and it isn't installed."
SUGGESTION_GONE = "That suggestion isn't here any more."
SUGGESTION_DIDNT_RUN = "That suggestion didn't run. Nothing changed."


def _what_changed(things: list[dict[str, Any]]) -> str:
    shown = [f"{t.get('name') or t.get('id')} is {t.get('now')}" for t in things[:4] if t.get("now") not in (None, "missing")]
    return (", ".join(shown) + ".") if shown else ""


def suggestion_ran(name: str, things: list[dict[str, Any]], taps: int, keep_after: int, kept: bool) -> str:
    done = f"Done: “{name}” ran. {_what_changed(things)}".strip()
    if kept:
        return (
            f"{done} That's {keep_after} times, so it's yours now: it runs by itself from here on. "
            "To take it back, say “undo that routine” or remove it under Settings → Automations."
        )
    left = keep_after - taps
    return f"{done} Tap it {left} more time{'s' if left != 1 else ''} and it runs by itself."


def suggestion_tapped(name: str) -> str:
    return f"Run \u201c{name}\u201d"


def suggestion_dismissed(name: str) -> str:
    return f"Removed “{name}”. I won't suggest it again."
