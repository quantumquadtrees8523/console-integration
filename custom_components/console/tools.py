"""Console's own tools for AI agents, beside Sunrise's: one LLM API ("console").

`dashboard` makes, lists and removes dashboards. Home Assistant has no action for that, so without this
tool an agent can't do "add a dashboard for the kids' room". The dashboard is built the same way the
Home dashboard is (dashboard.py): from the things the owner exposed, lights first, no guessing.
"""

from __future__ import annotations

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
    "unclear, then play the result's uri. `dashboard` makes a dashboard for rooms or things the person names "
    "(op=create), lists the ones made this way (op=list) and removes one (op=remove). `about` returns "
    "Console's own facts (versions, the plan and credits, the off switches, what this chat can and can't do): "
    "call it before answering a question about Console itself."
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
    title = "Make or remove a dashboard"
    description = (
        "Make a Home Assistant dashboard for some rooms or things, list the dashboards made this way, or remove "
        "one. op=create needs a title and rooms (room names) and/or entity_ids; it shows only things the owner "
        "exposed to Assist. Creating again with the same title rebuilds that dashboard. op=remove needs the title."
    )
    parameters = vol.Schema(
        {
            vol.Required("op", description="create, list or remove"): vol.In(["create", "list", "remove"]),
            vol.Optional("title", description="the dashboard's name, e.g. Kids' room"): str,
            vol.Optional("rooms", description="room names whose things go on it"): [str],
            vol.Optional("entity_ids", description="extra things to show, by entity id"): [str],
        }
    )
    annotations = llm.ToolAnnotations(read_only=False, destructive=True, idempotent=True, open_world=False)

    async def async_call(self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext) -> llm.ToolResult:
        args = dict(tool_input.tool_args or {})
        data = hass.data[DOMAIN]
        if args.get("op") != "list" and not await _admin(hass, llm_context):
            return llm.ToolResult(data={"error": "Only a Home Assistant administrator's agent can change dashboards."}, error=False)
        try:
            if args["op"] == "list":
                result: dict[str, Any] = {"dashboards": dashboard.made(data)}
            elif args["op"] == "create":
                result = await dashboard.make(
                    hass, data, str(args.get("title") or ""), list(args.get("rooms") or []), list(args.get("entity_ids") or [])
                )
            else:
                result = await dashboard.unmake(hass, data, str(args.get("title") or ""))
        except dashboard.Refused as error:
            result = {"error": str(error)}
        return llm.ToolResult(data=result, error=False)


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
        return llm.APIInstance(api=self, api_prompt=PROMPT, llm_context=llm_context, tools=[MusicTool(), DashboardTool(), AboutTool()])
