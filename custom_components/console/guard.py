"""The AI off switch (the cloud access switch is in switch.py and in the hub).

- AI off: no AI agent can use this house's tools. Home Assistant hands tools to AI agents
  through its LLM APIs (Sunrise's, and its own Assist API): Claude through the MCP server, Console's
  agent, and any other AI integration all ask there. With AI off, every such request is refused.

Plain commands still work with both off: Home Assistant's own agent matches sentences, it isn't AI.

The same door counts what goes through it (metrics.py): every tool an AI agent calls, whichever agent it
is (Console's own, Claude or Claude Code through the MCP server, another AI integration), is counted here
by its registered name and how it went. Never its arguments or its result.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm
from homeassistant.helpers.event import async_track_time_interval

from . import metrics, wording
from .const import DOMAIN
from .state import PATH


class CountedTool(llm.Tool):
    """A tool as it is, with its calls counted. Console's own plumbing (a tapped suggestion trying its
    routine, the suggestions reading how the house is used) isn't an agent and isn't counted."""

    def __init__(self, tool: llm.Tool, api_id: str, data) -> None:
        self.name = tool.name
        self.title = tool.title
        self.description = tool.description
        self.parameters = tool.parameters
        self.annotations = tool.annotations
        self.integration = tool.integration
        self.tool = tool
        self._api_id = api_id
        self._data = data

    async def async_call(self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext):
        counted = PATH.get() is not None or llm_context.platform != DOMAIN
        try:
            result = await self.tool.async_call(hass, tool_input, llm_context)
        except Exception:
            if counted:
                metrics.tool(self._data, self._api_id, self.name, tool_input.tool_args, None, True)
            raise
        if counted:
            said, error = (result.data, result.error) if isinstance(result, llm.ToolResult) else (result, False)
            metrics.tool(self._data, self._api_id, self.name, tool_input.tool_args, said, error)
        return result


@dataclass(slots=True, kw_only=True)
class GuardedAPI(llm.API):
    """An LLM API with the AI switch in front of it, and its tools counted."""

    inner: llm.API
    allowed: Callable[[], bool]
    data: object = None

    async def async_get_api_instance(self, llm_context: llm.LLMContext) -> llm.APIInstance:
        if not self.allowed():
            raise HomeAssistantError(wording.AI_OFF_TOOLS)
        instance = await self.inner.async_get_api_instance(llm_context)
        if self.data is not None:
            instance.tools = [CountedTool(tool, self.inner.id, self.data) for tool in instance.tools]
        return instance


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
                    hass=self.hass, id=api.id, name=api.name, inner=api, allowed=lambda: self.data.switch("ai"), data=self.data
                )
