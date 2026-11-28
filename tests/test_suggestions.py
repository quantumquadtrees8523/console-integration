"""Suggested routines: the setting, the hourly and Monday runs (each one turn of the agent, guided by Sunrise's
skill), Flash with thinking off and never Pro, live routines with Keep and Undo, pruning, and the wipe.

Sunrise's routine tool is stood in for here by a small fake with the same ops and answers (Sunrise's own
tests run the real one against Home Assistant's automations)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

from custom_components.console import suggestions as S

from .conftest import link

CONFIG = {
    "alias": "Kitchen light off at night",
    "description": "Off by hand around 23:10 on 9 of the last 14 nights",
    "triggers": [{"trigger": "time", "at": "23:15:00"}],
    "actions": [{"action": "light.turn_off", "target": {"entity_id": "light.kitchen"}}],
}


class FakeRoutines:
    """Sunrise's `routine` tool: suggestions saved (live with on=true), kept or dismissed."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, str | None]] = []
        self.n = 0

    def handle(self, args: dict[str, Any], user_id: str | None) -> dict[str, Any]:
        op, rid = args.get("op"), args.get("id")
        self.calls.append((op, user_id))
        if op == "list":
            return {"routines": [{"id": i, "entity_id": f"automation.{i}", "name": r["alias"], "on": r["on"],
                                  **({"suggestion": True} if r["suggestion"] else {})} for i, r in self.rows.items()]}
        if op == "get":
            return {"id": rid, "config": {k: v for k, v in self.rows[rid].items() if k not in ("on", "suggestion")}}
        if op == "suggest":
            self.n += 1
            rid = f"suggestion_{self.n}"
            self.rows[rid] = {**args["config"], "on": bool(args.get("on")), "suggestion": True}
            return {"ok": True, "saved": True, "id": rid}
        if op == "keep" and user_id is None:
            return {"error": "Changing the house's setup needs someone signed in to Home Assistant as an administrator."}
        if op == "keep":
            self.rows[rid].update(on=True, suggestion=False)
            return {"ok": True, "kept": rid, "entity_id": f"automation.{rid}", "change_id": "c1"}
        if op == "dismiss":
            self.rows.pop(rid, None)
            return {"ok": True, "dismissed": rid}
        return {"error": f"unknown op {op}"}


class _RoutineTool(llm.Tool):
    name = "routine"
    description = "Routines"

    def __init__(self, fake: FakeRoutines) -> None:
        self.fake = fake

    async def async_call(self, hass, tool_input, llm_context):
        user = llm_context.context.user_id if llm_context.context else None
        return llm.ToolResult(data=self.fake.handle(dict(tool_input.tool_args or {}), user), error=False)


class _Sunrise(llm.API):
    def __init__(self, hass, fake):
        super().__init__(hass=hass, id="sunrise", name="Sunrise")
        self.fake = fake

    async def async_get_api_instance(self, llm_context):
        return llm.APIInstance(api=self, api_prompt="Sunrise.", llm_context=llm_context, tools=[_RoutineTool(self.fake)])


def _sunrise(hass: HomeAssistant, monkeypatch) -> FakeRoutines:
    fake = FakeRoutines()
    llm.async_register_api(hass, _Sunrise(hass, fake))
    return fake


async def _admin(hass: HomeAssistant) -> str:
    return (await hass.auth.async_create_user("Owner", group_ids=["system-admin"])).id


HEARD = {
    "alias": "Turn the Hall light on when the Front door opens",
    "description": "5 of the 6 times the Front door opens between 18:35 and 19:51, someone did this by hand.",
    "triggers": [{"trigger": "state", "entity_id": "binary_sensor.front_door", "to": "on"}],
    "conditions": [{"condition": "time", "after": "18:35:00", "before": "19:51:00"}],
    "actions": [{"action": "light.turn_on", "target": {"entity_id": "light.hall"}}],
    "mode": "single",
}


async def test_suggestions_are_off_until_turned_on_and_turning_them_on_says_what_it_costs(hass, console, model, monkeypatch):
    fake = _sunrise(hass, monkeypatch)
    link(console)
    assert console.suggestions.state["on"] is False
    assert await console.suggestions.run() == {"ran": False, "why": "off"}
    assert await console.suggestions.run(heard=True) == {"ran": False, "why": "off"}
    await hass.services.async_call("console", "suggest_routines", {}, blocking=True)  # the house asking: off is off
    assert model.calls == [] and fake.calls == []  # nothing spent, nothing read, while it's off
    console.suggestions.set_on(True)
    await hass.async_block_till_done()
    from homeassistant.components import persistent_notification

    notes = persistent_notification._async_get_or_create_notifications(hass)  # noqa: SLF001
    assert "console_suggestions" in notes and "credits" in notes["console_suggestions"]["message"]


async def test_the_hourly_run_is_the_agent_following_sunrises_skill_and_what_it_saves_is_live(hass, console, model, monkeypatch):
    """Owner, 2026-11-28: "the house uses console which is guided by sunrise to properly do the task". Console
    hands the agent no routine and reads nothing itself: it asks, and the skill says how."""
    fake = _sunrise(hass, monkeypatch)
    link(console)
    console.suggestions.set_on(True)
    model.call_tool("sunrise__routine", {"op": "suggest", "on": True, "config": HEARD})
    model.say("Saved 1. [[customization]]")
    done = await console.suggestions.run(heard=True)
    assert done["ran"] and done["made"] == 1 and done["cost_usd"] > 0
    asked = model.calls[0]["messages"][-1]["content"]
    assert "get_skill name=routines" in asked and "Listening" in asked and "on=true" in asked
    assert "binary_sensor" not in asked and "op=suggest" not in asked  # how is the skill's, not Console's
    assert [op for op, _ in fake.calls if op not in ("list", "get")] == ["suggest"]  # Console itself only keeps its books
    [item] = console.suggestions.listing()["items"]
    assert item["name"] == HEARD["alias"] and set(item) == {"id", "name", "description", "made"}
    assert fake.rows[item["id"]]["on"] is True  # running from the moment it was saved

    # An hour with nothing heard: the agent says so and nothing changes.
    model.say("Saved 0: nothing new was heard. [[status]]")
    assert (await console.suggestions.run(heard=True))["made"] == 0 and len(fake.rows) == 1

    # The house can ask for it too.
    model.say("Saved 0. [[status]]")
    await hass.services.async_call("console", "suggest_routines", {"heard": True}, blocking=True)
    assert len(model.calls) == 4 and "Listening" in model.calls[-1]["messages"][-1]["content"]


async def test_every_run_is_flash_with_thinking_off_and_never_the_stronger_model(hass, console, model, monkeypatch):
    """Owner, 2026-11-28: "made using the flash model never reasoning"."""
    from custom_components.console import openrouter
    from custom_components.console.const import MODEL_FLASH

    fake = _sunrise(hass, monkeypatch)
    link(console)
    console.suggestions.set_on(True)
    model.call_tool("sunrise__routine", {"op": "suggest", "on": True, "config": CONFIG})
    model.say("Suggested 1. [[customization]]")
    done = await console.suggestions.run()  # Monday's run
    assert done["ran"] and done["made"] == 1
    assert "on=true" in model.calls[0]["messages"][-1]["content"]
    model.fail(openrouter.ModelError("flash gave up"))  # the hourly one: Flash fails, and nothing is handed up
    assert (await console.suggestions.run(heard=True))["made"] == 0
    assert {(c["model"], c["effort"]) for c in model.calls} == {(MODEL_FLASH, "none")}
    assert not any(t["function"]["name"] == "console_escalate" for c in model.calls for t in c["tools"])
    assert ("suggest", None) in fake.calls  # saved with nobody signed in


async def test_the_run_isnt_throttled_and_is_skipped_only_when_the_cloud_agent_cant_be_used(hass, console, model, monkeypatch):
    fake = _sunrise(hass, monkeypatch)
    link(console, cap=0.05)
    console.suggestions.set_on(True)
    console.add_spend(0.04)  # 80%: it still runs
    model.say("Suggested 0. [[customization]]")
    assert (await console.suggestions.run())["ran"] is True
    console.add_spend(0.02)  # 100%: the cloud agent is paused, so there's nothing to run it on
    assert (await console.suggestions.run())["why"] == "cloud agent over_limit"
    link(console, cap=1.0)
    console.set_switch("ai", False)
    assert (await console.suggestions.run())["why"] == "cloud agent ai_off"
    console.set_switch("ai", True)
    for n in range(3):
        fake.handle({"op": "suggest", "on": True, "config": {**CONFIG, "alias": f"Routine {n}", "triggers": [{"trigger": "time", "at": f"2{n}:00:00"}]}}, None)
    assert (await console.suggestions.run())["why"] == "full"
    assert (await console.suggestions.run(heard=True))["why"] == "full"  # three wait for an answer: no run, nothing spent
    assert len(model.calls) == 1


async def test_it_listens_every_hour_and_looks_at_the_whole_house_on_mondays_at_three(hass, console, monkeypatch):
    from datetime import datetime

    ran = []

    async def run(**kw):
        ran.append(kw)
        return {}

    monkeypatch.setattr(console.suggestions, "run", run)
    await console.suggestions._weekly(datetime(2026, 11, 30, 3, 0))  # a Monday
    await console.suggestions._weekly(datetime(2026, 12, 1, 3, 0))  # a Tuesday
    await console.suggestions._hourly(datetime(2026, 12, 1, 14, S.LISTEN_MINUTE))
    assert ran == [{}, {"heard": True}] and S.RUN_AT == (0, 3, 0)


async def test_keep_makes_it_an_ordinary_routine_and_undo_removes_it_for_good(hass, console, monkeypatch):
    fake = _sunrise(hass, monkeypatch)
    user = await _admin(hass)
    fake.handle({"op": "suggest", "on": True, "config": CONFIG}, None)
    fake.handle({"op": "suggest", "on": True, "config": HEARD}, None)
    await console.suggestions.reconcile()
    first, second = (i["id"] for i in console.suggestions.state["items"])

    kept = await console.suggestions.keep(first, user)
    assert kept["ok"] and "ordinary routine" in kept["reply"]
    assert fake.rows[first] == {**CONFIG, "on": True, "suggestion": False} and ("keep", user) in fake.calls
    assert console.suggestions.state["kept"][0]["change_id"] == "c1"

    undone = await console.suggestions.dismiss(second, user)
    assert "won't suggest it again" in undone["reply"] and second not in fake.rows
    assert console.suggestions.state["items"] == []
    assert console.suggestions.state["counts"][console.period] == {"suggested": 2, "kept": 1, "dismissed": 1}
    # The same routine under another name comes back: it is removed as soon as Console sees it, and the
    # hourly listen doesn't offer it again either.
    again = fake.handle({"op": "suggest", "on": True, "config": {**HEARD, "alias": "Hall at the door"}}, None)["id"]
    assert await console.suggestions.reconcile() == 0 and again not in fake.rows
    assert [n["name"] for n in console.suggestions.state["never"]] == [HEARD["alias"]]


async def test_one_nobody_answers_for_a_week_is_pruned_and_never_suggested_again(hass, console, model, monkeypatch, freezer):
    fake = _sunrise(hass, monkeypatch)
    link(console)
    console.suggestions.set_on(True)
    old = fake.handle({"op": "suggest", "on": True, "config": CONFIG}, None)["id"]
    await console.suggestions.reconcile()
    freezer.tick(timedelta(days=S.EXPIRE_DAYS - 1))
    new = fake.handle({"op": "suggest", "on": True, "config": HEARD}, None)["id"]
    await console.suggestions.reconcile()
    freezer.tick(timedelta(days=2))
    link(console)  # a fresh key: the last one ran out days ago
    model.say("Saved 0. [[status]]")
    assert (await console.suggestions.run(heard=True))["ran"]  # every run prunes first
    assert old not in fake.rows and new in fake.rows  # the old one stopped running; the newer one has days left
    assert [i["id"] for i in console.suggestions.state["items"]] == [new]
    assert [n["name"] for n in console.suggestions.state["never"]] == [CONFIG["alias"]]
    assert console.suggestions.state["counts"][console.period]["expired"] == 1
    again = fake.handle({"op": "suggest", "on": True, "config": {**CONFIG, "alias": "Kitchen off late"}}, None)["id"]
    assert await console.suggestions.reconcile() == 0 and again not in fake.rows


async def test_the_card_lists_them_and_only_an_administrator_keeps_or_undoes(hass, console, monkeypatch, hass_ws_client, hass_read_only_access_token):
    fake = _sunrise(hass, monkeypatch)
    fake.handle({"op": "suggest", "on": True, "config": CONFIG}, None)
    await console.suggestions.reconcile()
    sid = console.suggestions.state["items"][0]["id"]

    reader = await hass_ws_client(hass, hass_read_only_access_token)
    await reader.send_json({"id": 1, "type": "console/suggestions"})
    seen = (await reader.receive_json())["result"]
    assert seen["items"][0]["id"] == sid and seen["is_admin"] is False
    for n, what in enumerate(("keep", "dismiss"), start=2):
        await reader.send_json({"id": n, "type": f"console/suggestions/{what}", "suggestion_id": sid})
        assert (await reader.receive_json())["success"] is False
    assert fake.rows[sid]["suggestion"] is True

    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "console/suggestions"})
    got = (await ws.receive_json())["result"]
    assert got["items"][0]["id"] == sid and "credits" in got["cost_note"] and got["on"] is False and got["is_admin"] is True
    await ws.send_json({"id": 2, "type": "console/suggestions/keep", "suggestion_id": sid})
    kept = await ws.receive_json()
    assert kept["success"] and kept["result"]["reply"].startswith("Kept")
    await ws.send_json({"id": 3, "type": "console/suggestions/keep", "suggestion_id": sid})
    assert (await ws.receive_json())["error"]["message"] == "That suggestion isn't here any more."
    await ws.send_json({"id": 4, "type": "console/suggestions/set", "on": True})
    assert (await ws.receive_json())["result"] == {"on": True}


async def test_the_data_wipe_takes_the_waiting_suggestions_out_of_the_automations(hass, console, monkeypatch):
    from custom_components.console import wipe

    fake = _sunrise(hass, monkeypatch)
    fake.handle({"op": "suggest", "config": CONFIG}, None)
    await console.suggestions.reconcile()
    done = await wipe.erase_data(hass, "erase my data")
    assert done["erased"]["suggestions"] == 1 and fake.rows == {}
    assert console.suggestions.state["items"] == []
