"""The chat card's own channel: a turn told as it happens, kept on the box, and handed to Claude Code
when the chat can't do it."""

from __future__ import annotations

import json

from homeassistant.helpers import llm

from custom_components.console import openrouter, wording
from custom_components.console.credits import credits
from custom_components.console.trail import LabelGate

from .conftest import link


async def chat(hass, hass_ws_client, text: str, client=None, **extra) -> tuple[dict, list[dict]]:
    """Send one message the way the card does: the command's answer, then every event up to `done`."""
    client = client or await hass_ws_client(hass)
    chat.n = getattr(chat, "n", 0) + 1
    await client.send_json({"id": chat.n, "type": "console/chat", "text": text, **extra})
    answer = await client.receive_json()
    assert answer["success"], answer
    events = []
    while True:
        event = (await client.receive_json())["event"]
        events.append(event)
        if event["kind"] == "done":
            return answer["result"], events


def kinds(events: list[dict]) -> list[str]:
    return [e["kind"] for e in events]


def titles(events: list[dict]) -> list[str]:
    return [e["title"] for e in events if e["kind"] == "step" and e.get("title")]


async def test_a_local_turn_says_it_was_answered_at_home(hass, console, model, lights_off, hass_ws_client):
    link(console)
    result, events = await chat(hass, hass_ws_client, "turn off the kitchen light")
    assert result["conversation_id"].startswith("console-")
    assert titles(events) == ["Answered at home"]
    done = events[-1]
    assert done["reply"] and done["error"] is False and done["conversation_id"] == result["conversation_id"]
    assert [e for e in events if e["kind"] == "meta"][0]["route"] == "local"
    assert model.calls == []


async def test_a_cloud_turn_streams_its_route_its_thinking_and_its_words(hass, console, model, hass_ws_client):
    link(console)
    model.say("Two lights are on: the kitchen and the hall. [[status]]", thinking="They asked which lights. I can read that from the list.")
    _, events = await chat(hass, hass_ws_client, "which lights did we leave on downstairs and should I worry")
    assert titles(events) == ["Tried at home first", "Sent to the cloud agent"]
    route = [e for e in events if e["kind"] == "step" and e.get("title") == "Sent to the cloud agent"][0]
    assert "DeepSeek V4.1 Flash" in route["detail"] and "a little thinking" in route["detail"]
    assert "".join(e["text"] for e in events if e["kind"] == "thinking") == "They asked which lights. I can read that from the list."
    streamed = "".join(e["text"] for e in events if e["kind"] == "text")
    assert streamed.strip() == "Two lights are on: the kitchen and the hall."  # the label never reaches the card
    assert events[-1]["reply"] == "Two lights are on: the kitchen and the hall."
    meta = [e for e in events if e["kind"] == "meta"][0]
    assert meta["route"] == "flash" and meta["cost_usd"] == 0.001 and meta["model_calls"] == 1


async def test_each_tool_shows_as_a_step_with_what_came_back(hass, console, model, lights_off, hass_ws_client):
    link(console)
    model.script.append({"role": "assistant", "content": "Let me do that.", "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "assist__intent__HassTurnOff", "arguments": json.dumps({"name": "Kitchen light"})}}]})
    model.say("The kitchen light is off. [[control]]")
    _, events = await chat(hass, hass_ws_client, "could you make the kitchen dark for the movie")
    steps = [e for e in events if e["kind"] == "step"]
    started = [e for e in steps if e.get("title") == "Home Assistant action TurnOff"][0]
    assert started["state"] == "running" and "Kitchen light" in started["detail"]
    finished = [e for e in steps if e["key"] == started["key"] and "result" in e][0]
    assert finished["state"] == "done" and finished["result"]
    said = [e for e in events if e["kind"] == "said"][0]
    assert said["text"] == "Let me do that."  # words before a tool move into the steps
    assert events[-1]["reply"] == "The kitchen light is off."


async def test_a_hand_up_to_the_stronger_model_is_a_step_and_voids_what_was_written(hass, console, model, hass_ws_client):
    link(console)
    model.call_tool("console_escalate", {"reason": "multi-step"})
    model.say("Here's the plan. [[customization]]")
    _, events = await chat(hass, hass_ws_client, "design a full set of routines for a week away and explain each one")
    assert "reset" in kinds(events)
    handed = [e for e in events if e["kind"] == "step" and e.get("title") == "Handed to the stronger model"][0]
    assert "DeepSeek V4 Pro" in handed["detail"] and "asked for help" in handed["detail"]
    assert events[-1]["reply"] == "Here's the plan."


async def test_the_label_is_held_back_however_the_stream_is_cut():
    for size in (1, 2, 3, 5, 50):
        gate, shown = LabelGate(), ""
        text = "It has [[two]] modes. Done [[control]]"
        for start in range(0, len(text), size):
            shown += gate.feed(text[start : start + size])
        assert shown.strip() == "It has [[two]] modes. Done", size


async def test_what_the_chat_cannot_do_is_handed_to_claude_code(hass, console, model, hass_ws_client):
    link(console)
    model.call_tool("console_handoff", {
        "asked": "Fix the Wi-Fi channel on my router",
        "why": "it needs the router's own settings page",
        "found": "Kitchen Ceiling 1 drops off 2.4 GHz every few hours; token eyJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJhYmMifQ.abcdefghijklmnop was in the log",
        "next": "Open the router's page, sign in with me, and move 2.4 GHz to channel 1, 6 or 11.",
    })
    _, events = await chat(hass, hass_ws_client, "can you change my router's wifi channel")
    reply = events[-1]["reply"]
    assert reply.startswith("I can't do that from this chat (it needs the router's own settings page). Claude Code can.")
    assert "1. Open Claude Code on a computer on your home network." in reply and "```text" in reply
    block = reply.split("```text\n")[1].split("\n```")[0]
    assert "What I asked Console's chat: Fix the Wi-Fi channel on my router" in block
    assert "What I need you to do: Open the router's page" in block
    assert "never ask me to paste a password" in block
    assert "eyJhbGci" not in reply and "[removed]" in block  # nothing token-shaped gets through
    assert "Handed to Claude Code" in titles(events)
    assert len(model.calls) == 1  # no second model call: the handoff is the reply


async def test_a_conversation_is_kept_on_the_box_and_comes_back_ten_at_a_time(hass, console, model, hass_ws_client):
    link(console)
    client = await hass_ws_client(hass)
    for n in range(12):
        model.say(f"Answer {n}. [[other]]")
        await chat(hass, hass_ws_client, f"question number {n} about the garden", client)
    await client.send_json({"id": 900, "type": "console/chat/history"})
    newest = (await client.receive_json())["result"]
    assert newest["total"] == 24 and len(newest["messages"]) == 10 and newest["more"] is True
    assert [m["who"] for m in newest["messages"][-2:]] == ["you", "console"]
    assert newest["messages"][-1]["text"] == "Answer 11."
    await client.send_json({"id": 901, "type": "console/chat/history", "before": newest["from"]})
    earlier = (await client.receive_json())["result"]
    assert len(earlier["messages"]) == 10 and earlier["messages"][-1]["text"] == "Answer 6."
    assert earlier["from"] == 4 and earlier["more"] is True

    # It is in its own file, never in Console's store or in anything the relay reads.
    await console.async_save_now()
    assert "garden" not in json.dumps(console.data) and "garden" not in json.dumps(console.summary())

    await client.send_json({"id": 902, "type": "console/chat/clear"})
    assert (await client.receive_json())["result"] == {"deleted": 24}
    await client.send_json({"id": 903, "type": "console/knows"})
    assert (await client.receive_json())["result"]["my_chat_messages"] == 0


async def test_each_person_has_their_own_history(hass, console, model, hass_ws_client, hass_read_only_access_token):
    link(console)
    model.say("Hello. [[other]]")
    await chat(hass, hass_ws_client, "this is the owner speaking")
    other = await hass_ws_client(hass, hass_read_only_access_token)
    await other.send_json({"id": 1, "type": "console/chat/history"})
    assert (await other.receive_json())["result"]["total"] == 0


async def test_earlier_messages_on_screen_are_given_to_the_model_after_a_reload(hass, console, model, hass_ws_client):
    link(console)
    model.say("Her name is Priya. [[other]]")
    await chat(hass, hass_ws_client, "my sister is called Priya")
    model.say("Priya. [[other]]")
    await chat(hass, hass_ws_client, "what is my sister called", earlier=2)  # a new conversation, two earlier shown
    sent = [m["content"] for m in model.calls[-1]["messages"] if m["role"] in ("user", "assistant")]
    assert sent[:2] == ["my sister is called Priya", "Her name is Priya."] and sent[-1] == "what is my sister called"


async def test_the_card_is_also_a_dashboard_resource_for_the_phone_apps(hass, console):
    from homeassistant.components.lovelace.const import LOVELACE_DATA

    from custom_components.console import dashboard

    urls = [item["url"] for item in hass.data[LOVELACE_DATA].resources.async_items()]
    assert len(urls) == 1 and urls[0].startswith("/console_static/console-chat-card.js?v=")
    assert await dashboard.ensure_resource(hass, urls[0]) == "unchanged"
    assert await dashboard.ensure_resource(hass, "/console_static/console-chat-card.js?v=9.9.9") == "updated"
    assert len(hass.data[LOVELACE_DATA].resources.async_items()) == 1


def test_usage_is_counted_in_credits_one_cent_each():
    assert credits(1.0) == 100 and credits(0.1201) == 12 and credits(0.05) == 5.0 and credits(0.0006) == 0.06


async def test_the_status_shows_credits_and_never_needs_dollars(hass, console, hass_ws_client):
    link(console, cap=2.0)
    console.add_spend(0.25)
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "console/status"})
    assert (await client.receive_json())["result"]["credits"] == {"used": 25, "allowed": 200}


class _Lines:
    def __init__(self, lines: list[str]) -> None:
        self._lines = [line.encode() + b"\n" for line in lines]

    def __aiter__(self):
        return self

    async def __anext__(self) -> bytes:
        if not self._lines:
            raise StopAsyncIteration
        return self._lines.pop(0)


class _Answer:
    def __init__(self, status: int, lines: list[str]) -> None:
        self.status, self.content = status, _Lines(lines)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def json(self, content_type=None):
        return {"error": {"code": self.status}}


class _Session:
    def __init__(self, status: int, lines: list[str]) -> None:
        self.status, self.lines, self.sent = status, lines, None

    def post(self, url, json=None, headers=None):
        self.sent = json
        return _Answer(self.status, self.lines)


def _chunk(**delta) -> str:
    return "data: " + json.dumps({"model": "deepseek/deepseek-v4.1-flash", "choices": [{"delta": delta}]})


async def test_a_streamed_answer_is_put_back_together():
    heard = []
    session = _Session(200, [
        ": OPENROUTER PROCESSING", "",
        _chunk(reasoning="Kitchen. "), _chunk(reasoning="Play it."),
        _chunk(content="Playing "), _chunk(content="now."),
        _chunk(tool_calls=[{"index": 0, "id": "call_9", "function": {"name": "console__music", "arguments": '{"op":'}}]),
        _chunk(tool_calls=[{"index": 0, "function": {"arguments": '"play"}'}}]),
        "data: " + json.dumps({"choices": [], "usage": {"cost": 0.0007}}),
        "data: [DONE]",
    ])
    done = await openrouter.complete(session, {"key": "k", "base_url": "https://example.test/api/v1"}, "m", [], [], "low", on_delta=lambda kind, piece: heard.append((kind, piece)))
    assert session.sent["stream"] is True
    assert heard == [("thinking", "Kitchen. "), ("thinking", "Play it."), ("text", "Playing "), ("text", "now.")]
    assert done.message["content"] == "Playing now." and done.thinking == "Kitchen. Play it." and done.cost_usd == 0.0007
    assert done.message["tool_calls"] == [{"id": "call_9", "type": "function", "function": {"name": "console__music", "arguments": '{"op":"play"}'}}]


async def test_a_spent_key_and_a_broken_stream_are_told_apart():
    import pytest

    inference = {"key": "k", "base_url": "https://example.test/api/v1"}
    with pytest.raises(openrouter.LimitReached):
        await openrouter.complete(_Session(402, []), inference, "m", [], [], "low", on_delta=lambda *_: None)
    with pytest.raises(openrouter.KeyRejected):
        await openrouter.complete(_Session(401, []), inference, "m", [], [], "low", on_delta=lambda *_: None)
    broken = _Session(200, [_chunk(content="Half"), "data: " + json.dumps({"error": {"code": 502}, "choices": []})])
    with pytest.raises(openrouter.ModelError):
        await openrouter.complete(broken, inference, "m", [], [], "low", on_delta=lambda *_: None)


async def test_the_wording_of_the_off_replies_names_cloud_access(hass, console):
    assert "cloud access is turned off" in wording.CLOUD_OFF_REPLY
    assert "only be turned back on from inside the house" in wording.CLOUD_OFF
    assert llm  # the tools module is importable alongside


async def test_the_card_is_not_in_the_pages_start_up_list(hass, console, hass_client):
    """Loaded from there it can register before Home Assistant swaps its element registry, and be lost:
    the 'Configuration error' the phone and tablet apps showed. It re-registers itself if dropped."""
    from homeassistant.components import frontend

    assert not [url for url in hass.data[frontend.DATA_EXTRA_MODULE_URL].urls if "console-chat-card" in url]
    client = await hass_client()
    script = await (await client.get("/console_static/console-chat-card.js")).text()
    assert "setTimeout(register" in script and "class extends ConsoleChatCard" in script


async def test_the_card_shows_thinking_as_one_line_with_the_rest_a_tap_away(hass, console, hass_client):
    """Owner, 2026-11-27: the model's whole thinking, streamed, was too noisy. Each thinking step shows its
    first sentence (at most GIST characters); "Show all" opens the full text."""
    client = await hass_client()
    script = await (await client.get("/console_static/console-chat-card.js")).text()
    assert "const gist = (text)" in script and "thinking.d.textContent = gist(thinking.full)" in script
    assert '"Show all"' in script and "thinking.d.textContent += event.text" not in script
