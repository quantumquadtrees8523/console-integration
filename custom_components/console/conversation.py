"""Console's agent: the conversation agent behind Assist and the chat card.

One turn: Home Assistant's own agent first (no model, no internet). If it has no answer, the cloud
agent, on the household's own short-lived inference key, with Sunrise's tools. If the cloud agent can't
be used (allowance spent, relay out of reach, model error) the person is told so plainly and the house
keeps working on the local agent. Nothing a person says is stored by Console: a turn leaves one route
and one label in this month's counts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
import time
from typing import Any, Literal

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er, intent, llm
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.json import json_dumps

from . import openrouter, router, tools, wording
from .const import (
    AGENT_NAME,
    DOMAIN,
    EFFORT_FULL,
    LLM_API_ASSIST,
    LLM_API_SUNRISE,
    MAX_TOOL_ROUNDS,
    MODEL_FLASH,
    MODEL_PRO,
    ROUTE_FALLBACK,
    ROUTE_FAST,
    ROUTE_LOCAL,
    ROUTE_PRO,
)
from .state import ConsoleData

_LOGGER = logging.getLogger(__name__)

PROMPT = """You are Console, this home's assistant, answering inside Home Assistant. Be brief and plain:
one or two short sentences unless the person asks for more. Do the thing with your tools, then say what
actually happened. Never say something worked unless a tool result shows it. If you can't do something,
say so and say what the person can do instead.
End your final reply with one label in double square brackets saying what kind of request this was:
[[control]] (switching or setting a device), [[status]] (a question about the house), [[customization]]
(changing dashboards, routines, names, memory), [[setup]] (adding devices or first-time setup),
[[troubleshooting]] (something is broken) or [[other]]."""

DEVICES_HEADER = (
    "\n\nThings you may switch right now (entity id | name | room | state). Use these ids with the act tool "
    "directly; call house_map only when what the person means isn't here. For a question about what is on, "
    "off, playing or unreachable right now, answer from this list without calling a tool.\n"
)
ACTIONABLE = (
    "light", "switch", "fan", "media_player", "climate", "cover", "scene", "script", "vacuum", "humidifier",
    "input_boolean", "lock",
)  # fmt: skip

ESCALATE = "console_escalate"
ESCALATE_TOOL = {
    "type": "function",
    "function": {
        "name": ESCALATE,
        "description": (
            "Hand this request to a stronger, slower model. Use it only when the request needs careful "
            "multi-step work you aren't confident you can get right. Never for a simple command or question."
        ),
        "parameters": {"type": "object", "properties": {"reason": {"type": "string"}}},
    },
}


class Escalate(Exception):
    """Flash handed the turn up to Pro."""


@dataclass
class Turn:
    route: str
    text: str = ""
    cost_usd: float = 0.0
    calls: list[tuple[str, dict]] = field(default_factory=list)
    label: str | None = None
    model_calls: int = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([ConsoleAgent(hass, entry)])


def _tool_schema(tool: llm.Tool, serializer) -> dict[str, Any]:
    import probatio  # noqa: PLC0415 (Home Assistant's own schema library)

    schema = probatio.to_openapi(tool.parameters, custom_serializer=serializer, openapi_version="3.1.0")
    schema = {k: v for k, v in schema.items() if k not in ("oneOf", "anyOf", "allOf")}
    spec: dict[str, Any] = {"name": tool.name, "parameters": schema}
    if tool.description:
        spec["description"] = tool.description
    return {"type": "function", "function": spec}


def _to_message(content: conversation.Content) -> dict[str, Any] | None:
    """One chat-log entry as the provider's message."""
    if isinstance(content, conversation.ToolResultContent):
        return {
            "role": "tool",
            "tool_call_id": content.tool_call_id,
            "content": json_dumps({"data": content.result.data, "error": content.result.error}),
        }
    if content.role in ("system", "user"):
        return {"role": content.role, "content": content.content} if content.content else None
    if content.role == "assistant":
        message: dict[str, Any] = {"role": "assistant", "content": content.content}
        if isinstance(content, conversation.AssistantContent) and content.tool_calls:
            message["tool_calls"] = [
                {
                    "type": "function",
                    "id": call.id,
                    "function": {"name": call.tool_name, "arguments": json_dumps(call.tool_args)},
                }
                for call in content.tool_calls
            ]
        return message
    return None


def devices_block(hass: HomeAssistant) -> str:
    """The things the owner exposed to Assist, so a plain command needs no lookup first."""
    from homeassistant.components.homeassistant.exposed_entities import async_should_expose  # noqa: PLC0415

    entities, devices, areas = er.async_get(hass), dr.async_get(hass), ar.async_get(hass)
    lines = []
    for state in hass.states.async_all(ACTIONABLE):
        if not async_should_expose(hass, conversation.DOMAIN, state.entity_id):
            continue
        entry = entities.async_get(state.entity_id)
        area_id = entry.area_id if entry else None
        if entry and not area_id and entry.device_id and (device := devices.async_get(entry.device_id)):
            area_id = device.area_id
        area = areas.async_get_area(area_id).name if area_id and areas.async_get_area(area_id) else "-"
        lines.append(f"{state.entity_id} | {state.name} | {area} | {state.state}")
    return DEVICES_HEADER + "\n".join(sorted(lines)[:250]) if lines else ""


def _bare(tool_name: str) -> str:
    """A tool's own name, without the prefix Home Assistant adds when several APIs are merged."""
    return tool_name.rsplit("__", 1)[-1]


def confirmed_reply(calls: list[llm.ToolInput], results: list[conversation.ToolResultContent]) -> str | None:
    """A plain command that every device confirmed gets its reply from the read-back, with no second
    model call. None when anything wasn't a confirmed `act`."""
    if not calls or len(results) != len(calls) or any(_bare(call.tool_name) != "act" for call in calls):
        return None
    rows = []
    for result in results:
        data = result.result.data
        if result.result.error or not isinstance(data, dict) or not data.get("results"):
            return None
        rows += data["results"]
    if any(row.get("result") != "CHECKED" for row in rows):
        return None
    if len(rows) == 1:
        row = rows[0]
        now = f" is {row['now']}" if row.get("now") else ""
        level = f" at {row['brightness_pct']}%" if row.get("brightness_pct") is not None and row.get("now") == "on" else ""
        return f"Done. {row.get('name') or row.get('id')}{now}{level}."
    names = ", ".join(str(row.get("name") or row.get("id")) for row in rows[:6])
    return f"Done. {len(rows)} things changed: {names}{' and more' if len(rows) > 6 else ''}."


class ConsoleAgent(conversation.ConversationEntity):
    """Console's conversation agent."""

    _attr_has_entity_name = False
    _attr_name = AGENT_NAME
    _attr_supported_features = conversation.ConversationEntityFeature.CONTROL

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self.data: ConsoleData = hass.data[DOMAIN]
        self._attr_unique_id = entry.entry_id
        self.entity_id = "conversation.console"

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        return MATCH_ALL

    async def _async_handle_message(
        self, user_input: conversation.ConversationInput, chat_log: conversation.ChatLog
    ) -> conversation.ConversationResult:
        started = time.monotonic()
        local = await self._local(user_input, chat_log)
        if local is not None:
            return local

        state = self.data.cloud_state()
        if state == "ai_off":
            return self._say(user_input, chat_log, wording.AI_OFF_REPLY, ROUTE_FALLBACK, "other", False)
        if state == "cloud_off":
            return self._say(user_input, chat_log, wording.CLOUD_OFF_REPLY, ROUTE_FALLBACK, "other", False)
        if state == "over_limit":
            return self._say(user_input, chat_log, wording.OVER_LIMIT_REPLY, ROUTE_FALLBACK, "other", False)
        inference = self.data.key()
        if inference is None:
            return self._say(user_input, chat_log, wording.NOT_LINKED_REPLY, ROUTE_FALLBACK, "other", False)

        apis = {api.id for api in llm.async_get_apis(self.hass)}
        sunrise = LLM_API_SUNRISE in apis
        try:
            await chat_log.async_provide_llm_data(
                user_input.as_llm_context(DOMAIN),
                [LLM_API_SUNRISE if sunrise else LLM_API_ASSIST, tools.API_ID],
                PROMPT,
                user_input.extra_system_prompt,
            )
        except conversation.ConverseError as error:
            return error.as_conversation_result()
        if sunrise:
            system = chat_log.content[0]
            chat_log.content[0] = conversation.SystemContent(content=system.content + devices_block(self.hass))

        route, effort = router.first_route(user_input.text)
        turn = Turn(route=route, text=user_input.text)
        keep = len(chat_log.content)
        began = time.time()
        try:
            try:
                await self._run(chat_log, inference, MODEL_FLASH, effort, turn, escalate=route != ROUTE_FAST)
            except (openrouter.ModelError, Escalate) as why:
                # Flash failed or handed it up: start the turn again on Pro.
                _LOGGER.info("Console: Flash gave the turn to Pro (%s)", type(why).__name__)
                del chat_log.content[keep:]
                turn.route, turn.calls, turn.label = ROUTE_PRO, [], None
                await self._run(chat_log, inference, MODEL_PRO, EFFORT_FULL, turn, escalate=False)
        except openrouter.LimitReached:
            self.data.limit_reached()
            del chat_log.content[keep:]
            return self._say(user_input, chat_log, wording.OVER_LIMIT_REPLY, ROUTE_FALLBACK, "other", False)
        except openrouter.KeyRejected:
            del chat_log.content[keep:]
            return self._say(user_input, chat_log, wording.NOT_LINKED_REPLY, ROUTE_FALLBACK, "other", False)
        except openrouter.ModelError as why:
            _LOGGER.warning("Console: the cloud agent failed (%s)", why)
            del chat_log.content[keep:]
            return self._say(user_input, chat_log, wording.MODEL_FAILED_REPLY, turn.route, "other", False)
        finally:
            self.data.others.mark_own(began, time.time())

        category = turn.label or router.category_for_tools(turn.calls)
        self.data.count_turn(turn.route, category, True)
        _LOGGER.debug(
            "Console turn: route=%s category=%s model_calls=%s cost=%.5f ms=%d",
            turn.route, category, turn.model_calls, turn.cost_usd, (time.monotonic() - started) * 1000,
        )  # fmt: skip
        return conversation.async_get_result_from_chat_log(user_input, chat_log)

    async def _local(
        self, user_input: conversation.ConversationInput, chat_log: conversation.ChatLog
    ) -> conversation.ConversationResult | None:
        """Home Assistant's own agent: sentence triggers (learned sentences live there), then its
        built-in intents. None when it has no confident answer."""
        matched: dict[str, str] = {}

        def note(result) -> bool:
            matched["intent"] = result.intent.name
            return False  # never filter: this only records what matched

        try:
            said = await conversation.async_handle_sentence_triggers(self.hass, user_input, chat_log)
            if said is not None:
                response = intent.IntentResponse(language=user_input.language)
                response.async_set_speech(said)
                category = "control"
            else:
                response = await conversation.async_handle_intents(
                    self.hass, user_input, chat_log, intent_filter=note
                )
                category = router.category_for_intent(matched.get("intent"))
        except Exception:  # noqa: BLE001 (whatever the local agent trips on, the cloud agent gets the turn)
            _LOGGER.exception("Console: the local agent failed")
            return None
        if response is None:
            return None
        if response.response_type is intent.IntentResponseType.ERROR and self.data.cloud_state() in ("ok", "near_limit"):
            return None  # matched but couldn't do it: let the cloud agent work out why
        speech = (response.speech.get("plain") or {}).get("speech") or ""
        chat_log.async_add_assistant_content_without_tools(
            conversation.AssistantContent(agent_id=user_input.agent_id, content=speech)
        )
        ok = response.response_type is not intent.IntentResponseType.ERROR
        self.data.count_turn(ROUTE_LOCAL, category, ok)
        return conversation.ConversationResult(response=response, conversation_id=chat_log.conversation_id)

    def _say(
        self,
        user_input: conversation.ConversationInput,
        chat_log: conversation.ChatLog,
        words: str,
        route: str,
        category: str,
        ok: bool,
    ) -> conversation.ConversationResult:
        chat_log.async_add_assistant_content_without_tools(
            conversation.AssistantContent(agent_id=user_input.agent_id, content=words)
        )
        response = intent.IntentResponse(language=user_input.language)
        response.async_set_speech(words)
        self.data.count_turn(route, category, ok)
        return conversation.ConversationResult(response=response, conversation_id=chat_log.conversation_id)

    async def _run(
        self,
        chat_log: conversation.ChatLog,
        inference: dict[str, Any],
        model: str,
        effort: str,
        turn: Turn,
        *,
        escalate: bool,
    ) -> None:
        """Model calls and tool calls until the model answers in words."""
        session = async_get_clientsession(self.hass)
        tools: list[dict[str, Any]] = []
        if chat_log.llm_api:
            serializer = chat_log.llm_api.custom_serializer
            tools = [_tool_schema(tool, serializer) for tool in chat_log.llm_api.tools]
        if escalate:
            tools.append(ESCALATE_TOOL)
        for _ in range(MAX_TOOL_ROUNDS):
            messages = [m for content in chat_log.content if (m := _to_message(content))]
            done = await openrouter.complete(session, inference, model, messages, tools, effort)
            turn.model_calls += 1
            turn.cost_usd += done.cost_usd
            self.data.add_spend(done.cost_usd)
            calls: list[llm.ToolInput] = []
            for call in done.message.get("tool_calls") or []:
                function = call.get("function") or {}
                if function.get("name") == ESCALATE:
                    raise Escalate
                try:
                    args = json.loads(function.get("arguments") or "{}")
                except ValueError as error:
                    raise openrouter.ModelError("tool arguments weren't JSON") from error
                calls.append(llm.ToolInput(id=call["id"], tool_name=function["name"], tool_args=args))
                turn.calls.append((function["name"], args if isinstance(args, dict) else {}))
            text = done.message.get("content") or None
            if not calls:
                if not text:
                    raise openrouter.ModelError("empty answer")
                reply, turn.label = router.split_label(text)
                chat_log.async_add_assistant_content_without_tools(
                    conversation.AssistantContent(agent_id=self.entity_id, content=reply)
                )
                return
            results = [
                result
                async for result in chat_log.async_add_assistant_content(
                    conversation.AssistantContent(agent_id=self.entity_id, content=None, tool_calls=calls)
                )
            ]
            if turn.route == ROUTE_FAST and (reply := confirmed_reply(calls, results)):
                turn.label = "control"
                rows = [row for result in results for row in result.result.data["results"]]
                if self.data.learned.observe(turn.text, calls, rows):
                    reply += " " + wording.LEARNED
                chat_log.async_add_assistant_content_without_tools(
                    conversation.AssistantContent(agent_id=self.entity_id, content=reply)
                )
                return
        raise openrouter.ModelError("too many tool rounds")
