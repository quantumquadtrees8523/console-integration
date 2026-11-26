"""Onboarding: Sunrise's welcome, offered once in the chat card and run by the cloud agent."""

from __future__ import annotations

from homeassistant.helpers import llm

from custom_components.console import knows

from .conftest import ask, link


class _Store:
    """Sunrise's memory, as far as Console reads it."""

    def __init__(self) -> None:
        self.files: list[dict] = []

    def memory_list(self) -> list[dict]:
        return self.files


async def test_a_new_house_is_offered_the_welcome_once(hass, console, hass_ws_client, monkeypatch):
    store = _Store()
    monkeypatch.setattr(knows, "sunrise_store", lambda hass: store)
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "console/status"})
    first = (await ws.receive_json())["result"]["onboarding"]
    assert first == {"available": True, "offered": False, "state": "new", "progress": "", "done": False}

    await ws.send_json({"id": 2, "type": "console/onboarding/offered"})
    assert (await ws.receive_json())["success"] is True
    await ws.send_json({"id": 3, "type": "console/status"})
    assert (await ws.receive_json())["result"]["onboarding"]["offered"] is True


async def test_progress_is_read_from_sunrises_own_note(hass, console, monkeypatch):
    store = _Store()
    monkeypatch.setattr(knows, "sunrise_store", lambda hass: store)
    store.files = [{"name": "onboarding.md", "first_line": "Onboarding: stage 1 of 4 done, 2026-11-26"}]
    seen = await knows.onboarding(hass, console)
    assert seen["state"] == "started" and seen["done"] is False and "stage 1 of 4" in seen["progress"]
    store.files = [{"name": "onboarding.md", "first_line": "Onboarding: finished, 2026-11-27"}]
    assert (await knows.onboarding(hass, console))["done"] is True


async def test_without_sunrise_there_is_no_welcome_to_offer(hass, console):
    assert (await knows.onboarding(hass, console))["available"] is False


class _GetSkill(llm.Tool):
    name = "get_skill"
    description = "Read a skill"

    async def async_call(self, hass, tool_input, llm_context):
        return llm.ToolResult(data={"name": tool_input.tool_args["name"], "body": "Stage 1: learn the house."}, error=False)


class _Sunrise(llm.API):
    def __init__(self, hass):
        super().__init__(hass=hass, id="sunrise", name="Sunrise")

    async def async_get_api_instance(self, llm_context):
        return llm.APIInstance(api=self, api_prompt="If memory has no onboarding.md, offer welcome first.", llm_context=llm_context, tools=[_GetSkill()])


async def test_show_me_around_has_the_cloud_agent_follow_the_welcome_skill(hass, console, model):
    link(console)
    llm.async_register_api(hass, _Sunrise(hass))
    model.call_tool("sunrise__get_skill", {"name": "welcome"})
    model.say("Welcome. First I'll learn your house. How many people live here? [[setup]]")
    reply = await ask(hass, "Show me around.")
    assert reply == "Welcome. First I'll learn your house. How many people live here?"
    assert model.calls[0]["effort"] == "low"  # never the thinking-off route
    system = model.calls[0]["messages"][0]["content"]
    assert "call get_skill for\nthe skill named welcome" in system
    assert "Stage 1: learn the house." in model.calls[1]["messages"][-1]["content"]
    assert console.summary()["by_category"]["setup"] == 1


async def test_the_relay_can_ask_whether_a_grant_is_this_houses(hass, console, hass_client, hass_access_token, hass_read_only_access_token):
    client = await hass_client()
    grant = hass.auth.async_validate_access_token(hass_access_token)
    mine = await client.get(f"/api/console/relay/token?iss={grant.id}")
    assert (await mine.json()) == {"known": True}
    other = await client.get("/api/console/relay/token?iss=" + "f" * 32)
    assert (await other.json()) == {"known": False}
    assert (await (await client.get("/api/console/relay/token")).json()) == {"known": False}
    reader = await hass_client(hass_read_only_access_token)
    assert (await reader.get(f"/api/console/relay/token?iss={grant.id}")).status == 403
