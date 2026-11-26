"""The two off switches: cloud access, and all AI."""

from __future__ import annotations

import pytest

from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm

from custom_components.console import wording

from .conftest import ask, link


async def turn(hass, entity_id: str, on: bool) -> None:
    await hass.services.async_call("switch", "turn_on" if on else "turn_off", {"entity_id": entity_id}, blocking=True)
    await hass.async_block_till_done()


async def test_both_switches_are_on_until_someone_turns_one_off(hass, console):
    assert hass.states.get("switch.console_cloud_access").state == "on"
    assert hass.states.get("switch.console_ai").state == "on"


async def test_with_cloud_access_off_every_request_takes_the_local_path(hass, console, model, lights_off):
    link(console)
    await turn(hass, "switch.console_cloud_access", False)
    sensor = hass.states.get("sensor.console_cloud_agent")
    assert sensor.state == "cloud_off" and sensor.attributes["banner"] == wording.CLOUD_OFF
    await ask(hass, "turn off the kitchen light")
    assert len(lights_off) == 1
    assert await ask(hass, "what should I automate next in this house") == wording.CLOUD_OFF_REPLY
    assert model.calls == []  # not one model call
    assert console.summary()["by_route"] == {"local": 1, "flash_fast": 0, "flash": 0, "pro": 0, "fallback": 1, "other_agent": 0}

    await turn(hass, "switch.console_cloud_access", True)
    model.say("Back. [[other]]")
    assert await ask(hass, "are you there again") == "Back."


async def test_the_cloud_switch_leaves_other_agents_alone(hass, console):
    await turn(hass, "switch.console_cloud_access", False)
    context = llm.LLMContext(platform="mcp_server", context=Context(), language="en", assistant="conversation", device_id=None)
    instance = await llm.async_get_api(hass, "assist", context)
    assert instance.tools


async def test_with_ai_off_no_agent_can_use_the_houses_tools(hass, console, model, lights_off):
    link(console)
    await turn(hass, "switch.console_ai", False)
    sensor = hass.states.get("sensor.console_cloud_agent")
    assert sensor.state == "ai_off" and sensor.attributes["banner"] == wording.AI_OFF

    # Claude, through Home Assistant's MCP server, asks for an LLM API exactly like this.
    context = llm.LLMContext(platform="mcp_server", context=Context(), language="en", assistant="conversation", device_id=None)
    for api in llm.async_get_apis(hass):
        with pytest.raises(HomeAssistantError, match="AI is turned off for this house"):
            await llm.async_get_api(hass, api.id, context)

    assert await ask(hass, "what should I automate next in this house") == wording.AI_OFF_REPLY
    assert model.calls == []
    await ask(hass, "turn off the kitchen light")  # sentence matching isn't AI: it still works
    assert len(lights_off) == 1

    await turn(hass, "switch.console_ai", True)
    assert (await llm.async_get_api(hass, "assist", context)).tools


async def test_an_api_registered_later_is_guarded_too(hass, console):
    class Late(llm.API):
        async def async_get_api_instance(self, llm_context):
            return llm.APIInstance(api=self, api_prompt="", llm_context=llm_context, tools=[])

    await turn(hass, "switch.console_ai", False)
    llm.async_register_api(hass, Late(hass=hass, id="late", name="Late"))
    console.guard.apply()
    context = llm.LLMContext(platform="mcp_server", context=Context(), language="en", assistant=None, device_id=None)
    with pytest.raises(HomeAssistantError):
        await llm.async_get_api(hass, "late", context)


async def test_erasing_data_never_turns_ai_back_on(hass, console):
    await turn(hass, "switch.console_ai", False)
    await console.async_erase()
    assert console.switch("ai") is False and console.switch("cloud") is True


async def test_the_switches_survive_a_restart(hass, console):
    await turn(hass, "switch.console_cloud_access", False)
    await console.async_save_now()
    again = type(console)(hass)
    await again.async_load()
    assert again.switch("cloud") is False and again.switch("ai") is True


async def test_with_cloud_access_off_the_relay_is_refused(hass, console, hass_client):
    """The hub drops the tunnel when this switch goes off; a handover that still arrives is refused too."""
    await turn(hass, "switch.console_cloud_access", False)
    client = await hass_client()
    refused = await client.post("/api/console/relay/config", json={"plan": {"tier": "free"}})
    assert refused.status == 423 and console.key() is None
    status = await (await client.get("/api/console/relay/status")).json()
    assert status["switches"] == {"cloud": False, "ai": True}


async def test_the_old_cloud_agent_switch_is_gone(hass, console):
    assert hass.states.get("switch.console_cloud_agent") is None
