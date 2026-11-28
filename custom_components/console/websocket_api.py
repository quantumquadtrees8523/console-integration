"""What the chat card and Console settings ask over Home Assistant's WebSocket.

Reading is for anyone signed in to Home Assistant. Changing or deleting anything is for administrators.
"""

from __future__ import annotations

import logging
from typing import Any

import probatio as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from . import backups, dashboard, features, knows, suggestions, wipe, wording
from .const import DOMAIN, PATH_CHAT, ROUTE_LOCAL
from .history import new_id
from .status import status
from .trail import LiveTurn

EARLIER = 20  # messages of a thread given to a model that starts fresh on it (after a restart, or a long pause)

_LOGGER = logging.getLogger(__name__)


@callback
def async_setup(hass: HomeAssistant) -> None:
    for command in (
        ws_status,
        ws_onboarding_offered,
        ws_knows,
        ws_memory_read,
        ws_memory_write,
        ws_memory_delete,
        ws_learned_forget,
        ws_assist_clear,
        ws_dashboard_rebuild,
        ws_support_set,
        ws_wipe,
        ws_relink,
        ws_backup_status,
        ws_backup_code,
        ws_backup_now,
        ws_chat,
        ws_chat_watch,
        ws_chat_threads,
        ws_chat_history,
        ws_chat_thread_delete,
        ws_chat_clear,
        ws_suggestions,
        ws_suggestions_set,
        ws_suggestions_run,
        ws_suggestions_seen,
        ws_suggestion_tap,
        ws_suggestion_keep,
        ws_suggestion_dismiss,
        ws_features,
        ws_features_set,
        ws_usage_paths,
    ):
        websocket_api.async_register_command(hass, command)


@websocket_api.websocket_command({vol.Required("type"): "console/status"})
@websocket_api.async_response
async def ws_status(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    data = hass.data[DOMAIN]
    answer = status(hass, data) | {"is_admin": connection.user.is_admin}
    answer["onboarding"] = await knows.onboarding(hass, data)
    connection.send_result(msg["id"], answer)


@websocket_api.websocket_command({vol.Required("type"): "console/onboarding/offered"})
@callback
def ws_onboarding_offered(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """The chat card has offered the welcome once: it won't open with the offer again."""
    data = hass.data[DOMAIN]
    data.data["onboarding"]["offered"] = True
    data.changed()
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command({vol.Required("type"): "console/knows"})
@websocket_api.async_response
async def ws_knows(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """What the house knows about the people in it."""
    answer = await knows.everything(hass, hass.data[DOMAIN])
    answer["my_chat_messages"] = hass.data[DOMAIN].history.count(connection.user.id)
    connection.send_result(msg["id"], answer)


@websocket_api.websocket_command({vol.Required("type"): "console/memory/read", vol.Required("name"): str})
@websocket_api.async_response
async def ws_memory_read(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    text = await knows.memory_read(hass, msg["name"])
    if text is None:
        connection.send_error(msg["id"], "not_found", "There's no memory file with that name.")
        return
    connection.send_result(msg["id"], {"name": msg["name"], "text": text})


@websocket_api.websocket_command(
    {vol.Required("type"): "console/memory/write", vol.Required("name"): str, vol.Required("text"): str}
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_memory_write(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    try:
        await knows.memory_write(hass, msg["name"], msg["text"])
    except Exception as error:  # noqa: BLE001 (Sunrise's own refusals are worded for the person)
        connection.send_error(msg["id"], "refused", str(error))
        return
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command({vol.Required("type"): "console/memory/delete", vol.Required("name"): str})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_memory_delete(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    try:
        await knows.memory_delete(hass, msg["name"])
    except Exception as error:  # noqa: BLE001
        connection.send_error(msg["id"], "refused", str(error))
        return
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command({vol.Required("type"): "console/learned/forget", vol.Required("sentence_id"): str})
@websocket_api.require_admin
@callback
def ws_learned_forget(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    connection.send_result(msg["id"], {"ok": hass.data[DOMAIN].learned.forget(msg["sentence_id"])})


@websocket_api.websocket_command({vol.Required("type"): "console/assist/clear"})
@websocket_api.require_admin
@callback
def ws_assist_clear(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    connection.send_result(msg["id"], {"cleared": knows.clear_assist_runs(hass)})


@websocket_api.websocket_command({vol.Required("type"): "console/dashboard/rebuild"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_dashboard_rebuild(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    connection.send_result(msg["id"], await dashboard.ensure(hass, hass.data[DOMAIN], force=True))


@websocket_api.websocket_command({vol.Required("type"): "console/support/set", vol.Required("on"): bool})
@websocket_api.require_admin
@callback
def ws_support_set(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    who = connection.user.name or "an administrator"
    connection.send_result(msg["id"], hass.data[DOMAIN].support.set(msg["on"], who))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "console/wipe",
        vol.Required("level"): vol.In(["data", "factory"]),
        vol.Required("confirm"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_wipe(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Erase Console and Sunrise data, or factory reset Home Assistant. The words must be typed."""
    try:
        if msg["level"] == "data":
            done = await wipe.erase_data(hass, msg["confirm"])
        else:
            done = await wipe.factory_reset(hass, msg["confirm"])
    except wipe.Refused as error:
        connection.send_error(msg["id"], "not_confirmed", str(error))
        return
    connection.send_result(msg["id"], done)


@websocket_api.websocket_command({vol.Required("type"): "console/relink"})
@websocket_api.require_admin
@callback
def ws_relink(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Let the relay hand this house a key again after its data was erased."""
    data = hass.data[DOMAIN]
    data.data["unlinked"] = False
    data.changed()
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command({vol.Required("type"): "console/backup/status"})
@callback
def ws_backup_status(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    connection.send_result(msg["id"], backups.status(hass))


@websocket_api.websocket_command({vol.Required("type"): "console/backup/recovery_code"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_backup_code(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """The recovery code, for an administrator to write down or download. Made here if there is none."""
    try:
        connection.send_result(msg["id"], await backups.recovery_code(hass))
    except backups.Unavailable as error:
        connection.send_error(msg["id"], "unavailable", str(error))


@websocket_api.websocket_command({vol.Required("type"): "console/backup/now"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_backup_now(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    try:
        connection.send_result(msg["id"], await backups.backup_now(hass))
    except backups.Unavailable as error:
        connection.send_error(msg["id"], "unavailable", str(error))
    except Exception as error:  # noqa: BLE001 (Home Assistant's own reason, e.g. a backup already running)
        connection.send_error(msg["id"], "failed", str(error))


def _thread_for(data, user_id: str, asked: str | None) -> str:
    """The thread a message goes into: the one asked for when it is this person's own (or nobody's yet),
    else a new one. A thread's id is its conversation's id, so nobody can join another person's."""
    if asked and all(thread["id"] != asked for other, threads in data.history.people.items() if other != user_id for thread in threads):
        return asked
    return new_id()


@websocket_api.websocket_command(
    {
        vol.Required("type"): "console/chat",
        vol.Required("text"): str,
        vol.Optional("thread_id"): vol.Any(str, None),
        vol.Optional("conversation_id"): vol.Any(str, None),  # what the card before threads sent
        vol.Optional("earlier", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=40)),  # the same; not used
    }
)
@websocket_api.async_response
async def ws_chat(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """One turn with Console's agent in one of this person's chats, told as it happens. The answer to the
    command is the thread's id; then events follow (trail.py): steps, thinking, pieces of the reply, and at
    last `done` with the whole reply. What was said, and the steps behind the reply, go into that thread on
    the box. The turn carries on if the card goes away: a card that opens the thread meanwhile watches it
    (console/chat/watch), and one that opens it afterwards finds the reply there."""
    import time  # noqa: PLC0415

    from homeassistant.components import conversation  # noqa: PLC0415

    data = hass.data[DOMAIN]
    user_id = connection.user.id
    text = msg["text"].strip()
    thread_id = _thread_for(data, user_id, msg.get("thread_id") or msg.get("conversation_id"))

    def send(event: dict[str, Any]) -> None:
        connection.send_message(websocket_api.event_message(msg["id"], event))

    if thread_id in data.live:
        connection.send_error(msg["id"], "busy", wording.CHAT_BUSY)
        return
    live = data.live[thread_id] = LiveTurn(user_id)
    live.attach(send)
    connection.subscriptions[msg["id"]] = lambda: live.detach(send)
    connection.send_result(msg["id"], {"thread_id": thread_id, "conversation_id": thread_id})
    live.emit({"kind": "thread", "thread_id": thread_id})  # first, so a card knows which chat this is before anything else
    if not text:
        data.live.pop(thread_id, None)
        send({"kind": "done", "reply": "", "thread_id": thread_id, "conversation_id": thread_id, "error": True})
        return
    data.earlier[thread_id] = data.history.context(user_id, thread_id, EARLIER)
    data.streams[thread_id] = live.emit
    data.history.add(user_id, "you", text, thread_id)
    started = time.monotonic()
    try:
        context = connection.context(msg)
        data.via[context.id] = PATH_CHAT
        result = await conversation.async_converse(
            hass, text, thread_id, context, hass.config.language, agent_id="conversation.console"
        )
        speech = (result.response.speech.get("plain") or {}).get("speech") or ""
        failed = result.response.response_type.value == "error"
    except Exception as error:  # noqa: BLE001 (whatever went wrong, the card must hear the end of the turn)
        speech, failed = wording.MODEL_FAILED_REPLY, True
        _LOGGER.warning("Console: a chat turn failed (%s)", type(error).__name__)
    finally:
        data.streams.pop(thread_id, None)
        data.earlier.pop(thread_id, None)
        data.live.pop(thread_id, None)
        if "context" in locals():
            data.via.pop(context.id, None)
    if not speech:
        speech, failed = wording.MODEL_FAILED_REPLY, True
    ms = round((time.monotonic() - started) * 1000)
    kept = live.kept
    data.history.add(
        user_id, "console", speech, thread_id,
        failed=failed, steps=kept.steps, meta={k: kept.meta.get(k) for k in ("route", "cost_usd") if k in kept.meta} | {"ms": ms},
    )  # fmt: skip
    live.emit({"kind": "done", "reply": speech, "thread_id": thread_id, "conversation_id": thread_id, "error": failed, "ms": ms})


@websocket_api.websocket_command({vol.Required("type"): "console/chat/watch", vol.Required("thread_id"): str})
@callback
def ws_chat_watch(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Watch the turn running in one of this person's chats: everything it has done so far, then the
    rest, ending with `done`. The answer says whether a turn is running at all; when none is, one `gone`
    event follows, so a card that was waiting reads the thread again instead."""
    live = hass.data[DOMAIN].live.get(msg["thread_id"])

    def send(event: dict[str, Any]) -> None:
        connection.send_message(websocket_api.event_message(msg["id"], event))

    if live is None or live.user_id != connection.user.id:
        connection.send_result(msg["id"], {"working": False})
        send({"kind": "gone"})  # the turn ended a moment ago: the reply is in the thread
        return

    connection.subscriptions[msg["id"]] = lambda: live.detach(send)
    connection.send_result(msg["id"], {"working": True})
    live.attach(send)


@websocket_api.websocket_command({vol.Required("type"): "console/chat/threads"})
@callback
def ws_chat_threads(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """This person's chats, the one used last first."""
    data = hass.data[DOMAIN]
    rows = data.history.threads(connection.user.id)
    for row in rows:
        row["working"] = row["id"] in data.live
    connection.send_result(msg["id"], {"threads": rows})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "console/chat/history",
        vol.Optional("thread_id"): vol.Any(str, None),
        vol.Optional("before"): vol.Any(vol.Coerce(int), None),
        vol.Optional("limit", default=10): vol.All(vol.Coerce(int), vol.Range(min=1, max=50)),
    }
)
@callback
def ws_chat_history(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """One of this person's chats, a page at a time, newest page first: what was said, and with each of
    Console's replies the steps behind it. With no thread named: the chat they used last. `working` says a
    turn is running in it right now (watch it with console/chat/watch)."""
    data = hass.data[DOMAIN]
    page = data.history.page(connection.user.id, msg.get("thread_id"), msg.get("before"), msg["limit"])
    live = data.live.get(page["thread_id"])
    connection.send_result(msg["id"], page | {"working": bool(live and live.user_id == connection.user.id)})


@websocket_api.websocket_command({vol.Required("type"): "console/chat/thread/delete", vol.Required("thread_id"): str})
@callback
def ws_chat_thread_delete(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Delete one of this person's chats from the box."""
    connection.send_result(msg["id"], {"deleted": hass.data[DOMAIN].history.delete(connection.user.id, msg["thread_id"])})


@websocket_api.websocket_command({vol.Required("type"): "console/chat/clear"})
@callback
def ws_chat_clear(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Delete all of this person's chats from the box."""
    connection.send_result(msg["id"], {"deleted": hass.data[DOMAIN].history.clear(connection.user.id)})


# --- suggestions and quick actions (suggestions.py) -------------------------------------------------


@websocket_api.websocket_command({vol.Required("type"): "console/suggestions"})
@websocket_api.async_response
async def ws_suggestions(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """What the chat offers right now (`suggested`, always three, and `quick`), and for the settings
    page the suggested routines, the weekly run's setting and its last run."""
    data = hass.data[DOMAIN]
    routines = data.cloud_state() not in ("ai_off", "cloud_off")  # the tools behind a suggested routine are off
    answer = await data.suggestions.listing(admin=connection.user.is_admin, routines=routines)
    if not data.feature(features.CHIPS):
        answer["suggested"], answer["quick"] = [], []
    connection.send_result(
        msg["id"],
        answer | {"cost_note": wording.SUGGESTIONS_COST, "is_admin": connection.user.is_admin, "shown": data.feature(features.CHIPS)},
    )


@websocket_api.websocket_command({vol.Required("type"): "console/suggestions/set", vol.Required("on"): bool})
@websocket_api.require_admin
@callback
def ws_suggestions_set(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    connection.send_result(msg["id"], hass.data[DOMAIN].suggestions.set_on(msg["on"]))


@websocket_api.websocket_command({vol.Required("type"): "console/suggestions/run"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_suggestions_run(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Run the weekly suggestions now (an administrator asked, so it runs even with the setting off)."""
    try:
        connection.send_result(msg["id"], await hass.data[DOMAIN].suggestions.run(force=True))
    except suggestions.Refused as error:
        connection.send_error(msg["id"], "refused", str(error))


@websocket_api.websocket_command({vol.Required("type"): "console/suggestions/seen", vol.Required("ids"): [str]})
@websocket_api.async_response
async def ws_suggestions_seen(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """The chat showed these suggestions to someone. One seen a few times and never tapped is discarded."""
    connection.send_result(msg["id"], await hass.data[DOMAIN].suggestions.seen(msg["ids"][:12]))


@websocket_api.websocket_command(
    {vol.Required("type"): "console/suggestions/tap", vol.Required("suggestion_id"): str, vol.Optional("thread_id"): vol.Any(str, None)}
)
@websocket_api.async_response
async def ws_suggestion_tap(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Run a suggestion or a quick action once, as the person who tapped it, and put it in their chat.
    Something to ask comes back as words (`ask`) for the card to send like any message."""
    data = hass.data[DOMAIN]
    user_id = connection.user.id
    try:
        done = await data.suggestions.tap(msg["suggestion_id"], user_id)
    except suggestions.Refused as error:
        connection.send_error(msg["id"], "refused", str(error))
        return
    if done["kind"] != "ask":
        thread_id = data.history.add(user_id, "you", wording.suggestion_tapped(done["name"]), _thread_for(data, user_id, msg.get("thread_id")))
        title, detail = wording.TAP_STEP
        data.history.add(user_id, "console", done["reply"], thread_id, steps=[{"title": title, "detail": detail}], meta={"route": ROUTE_LOCAL})
        done["thread_id"] = thread_id
    connection.send_result(msg["id"], done)


@websocket_api.websocket_command({vol.Required("type"): "console/suggestions/keep", vol.Required("suggestion_id"): str})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_suggestion_keep(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Let a suggested routine run by itself from now on."""
    try:
        connection.send_result(msg["id"], await hass.data[DOMAIN].suggestions.keep(msg["suggestion_id"], connection.user.id))
    except suggestions.Refused as error:
        connection.send_error(msg["id"], "refused", str(error))


@websocket_api.websocket_command({vol.Required("type"): "console/suggestions/dismiss", vol.Required("suggestion_id"): str})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_suggestion_dismiss(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    try:
        connection.send_result(msg["id"], await hass.data[DOMAIN].suggestions.dismiss(msg["suggestion_id"], connection.user.id))
    except suggestions.Refused as error:
        connection.send_error(msg["id"], "refused", str(error))


# --- AI features (features.py) ----------------------------------------------------------------------


@websocket_api.websocket_command({vol.Required("type"): "console/features"})
@callback
def ws_features(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Each AI feature: what it's for, what it tends to cost, what it used this month, and whether it's on."""
    connection.send_result(msg["id"], features.listing(hass, hass.data[DOMAIN]) | {"is_admin": connection.user.is_admin})


@websocket_api.websocket_command(
    {vol.Required("type"): "console/features/set", vol.Required("feature"): vol.In(list(features.BY_KEY)), vol.Required("on"): bool}
)
@websocket_api.require_admin
@callback
def ws_features_set(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    data = hass.data[DOMAIN]
    connection.send_result(msg["id"], {"feature": msg["feature"], "on": features.set_on(data, msg["feature"], msg["on"])})


@websocket_api.websocket_command({vol.Required("type"): "console/usage/paths"})
@callback
def ws_usage_paths(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """This month's requests and credits by where they came from: the Plan tab's "Where it went".
    Kept on the box; not part of the summary sent to the relay."""
    from .const import PATHS  # noqa: PLC0415
    from .credits import credits  # noqa: PLC0415

    data = hass.data[DOMAIN]
    got = data.paths()
    rows = [{"path": p, "turns": got.get(p, {}).get("turns", 0), "spend_usd": round(got.get(p, {}).get("spend_usd", 0.0), 6),
             "credits": credits(got.get(p, {}).get("spend_usd", 0.0))} for p in PATHS]
    connection.send_result(msg["id"], {"period": data.period, "paths": rows, "credits_used": credits(data.spend_usd)})
