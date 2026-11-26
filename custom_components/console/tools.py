"""Console's own tools for AI agents, beside Sunrise's: one LLM API ("console").

`dashboard` makes, lists and removes dashboards. Home Assistant has no action for that, so without this
tool an agent can't do "add a dashboard for the kids' room". The dashboard is built the same way the
Home dashboard is (dashboard.py): from the things the owner exposed, lights first, no guessing.
"""

from __future__ import annotations

from typing import Any

import probatio as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

from . import dashboard
from .const import DOMAIN, NAME

API_ID = DOMAIN

PROMPT = (
    "Console's tools: `dashboard` makes a dashboard for rooms or things the person names (op=create), lists "
    "the ones made this way (op=list) and removes one (op=remove). After creating one, tell the person its "
    "name and that it's in the sidebar. Only remove a dashboard the person asked you to remove."
)


class DashboardTool(llm.Tool):
    integration = DOMAIN
    name = "dashboard"
    title = "Make or remove a dashboard"
    description = (
        "Make a Home Assistant dashboard for some rooms or things, list the dashboards made this way, or remove "
        "one. op=create needs a title and rooms (room names) and/or entity_ids; it shows only things the owner "
        "exposed to Assist. Creating again with the same title rebuilds that dashboard. op=remove needs the title."
    )
    parameters = vol.Schema(
        {
            vol.Required("op", description="create, list or remove"): vol.In(["create", "list", "remove"]),
            vol.Optional("title", description="the dashboard's name, e.g. Kids' room"): str,
            vol.Optional("rooms", description="room names whose things go on it"): [str],
            vol.Optional("entity_ids", description="extra things to show, by entity id"): [str],
        }
    )
    annotations = llm.ToolAnnotations(read_only=False, destructive=True, idempotent=True, open_world=False)

    async def async_call(self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext) -> llm.ToolResult:
        args = dict(tool_input.tool_args or {})
        data = hass.data[DOMAIN]
        if args.get("op") != "list" and not await _admin(hass, llm_context):
            return llm.ToolResult(data={"error": "Only a Home Assistant administrator's agent can change dashboards."}, error=False)
        try:
            if args["op"] == "list":
                result: dict[str, Any] = {"dashboards": dashboard.made(data)}
            elif args["op"] == "create":
                result = await dashboard.make(
                    hass, data, str(args.get("title") or ""), list(args.get("rooms") or []), list(args.get("entity_ids") or [])
                )
            else:
                result = await dashboard.unmake(hass, data, str(args.get("title") or ""))
        except dashboard.Refused as error:
            result = {"error": str(error)}
        return llm.ToolResult(data=result, error=False)


async def _admin(hass: HomeAssistant, llm_context: llm.LLMContext) -> bool:
    """A signed-in person must be an administrator; Home Assistant's own pipelines (no user) may not
    change dashboards at all."""
    user_id = llm_context.context.user_id if llm_context.context else None
    user = await hass.auth.async_get_user(user_id) if user_id else None
    return bool(user and user.is_admin)


class ConsoleAPI(llm.API):
    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(hass=hass, id=API_ID, name=NAME)

    async def async_get_api_instance(self, llm_context: llm.LLMContext) -> llm.APIInstance:
        return llm.APIInstance(api=self, api_prompt=PROMPT, llm_context=llm_context, tools=[DashboardTool()])
