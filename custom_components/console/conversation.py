"""Console's agent: the conversation agent behind Assist and the chat card.

One turn: Home Assistant's own agent first (no model, no internet). If it has no answer, the cloud
agent, on the household's own short-lived inference key, with Sunrise's tools and Console's. If the
cloud agent can't be used (a switch is off, the allowance is spent, the relay is out of reach, the model
fails) the person is told so plainly and the house keeps working on the local agent.

While a turn runs, the chat card is told what is happening as it happens (trail.py): where the request
went and why, the model's thinking, each tool it used and what came back, a hand-up to the stronger
model. A chat turn's steps are kept with its reply in that person's chat history on the box; a turn
leaves one route and one label, and nothing that was said, in this month's counts.
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

from . import features, openrouter, router, tools, topics, wording
from .const import (
    AGENT_NAME,
    DOMAIN,
    EFFORT_FAST,
    EFFORT_FULL,
    LLM_API_ASSIST,
    LLM_API_SUNRISE,
    MAX_TOOL_ROUNDS,
    MAX_TOOL_ROUNDS_FULL,
    MODEL_FLASH,
    MODEL_PRO,
    PATH_ASSIST,
    PATH_AUTOMATIONS,
    PATH_CHAT,
    PATH_SUGGESTIONS,
    PATH_VOICE,
    ROUTE_FALLBACK,
    ROUTE_FAST,
    ROUTE_FULL,
    ROUTE_LOCAL,
    ROUTE_PRO,
)
from .state import PATH, ConsoleData
from .trail import LabelGate, Trail, tool_step

_LOGGER = logging.getLogger(__name__)

PROMPT = """You are Console, this home's assistant, answering inside Home Assistant. Be brief and plain:
one or two short sentences unless the person asks for more. Do the thing with your tools, then say what
actually happened. Never say something worked unless a tool result shows it. You may use simple
Markdown (bold, lists, code) when it helps; never show tool names or entity ids unless asked.
Music: for anything about music, radio, podcasts, playlists or speakers, use the music tool. It
searches the household's music services (Spotify and the rest, through Music Assistant), reads their
playlists and library, plays by name on a room's speaker, shows and moves the queue, and pauses, skips
and sets volume. Never say you can't search or play music before you have tried it.
When the person wants to be shown around, to get started or to set the house up, call get_skill for
the skill named welcome and follow it exactly: its stages, its questions and its own wording replace the
brevity rule above, and you ask one thing at a time and wait for the answer. The same goes for any skill
you follow.
When the person needs something your tools can't do (a web browser, the router's own pages, a shell on
the box, installing software, files outside Home Assistant), don't improvise and don't just refuse: call
console_handoff with what they asked, what you found, and what should happen next. They get instructions
and a block to paste into Claude Code, which can do those things.
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
HANDOFF = "console_handoff"
HANDOFF_TOOL = {
    "type": "function",
    "function": {
        "name": HANDOFF,
        "description": (
            "Hand a request you can't do with your tools to Claude Code: anything needing a browser, the "
            "router's own pages, a shell on the box, installing software or files outside Home Assistant. "
            "Try your own tools first. Never put a password, key or token in any field."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "asked": {"type": "string", "description": "what the person asked for, in their words"},
                "why": {"type": "string", "description": "why you can't do it from here, in a few plain words"},
                "found": {"type": "string", "description": "what you checked and found, with names and facts"},
                "next": {"type": "string", "description": "what Claude Code should do next, step by step"},
            },
            "required": ["asked", "why", "next"],
        },
    },
}


class Escalate(Exception):
    """Flash handed the turn up to Pro."""


class HandedOff(Exception):
    """The model handed the request to Claude Code: the reply is the handoff itself."""

    def __init__(self, reply: str) -> None:
        super().__init__("handed off")
        self.reply = reply


@dataclass
class Turn:
    route: str
    text: str = ""
    cost_usd: float = 0.0
    calls: list[tuple[str, dict]] = field(default_factory=list)
    label: str | None = None
    model_calls: int = 0
    touched: set[str] = field(default_factory=set)  # devices its tools changed (prefs.py)
    asked: set[tuple[str, str]] = field(default_factory=set)  # (device, setting) its tools set on purpose


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
    """The things the owner exposed to Assist, so a plain command needs no lookup first. Speakers are
    left out when Music Assistant runs them: the music tool knows them by room, once each."""
    from homeassistant.components.homeassistant.exposed_entities import async_should_expose  # noqa: PLC0415

    entities, devices, areas = er.async_get(hass), dr.async_get(hass), ar.async_get(hass)
    music = bool(tools.music_players(hass))
    lines = []
    for state in hass.states.async_all(ACTIONABLE):
        if not async_should_expose(hass, conversation.DOMAIN, state.entity_id):
            continue
        if music and state.domain == "media_player":
            continue
        entry = entities.async_get(state.entity_id)
        area_id = entry.area_id if entry else None
        if entry and not area_id and entry.device_id and (device := devices.async_get(entry.device_id)):
            area_id = device.area_id
        area = areas.async_get_area(area_id).name if area_id and areas.async_get_area(area_id) else "-"
        lines.append(f"{state.entity_id} | {state.name} | {area} | {state.state}")
    block = DEVICES_HEADER + "\n".join(sorted(lines)[:250]) if lines else ""
    if music:
        players = ", ".join(f"{p['name']} ({p['state']})" for p in tools.music_players(hass))
        block += f"\nSpeakers, through the music tool only: {players}."
    return block


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


def path_of(data: ConsoleData, user_input: conversation.ConversationInput) -> str:
    """Where a request came from: the chat card and the suggestions run mark their own requests;
    otherwise a speaker says which it is, someone signed in is Assist in an app, and a request with
    neither is an automation or a script."""
    context = user_input.context
    if context is not None and (marked := data.via.get(context.id)):
        return marked
    if getattr(user_input, "satellite_id", None) or user_input.device_id:
        return PATH_VOICE
    if context is not None and context.user_id:
        return PATH_ASSIST
    return PATH_AUTOMATIONS


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
        token = PATH.set(path_of(self.data, user_input))  # every count and spend in this turn goes to its path
        try:
            return await self._handle(user_input, chat_log)
        finally:
            PATH.reset(token)

    async def _handle(
        self, user_input: conversation.ConversationInput, chat_log: conversation.ChatLog
    ) -> conversation.ConversationResult:
        started = time.monotonic()
        trail = Trail(self.data.streams.get(chat_log.conversation_id))
        self._earlier(chat_log)

        local = await self._local(user_input, chat_log, trail)
        if local is not None:
            return local

        state = self.data.cloud_state()
        blocked = {
            "ai_off": (wording.AI_OFF_REPLY, "AI is turned off for this house"),
            "cloud_off": (wording.CLOUD_OFF_REPLY, "Cloud access is turned off for this house"),
            "over_limit": (wording.OVER_LIMIT_REPLY, "This month's allowance is used up"),
        }
        if state in blocked:
            words, why = blocked[state]
            trail.step("The cloud agent wasn't used", why)
            return self._say(user_input, chat_log, words, ROUTE_FALLBACK, "other", False)
        if PATH.get() not in features.OWN_SWITCH and not self.data.feature(features.AGENT):
            trail.step("The cloud agent wasn't used", "It is switched off under AI features")
            return self._say(user_input, chat_log, wording.AGENT_OFF_REPLY, ROUTE_FALLBACK, "other", False)
        inference = self.data.key()
        if inference is None:
            trail.step("The cloud agent wasn't used", "This house has no cloud-agent key right now")
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
        if scope := self.data.scope.pop(chat_log.conversation_id, None):  # the chat card: one conversation, or all of them
            chat_log.content[0] = conversation.SystemContent(content=chat_log.content[0].content + scope)
        if prefs := self.data.prefs.prompt():  # the levels this household wants its speakers and lights at
            chat_log.content[0] = conversation.SystemContent(content=chat_log.content[0].content + prefs)

        route, effort = router.first_route(user_input.text)
        # A suggestions run is Flash with thinking off, and never the stronger model (owner, 2026-11-28: "made
        # using the flash model never reasoning"). It keeps the full tool rounds: the skill reads usage and saves.
        unattended = PATH.get() == PATH_SUGGESTIONS
        if unattended:
            route, effort = ROUTE_FULL, EFFORT_FAST
        turn = Turn(route=route, text=user_input.text)
        trail.step(
            "Sent to the cloud agent",
            "DeepSeek V4.1 Flash, thinking off: suggested routines never use thinking or the stronger model."
            if unattended
            else "DeepSeek V4.1 Flash, thinking off: this reads as a plain command."
            if effort == EFFORT_FAST
            else "DeepSeek V4.1 Flash, with a little thinking: this isn't a plain command.",
        )
        keep = len(chat_log.content)
        began = time.time()
        stronger = self.data.feature(features.PRO) and not unattended
        try:
            try:
                await self._run(chat_log, inference, MODEL_FLASH, effort, turn, trail, escalate=stronger and route != ROUTE_FAST)
            except (openrouter.ModelError, Escalate) as why:
                if not stronger:  # the stronger model is switched off under AI features: this is where it ends
                    raise openrouter.ModelError(f"no stronger model to hand to ({why})") from why
                # Flash failed or handed it up: start the turn again on Pro.
                _LOGGER.info("Console: Flash gave the turn to Pro (%s)", type(why).__name__)
                del chat_log.content[keep:]
                turn.route, turn.calls, turn.label = ROUTE_PRO, [], None
                trail.reset()
                trail.step(
                    "Handed to the stronger model",
                    "DeepSeek V4 Pro: the first model asked for help with this one."
                    if isinstance(why, Escalate)
                    else "DeepSeek V4 Pro: the first model failed, so this one starts the request again.",
                )
                await self._run(chat_log, inference, MODEL_PRO, EFFORT_FULL, turn, trail, escalate=False)
        except HandedOff as handed:
            del chat_log.content[keep:]
            trail.step("Handed to Claude Code", "This needs something the chat's tools can't do.")
            return self._say(
                user_input, chat_log, handed.reply, turn.route, "other", True, trail, turn, topic="handoff.other"
            )
        except openrouter.LimitReached:
            self.data.limit_reached()
            del chat_log.content[keep:]
            trail.reset()
            trail.step("The cloud agent stopped", "This month's allowance is used up")
            return self._say(user_input, chat_log, wording.OVER_LIMIT_REPLY, ROUTE_FALLBACK, "other", False)
        except openrouter.KeyRejected:
            del chat_log.content[keep:]
            trail.reset()
            trail.step("The cloud agent stopped", "The model provider didn't accept this house's key")
            return self._say(user_input, chat_log, wording.NOT_LINKED_REPLY, ROUTE_FALLBACK, "other", False)
        except openrouter.ModelError as why:
            _LOGGER.warning("Console: the cloud agent failed (%s)", why)
            del chat_log.content[keep:]
            trail.reset()
            trail.step(
                "The cloud agent failed",
                "Both models gave up on this request" if stronger else "The model gave up on this request, and the stronger one is switched off",
                ok=False,
            )
            return self._say(user_input, chat_log, wording.MODEL_FAILED_REPLY, turn.route, "other", False)
        finally:
            self.data.others.mark_own(began, time.time())

        category = turn.label or router.category_for_tools(turn.calls)
        topic = topics.for_turn(self._with_kinds(turn.calls), category)
        self.data.count_turn(turn.route, category, True, topic=topic)
        # Learn from it: a person who asked about a device's level (prefs.py). Never the house's own runs.
        self.data.prefs.after_turn(user_input.text, turn.asked, by_person=PATH.get() in (PATH_CHAT, PATH_VOICE, PATH_ASSIST))
        trail.meta(route=turn.route, cost_usd=turn.cost_usd, model_calls=turn.model_calls)
        _LOGGER.debug(
            "Console turn: route=%s category=%s model_calls=%s cost=%.5f ms=%d",
            turn.route, category, turn.model_calls, turn.cost_usd, (time.monotonic() - started) * 1000,
        )  # fmt: skip
        return conversation.async_get_result_from_chat_log(user_input, chat_log)

    def _earlier(self, chat_log: conversation.ChatLog) -> None:
        """A chat picked up where Home Assistant no longer remembers it (a restart, or a long pause):
        give the model the thread's last messages, once, at the start of a fresh chat log."""
        earlier = self.data.earlier.pop(chat_log.conversation_id, None)
        if not earlier or len(chat_log.content) > 2:
            return
        past: list[conversation.Content] = []
        for message in earlier:
            if message.get("who") == "you":
                past.append(conversation.UserContent(content=str(message.get("text") or "")))
            else:
                past.append(conversation.AssistantContent(agent_id=self.entity_id, content=str(message.get("text") or "")))
        chat_log.content[1:1] = past

    async def _local(
        self, user_input: conversation.ConversationInput, chat_log: conversation.ChatLog, trail: Trail
    ) -> conversation.ConversationResult | None:
        """Home Assistant's own agent: sentence triggers (learned sentences live there), then its
        built-in intents. None when it has no confident answer."""
        matched: dict[str, str] = {}

        def note(result) -> bool:
            matched["intent"] = result.intent.name
            kind = (getattr(result, "entities", None) or {}).get("domain")
            if kind is not None and isinstance(getattr(kind, "value", None), str):
                matched["domain"] = kind.value  # "light", from "the lights": a kind of thing, never a name
            return False  # never filter: this only records what matched

        try:
            said = await conversation.async_handle_sentence_triggers(self.hass, user_input, chat_log)
            if said is not None:
                response = intent.IntentResponse(language=user_input.language)
                response.async_set_speech(said)
                category = "control"
                topic = "learned.run"
            else:
                response = await conversation.async_handle_intents(
                    self.hass, user_input, chat_log, intent_filter=note
                )
                category = router.category_for_intent(matched.get("intent"))
                kinds = [state.domain for state in getattr(response, "matched_states", None) or []]
                topic = topics.for_intent(matched.get("intent"), kinds or matched.get("domain"))
        except Exception:  # noqa: BLE001 (whatever the local agent trips on, the cloud agent gets the turn)
            _LOGGER.exception("Console: the local agent failed")
            return None
        if response is None:
            trail.step("Tried at home first", "Home Assistant's own agent didn't recognise this sentence.")
            return None
        if response.response_type is intent.IntentResponseType.ERROR and self.data.cloud_state() in ("ok", "near_limit"):
            trail.step("Tried at home first", "Home Assistant recognised it but couldn't do it.", ok=False)
            return None  # matched but couldn't do it: let the cloud agent work out why
        speech = (response.speech.get("plain") or {}).get("speech") or ""
        chat_log.async_add_assistant_content_without_tools(
            conversation.AssistantContent(agent_id=user_input.agent_id, content=speech)
        )
        ok = response.response_type is not intent.IntentResponseType.ERROR
        self.data.count_turn(ROUTE_LOCAL, category, ok, topic=topic)
        trail.step(
            "Answered at home",
            "A sentence this house learned: no AI, no internet."
            if said is not None
            else "Home Assistant's own agent recognised it: no AI, no internet.",
        )
        trail.meta(route=ROUTE_LOCAL, cost_usd=0.0, model_calls=0)
        return conversation.ConversationResult(response=response, conversation_id=chat_log.conversation_id)

    def _touched(self, calls: list[llm.ToolInput], results: list[conversation.ToolResultContent]) -> tuple[set[str], set[tuple[str, str]]]:
        """What a round of tool calls did to devices: every device named in what was asked or what came back
        (and the speaker a music call was about), and the (device, setting) pairs a call set on purpose."""
        from . import music, prefs  # noqa: PLC0415

        found: set[str] = set()
        asked: set[tuple[str, str]] = set()
        for call, result in zip(calls, results, strict=False):
            args = call.tool_args or {}
            mine = prefs.entities_in(args) | prefs.entities_in(result.result.data)
            if _bare(call.tool_name) == "music" and args.get("op") in ("play", "control", "move"):
                for room in (args.get("room"), args.get("to")):
                    if room:
                        try:
                            mine.add(music._player(self.hass, str(room))["id"])  # noqa: SLF001
                        except music.Refused:
                            pass
            found |= mine
            if not result.result.error:
                asked |= prefs.asked(_bare(call.tool_name), args, mine)
        return found, asked

    def _with_kinds(self, calls: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
        """The same calls, with the kind of thing ("light") filled in where an intent tool was given only
        a name: the label is by kind, and the name goes no further than this lookup."""
        out = []
        for name, args in calls:
            named = args.get("name")
            if name.rsplit("__", 1)[-1].startswith("Hass") and not args.get("domain") and isinstance(named, str):
                wanted = named.casefold()
                kind = next((s.domain for s in self.hass.states.async_all() if s.name.casefold() == wanted), None)
                if kind:
                    args = args | {"domain": kind}
            out.append((name, args))
        return out

    def _say(
        self,
        user_input: conversation.ConversationInput,
        chat_log: conversation.ChatLog,
        words: str,
        route: str,
        category: str,
        ok: bool,
        trail: Trail | None = None,
        turn: Turn | None = None,
        topic: str = topics.NOTHING,
    ) -> conversation.ConversationResult:
        chat_log.async_add_assistant_content_without_tools(
            conversation.AssistantContent(agent_id=user_input.agent_id, content=words)
        )
        response = intent.IntentResponse(language=user_input.language)
        response.async_set_speech(words)
        self.data.count_turn(route, category, ok, topic=topic)
        if not ok:  # the agent couldn't do it: the chat card shows that conversation as errored
            self.data.unfinished.add(chat_log.conversation_id)
        if trail is not None and turn is not None:
            trail.meta(route=route, cost_usd=turn.cost_usd, model_calls=turn.model_calls)
        return conversation.ConversationResult(response=response, conversation_id=chat_log.conversation_id)

    async def _run(
        self,
        chat_log: conversation.ChatLog,
        inference: dict[str, Any],
        model: str,
        effort: str,
        turn: Turn,
        trail: Trail,
        *,
        escalate: bool,
    ) -> None:
        """Model calls and tool calls until the model answers in words."""
        session = async_get_clientsession(self.hass)
        offered: list[dict[str, Any]] = []
        if chat_log.llm_api:
            serializer = chat_log.llm_api.custom_serializer
            offered = [_tool_schema(tool, serializer) for tool in chat_log.llm_api.tools]
        offered.append(HANDOFF_TOOL)
        if escalate:
            offered.append(ESCALATE_TOOL)
        for _ in range(MAX_TOOL_ROUNDS if turn.route == ROUTE_FAST else MAX_TOOL_ROUNDS_FULL):
            messages = [m for content in chat_log.content if (m := _to_message(content))]
            gate = LabelGate()

            def on_delta(kind: str, piece: str, gate: LabelGate = gate) -> None:
                if kind == "thinking":
                    trail.thinking(piece)
                elif shown := gate.feed(piece):
                    trail.text(shown)

            done = await openrouter.complete(
                session, inference, model, messages, offered, effort, on_delta=on_delta if trail.live else None
            )
            turn.model_calls += 1
            turn.cost_usd += done.cost_usd
            self.data.add_spend(done.cost_usd, model=model)
            if done.thinking and not trail.live:
                trail.thinking(done.thinking)
            calls: list[llm.ToolInput] = []
            for call in done.message.get("tool_calls") or []:
                function = call.get("function") or {}
                try:
                    args = json.loads(function.get("arguments") or "{}")
                except ValueError as error:
                    raise openrouter.ModelError("tool arguments weren't JSON") from error
                if function.get("name") == ESCALATE:
                    raise Escalate
                if function.get("name") == HANDOFF:
                    raise HandedOff(wording.handoff(args if isinstance(args, dict) else {}))
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
            if text:
                trail.said(router.split_label(text)[0])
            keys = [trail.begin(*tool_step(_bare(call.tool_name), call.tool_args)) for call in calls]
            results = [
                result
                async for result in chat_log.async_add_assistant_content(
                    conversation.AssistantContent(agent_id=self.entity_id, content=None, tool_calls=calls)
                )
            ]
            for key, result in zip(keys, results, strict=False):
                trail.end(key, result.result.data, bool(result.result.error))
            touched, asked = self._touched(calls, results)
            self.data.prefs.agent_touched(touched)
            turn.touched |= touched
            turn.asked |= asked
            if turn.route == ROUTE_FAST and (reply := confirmed_reply(calls, results)):
                turn.label = "control"
                rows = [row for result in results for row in result.result.data["results"]]
                if self.data.learned.observe(turn.text, calls, rows):
                    reply += " " + wording.LEARNED
                trail.step("Answered from the read-back", "Every device confirmed the change, so no second model call was needed.")
                chat_log.async_add_assistant_content_without_tools(
                    conversation.AssistantContent(agent_id=self.entity_id, content=reply)
                )
                return
        raise openrouter.ModelError("too many tool rounds")
