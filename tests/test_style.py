"""Reply style: the `chat_history` tool reads only the asking person's own chat, and the weekly run fires
Sunrise's match-my-style skill once per person who has enough chat, as that person."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json

from homeassistant.core import Context
from homeassistant.helpers import llm

from custom_components.console import style as S
from custom_components.console.const import DOMAIN

from .conftest import ask, link


def chat(console, user_id: str, n: int, *, start: datetime | None = None) -> None:
    """n exchanges for one person: their message, then Console's reply."""
    start = start or datetime.now(UTC) - timedelta(hours=n)
    mine = console.history.people.setdefault(user_id, [])
    for i in range(n):
        at = (start + timedelta(hours=i)).isoformat()
        mine.append({"at": at, "who": "you", "text": f"{user_id} says {i}"})
        mine.append({"at": at, "who": "console", "text": f"reply {i}"})


async def read(hass, user_id: str | None, **args):
    ctx = llm.LLMContext(platform=DOMAIN, context=Context(user_id=user_id), language="en", assistant="conversation", device_id=None)
    api = await llm.async_get_api(hass, DOMAIN, ctx)
    result = await api.async_call_tool(llm.ToolInput(tool_name="chat_history", tool_args=args))
    return getattr(result, "data", result)


async def test_chat_history_is_only_the_asking_persons_own(hass, console, hass_admin_user, hass_read_only_user):
    chat(console, hass_admin_user.id, 3)
    chat(console, hass_read_only_user.id, 2)

    mine = await read(hass, hass_admin_user.id)
    assert mine["count"] == 6 and mine["yours"] == 3
    assert all(hass_read_only_user.id not in m["text"] for m in mine["messages"])
    assert [m["who"] for m in mine["messages"][:2]] == ["you", "console"]  # oldest first

    theirs = await read(hass, hass_read_only_user.id)
    assert theirs["count"] == 4
    assert all(hass_admin_user.id not in m["text"] for m in theirs["messages"])


async def test_chat_history_is_refused_with_nobody_signed_in(hass, console, hass_admin_user):
    chat(console, hass_admin_user.id, 3)
    out = await read(hass, None)
    assert "error" in out and "messages" not in out


async def test_chat_history_limit_and_days(hass, console, hass_admin_user):
    old = datetime.now(UTC) - timedelta(days=40)
    chat(console, hass_admin_user.id, 2, start=old)
    chat(console, hass_admin_user.id, 3)

    assert (await read(hass, hass_admin_user.id, days=30))["yours"] == 3
    assert (await read(hass, hass_admin_user.id, limit=2))["count"] == 2
    assert (await read(hass, hass_admin_user.id, limit=5000))["count"] == 10  # capped at 200, all 10 fit


async def test_the_chat_agent_is_given_the_tool(hass, console, model, hass_admin_user):
    link(console)
    model.say("You asked for night mode. [[other]]")
    await ask(hass, "what did I ask you yesterday about the lights", Context(user_id=hass_admin_user.id))
    names = [t["function"]["name"].rsplit("__", 1)[-1] for t in model.calls[0]["tools"]]
    assert "chat_history" in names


async def test_weekly_run_is_one_turn_per_person_as_that_person(hass, console, model, hass_admin_user, hass_read_only_user, monkeypatch):
    link(console)
    chat(console, hass_admin_user.id, S.MIN_MESSAGES)
    chat(console, hass_read_only_user.id, S.MIN_MESSAGES - 1)  # not enough to go on: skipped
    seen: list[str | None] = []

    async def converse(hass_, text, conversation_id, context, language=None, agent_id=None, **kw):
        assert S.SKILL in text and agent_id == "conversation.console"
        seen.append((context.user_id, console.via.get(context.id)))

    from homeassistant.components import conversation

    monkeypatch.setattr(conversation, "async_converse", converse)
    out = await console.style.run()
    assert out == {"ran": True, "why": None, "people": 1}
    assert seen == [(hass_admin_user.id, "style")]  # counted on the Plan tab as its own line
    assert console.via == {}
    assert console.data["style"]["last_run"]["people"] == 1
    assert hass_admin_user.id not in json.dumps(console.data["style"])  # Console's store keeps counts, not people


async def test_weekly_run_waits_for_the_cloud_agent_and_for_enough_chat(hass, console, hass_admin_user):
    chat(console, hass_admin_user.id, S.MIN_MESSAGES)
    assert (await console.style.run())["why"].startswith("cloud agent")  # not linked
    link(console)
    console.history.people.clear()
    assert (await console.style.run())["why"] == "not enough chat yet"


async def test_weekly_run_fires_only_on_sunday(hass, console, monkeypatch):
    calls = []

    async def run(**kw):
        calls.append(1)

    monkeypatch.setattr(console.style, "run", run)
    saturday, sunday = datetime(2026, 11, 28, 10, 23), datetime(2026, 11, 29, 10, 23)
    await console.style._tick(saturday)
    await console.style._tick(sunday)
    assert calls == [1]
