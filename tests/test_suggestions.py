"""Suggested routines: the setting, the hourly listen, Monday's run, Flash with thinking off and never Pro, live
routines with Keep and Undo, and the wipe.

Sunrise's routine tool is stood in for here by a small fake with the same ops and answers (Sunrise's own
tests run the real one against Home Assistant's automations)."""

from __future__ import annotations

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
    """Sunrise's `routine` tool (suggestions saved, live with on=true, kept or dismissed) and its `usage` tool's
    `follows` (what the house heard)."""

    def __init__(self) -> None:
        self.follows: list[dict[str, Any]] = []
        self.rows: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, str | None]] = []
        self.n = 0

    def handle(self, args: dict[str, Any], user_id: str | None) -> dict[str, Any]:
        op, rid = args.get("op"), args.get("id")
        if "op" not in args:  # the usage tool
            self.calls.append(("usage", user_id))
            return {"days": args.get("days"), "things": [], "follows": self.follows}
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
    description = "Sunrise"

    def __init__(self, fake: FakeRoutines, name: str = "routine") -> None:
        self.fake = fake
        self.name = name

    async def async_call(self, hass, tool_input, llm_context):
        user = llm_context.context.user_id if llm_context.context else None
        return llm.ToolResult(data=self.fake.handle(dict(tool_input.tool_args or {}), user), error=False)


class _Sunrise(llm.API):
    def __init__(self, hass, fake):
        super().__init__(hass=hass, id="sunrise", name="Sunrise")
        self.fake = fake

    async def async_get_api_instance(self, llm_context):
        return llm.APIInstance(api=self, api_prompt="Sunrise.", llm_context=llm_context, tools=[_RoutineTool(self.fake), _RoutineTool(self.fake, "usage")])


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
    fake.follows = [{"routine": HEARD}]
    link(console)
    assert console.suggestions.state["on"] is False
    assert await console.suggestions.run() == {"ran": False, "why": "off"}
    assert await console.suggestions.listen() == {"ran": False, "why": "off"}
    assert model.calls == [] and fake.calls == []  # nothing spent, nothing read, while it's off
    console.suggestions.set_on(True)
    await hass.async_block_till_done()
    from homeassistant.components import persistent_notification

    notes = persistent_notification._async_get_or_create_notifications(hass)  # noqa: SLF001
    assert "console_suggestions" in notes and "credits" in notes["console_suggestions"]["message"]


async def test_an_hour_with_nothing_new_costs_nothing_and_a_new_pattern_becomes_a_live_routine(hass, console, model, monkeypatch):
    fake = _sunrise(hass, monkeypatch)
    link(console)
    console.suggestions.set_on(True)
    assert await console.suggestions.listen() == {"ran": False, "why": "nothing new"}
    assert model.calls == [] and fake.calls == [("usage", None)]  # Sunrise was asked; no model was

    fake.follows = [{"routine": HEARD}]
    model.call_tool("sunrise__routine", {"op": "suggest", "on": True, "config": HEARD})
    model.say("Saved 1. [[customization]]")
    done = await console.suggestions.listen()
    assert done["ran"] and done["made"] == 1 and done["cost_usd"] > 0
    asked = model.calls[0]["messages"][-1]["content"]
    assert "on=true" in asked and "binary_sensor.front_door" in asked  # the routine itself is handed over
    [item] = console.suggestions.listing()["items"]
    assert item["name"] == HEARD["alias"] and set(item) == {"id", "name", "description", "made"}
    assert fake.rows[item["id"]]["on"] is True  # running from the moment it was saved

    # The next hour hears the same thing: it isn't made, or paid for, twice.
    assert await console.suggestions.listen() == {"ran": False, "why": "nothing new"}
    assert len(model.calls) == 2


async def test_a_pattern_sunrise_wont_save_is_offered_once_not_every_hour(hass, console, model, monkeypatch):
    fake = _sunrise(hass, monkeypatch)
    link(console)
    console.suggestions.set_on(True)
    fake.follows = [{"routine": HEARD}]
    model.say("Saved 0: the light isn't exposed. [[customization]]")
    assert (await console.suggestions.listen())["made"] == 0
    assert await console.suggestions.listen() == {"ran": False, "why": "nothing new"}
    assert len(model.calls) == 1


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
    fake.follows = [{"routine": HEARD}]
    model.fail(openrouter.ModelError("flash gave up"))  # the hourly one: Flash fails, and nothing is handed up
    assert (await console.suggestions.listen())["made"] == 0
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
    assert (await console.suggestions.listen())["why"] == "not now"
    link(console, cap=1.0)
    console.set_switch("ai", False)
    assert (await console.suggestions.run())["why"] == "cloud agent ai_off"
    console.set_switch("ai", True)
    for n in range(3):
        fake.handle({"op": "suggest", "on": True, "config": {**CONFIG, "alias": f"Routine {n}", "triggers": [{"trigger": "time", "at": f"2{n}:00:00"}]}}, None)
    assert (await console.suggestions.run())["why"] == "full"
    fake.follows = [{"routine": HEARD}]
    assert (await console.suggestions.listen())["why"] == "full"  # three wait for an answer: no more until one gets it
    assert len(model.calls) == 1


async def test_it_listens_every_hour_and_looks_at_the_whole_house_on_mondays_at_three(hass, console, monkeypatch):
    from datetime import datetime

    ran, listened = [], []

    async def run(**kw):
        ran.append(kw)
        return {}

    async def listen():
        listened.append(1)
        return {}

    monkeypatch.setattr(console.suggestions, "run", run)
    monkeypatch.setattr(console.suggestions, "listen", listen)
    await console.suggestions._weekly(datetime(2026, 11, 30, 3, 0))  # a Monday
    await console.suggestions._weekly(datetime(2026, 12, 1, 3, 0))  # a Tuesday
    await console.suggestions._hourly(datetime(2026, 12, 1, 14, S.LISTEN_MINUTE))
    assert len(ran) == 1 and S.RUN_AT == (0, 3, 0) and listened == [1]


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
