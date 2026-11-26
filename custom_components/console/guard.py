"""The AI off switch (the cloud access switch is in switch.py and in the hub).

- AI off: no AI agent can use this house's tools. Home Assistant hands tools to AI agents
  through its LLM APIs (Sunrise's, and its own Assist API): Claude through the MCP server, Console's
  agent, and any other AI integration all ask there. With AI off, every such request is refused.

Plain commands still work with both off: Home Assistant's own agent matches sentences, it isn't AI.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm
from homeassistant.helpers.event import async_track_time_interval

from . import wording


@dataclass(slots=True, kw_only=True)
class GuardedAPI(llm.API):
    """An LLM API with the AI switch in front of it."""

    inner: llm.API
    allowed: Callable[[], bool]

    async def async_get_api_instance(self, llm_context: llm.LLMContext) -> llm.APIInstance:
        if not self.allowed():
            raise HomeAssistantError(wording.AI_OFF_TOOLS)
        return await self.inner.async_get_api_instance(llm_context)


class AiGuard:
    def __init__(self, hass: HomeAssistant, data) -> None:
        self.hass = hass
        self.data = data
        self._stop = None

    @callback
    def start(self) -> None:
        self.apply()
        # An integration that reloads registers its API afresh: put the switch back in front of it.
        self._stop = async_track_time_interval(self.hass, lambda _now: self.apply(), timedelta(seconds=15))

    @callback
    def stop(self) -> None:
        if self._stop:
            self._stop()
        apis = llm._async_get_apis(self.hass)  # noqa: SLF001 (Home Assistant has no public way to wrap an API)
        for api_id, api in list(apis.items()):
            if isinstance(api, GuardedAPI):
                apis[api_id] = api.inner

    @callback
    def apply(self) -> None:
        apis = llm._async_get_apis(self.hass)  # noqa: SLF001
        for api_id, api in list(apis.items()):
            if not isinstance(api, GuardedAPI):
                apis[api_id] = GuardedAPI(
                    hass=self.hass, id=api.id, name=api.name, inner=api, allowed=lambda: self.data.switch("ai")
                )
