"""What the chat card and the Console page ask over Home Assistant's WebSocket.

Reading is for anyone signed in to Home Assistant. Changing or deleting anything is for administrators.
"""

from __future__ import annotations

import logging
from typing import Any

import probatio as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from . import backups, dashboard, knows, suggestions, wipe, wording
from .const import DOMAIN
from .status import status

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
        ws_chat_history,
        ws_chat_clear,
        ws_suggestions,
        ws_suggestions_set,
        ws_suggestions_run,
        ws_suggestion_tap,
        ws_suggestion_dismiss,
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


@websocket_api.websocket_command(
    {
        vol.Required("type"): "console/chat",
        vol.Required("text"): str,
        vol.Optional("conversation_id"): vol.Any(str, None),
        vol.Optional("earlier", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=40)),
    }
)
@websocket_api.async_response
async def ws_chat(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """One turn with Console's agent, told as it happens. The answer to the command is the conversation's
    id; then events follow (trail.py): steps, thinking, pieces of the reply, and at last `done` with the
    whole reply. What was said goes into this person's chat history on the box."""
    import secrets  # noqa: PLC0415
    import time  # noqa: PLC0415

    from homeassistant.components import conversation  # noqa: PLC0415

    data = hass.data[DOMAIN]
    user_id = connection.user.id
    text = msg["text"].strip()
    conversation_id = msg.get("conversation_id") or f"console-{secrets.token_hex(8)}"

    def send(event: dict[str, Any]) -> None:
        connection.send_message(websocket_api.event_message(msg["id"], event))

    connection.subscriptions[msg["id"]] = lambda: data.streams.pop(conversation_id, None)
    connection.send_result(msg["id"], {"conversation_id": conversation_id})
    if not text:
        send({"kind": "done", "reply": "", "conversation_id": conversation_id, "error": True})
        return
    if msg["earlier"]:
        data.earlier[conversation_id] = data.history.last(user_id, msg["earlier"])
    data.streams[conversation_id] = send
    data.history.add(user_id, "you", text)
    started = time.monotonic()
    try:
        result = await conversation.async_converse(
            hass, text, conversation_id, connection.context(msg), hass.config.language, agent_id="conversation.console"
        )
        speech = (result.response.speech.get("plain") or {}).get("speech") or ""
        failed = result.response.response_type.value == "error"
        conversation_id_now = result.conversation_id or conversation_id
    except Exception as error:  # noqa: BLE001 (whatever went wrong, the card must hear the end of the turn)
        speech, failed, conversation_id_now = wording.MODEL_FAILED_REPLY, True, conversation_id
        hass.data[DOMAIN].streams.pop(conversation_id, None)
        _LOGGER.warning("Console: a chat turn failed (%s)", type(error).__name__)
    finally:
        data.streams.pop(conversation_id, None)
        data.earlier.pop(conversation_id, None)
    data.history.add(user_id, "console", speech, **({"failed": True} if failed else {}))
    send(
        {
            "kind": "done",
            "reply": speech,
            "conversation_id": conversation_id_now,
            "error": failed,
            "ms": round((time.monotonic() - started) * 1000),
        }
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "console/chat/history",
        vol.Optional("before"): vol.Any(vol.Coerce(int), None),
        vol.Optional("limit", default=10): vol.All(vol.Coerce(int), vol.Range(min=1, max=50)),
    }
)
@callback
def ws_chat_history(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """This person's earlier chat messages, a page at a time, newest page first."""
    history = hass.data[DOMAIN].history
    connection.send_result(msg["id"], history.page(connection.user.id, msg.get("before"), msg["limit"]))


@websocket_api.websocket_command({vol.Required("type"): "console/chat/clear"})
@callback
def ws_chat_clear(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Delete this person's chat history from the box."""
    connection.send_result(msg["id"], {"deleted": hass.data[DOMAIN].history.clear(connection.user.id)})


# --- suggested routines (suggestions.py) ----------------------------------------------------------


@websocket_api.websocket_command({vol.Required("type"): "console/suggestions"})
@callback
def ws_suggestions(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """The suggested routines waiting in the chat card, the setting, and the last night's run."""
    data = hass.data[DOMAIN]
    answer = data.suggestions.listing()
    if data.cloud_state() in ("ai_off", "cloud_off") or not answer["available"]:
        answer["items"] = []  # nothing to tap: the tools behind them are off or missing
    connection.send_result(msg["id"], answer | {"cost_note": wording.SUGGESTIONS_COST, "is_admin": connection.user.is_admin})


@websocket_api.websocket_command({vol.Required("type"): "console/suggestions/set", vol.Required("on"): bool})
@websocket_api.require_admin
@callback
def ws_suggestions_set(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    connection.send_result(msg["id"], hass.data[DOMAIN].suggestions.set_on(msg["on"]))


@websocket_api.websocket_command({vol.Required("type"): "console/suggestions/run"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_suggestions_run(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Run tonight's suggestions now (an administrator asked, so it runs even with the setting off)."""
    try:
        connection.send_result(msg["id"], await hass.data[DOMAIN].suggestions.run(force=True))
    except suggestions.Refused as error:
        connection.send_error(msg["id"], "refused", str(error))


@websocket_api.websocket_command({vol.Required("type"): "console/suggestions/tap", vol.Required("suggestion_id"): str})
@websocket_api.async_response
async def ws_suggestion_tap(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Run a suggestion once, as the person who tapped it. The fifth tap keeps it."""
    data = hass.data[DOMAIN]
    try:
        done = await data.suggestions.tap(msg["suggestion_id"], connection.user.id)
    except suggestions.Refused as error:
        connection.send_error(msg["id"], "refused", str(error))
        return
    data.history.add(connection.user.id, "you", wording.suggestion_tapped(done["name"]))
    data.history.add(connection.user.id, "console", done["reply"])
    connection.send_result(msg["id"], done)


@websocket_api.websocket_command({vol.Required("type"): "console/suggestions/dismiss", vol.Required("suggestion_id"): str})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_suggestion_dismiss(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    try:
        connection.send_result(msg["id"], await hass.data[DOMAIN].suggestions.dismiss(msg["suggestion_id"], connection.user.id))
    except suggestions.Refused as error:
        connection.send_error(msg["id"], "refused", str(error))
