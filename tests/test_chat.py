"""The chat card's own channel: a turn told as it happens, kept on the box in the thread it belongs to
with the steps behind each reply, and handed to Claude Code when the chat can't do it."""

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


async def test_a_chat_is_a_thread_kept_on_the_box_and_comes_back_ten_at_a_time(hass, console, model, hass_ws_client):
    link(console)
    client = await hass_ws_client(hass)
    thread = None
    for n in range(12):
        model.say(f"Answer {n}. [[other]]")
        result, _ = await chat(hass, hass_ws_client, f"question number {n} about the garden", client, **({"thread_id": thread} if thread else {}))
        thread = thread or result["thread_id"]
        assert result["thread_id"] == thread  # every message went into the one chat
    await client.send_json({"id": 900, "type": "console/chat/history", "thread_id": thread})
    newest = (await client.receive_json())["result"]
    assert newest["total"] == 24 and len(newest["messages"]) == 10 and newest["more"] is True and newest["working"] is False
    assert newest["title"] == "question number 0 about the garden"  # a chat is called what it was started with
    assert [m["who"] for m in newest["messages"][-2:]] == ["you", "console"]
    assert newest["messages"][-1]["text"] == "Answer 11."
    await client.send_json({"id": 901, "type": "console/chat/history", "thread_id": thread, "before": newest["from"]})
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


async def test_the_work_behind_a_reply_is_kept_in_its_thread(hass, console, model, lights_off, hass_ws_client):
    """Owner, 2026-11-28: show each chat and the agent's work within the thread of a chat. So a reply is
    stored with its steps (where it went, the thinking, each tool and what came back) and its facts."""
    link(console)
    model.script.append({"role": "assistant", "content": "Let me do that.", "thinking": "They want it dark. Turn the kitchen light off.", "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "assist__intent__HassTurnOff", "arguments": json.dumps({"name": "Kitchen light"})}}]})
    model.say("The kitchen light is off. [[control]]")
    client = await hass_ws_client(hass)
    result, _ = await chat(hass, hass_ws_client, "could you make the kitchen dark for the movie", client)
    await client.send_json({"id": 950, "type": "console/chat/history", "thread_id": result["thread_id"]})
    you, reply = (await client.receive_json())["result"]["messages"]
    assert you == {"at": you["at"], "who": "you", "text": "could you make the kitchen dark for the movie"}  # nothing extra on a person's own message
    steps = reply["steps"]
    assert [s["title"] for s in steps] == ["Tried at home first", "Sent to the cloud agent", "Thinking", "Said", "Home Assistant action TurnOff"]
    assert steps[2] == {"kind": "think", "title": "Thinking", "detail": "They want it dark. Turn the kitchen light off."}
    assert steps[3]["detail"] == "Let me do that." and "Kitchen light" in steps[4]["detail"] and steps[4]["result"]
    assert reply["meta"]["route"] == "flash" and reply["meta"]["cost_usd"] == 0.002 and reply["meta"]["ms"] >= 0
    # Still on the box only: the steps are in the chat file, not in Console's store.
    assert "make the kitchen dark" not in json.dumps(console.data) and "Tried at home first" not in json.dumps(console.data)


async def test_chats_are_listed_newest_first_and_one_can_be_deleted(hass, console, model, hass_ws_client):
    link(console)
    client = await hass_ws_client(hass)
    model.say("Roses like sun. [[other]]")
    first, _ = await chat(hass, hass_ws_client, "where should the roses go in the garden", client)
    model.say("Tuesday. [[other]]")
    second, _ = await chat(hass, hass_ws_client, "when is the recycling collected on our street", client)
    assert first["thread_id"] != second["thread_id"]  # a message with no chat named starts a new one
    await client.send_json({"id": 960, "type": "console/chat/threads"})
    threads = (await client.receive_json())["result"]["threads"]
    assert [t["title"] for t in threads] == ["when is the recycling collected on our street", "where should the roses go in the garden"]
    assert threads[0]["count"] == 2 and threads[0]["last"] == "Tuesday." and threads[0]["working"] is False
    await client.send_json({"id": 961, "type": "console/chat/history"})  # no chat named: the one used last
    assert (await client.receive_json())["result"]["thread_id"] == second["thread_id"]
    await client.send_json({"id": 962, "type": "console/chat/thread/delete", "thread_id": second["thread_id"]})
    assert (await client.receive_json())["result"] == {"deleted": 2}
    await client.send_json({"id": 963, "type": "console/chat/threads"})
    assert [t["id"] for t in (await client.receive_json())["result"]["threads"]] == [first["thread_id"]]


async def test_a_history_from_before_threads_becomes_one_chat(hass, console):
    from custom_components.console.history import EARLIER, ChatHistory

    old = [{"at": "2026-11-01T10:00:00+00:00", "who": "you", "text": "hello"}, {"at": "2026-11-01T10:00:02+00:00", "who": "console", "text": "Hi."}]
    [thread] = ChatHistory._threads(old)  # noqa: SLF001
    assert thread["title"] == EARLIER and thread["messages"] == old and thread["id"].startswith("console-")
    assert ChatHistory._threads([thread]) == [thread]  # noqa: SLF001 (already threads: left as they are)


async def test_each_person_has_their_own_chats(hass, console, model, hass_ws_client, hass_read_only_access_token):
    link(console)
    model.say("Hello. [[other]]")
    mine, _ = await chat(hass, hass_ws_client, "this is the owner speaking")
    other = await hass_ws_client(hass, hass_read_only_access_token)
    await other.send_json({"id": 1, "type": "console/chat/history"})
    assert (await other.receive_json())["result"]["total"] == 0
    await other.send_json({"id": 2, "type": "console/chat/history", "thread_id": mine["thread_id"]})
    assert (await other.receive_json())["result"]["total"] == 0  # naming someone's chat shows nothing of it
    model.say("Hi. [[other]]")
    theirs, _ = await chat(hass, hass_ws_client, "let me into that chat please", other, thread_id=mine["thread_id"])
    assert theirs["thread_id"] != mine["thread_id"]  # nor can they write into it: they get a chat of their own
    assert "owner speaking" not in json.dumps(model.calls[-1]["messages"])


async def test_a_thread_picked_up_later_gives_the_model_what_was_said_in_it(hass, console, model, hass_ws_client):
    from homeassistant.helpers.chat_session import DATA_CHAT_SESSION

    link(console)
    client = await hass_ws_client(hass)
    model.say("Her name is Priya. [[other]]")
    first, _ = await chat(hass, hass_ws_client, "my sister is called Priya", client)
    model.say("Something else. [[other]]")
    await chat(hass, hass_ws_client, "this is a different chat about the boiler", client)
    for session in list(hass.data[DATA_CHAT_SESSION].values()):  # Home Assistant forgets its conversations (a restart)
        session.async_cleanup()
    model.say("Priya. [[other]]")
    await chat(hass, hass_ws_client, "what is my sister called", client, thread_id=first["thread_id"])
    sent = [m["content"] for m in model.calls[-1]["messages"] if m["role"] in ("user", "assistant")]
    assert sent == ["my sister is called Priya", "Her name is Priya.", "what is my sister called"]  # that thread, and only it


async def test_a_card_that_opens_a_chat_mid_turn_watches_the_turn_and_the_reply_is_kept_without_it(hass, console, model, hass_ws_client):
    """The streaming bugs (2026-11-28): a card that reloaded or reconnected mid-turn waited for ever, and
    its reconnect sent the message again. Now the turn runs whoever is listening, a card that opens the
    chat meanwhile is told everything so far and then the rest, and one message is one turn."""
    import asyncio

    link(console)
    gate, entered = asyncio.Event(), asyncio.Event()
    real = model.complete

    async def slow(*args, **kwargs):
        on_delta = kwargs.get("on_delta")
        if on_delta:
            on_delta("thinking", "Let me look.")
        entered.set()
        await gate.wait()
        kwargs["on_delta"] = None
        return await real(*args, **kwargs)

    model.complete = slow
    from custom_components.console import openrouter as provider

    provider.complete = slow
    model.say("All quiet in the garden. [[status]]")
    asker = await hass_ws_client(hass)
    await asker.send_json({"id": 1, "type": "console/chat", "text": "is anything odd going on in the garden tonight"})
    thread = (await asker.receive_json())["result"]["thread_id"]
    await entered.wait()

    await asker.send_json({"id": 2, "type": "console/chat", "text": "and again", "thread_id": thread})
    while (busy := await asker.receive_json())["id"] != 2:
        pass
    assert busy["success"] is False and busy["error"]["code"] == "busy"  # one turn at a time in a chat

    late = await hass_ws_client(hass)
    await late.send_json({"id": 1, "type": "console/chat/history", "thread_id": thread})
    page = (await late.receive_json())["result"]
    assert page["working"] is True and [m["who"] for m in page["messages"]] == ["you"]
    await late.send_json({"id": 2, "type": "console/chat/watch", "thread_id": thread})
    assert (await late.receive_json())["result"] == {"working": True}
    caught_up = [(await late.receive_json())["event"] for _ in range(4)]
    assert caught_up[0] == {"kind": "thread", "thread_id": thread, "scope": "all"}
    assert [e.get("title") or e["kind"] for e in caught_up[1:]] == ["Tried at home first", "Sent to the cloud agent", "thinking"]

    await asker.close()  # the card that asked goes away mid-turn
    await hass.async_block_till_done()
    gate.set()
    while (event := (await late.receive_json())["event"])["kind"] != "done":
        pass
    assert event["reply"] == "All quiet in the garden." and event["thread_id"] == thread
    assert console.live == {} and console.streams == {}
    replies = [m for m in console.history.page(late_user(console), thread)["messages"] if m["who"] == "console"]
    assert len(replies) == 1 and replies[0]["text"] == "All quiet in the garden." and len(model.calls) == 1

    await late.send_json({"id": 3, "type": "console/chat/watch", "thread_id": thread})
    assert (await late.receive_json())["result"] == {"working": False}  # nothing running any more
    assert (await late.receive_json())["event"] == {"kind": "gone"}  # so a card that was waiting reads the thread instead


def late_user(console) -> str:
    [user_id] = list(console.history.people)
    return user_id


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


async def test_the_card_keeps_one_turn_one_message_and_shows_conversations_as_comment_threads(hass, console, hass_client):
    """What the card must do for the server's promises to hold: never send a message again when its
    connection comes back, pick a running turn up by watching it, and show each conversation as a comment
    thread (owner, 2026-11-28: "i need it to look like facebook comment threads"): what started it, the
    replies under it, a Reply under each, and copying one conversation or all of them."""
    client = await hass_client()
    script = await (await client.get("/console_static/console-chat-card.js")).text()
    assert "resubscribe: false" in script  # Home Assistant would otherwise send the chat command again on reconnect
    assert '"console/chat/watch"' in script and 'addEventListener("ready"' in script
    assert '"console/chat/feed"' in script and '"console/chat/export"' in script and '"console/chat/thread/delete"' in script
    assert 'el("div", "replies")' in script and "View earlier conversations" in script and '"Reply"' in script
    assert "Copy all" in script and "Copy conversation" in script
    assert '"console/suggestions/seen"' in script and "_drawSuggested" in script and "_drawQuick" in script


async def test_the_feed_is_each_conversation_with_its_newest_replies_and_the_rest_a_tap_away(hass, console, model, hass_ws_client):
    link(console)
    client = await hass_ws_client(hass)
    model.say("Roses like sun. [[other]]")
    roses, _ = await chat(hass, hass_ws_client, "where should the roses go in the garden", client)
    for n in range(3):
        model.say(f"Answer {n}. [[other]]")
        await chat(hass, hass_ws_client, f"and question {n} about roses", client, thread_id=roses["thread_id"])
    model.say("Tuesday. [[other]]")
    bins, _ = await chat(hass, hass_ws_client, "when is the recycling collected on our street", client)

    await client.send_json({"id": 970, "type": "console/chat/feed", "limit": 1})
    page = (await client.receive_json())["result"]
    assert [t["id"] for t in page["threads"]] == [bins["thread_id"]] and page["more"] is True  # the one used last first
    await client.send_json({"id": 971, "type": "console/chat/feed", "skip": 1, "limit": 5})
    page = (await client.receive_json())["result"]
    [thread] = page["threads"]
    assert page["more"] is False and thread["working"] is False and thread["total"] == 8
    assert thread["root"]["text"] == "where should the roses go in the garden"  # what started it, always shown
    assert [m["text"] for m in thread["replies"]] == ["and question 2 about roses", "Answer 2."] and thread["from"] == 6
    await client.send_json({"id": 972, "type": "console/chat/history", "thread_id": roses["thread_id"], "before": thread["from"], "limit": 10})
    earlier = (await client.receive_json())["result"]
    assert earlier["from"] == 0 and [m["text"] for m in earlier["messages"]][1:3] == ["Roses like sun.", "and question 0 about roses"]
    await client.send_json({"id": 973, "type": "console/chat/feed", "thread_id": bins["thread_id"]})
    assert [t["root"]["text"] for t in (await client.receive_json())["result"]["threads"]] == ["when is the recycling collected on our street"]


async def test_a_new_conversation_sees_the_others_and_a_reply_sees_only_its_own(hass, console, model, hass_ws_client):
    """Owner, 2026-11-28: capture "the full set of conversations or a single conversation depending on the
    scope of the message". Where it is written says which: a new conversation is told about the person's
    other recent ones; a reply is kept to its own conversation and pointed at chat_history for the rest."""
    link(console)
    client = await hass_ws_client(hass)
    model.say("Her name is Priya. [[other]]")
    sister, events = await chat(hass, hass_ws_client, "my sister is called Priya", client)
    assert events[0] == {"kind": "thread", "thread_id": sister["thread_id"], "scope": "all"}
    assert "no other conversations with you yet" in model.calls[-1]["messages"][0]["content"]
    model.say("Every other Tuesday. [[other]]")
    await chat(hass, hass_ws_client, "the boiler gets serviced every other tuesday", client)

    model.say("You told me about your sister Priya and the boiler. [[other]]")
    _, events = await chat(hass, hass_ws_client, "what have we talked about so far", client)
    assert events[0]["scope"] == "all"
    system = model.calls[-1]["messages"][0]["content"]
    assert "other recent conversations" in system
    assert system.index("the boiler gets serviced") < system.index("my sister is called Priya")  # newest first
    assert "They: my sister is called Priya / You: Her name is Priya." in system

    model.say("Priya. [[other]]")
    _, events = await chat(hass, hass_ws_client, "remind me of her name", client, thread_id=sister["thread_id"])
    assert events[0]["scope"] == "conversation"
    system = model.calls[-1]["messages"][0]["content"]
    assert "reply inside one of this person's conversations" in system and "“my sister is called Priya”" in system
    assert "boiler" not in json.dumps(model.calls[-1]["messages"])  # the other conversation stays out of a reply
    assert console.scope == {}  # nothing left behind for the next turn


async def test_one_conversation_or_all_of_them_can_be_copied_as_text(hass, console, model, hass_ws_client, hass_admin_user):
    link(console)
    client = await hass_ws_client(hass)
    model.say("Her name is Priya. [[other]]")
    sister, _ = await chat(hass, hass_ws_client, "my sister is called Priya", client)
    model.say("Every other Tuesday. [[other]]")
    await chat(hass, hass_ws_client, "the boiler gets serviced every other tuesday", client)
    await client.send_json({"id": 980, "type": "console/chat/export", "thread_id": sister["thread_id"]})
    one = (await client.receive_json())["result"]
    name = hass_admin_user.name
    assert one["conversations"] == 1 and one["messages"] == 2
    assert one["text"].startswith("my sister is called Priya (") and f"{name}: my sister is called Priya\n\nConsole: Her name is Priya." in one["text"]
    assert "boiler" not in one["text"] and "Tried at home first" not in one["text"]  # that conversation only, and no steps
    await client.send_json({"id": 981, "type": "console/chat/export"})
    every = (await client.receive_json())["result"]
    assert every["conversations"] == 2 and every["text"].index("Priya") < every["text"].index("boiler")  # oldest first


async def test_chat_history_says_which_conversation_each_message_is_in(hass, console, model, hass_ws_client, hass_admin_user):
    from homeassistant.core import Context
    from homeassistant.helpers import llm

    from custom_components.console.const import DOMAIN

    link(console)
    client = await hass_ws_client(hass)
    model.say("Her name is Priya. [[other]]")
    sister, _ = await chat(hass, hass_ws_client, "my sister is called Priya", client)
    model.say("Every other Tuesday. [[other]]")
    await chat(hass, hass_ws_client, "the boiler gets serviced every other tuesday", client)
    ctx = llm.LLMContext(platform=DOMAIN, context=Context(user_id=hass_admin_user.id), language="en", assistant="conversation", device_id=None)
    api = await llm.async_get_api(hass, DOMAIN, ctx)
    got = (await api.async_call_tool(llm.ToolInput(tool_name="chat_history", tool_args={}))).data
    assert [m["conversation"] for m in got["messages"]] == ["my sister is called Priya"] * 2 + ["the boiler gets serviced every other tuesday"] * 2
    one = (await api.async_call_tool(llm.ToolInput(tool_name="chat_history", tool_args={"thread_id": sister["thread_id"]}))).data
    assert [m["text"] for m in one["messages"]] == ["my sister is called Priya", "Her name is Priya."]
