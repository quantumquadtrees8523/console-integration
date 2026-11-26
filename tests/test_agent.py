"""One turn through Console's agent: local first, then the cloud agent, then the fallbacks."""

from __future__ import annotations

import json

from custom_components.console import openrouter, wording
from custom_components.console.const import MODEL_FLASH, MODEL_PRO

from .conftest import ask, link


async def test_a_command_the_local_agent_knows_makes_no_model_call(hass, console, model, lights_off):
    link(console)
    reply = await ask(hass, "turn off the kitchen light")
    assert model.calls == []
    assert len(lights_off) == 1 and lights_off[0].data["entity_id"] == ["light.kitchen"]
    assert reply
    month = console.summary()
    assert month["by_route"]["local"] == 1 and month["by_category"]["control"] == 1 and month["spend_usd"] == 0


async def test_anything_else_goes_to_flash_and_its_label_is_counted(hass, console, model):
    link(console)
    model.say("Two lights are on: the kitchen and the hall. [[status]]")
    reply = await ask(hass, "which lights did we leave on downstairs and should I worry")
    assert reply == "Two lights are on: the kitchen and the hall."
    assert [c["model"] for c in model.calls] == [MODEL_FLASH] and model.calls[0]["effort"] == "low"
    month = console.summary()
    assert month["by_route"]["flash"] == 1 and month["by_category"]["status"] == 1
    assert month["spend_usd"] == 0.001


async def test_a_plain_command_the_local_agent_missed_runs_with_thinking_off(hass, console, model):
    link(console)
    model.say("I couldn't find a fountain here. [[control]]")
    await ask(hass, "turn on the fountain")
    assert model.calls[0]["effort"] == "none" and console.summary()["by_route"]["flash_fast"] == 1


async def test_the_model_gets_the_exposed_things_only_with_sunrise(hass, console, model):
    """Without Sunrise the agent uses Home Assistant's own Assist tools, which list the house themselves."""
    link(console)
    model.say("Hello. [[other]]")
    await ask(hass, "tell me something nice about this house")
    names = [tool["function"]["name"] for tool in model.calls[0]["tools"]]
    assert "intent__HassTurnOn" in names and "console_escalate" in names
    assert model.calls[0]["messages"][0]["role"] == "system"


async def test_a_tool_call_is_run_and_its_result_goes_back_to_the_model(hass, console, model, lights_off):
    link(console)
    model.call_tool("intent__HassTurnOff", {"name": "Kitchen light"})
    model.say("The kitchen light is off. [[control]]")
    reply = await ask(hass, "could you make the kitchen dark for the movie")
    assert reply == "The kitchen light is off."
    assert len(lights_off) == 1
    assert model.calls[1]["messages"][-1]["role"] == "tool"
    assert console.summary()["spend_usd"] == 0.002


async def test_when_flash_fails_pro_takes_the_turn(hass, console, model):
    link(console)
    model.fail(openrouter.ModelError("http 500"))
    model.say("Done thinking: nothing is wrong. [[troubleshooting]]")
    reply = await ask(hass, "why does the hallway light keep dropping off the network")
    assert reply == "Done thinking: nothing is wrong."
    assert [c["model"] for c in model.calls] == [MODEL_FLASH, MODEL_PRO]
    assert console.summary()["by_route"]["pro"] == 1


async def test_flash_can_hand_a_hard_case_up_to_pro(hass, console, model):
    link(console)
    model.call_tool("console_escalate", {"reason": "multi-step"})
    model.say("Here's the plan. [[customization]]")
    await ask(hass, "design a full set of routines for a week away and explain each one")
    assert [c["model"] for c in model.calls] == [MODEL_FLASH, MODEL_PRO]
    assert "console_escalate" not in [t["function"]["name"] for t in model.calls[1]["tools"]]


async def test_when_both_models_fail_the_person_is_told_and_nothing_is_claimed(hass, console, model):
    link(console)
    model.fail(openrouter.ModelError("timeout"))
    model.fail(openrouter.ModelError("timeout"))
    reply = await ask(hass, "what should I automate next in this house")
    assert reply == wording.MODEL_FAILED_REPLY
    assert console.summary()["failed"] == 1


async def test_at_eighty_percent_the_banner_names_the_next_tier(hass, console, model):
    link(console, cap=0.05, next={"name": "Standard", "price": "$6.50 a month"}, contact="Surya")
    console.add_spend(0.04)
    await hass.async_block_till_done()
    sensor = hass.states.get("sensor.console_cloud_agent")
    assert sensor.state == "near_limit" and sensor.attributes["banner_kind"] == "warn"
    assert sensor.attributes["banner"] == (
        "You've used 80% of this month's Console agent allowance. Need more? Standard is $6.50 a month: contact Surya."
    )
    model.say("Still here. [[other]]")
    assert await ask(hass, "are you still answering questions today") == "Still here."


async def test_at_the_cap_the_cloud_agent_stops_and_the_house_still_works(hass, console, model, lights_off):
    link(console, cap=0.05)
    console.add_spend(0.05)
    await hass.async_block_till_done()
    sensor = hass.states.get("sensor.console_cloud_agent")
    assert sensor.state == "over_limit" and sensor.attributes["banner_kind"] == "stop"
    assert "paused until" in sensor.attributes["banner"] and "Your house still works" in sensor.attributes["banner"]
    assert await ask(hass, "what should I automate next in this house") == wording.OVER_LIMIT_REPLY
    await ask(hass, "turn off the kitchen light")
    assert model.calls == [] and len(lights_off) == 1


async def test_the_top_tier_is_told_to_contact_surya(hass, console):
    link(console, cap=5.0, tier="pro", tier_name="Pro", next=None, contact="Surya")
    console.add_spend(4.5)
    assert wording.near_limit(90, console.plan).endswith("Need more? Contact Surya.")


async def test_when_the_provider_says_the_key_is_spent_the_agent_stops(hass, console, model):
    link(console)
    model.fail(openrouter.LimitReached("402"))
    assert await ask(hass, "what should I automate next in this house") == wording.OVER_LIMIT_REPLY
    assert console.cloud_state() == "over_limit"
    assert await ask(hass, "and what about the garden") == wording.OVER_LIMIT_REPLY
    assert len(model.calls) == 1


async def test_with_no_key_the_house_still_works(hass, console, model, lights_off):
    """Never linked, or the relay has been out of reach for longer than a key lasts."""
    assert console.cloud_state() == "not_linked"
    assert await ask(hass, "what should I automate next in this house") == wording.NOT_LINKED_REPLY
    await ask(hass, "turn off the kitchen light")
    assert model.calls == [] and len(lights_off) == 1


async def test_an_expired_key_is_not_used(hass, console, model, freezer):
    link(console)
    freezer.tick(7 * 3600)
    assert console.cloud_state() == "not_linked"
    assert await ask(hass, "what should I automate next in this house") == wording.NOT_LINKED_REPLY
    assert model.calls == []


async def test_a_new_month_starts_the_allowance_again(hass, console, freezer):
    freezer.move_to("2026-11-30T23:00:00+00:00")
    link(console, cap=0.05)
    console.add_spend(0.05)
    assert console.cloud_state() == "over_limit"
    freezer.move_to("2026-12-01T00:00:01+00:00")
    link(console, cap=0.05)
    assert console.used == 0 and console.cloud_state() == "ok"
    assert console.summary("2026-11")["spend_usd"] == 0.05


async def test_nothing_a_person_says_is_kept(hass, console, model):
    link(console)
    model.say("I won't tell anyone about the surprise party. [[other]]")
    await ask(hass, "remember the surprise party for Priya on Saturday")
    await console.async_save_now()
    kept = json.dumps(console.data)
    assert "Priya" not in kept and "surprise" not in kept
    assert set(console.summary()) == {"period", "spend_usd", "turns", "ok", "failed", "by_route", "by_category", "by_agent"}
