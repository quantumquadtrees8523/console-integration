"""Music by chat: search, the household's own playlists and library, play by name on a room's speaker,
the queue, moving it between rooms, and the usual controls.

It works through Music Assistant, which holds the household's music services (Spotify and the rest) and
knows each speaker once. Every call here is a local Home Assistant action; nothing in this file talks to
the internet. A room's speaker is always Music Assistant's player for it, never a second copy of the
same speaker from another integration.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

MA = "music_assistant"
KINDS = ("track", "album", "artist", "playlist", "radio", "podcast", "audiobook")
WAIT_S = 8.0
CONTROLS = {
    "pause": ("media_pause", {}),
    "resume": ("media_play", {}),
    "stop": ("media_stop", {}),
    "next": ("media_next_track", {}),
    "previous": ("media_previous_track", {}),
    "shuffle_on": ("shuffle_set", {"shuffle": True}),
    "shuffle_off": ("shuffle_set", {"shuffle": False}),
    "repeat_off": ("repeat_set", {"repeat": "off"}),
    "repeat_all": ("repeat_set", {"repeat": "all"}),
    "repeat_one": ("repeat_set", {"repeat": "one"}),
    "mute": ("volume_mute", {"is_volume_muted": True}),
    "unmute": ("volume_mute", {"is_volume_muted": False}),
}


SPOTIFY_URI = re.compile(r"^spotify(?:--[\w-]+)?://(track|album|playlist|artist|show|episode)/([A-Za-z0-9]+)")
ACTIVE = ("playing", "paused", "buffering")
VIA_TWIN = (
    "Music Assistant found this but couldn't stream it from Spotify, so it is playing through the speaker's "
    "own Spotify link instead. Search and playlists still come from Music Assistant. To make Music Assistant "
    "itself play Spotify, its Spotify settings need attention (Music Assistant > Settings > Music sources)."
)


class Refused(ValueError):
    """Not something the music tool can do as asked; the words are for the model to pass on."""


def _exposed(hass: HomeAssistant, entity_id: str) -> bool:
    from homeassistant.components.homeassistant.exposed_entities import async_should_expose  # noqa: PLC0415

    return async_should_expose(hass, "conversation", entity_id)


def entry_id(hass: HomeAssistant) -> str | None:
    loaded = [e for e in hass.config_entries.async_entries(MA) if e.state.name == "LOADED"]
    return loaded[0].entry_id if loaded else None


def players(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Music Assistant's speakers that the owner exposed to Assist, one per room."""
    found = []
    for entry in er.async_get(hass).entities.values():
        if entry.platform != MA or entry.domain != "media_player" or entry.disabled:
            continue
        state = hass.states.get(entry.entity_id)
        if state is None or not _exposed(hass, entry.entity_id):
            continue
        attrs = state.attributes
        volume = attrs.get("volume_level")
        shown = state.state
        if shown not in ACTIVE:  # the other copy of this speaker may be the one with music on it
            twin = _twin(hass, {"name": state.name})
            other = hass.states.get(twin) if twin else None
            if other is not None and other.state in ACTIVE:
                shown, attrs = other.state, other.attributes
        found.append(
            {
                "name": state.name,
                "id": entry.entity_id,
                "state": shown,
                "volume": round(volume * 100) if isinstance(volume, int | float) else None,
                "playing": " - ".join(str(x) for x in (attrs.get("media_artist"), attrs.get("media_title")) if x) or None,
            }
        )
    return sorted(found, key=lambda p: p["name"].lower())


def _twin(hass: HomeAssistant, player: dict[str, Any]) -> str | None:
    """The same speaker as another integration shows it (say, the speaker maker's own), if there is one:
    a media player with the same name that isn't Music Assistant's and isn't a music service's own entity."""
    for entry in er.async_get(hass).entities.values():
        if entry.domain != "media_player" or entry.platform in (MA, "spotify") or entry.disabled:
            continue
        state = hass.states.get(entry.entity_id)
        if state is not None and state.name.strip().lower() == player["name"].strip().lower() and state.state != "unavailable":
            return entry.entity_id
    return None


def _spotify_entry(hass: HomeAssistant) -> str | None:
    loaded = [e for e in hass.config_entries.async_entries("spotify") if e.state.name == "LOADED"]
    return loaded[0].entry_id if loaded else None


def _controls(hass: HomeAssistant, player: dict[str, Any]) -> str:
    """Which copy of the speaker to send pause, skip and volume to: Music Assistant's, unless the other
    copy is the one with music on it right now."""
    twin = _twin(hass, player)
    ours = hass.states.get(player["id"])
    theirs = hass.states.get(twin) if twin else None
    if theirs is not None and theirs.state in ACTIVE and (ours is None or ours.state not in ACTIVE):
        return twin
    return player["id"]


async def _first_uri(hass: HomeAssistant, config_entry: str, args: dict[str, Any]) -> str | None:
    """A name turned into something playable: the best match from search."""
    data: dict[str, Any] = {"config_entry_id": config_entry, "name": str(args.get("what") or "")}
    if args.get("artist"):
        data["artist"] = args["artist"]
    if args.get("album"):
        data["album"] = args["album"]
    if args.get("kind") in KINDS:
        data["media_type"] = [args["kind"]]
    found = await _ask(hass, "search", data)
    order = [f"{args['kind']}s"] if args.get("kind") in KINDS else ["tracks", "albums", "playlists", "artists"]
    for kind in order:
        for item in (found or {}).get(kind) or []:
            if isinstance(item, dict) and item.get("uri"):
                return str(item["uri"])
    return None


async def _play_on_twin(hass: HomeAssistant, player: dict[str, Any], uri: str) -> dict[str, Any] | None:
    """Play a Spotify item on the speaker's other copy, through Home Assistant's own Spotify link."""
    match, twin, spotify = SPOTIFY_URI.match(uri or ""), _twin(hass, player), _spotify_entry(hass)
    if not match or not twin or not spotify:
        return None
    kind, item = match.group(1), match.group(2)
    try:
        await hass.services.async_call(
            "media_player",
            "play_media",
            {
                "entity_id": twin,
                "media_content_id": f"spotify://{spotify.lower()}/spotify:{kind}:{item}",
                "media_content_type": f"spotify://{kind}",
            },
            blocking=True,
        )
    except HomeAssistantError:
        return None
    now = await _now(hass, {"id": twin, "name": player["name"]}, want_playing=True)
    now["result"] = "CHECKED" if now["state"] == "playing" else "NOT CONFIRMED"
    now["note"] = VIA_TWIN
    return now


def _player(hass: HomeAssistant, room: str) -> dict[str, Any]:
    wanted = (room or "").strip().lower()
    every = players(hass)
    if not every:
        raise Refused("No Music Assistant speaker is exposed to Assist, so there's nothing to play on.")
    if not wanted:
        if len(every) == 1:
            return every[0]
        raise Refused(f"Which speaker? The speakers are: {', '.join(p['name'] for p in every)}.")
    exact = [p for p in every if wanted in (p["name"].lower(), p["id"].lower())]
    close = exact or [p for p in every if wanted in p["name"].lower() or p["name"].lower() in wanted]
    if len(close) != 1:
        raise Refused(f"There's no single speaker called {room}. The speakers are: {', '.join(p['name'] for p in every)}.")
    if close[0]["state"] == "unavailable":
        raise Refused(f"The {close[0]['name']} speaker is unreachable right now.")
    return close[0]


def _item(raw: dict[str, Any]) -> dict[str, Any]:
    item: dict[str, Any] = {"name": raw.get("name"), "uri": raw.get("uri")}
    artists = [a.get("name") for a in raw.get("artists") or [] if isinstance(a, dict) and a.get("name")]
    if artists:
        item["artists"] = ", ".join(artists[:3])
    album = raw.get("album")
    if isinstance(album, dict) and album.get("name"):
        item["album"] = album["name"]
    if raw.get("version"):
        item["version"] = raw["version"]
    return item


def _lists(answer: Any, limit: int) -> dict[str, list[dict[str, Any]]]:
    """Music Assistant's answer, cut down to names and the uri to play each by."""
    out: dict[str, list[dict[str, Any]]] = {}
    if isinstance(answer, dict) and isinstance(answer.get("items"), list):
        answer = {"items": answer["items"]}
    for kind, rows in (answer or {}).items():
        if isinstance(rows, list) and rows:
            out[kind] = [_item(r) for r in rows[:limit] if isinstance(r, dict)]
    return out


async def _ask(hass: HomeAssistant, service: str, data: dict[str, Any], target: str | None = None) -> Any:
    try:
        return await hass.services.async_call(
            MA, service, data, blocking=True, return_response=True, target={"entity_id": [target]} if target else None
        )
    except HomeAssistantError as error:
        raise Refused(f"Music Assistant refused: {error}") from error


async def _now(hass: HomeAssistant, player: dict[str, Any], want_playing: bool = False) -> dict[str, Any]:
    """The speaker as it is now, waiting a few seconds for a change to show."""
    deadline = asyncio.get_running_loop().time() + (WAIT_S if want_playing else 1.0)
    while True:
        state = hass.states.get(player["id"])
        if state is None:
            return {"speaker": player["name"], "state": "gone"}
        playing = state.state == "playing"
        if not want_playing or playing or asyncio.get_running_loop().time() > deadline:
            attrs = state.attributes
            volume = attrs.get("volume_level")
            return {
                "speaker": state.name,
                "state": state.state,
                "title": attrs.get("media_title"),
                "artist": attrs.get("media_artist"),
                "album": attrs.get("media_album_name"),
                "volume": round(volume * 100) if isinstance(volume, int | float) else None,
                "shuffle": attrs.get("shuffle"),
                "repeat": attrs.get("repeat"),
            }
        await asyncio.sleep(0.4)


async def run(hass: HomeAssistant, args: dict[str, Any]) -> dict[str, Any]:
    op = args.get("op")
    if op == "speakers":
        return {"speakers": players(hass)}
    config_entry = entry_id(hass)
    if config_entry is None:
        raise Refused(
            "Music Assistant isn't set up in this Home Assistant, so music can't be searched or played by "
            "name from here. It is added under Settings > Devices & services."
        )

    if op == "search":
        query = str(args.get("query") or "").strip()
        if not query:
            raise Refused("Say what to search for in query.")
        data: dict[str, Any] = {"config_entry_id": config_entry, "name": query}
        if args.get("artist"):
            data["artist"] = args["artist"]
        if args.get("kind") in KINDS:
            data["media_type"] = [args["kind"]]
        found = _lists(await _ask(hass, "search", data), 6)
        return {"found": found} if found else {"found": {}, "note": "Nothing matched. Try fewer words, or the artist in artist."}

    if op == "library":
        kind = args.get("kind") if args.get("kind") in KINDS else "playlist"
        data = {"config_entry_id": config_entry, "media_type": kind}
        if args.get("query"):
            data["search"] = args["query"]
        if args.get("favorites"):
            data["favorite"] = True
        return {"kind": kind, "library": _lists(await _ask(hass, "get_library", data), 40)}

    if op == "queue":
        player = _player(hass, str(args.get("room") or ""))
        answer = await _ask(hass, "get_queue", {}, player["id"])
        queue = (answer or {}).get(player["id"]) if isinstance(answer, dict) else None
        if not isinstance(queue, dict):
            return {"speaker": player["name"], "queue": None}
        keep = ("state", "shuffle_enabled", "repeat_mode", "items", "current_index", "elapsed_time")
        out = {k: queue.get(k) for k in keep if k in queue}
        for slot in ("current_item", "next_item"):
            item = queue.get(slot)
            if isinstance(item, dict):
                media = item.get("media_item") if isinstance(item.get("media_item"), dict) else {}
                out[slot] = {"name": item.get("name") or media.get("name"), "uri": media.get("uri")}
        return {"speaker": player["name"], "queue": out}

    if op == "play":
        what = str(args.get("what") or "").strip()
        if not what:
            raise Refused("Say what to play in what: a name, or a uri from search or library.")
        player = _player(hass, str(args.get("room") or ""))
        volume = args.get("volume")
        learned = None
        if volume is None:  # no level asked for: the one this household wants this speaker at, if it has one (prefs.py)
            prefs = getattr(hass.data.get(DOMAIN), "prefs", None)
            learned = prefs.level(player["id"], "volume") if prefs is not None else None
            volume = learned
        if volume is not None:
            level = max(0, min(100, int(volume))) / 100
            await hass.services.async_call("media_player", "volume_set", {"entity_id": player["id"], "volume_level": level}, blocking=True)
        data = {"media_id": what}
        for ours, theirs in (("artist", "artist"), ("album", "album")):
            if args.get(ours):
                data[theirs] = args[ours]
        if args.get("kind") in KINDS:
            data["media_type"] = args["kind"]
        if args.get("mode") in ("play", "replace", "next", "replace_next", "add"):
            data["enqueue"] = args["mode"]
        if args.get("radio"):
            data["radio_mode"] = True
        try:
            await hass.services.async_call(MA, "play_media", data, blocking=True, target={"entity_id": [player["id"]]})
        except HomeAssistantError as error:
            # Found but not streamable (a music service that lets Music Assistant search but not play):
            # try the same speaker's own link to that service before giving up.
            uri = what if SPOTIFY_URI.match(what) else await _first_uri(hass, config_entry, args)
            via_twin = await _play_on_twin(hass, player, uri) if uri else None
            if via_twin is not None:
                return via_twin
            raise Refused(
                f"Music Assistant couldn't play that: {error}. It found the item but its music service didn't "
                "let it stream, and this speaker has no other link to that service to fall back on."
            ) from error
        now = await _now(hass, player, want_playing=True)
        if now["state"] != "playing":
            uri = what if SPOTIFY_URI.match(what) else await _first_uri(hass, config_entry, args)
            via_twin = await _play_on_twin(hass, player, uri) if uri else None
            if via_twin is not None:
                return via_twin
        now["result"] = "CHECKED" if now["state"] == "playing" else "NOT CONFIRMED"
        if learned is not None:
            now["volume_from"] = f"the {learned}% this household wants this speaker at (learned)"
        return now

    if op == "move":
        source = _player(hass, str(args.get("room") or ""))
        target = _player(hass, str(args.get("to") or ""))
        if source["id"] == target["id"]:
            raise Refused("That's the same speaker.")
        playing_on, other = _controls(hass, source), _twin(hass, target)
        if playing_on != source["id"] and other:
            # The music is on the speakers' other copies: group the target in, then drop the source out.
            try:
                await hass.services.async_call("media_player", "join", {"entity_id": playing_on, "group_members": [other]}, blocking=True)
                await asyncio.sleep(1.5)
                await hass.services.async_call("media_player", "unjoin", {"entity_id": playing_on}, blocking=True)
            except HomeAssistantError as error:
                raise Refused(f"The speakers couldn't hand the music over: {error}") from error
            now = await _now(hass, {"id": other, "name": target["name"]}, want_playing=True)
            now["result"] = "CHECKED" if now["state"] == "playing" else "NOT CONFIRMED"
            return now | {"moved_from": source["name"]}
        await _ask_plain(hass, "transfer_queue", {"source_player": source["id"], "auto_play": True}, target["id"])
        now = await _now(hass, target, want_playing=True)
        now["result"] = "CHECKED" if now["state"] == "playing" else "NOT CONFIRMED"
        return now | {"moved_from": source["name"]}

    if op == "control":
        player = _player(hass, str(args.get("room") or ""))
        action = str(args.get("action") or "")
        if action == "volume":
            if args.get("volume") is None:
                raise Refused("Give the volume as a number from 0 to 100.")
            level = max(0, min(100, int(args["volume"]))) / 100
            service, data = "volume_set", {"volume_level": level}
        elif action == "seek":
            service, data = "media_seek", {"seek_position": max(0, int(args.get("seconds") or 0))}
        elif action in CONTROLS:
            service, data = CONTROLS[action]
        else:
            raise Refused(f"action is one of: {', '.join([*CONTROLS, 'volume', 'seek'])}.")
        where = _controls(hass, player)
        try:
            await hass.services.async_call("media_player", service, {"entity_id": where, **data}, blocking=True)
        except HomeAssistantError as error:
            raise Refused(f"The {player['name']} speaker refused: {error}") from error
        await asyncio.sleep(0.6)
        return await _now(hass, {"id": where, "name": player["name"]})

    raise Refused("op is one of: speakers, search, library, play, queue, move, control.")


async def _ask_plain(hass: HomeAssistant, service: str, data: dict[str, Any], target: str) -> None:
    try:
        await hass.services.async_call(MA, service, data, blocking=True, target={"entity_id": [target]})
    except HomeAssistantError as error:
        raise Refused(f"Music Assistant refused: {error}") from error
