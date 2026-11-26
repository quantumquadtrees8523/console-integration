"""Shared setup: a test Home Assistant with Console set up, a few exposed things, and a stand-in for
the model provider that answers from a script and records what it was sent."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from homeassistant.components.homeassistant.exposed_entities import async_expose_entity
from homeassistant.core import Context, HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.console import openrouter
from custom_components.console.const import DOMAIN, OPENROUTER_URL


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


class Model:
    """The model provider, scripted: each call takes the next answer (a message, or an exception)."""

    def __init__(self) -> None:
        self.script: list[Any] = []
        self.calls: list[dict[str, Any]] = []
        self.cost = 0.001

    def say(self, text: str, thinking: str = "") -> None:
        self.script.append({"role": "assistant", "content": text} | ({"thinking": thinking} if thinking else {}))

    def call_tool(self, name: str, args: dict[str, Any], call_id: str = "call_1") -> None:
        import json

        call = {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
        self.script.append({"role": "assistant", "content": None, "tool_calls": [call]})

    def fail(self, error: Exception) -> None:
        self.script.append(error)

    async def complete(self, session, inference, model, messages, tools, effort, timeout_s=25, on_delta=None):
        self.calls.append({"model": model, "messages": messages, "tools": tools, "effort": effort, "key": inference["key"]})
        assert self.script, f"the model was called more often than the test expected: {messages[-1]}"
        answer = self.script.pop(0)
        if isinstance(answer, Exception):
            raise answer
        thinking = answer.pop("thinking", "") if isinstance(answer, dict) else ""
        if on_delta is not None:  # a card is listening: hand the answer over in pieces, as a stream would
            if thinking:
                on_delta("thinking", thinking)
            text = answer.get("content") or ""
            for start in range(0, len(text), 7):
                on_delta("text", text[start : start + 7])
        return openrouter.Completion(message=answer, cost_usd=self.cost, model=model, thinking=thinking)


@pytest.fixture
def model(monkeypatch) -> Model:
    fake = Model()
    monkeypatch.setattr(openrouter, "complete", fake.complete)
    return fake


@pytest.fixture
async def console(hass: HomeAssistant):
    """Console set up on a house with a kitchen light Home Assistant's own agent can switch."""
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, "conversation", {})
    assert await async_setup_component(hass, "intent", {})
    hass.states.async_set("light.kitchen", "on", {"friendly_name": "Kitchen light"})
    async_expose_entity(hass, "conversation", "light.kitchen", True)
    entry = MockConfigEntry(domain=DOMAIN, title="Console", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return hass.data[DOMAIN]


def link(data, cap: float = 1.0, **plan) -> None:
    """What the relay hands over: a key good for six hours, and the plan."""
    data.apply_relay_config(
        {
            "inference": {
                "base_url": OPENROUTER_URL,
                "key": "test-key",
                "expires_at": (datetime.now(UTC) + timedelta(hours=6)).isoformat(),
            },
            "plan": {"tier": "free", "tier_name": "Free", "cap_usd": cap} | plan,
        }
    )


async def ask(hass: HomeAssistant, text: str, context: Context | None = None) -> str:
    from homeassistant.components import conversation

    result = await conversation.async_converse(
        hass, text, None, context or Context(), agent_id="conversation.console"
    )
    return result.response.speech["plain"]["speech"]


@pytest.fixture
def lights_off(hass: HomeAssistant):
    return async_mock_service(hass, "light", "turn_off")
