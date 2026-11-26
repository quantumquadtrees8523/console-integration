"""Music by chat: search, the household's own playlists and library, play by name on a room's speaker,
the queue, moving it between rooms, and the usual controls.

It works through Music Assistant, which holds the household's music services (Spotify and the rest) and
knows each speaker once. Every call here is a local Home Assistant action; nothing in this file talks to
the internet. A room's speaker is always Music Assistant's player for it, never a second copy of the
same speaker from another integration.
"""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

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
        found.append(
            {
                "name": state.name,
                "id": entry.entity_id,
                "state": state.state,
                "volume": round(volume * 100) if isinstance(volume, int | float) else None,
                "playing": " - ".join(str(x) for x in (attrs.get("media_artist"), attrs.get("media_title")) if x) or None,
            }
        )
    return sorted(found, key=lambda p: p["name"].lower())


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
        if args.get("volume") is not None:
            level = max(0, min(100, int(args["volume"]))) / 100
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
            raise Refused(f"Music Assistant couldn't play that: {error}. Search first and play a result's uri.") from error
        now = await _now(hass, player, want_playing=True)
        now["result"] = "CHECKED" if now["state"] == "playing" else "NOT CONFIRMED"
        return now

    if op == "move":
        source = _player(hass, str(args.get("room") or ""))
        target = _player(hass, str(args.get("to") or ""))
        if source["id"] == target["id"]:
            raise Refused("That's the same speaker.")
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
        try:
            await hass.services.async_call("media_player", service, {"entity_id": player["id"], **data}, blocking=True)
        except HomeAssistantError as error:
            raise Refused(f"The {player['name']} speaker refused: {error}") from error
        await asyncio.sleep(0.6)
        return await _now(hass, player)

    raise Refused("op is one of: speakers, search, library, play, queue, move, control.")


async def _ask_plain(hass: HomeAssistant, service: str, data: dict[str, Any], target: str) -> None:
    try:
        await hass.services.async_call(MA, service, data, blocking=True, target={"entity_id": [target]})
    except HomeAssistantError as error:
        raise Refused(f"Music Assistant refused: {error}") from error
