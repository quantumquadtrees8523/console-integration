"""Where the credits went: each request counted by where it came from, shown as the Plan tab's pie, and
the 80% and 100% notifications that link to it. Kept on the box: not in the summary sent out."""

from __future__ import annotations

from homeassistant.components import persistent_notification
from homeassistant.core import Context

from custom_components.console.const import PATHS

from .conftest import ask, link


async def _paths(hass, ws_client) -> dict:
    ws = await ws_client(hass)
    await ws.send_json({"id": 1, "type": "console/usage/paths"})
    got = (await ws.receive_json())["result"]
    assert [r["path"] for r in got["paths"]] == list(PATHS)
    return {r["path"]: r for r in got["paths"]}


async def test_each_request_is_counted_by_where_it_came_from(hass, console, model, hass_ws_client, hass_admin_user, lights_off):
    link(console)
    model.cost = 0.002
    # An automation or script (nobody signed in, no speaker)
    model.say("It's 21 degrees. [[status]]")
    await ask(hass, "what's the temperature like")
    # Assist in the app, someone signed in
    model.say("Nothing is on. [[status]]")
    await ask(hass, "is anything left on", Context(user_id=hass_admin_user.id))
    # A voice speaker
    from homeassistant.components import conversation

    model.say("Done. [[status]]")
    await conversation.async_converse(hass, "how warm is the den", None, Context(), device_id="satellite-1", agent_id="conversation.console")
    # The chat card
    ws = await hass_ws_client(hass)
    model.say("All quiet. [[status]]")
    await ws.send_json({"id": 7, "type": "console/chat", "text": "how is the house"})
    while (msg := await ws.receive_json()).get("event", {}).get("kind") != "done":
        pass
    # Handled at home: counted on its path with no credits
    await ask(hass, "turn off the kitchen light")

    got = await _paths(hass, hass_ws_client)
    assert got["automations"]["turns"] == 2 and got["automations"]["spend_usd"] == 0.002
    assert got["assist"]["turns"] == 1 and got["voice"]["turns"] == 1 and got["chat"]["turns"] == 1
    assert got["chat"]["spend_usd"] == 0.002 and got["chat"]["credits"] == 0.2
    assert "by_path" not in console.summary()  # never in what is sent out


async def test_claude_and_support_mode_are_their_own_paths(hass, console):
    console.count_turn("other_agent", "control", True, agent="other_agents", path="claude")
    console.count_turn("other_agent", "control", True, agent="other_agents", path="support")
    console.count_path("suggestion_taps")
    got = console.paths()
    assert got["claude"]["turns"] == 1 and got["support"]["turns"] == 1 and got["suggestion_taps"] == {"turns": 1, "spend_usd": 0.0}


async def test_notified_once_at_80_and_once_at_100_with_a_link_to_the_plan_tab(hass, console):
    link(console, cap=0.10)
    notes = persistent_notification._async_get_or_create_notifications(hass)  # noqa: SLF001
    console.add_spend(0.05)
    await hass.async_block_till_done()
    assert "console_usage" not in notes
    console.add_spend(0.03)  # 80%
    await hass.async_block_till_done()
    assert "80%" in notes["console_usage"]["message"] and "](/console)" in notes["console_usage"]["message"]
    persistent_notification.async_dismiss(hass, "console_usage")
    console.add_spend(0.001)
    await hass.async_block_till_done()
    assert "console_usage" not in notes  # once a month, not on every request
    console.add_spend(0.02)  # 100%
    await hass.async_block_till_done()
    assert "used up" in notes["console_usage"]["title"] and "](/console)" in notes["console_usage"]["message"]
    assert console.data["alerts"]["levels"] == ["near", "out"]
