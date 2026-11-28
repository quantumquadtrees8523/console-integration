"""Console's own tools for AI agents, beside Sunrise's: one LLM API ("console").

`dashboard` makes, changes and removes dashboards. Home Assistant has no action for that, so without this
tool an agent can't do "add a dashboard for the kids' room". op=create builds one the same way the Home
dashboard is (dashboard.py); op=get/check/save let the agent write the whole config itself, every save undoable.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import probatio as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

from . import dashboard, music
from .const import DOMAIN, NAME

API_ID = DOMAIN

PROMPT = (
    "Console's tools: `music` is for anything about music and speakers: search the household's music "
    "services, read their playlists and library, play by name or uri on a room's speaker, show the queue, "
    "move it to another room, pause, skip, seek and set volume. For a request like \"play X by Y in the kitchen "
    "at 60\", call it once with op=play, what, artist, room and volume; search first only when the name is "
    "unclear, then play the result's uri. `dashboard` makes a quick dashboard for rooms or things the person names "
    "(op=create), and for anything richer (a map of where people and devices are, graphs, conditional cards) "
    "reads, dry-runs and writes a whole dashboard config (op=get, check, save; op=undo puts it back). `about` returns "
    "Console's own facts (versions, the plan and credits, the off switches, what this chat can and can't do): "
    "call it before answering a question about Console itself. `chat_history` reads the person's own "
    "earlier messages in Console's chat (theirs only, read-only): use it for the match-my-style skill or "
    "when they ask about something they said before."
)


def music_players(hass: HomeAssistant) -> list[dict[str, Any]]:
    return music.players(hass)


class MusicTool(llm.Tool):
    integration = DOMAIN
    name = "music"
    title = "Music and speakers"
    description = (
        "Search, browse and play music through Music Assistant (Spotify and the household's other music "
        "services), and control the speakers. op=speakers lists them. op=search needs query (optional artist, "
        "kind). op=library lists the household's own playlists, albums, artists or tracks (kind; optional "
        "query, favorites). op=play needs what (a name or a uri) and room; optional artist, album, kind, "
        "volume 0-100, mode (play, replace, next, add) and radio=true for more like it. op=queue needs room. "
        "op=move needs room and to. op=control needs room and action (pause, resume, stop, next, previous, "
        "shuffle_on, shuffle_off, repeat_off, repeat_all, repeat_one, mute, unmute, volume with volume, seek "
        "with seconds). Play and move answer CHECKED when the speaker is really playing."
    )
    parameters = vol.Schema(
        {
            vol.Required("op", description="speakers, search, library, play, queue, move or control"): vol.In(
                ["speakers", "search", "library", "play", "queue", "move", "control"]
            ),
            vol.Optional("query", description="what to search for"): str,
            vol.Optional("what", description="what to play: a name, or a uri from search or library"): str,
            vol.Optional("artist"): str,
            vol.Optional("album"): str,
            vol.Optional("kind", description="track, album, artist, playlist, radio, podcast or audiobook"): str,
            vol.Optional("room", description="the speaker, by its room or name"): str,
            vol.Optional("to", description="the speaker to move the music to"): str,
            vol.Optional("volume", description="0 to 100"): vol.Coerce(int),
            vol.Optional("mode", description="play, replace, next or add"): str,
            vol.Optional("radio", description="keep playing similar music afterwards"): bool,
            vol.Optional("favorites", description="only favorites, for op=library"): bool,
            vol.Optional("action", description="for op=control"): str,
            vol.Optional("seconds", description="for action=seek"): vol.Coerce(int),
        }
    )
    annotations = llm.ToolAnnotations(read_only=False, destructive=False, idempotent=False, open_world=True)

    async def async_call(self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext) -> llm.ToolResult:
        try:
            return llm.ToolResult(data=await music.run(hass, dict(tool_input.tool_args or {})), error=False)
        except music.Refused as error:
            return llm.ToolResult(data={"error": str(error)}, error=False)


class AboutTool(llm.Tool):
    integration = DOMAIN
    name = "about"
    title = "About Console"
    description = (
        "Console's own facts, read live: versions, the plan and this month's credits, the two off switches, "
        "support mode, the relay's address, which tools and music services this house has, and what this "
        "chat can't do and hands to Claude Code. Call it before answering anything about Console itself."
    )
    parameters = vol.Schema({})
    annotations = llm.ToolAnnotations(read_only=True, destructive=False, idempotent=True, open_world=False)

    async def async_call(self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext) -> llm.ToolResult:
        from . import about  # noqa: PLC0415

        return llm.ToolResult(data=await about.facts(hass), error=False)


class DashboardTool(llm.Tool):
    integration = DOMAIN
    name = "dashboard"
    title = "Make, change or remove a dashboard"
    description = (
        "Home Assistant dashboards. op=list: every dashboard (title, url, mode). Quick layout: op=create needs a "
        "title and rooms and/or entity_ids and builds tiles for the things exposed to Assist; op=remove takes a "
        "title Console made. Anything richer (map, history-graph, statistics-graph, gauge, conditional, stacks, "
        "markdown, sections, badges, installed custom: cards): op=get reads a dashboard's full Lovelace config by "
        "url or title; op=check is the dry run of a config, saving nothing; op=save writes a whole config to the "
        "dashboard at url, or to a new one named title, and returns change_id; op=undo with change_id puts back "
        "what that save replaced. Get before you change an existing one, then save the whole edited config. "
        "Use only entity ids that exist (from house_map); a map needs things with a location (person.*, "
        "device_tracker.*, zone.*)."
    )
    parameters = vol.Schema(
        {
            vol.Required("op", description="list, create, remove, get, check, save or undo"): vol.In(
                ["create", "list", "remove", "get", "check", "save", "undo"]
            ),
            vol.Optional("title", description="the dashboard's name, e.g. Kids' room"): str,
            vol.Optional("url", description="an existing dashboard's address, e.g. /console-home or /lovelace"): str,
            vol.Optional("rooms", description="room names whose things go on it, for op=create"): [str],
            vol.Optional("entity_ids", description="extra things to show, by entity id, for op=create"): [str],
            vol.Optional("config", description="the whole Lovelace config, {views: [...]}, for check and save"): dict,
            vol.Optional("change_id", description="from op=save, for op=undo"): str,
        }
    )
    annotations = llm.ToolAnnotations(read_only=False, destructive=True, idempotent=False, open_world=False)

    async def async_call(self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext) -> llm.ToolResult:
        args = dict(tool_input.tool_args or {})
        data = hass.data[DOMAIN]
        op = args.get("op")
        if op != "list" and not await _admin(hass, llm_context):
            return llm.ToolResult(data={"error": "Only a Home Assistant administrator's agent can read or change dashboards."}, error=False)
        title, url = str(args.get("title") or ""), str(args.get("url") or "")
        try:
            if op == "list":
                result: dict[str, Any] = {"dashboards": dashboard.all_dashboards(hass, data)}
            elif op == "create":
                result = await dashboard.make(hass, data, title, list(args.get("rooms") or []), list(args.get("entity_ids") or []))
            elif op == "remove":
                result = await dashboard.unmake(hass, data, title)
            elif op == "get":
                result = await dashboard.get(hass, data, url, title)
            elif op == "check":
                result = dashboard.check(hass, args.get("config"))
            elif op == "save":
                result = await dashboard.save(hass, data, url, title, args.get("config"))
            else:
                result = await dashboard.undo(hass, data, str(args.get("change_id") or ""))
        except dashboard.Refused as error:
            result = {"error": str(error)}
        return llm.ToolResult(data=result, error=False)


HISTORY_MAX = 200


class ChatHistoryTool(llm.Tool):
    """The asking person's own chat with Console, read-only. The same messages the chat card already
    gives the model as earlier context; never another person's, and nothing for a turn with no one
    signed in (a pipeline, an automation)."""

    integration = DOMAIN
    name = "chat_history"
    title = "Read my chat with Console"
    description = (
        "The signed-in person's own earlier messages in Console's chat and Console's replies, across all their "
        "conversations, oldest first: each with when, who (you or console), the text, and the conversation it "
        "is in (its title and thread_id). Only theirs, never another household member's. limit is how many of "
        "the newest messages (at most 200); days keeps only the last N days; thread_id keeps one conversation."
    )
    parameters = vol.Schema(
        {
            vol.Optional("limit", description="how many of the newest messages, at most 200"): vol.Coerce(int),
            vol.Optional("days", description="only messages from the last N days"): vol.Coerce(int),
            vol.Optional("thread_id", description="only this conversation"): str,
        }
    )
    annotations = llm.ToolAnnotations(read_only=True, destructive=False, idempotent=True, open_world=False)

    async def async_call(self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext) -> llm.ToolResult:
        args = dict(tool_input.tool_args or {})
        user_id = llm_context.context.user_id if llm_context.context else None
        if not user_id:
            return llm.ToolResult(data={"error": "Only a signed-in person's own chat can be read, and nobody is signed in to this turn."}, error=False)
        limit = max(1, min(int(args.get("limit") or HISTORY_MAX), HISTORY_MAX))
        messages = hass.data[DOMAIN].history.everything(user_id)
        if args.get("thread_id"):
            messages = [m for m in messages if m.get("thread_id") == args["thread_id"]]
        messages = messages[-limit:]
        if args.get("days"):
            since = datetime.now(UTC) - timedelta(days=max(1, int(args["days"])))
            messages = [m for m in messages if _when(m.get("at")) >= since]
        out = [{"at": m.get("at"), "who": m.get("who"), "text": m.get("text"), "conversation": m.get("conversation"),
                "thread_id": m.get("thread_id")} for m in messages]
        return llm.ToolResult(
            data={"messages": out, "count": len(out), "yours": sum(1 for m in out if m["who"] == "you")}, error=False
        )


def _when(at: Any) -> datetime:
    try:
        when = datetime.fromisoformat(str(at))
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    return when if when.tzinfo else when.replace(tzinfo=UTC)


async def _admin(hass: HomeAssistant, llm_context: llm.LLMContext) -> bool:
    """A signed-in person must be an administrator; Home Assistant's own pipelines (no user) may not
    change dashboards at all."""
    user_id = llm_context.context.user_id if llm_context.context else None
    user = await hass.auth.async_get_user(user_id) if user_id else None
    return bool(user and user.is_admin)


class ConsoleAPI(llm.API):
    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(hass=hass, id=API_ID, name=NAME)

    async def async_get_api_instance(self, llm_context: llm.LLMContext) -> llm.APIInstance:
        return llm.APIInstance(api=self, api_prompt=PROMPT, llm_context=llm_context, tools=[MusicTool(), DashboardTool(), AboutTool(), ChatHistoryTool()])
