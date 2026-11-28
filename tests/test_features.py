"""AI features: each use of Console's cloud agent has a switch of its own, with what it's for, what it
tends to cost, and what this house spent on it this month."""

from __future__ import annotations

from custom_components.console import features, openrouter, wording
from custom_components.console.const import MODEL_PRO

from .conftest import ask, link


async def ws(hass, hass_ws_client, message: dict, token: str | None = None) -> dict:
    client = await hass_ws_client(hass, token) if token else await hass_ws_client(hass)
    await client.send_json({"id": 1, **message})
    return await client.receive_json()


async def test_the_page_lists_each_feature_with_its_cost_and_what_it_used(hass, console, model, hass_ws_client):
    link(console)
    model.say("Two lights are on. [[status]]")
    await ask(hass, "which lights did we leave on downstairs and should I worry")
    got = (await ws(hass, hass_ws_client, {"type": "console/features"}))["result"]
    rows = {row["key"]: row for row in got["features"]}
    assert list(rows) == ["agent", "pro", "suggestions", "style", "chips"]
    assert [rows[k]["on"] for k in rows] == [True, True, False, True, True]  # the weekly run is the one that's off until asked for
    assert [rows[k]["level_name"] for k in rows] == ["Low", "High", "Medium", "Medium", "Free"]
    for row in rows.values():  # every feature says what it is, what it tends to cost and what off means
        assert row["name"] and row["what"] and row["cost"] and row["off"].startswith("Off:")
    assert "credit" in rows["agent"]["cost"] and rows["chips"]["cost"].startswith("Free.")
    assert rows["agent"]["this_month"] == {"requests": 1, "credits": 0.1, "each": 0.1}  # counted on this box, in credits
    assert rows["pro"]["this_month"] == {"requests": 0, "credits": 0.0, "each": None}
    assert got["credits"] == {"used": 0.1, "allowed": 100} and got["is_admin"] is True and "One credit is one cent" in got["about"]


async def test_only_an_administrator_switches_a_feature(hass, console, hass_ws_client, hass_read_only_access_token):
    refused = await ws(hass, hass_ws_client, {"type": "console/features/set", "feature": "style", "on": False}, hass_read_only_access_token)
    assert refused["success"] is False and console.feature("style") is True
    done = await ws(hass, hass_ws_client, {"type": "console/features/set", "feature": "style", "on": False})
    assert done["result"] == {"feature": "style", "on": False} and console.style.state["on"] is False
    assert (await console.style.run()) == {"ran": False, "why": "off"}
    unknown = await ws(hass, hass_ws_client, {"type": "console/features/set", "feature": "everything", "on": False})
    assert unknown["success"] is False


async def test_with_the_cloud_agent_feature_off_only_plain_commands_are_answered(hass, console, model, lights_off, hass_ws_client):
    link(console)
    features.set_on(console, features.AGENT, False)
    assert await ask(hass, "which lights did we leave on downstairs and should I worry") == wording.AGENT_OFF_REPLY
    assert model.calls == [] and console.spend_usd == 0  # nothing was sent out, nothing was spent
    assert "turned off" in (await ask(hass, "turn off the kitchen light")).lower() and len(lights_off) == 1  # at home, as ever
    assert console.cloud_state() == "ok"  # what the relay is told is unchanged: this is a setting of the house's own
    status = (await ws(hass, hass_ws_client, {"type": "console/status"}))["result"]
    assert status["agent"] is False and status["banner"] == {"kind": "off", "text": wording.AGENT_OFF}

    # The weekly features have their own switches: this one doesn't stop them.
    console.suggestions.set_on(True)
    model.say("Suggested 0. [[customization]]")
    from homeassistant.core import Context

    context = Context()
    console.via[context.id] = "suggestions"
    assert await ask(hass, "Suggest up to 3 routines for this house from how it is used", context) == "Suggested 0."


async def test_with_the_stronger_model_off_the_first_model_is_on_its_own(hass, console, model, hass_ws_client):
    link(console)
    features.set_on(console, features.PRO, False)
    model.fail(openrouter.ModelError("http 500"))
    assert await ask(hass, "design a full set of routines for a week away and explain each one") == wording.MODEL_FAILED_REPLY
    assert len(model.calls) == 1  # it wasn't started again on the stronger model
    assert "console_escalate" not in [t["function"]["name"] for t in model.calls[0]["tools"]]  # nor offered the hand-up

    features.set_on(console, features.PRO, True)
    model.call_tool("console_escalate", {"reason": "multi-step"})
    model.say("Here's the plan. [[customization]]")
    assert await ask(hass, "design a full set of routines for a week away and explain each one") == "Here's the plan."
    assert model.calls[-1]["model"] == MODEL_PRO
    row = {r["key"]: r for r in (await ws(hass, hass_ws_client, {"type": "console/features"}))["result"]["features"]}["pro"]
    assert row["this_month"] == {"requests": 1, "credits": 0.1, "each": 0.1}  # what the stronger model itself cost


async def test_with_suggestions_in_chat_off_the_card_gets_none(hass, console, hass_ws_client):
    got = (await ws(hass, hass_ws_client, {"type": "console/suggestions"}))["result"]
    assert len(got["suggested"]) == 3 and got["shown"] is True
    features.set_on(console, features.CHIPS, False)
    got = (await ws(hass, hass_ws_client, {"type": "console/suggestions"}))["result"]
    assert got["suggested"] == [] and got["quick"] == [] and got["shown"] is False


async def test_erasing_data_never_turns_a_feature_back_on(hass, console):
    for key in (features.AGENT, features.PRO, features.STYLE, features.CHIPS):
        features.set_on(console, key, False)
    await console.async_erase()
    assert [console.feature(k) for k in ("agent", "pro", "suggestions", "style", "chips")] == [False, False, False, False, False]


async def test_the_page_is_called_console_settings_and_has_an_ai_features_tab(hass, console, hass_client):
    """Owner, 2026-11-28: "console settings should also be labeled console settings not console", and the AI
    features get "a dedicated page that describes the ai feature and how credit expensive it tends to be"."""
    from homeassistant.components import frontend

    panel = hass.data[frontend.DATA_PANELS]["console"]
    assert panel.sidebar_title == "Console settings" == wording.PANEL_TITLE
    client = await hass_client()
    script = await (await client.get("/console_static/console-panel.js")).text()
    assert 'const TITLE = "Console settings"' in script and "<header>Console</header>" not in script
    assert '["features", "AI features"]' in script and '"console/features"' in script and '"console/features/set"' in script
    assert "What it tends to cost" in script and "Used this month" in script and "If you turn it off" in script
