"""Every sentence Console shows a household, in one place."""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any


PANEL_TITLE = "Console settings"  # the page in Home Assistant's sidebar


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
        "Turn it off any time in Console settings."
    )


UNLINKED = (
    "This house isn't connected to Console. Its data was erased here. Connect it again in Console settings."
)


CLOUD_OFF = (
    "Cloud access is turned off for this house: it is off Console's relay, so nothing reaches it from "
    "outside and Console's cloud agent is off. Plain commands still run at home. It can only be turned back "
    "on from inside the house, in Console settings."
)
AI_OFF = (
    "AI is turned off for this house: Console's cloud agent, Claude and any other AI agent can't read or "
    "change anything here. Plain commands still run at home. Turn it back on in Console settings."
)
CLOUD_OFF_REPLY = (
    "I couldn't do that one: cloud access is turned off for this house, so I can only do plain commands "
    "like \u201cturn off the kitchen lights\u201d."
)
AI_OFF_REPLY = (
    "I couldn't do that one: AI is turned off for this house, so I can only do plain commands like "
    "\u201cturn off the kitchen lights\u201d."
)
AGENT_OFF = (
    "Console's cloud agent is switched off under AI features, so only plain commands like “turn off the kitchen "
    "lights” are answered. Turn it back on in Console settings, under AI features."
)
AGENT_OFF_REPLY = (
    "I couldn't do that one: Console's cloud agent is switched off under AI features, so I can only do plain "
    "commands like \u201cturn off the kitchen lights\u201d."
)
AI_OFF_TOOLS = "AI is turned off for this house, in Console settings in Home Assistant. No AI agent can use its tools until someone there turns it back on."


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
        "If Claude Code isn't connected to this house yet, Console settings has the steps."
    )


# --- suggestions and quick actions (suggestions.py) -------------------------------------------------

SUGGESTIONS_ON_TITLE = "Suggested routines are on"
SUGGESTIONS_ON = (
    "Console now listens to the house. Every hour its cloud agent checks what the house heard (a door opened, then "
    "someone switched a light), and every Monday at 3 AM it looks at how your house is used, and suggests a few "
    "routines in the chat. A suggestion stays off until it's been tapped twice; then it runs by itself. Every run "
    "uses some of this month's credits, the hourly ones too: see what they used in [Console settings](/console), "
    "under Where it went. Turn it off any time under AI features."
)
SUGGESTIONS_COST = (
    "Every run uses some of this month's credits: a little each hour, more on Mondays. None runs while three "
    "suggested routines are waiting. The Plan tab shows what they used, under Where it went."
)
SUGGESTIONS_NO_SUNRISE = "Suggested routines need Sunrise, and it isn't installed."
SUGGESTION_GONE = "That suggestion isn't here any more."
SUGGESTION_DIDNT_RUN = "That suggestion didn't run. Nothing changed."

# Something to ask Console: what fills the chat's suggestions when the house has nothing better to offer.
ASKS = {
    "whats_on": "What's on right now?",
    "routines": "What routines would help here?",
    "can_do": "What can you do?",
}
ALL_LIGHTS_OFF = "Turn off all the lights"
WHY_ON_ONE = "It's on right now."
WHY_SCENE = "One of your scenes."
WHY_USED = "One of the things this house switches most."
WHY_THING = "Something this house can switch."
WHY_ASK = "Ask Console."


def room_lights(what: str, room: str) -> str:
    return f"Turn {what} the {room} lights"


def switch_thing(what: str, name: str) -> str:
    return f"Turn {what} {name}"


def why_on(count: int, room: str | None = None) -> str:
    return f"{count} light{' is' if count == 1 else 's are'} on{' there' if room else ''} right now."


def why_habit(hour: int, days: int, of: int) -> str:
    clock = f"{hour % 12 or 12} {'AM' if hour < 12 else 'PM'}"
    return f"Usually on around {clock}: {days} of the last {of} days."


def _what_changed(things: list[dict[str, Any]]) -> str:
    shown = [f"{t.get('name') or t.get('id')} is {t.get('now')}" for t in things[:4] if t.get("now") not in (None, "missing")]
    return (", ".join(shown) + ".") if shown else ""


def routine_ran(name: str, things: list[dict[str, Any]]) -> str:
    return f"Done: “{name}” ran. {_what_changed(things)}".strip()


def action_ran(name: str, rows: list[dict[str, Any]]) -> str:
    """What a tapped suggestion did, from the read-back: only what a thing shows may be called done."""
    done = [r for r in rows if r.get("result") == "CHECKED"]
    down = [r for r in rows if r.get("result") == "UNREACHABLE"]
    unsure = [r for r in rows if r.get("result") == "NOT CONFIRMED"]

    def names(some: list[dict[str, Any]]) -> str:
        return ", ".join(str(r.get("name") or r.get("id")) for r in some[:4]) + (" and more" if len(some) > 4 else "")

    said = []
    if done and all(r.get("now") in ("on", "off") for r in done):
        now = done[0]["now"] if len({r["now"] for r in done}) == 1 else None
        if len(done) == 1:
            said.append(f"Done. {names(done)} is {done[0]['now']}.")
        elif now:
            said.append(f"Done. {len(done)} things are {now}: {names(done)}.")
        else:
            said.append(f"Done. {_what_changed(done)}")
    elif done:
        said.append(f"Done: “{name}” ran.")
    else:
        said.append(f"“{name}” didn't run.")
    if unsure:
        said.append(f"{names(unsure)} didn't show the change.")
    if down:
        said.append(f"{names(down)} can't be reached.")
    return " ".join(said)


def action_failed(name: str, why: str) -> str:
    return f"“{name}” didn't run: {why}. Nothing changed." if why.strip() else f"“{name}” didn't run: you aren't allowed to switch that. Nothing changed."


def suggestion_progress(taps: int, days: int, need_taps: int, need_days: int, promoted: bool, was_quick: bool) -> str:
    """What a tap did for a suggestion's standing, in a few words. Nothing for a quick action: it's already one."""
    if promoted:
        return "You keep using this one, so it's a quick action now: it stays under the chat."
    if was_quick:
        return ""
    if taps < need_taps:
        left = need_taps - taps
        return f"Use it {left} more time{'s' if left != 1 else ''} and it stays under the chat as a quick action."
    if days < need_days:
        return "Use it on another day and it stays under the chat as a quick action."
    return ""


def suggestion_tapped(name: str) -> str:
    return f"Run \u201c{name}\u201d"


def suggestion_kept(name: str) -> str:
    return (
        f"“{name}” runs by itself from now on. To take it back, say “undo that routine” or remove it under "
        "Settings → Automations."
    )


def suggestion_dismissed(name: str) -> str:
    return f"Removed “{name}”. I won't suggest it again."


# --- what a chat turn may draw on (websocket_api.py): the model reads these, a household never does -----

def scope_reply(title: str) -> str:
    named = f" (“{title}”)" if title else ""
    return (
        f"\n\nThis message is a reply inside one of this person's conversations with you{named}. Answer within "
        "that conversation. If it asks about something they said in another conversation, read it with "
        "chat_history first."
    )


def scope_all(rows: list[dict[str, Any]]) -> str:
    """A new conversation: the person's other recent ones, so a message about all of them can be answered."""
    if not rows:
        return "\n\nThis message starts a new conversation. The person has no other conversations with you yet."
    lines = []
    for row in rows:
        said = " / ".join(f"{'They' if m['who'] == 'you' else 'You'}: {m['text']}" for m in row["said"])
        lines.append(f"- “{row['title'] or 'Untitled'}”{(' (' + row['when'] + ')') if row.get('when') else ''}: {said}")
    return (
        "\n\nThis message starts a new conversation. These are this person's other recent conversations with you, "
        "newest first. Each is separate from this one: draw on them only when the message is about them (\"what "
        "did we talk about\", \"that thing from earlier\"), and read chat_history for anything older or in full.\n"
        + "\n".join(lines)
    )


def export_text(threads: list[dict[str, Any]], person: str, agent: str = "Console") -> str:
    """Conversations as plain text to copy or keep: each with its title and date, then who said what."""
    parts = []
    for thread in threads:
        made = (thread.get("made") or "")[:10]
        head = f"{thread.get('title') or 'Conversation'}" + (f" ({made})" if made else "")
        said = [f"{person if m.get('who') == 'you' else agent}: {m.get('text') or ''}" for m in thread["messages"]]
        parts.append(head + "\n" + "-" * min(len(head), 60) + "\n" + "\n\n".join(said))
    return "\n\n\n".join(parts) + ("\n" if parts else "")


TAP_STEP = ("Ran at home", "A tap on a suggestion: no AI, no internet.")
CHAT_BUSY = "Console is still answering in this chat. Wait for it to finish, or start a new chat."


# --- AI features (features.py): what each is for, what it tends to cost, what off means ---------------

FEATURES_ABOUT = (
    "Each thing Console does with AI has its own switch here. One credit is one cent of AI use. What a feature "
    "tends to cost is a guide; what it used this month is counted on this box."
)
COST_LEVELS = {"none": "Free", "low": "Low", "medium": "Medium", "high": "High"}
FEATURES = {
    "agent": {
        "name": "Cloud agent in chat, voice and Assist",
        "what": (
            "Answers what Home Assistant's own agent can't: questions about the house, requests that take several "
            "steps, music, routines and dashboards. Plain commands like “turn off the kitchen lights” are tried at "
            "home first and cost nothing."
        ),
        "cost": (
            "Low for each request, and it adds up with use: about a twentieth of a credit for a plain request, a few "
            "tenths for a long one that takes several steps. This is where most of a month's credits go."
        ),
        "off": (
            "Off: only plain commands are answered. Anything else gets a reply saying the cloud agent is switched "
            "off. Claude through the connector isn't affected."
        ),
    },
    "pro": {
        "name": "Stronger model for hard requests",
        "what": (
            "When the first model fails, or says a request needs careful multi-step work, a stronger and slower "
            "model starts the request again."
        ),
        "cost": (
            "High for each request it takes, and rare: the stronger model costs more for the same words, and the "
            "first model's attempt is paid for too."
        ),
        "off": (
            "Off: the first model handles everything by itself. A request it can't finish ends with a plain "
            "“I didn't finish that” instead of being tried again."
        ),
    },
    "suggestions": {
        "name": "Suggested routines",
        "what": (
            "Console listens to the house. Every hour the cloud agent checks what the house heard (a door opened or "
            "someone came home, and a light was switched by hand right after), and every Monday at 3 AM it reads "
            "how the house was used. It suggests up to 3 routines: each is a real automation, switched off, that "
            "shows as a suggestion in the chat. Tapped twice, it runs by itself from then on."
        ),
        "cost": "Medium: a short request every hour, and one long one a week. Flash only, with thinking off.",
        "off": (
            "Off: the chat still has its suggestions, made at home for free. Only the routines the cloud agent "
            "writes stop arriving."
        ),
    },
    "style": {
        "name": "Weekly reply style",
        "what": (
            "Every Sunday morning the cloud agent rereads how each person writes to it and updates a note, so its "
            "replies keep matching them: short when you're short, casual when you're casual."
        ),
        "cost": (
            "Medium, once a week for each person with enough chat: one long request that reads up to 200 of their "
            "own messages."
        ),
        "off": "Off: the note it already has is still followed. It just isn't updated.",
    },
    "chips": {
        "name": "Suggestions and quick actions in chat",
        "what": (
            "Three things to tap in the chat, made on this box from what's on and how the house is used. The ones "
            "you keep using stay under the chat as quick actions."
        ),
        "cost": "Free. They're made at home with no AI, and a tap runs at home.",
        "off": "Off: the chat shows no suggestions and no quick actions. Nothing is forgotten; they're back when this is on.",
    },
}


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
