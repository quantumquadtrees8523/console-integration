"""Suggested routines: the nightly setting, the run, a tap, the fifth tap, expiry, removal and the wipe.

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
    """Sunrise's `routine` tool: suggestions saved off, run by try, kept or dismissed."""

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
            self.rows[rid] = {**args["config"], "on": False, "suggestion": True}
            return {"ok": True, "saved": True, "id": rid}
        if op in ("try", "keep") and user_id is None:
            return {"error": "Changing the house's setup needs someone signed in to Home Assistant as an administrator."}
        if op == "try":
            return {"ok": True, "ran": True, "things": [{"id": "light.kitchen", "name": "Kitchen light", "now": "off"}]}
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


async def test_nightly_suggestions_are_off_until_turned_on_and_turning_them_on_says_what_it_costs(hass, console, model, monkeypatch):
    _sunrise(hass, monkeypatch)
    link(console)
    assert console.suggestions.state["on"] is False
    assert await console.suggestions.run() == {"ran": False, "why": "off"}
    assert model.calls == []  # nothing spent while it's off
    console.suggestions.set_on(True)
    await hass.async_block_till_done()
    from homeassistant.components import persistent_notification

    notes = persistent_notification._async_get_or_create_notifications(hass)  # noqa: SLF001
    assert "console_suggestions" in notes and "credits" in notes["console_suggestions"]["message"]


async def test_the_run_asks_the_cloud_agent_and_picks_up_what_sunrise_saved(hass, console, model, monkeypatch):
    fake = _sunrise(hass, monkeypatch)
    link(console)
    console.suggestions.set_on(True)
    model.call_tool("sunrise__routine", {"op": "suggest", "config": CONFIG})
    model.say("Suggested 1. [[customization]]")
    done = await console.suggestions.run()
    assert done["ran"] and done["made"] == 1 and done["cost_usd"] > 0
    assert model.calls[0]["effort"] == "low"  # Flash with a little thinking
    assert "op=suggest" in model.calls[0]["messages"][-1]["content"]
    [item] = console.suggestions.listing()["items"]
    assert item["name"] == CONFIG["alias"] and item["taps"] == 0 and item["keep_after"] == 5
    assert ("suggest", None) in fake.calls  # saved with nobody signed in: the nightly run
    assert console.suggestions.state["last_run"]["made"] == 1


async def test_the_run_is_skipped_near_the_limit_with_ai_off_or_when_full(hass, console, model, monkeypatch):
    fake = _sunrise(hass, monkeypatch)
    link(console, cap=0.05)
    console.suggestions.set_on(True)
    console.add_spend(0.04)  # 80%
    assert (await console.suggestions.run())["why"] == "cloud agent near_limit"
    link(console, cap=1.0)
    console.set_switch("ai", False)
    assert (await console.suggestions.run())["why"] == "cloud agent ai_off"
    console.set_switch("ai", True)
    for n in range(3):
        fake.handle({"op": "suggest", "config": {**CONFIG, "alias": f"Routine {n}", "triggers": [{"trigger": "time", "at": f"2{n}:00:00"}]}}, None)
    assert (await console.suggestions.run())["why"] == "full"
    assert model.calls == []


async def test_each_tap_runs_it_once_and_the_fifth_keeps_it(hass, console, monkeypatch):
    fake = _sunrise(hass, monkeypatch)
    user = await _admin(hass)
    fake.handle({"op": "suggest", "config": CONFIG}, None)
    await console.suggestions.reconcile()
    sid = console.suggestions.state["items"][0]["id"]
    for n in range(1, 5):
        done = await console.suggestions.tap(sid, user)
        assert done["taps"] == n and not done["kept"] and "Kitchen light is off" in done["reply"]
    assert "1 more time and" in done["reply"]
    assert fake.rows[sid]["on"] is False  # still a suggestion: it only ran when tapped
    done = await console.suggestions.tap(sid, user)
    assert done["kept"] and "runs by itself from here on" in done["reply"]
    assert fake.rows[sid]["on"] is True and console.suggestions.state["items"] == []
    assert console.suggestions.state["kept"][0]["change_id"] == "c1"
    assert [op for op, _ in fake.calls].count("try") == 5 and ("keep", user) in fake.calls
    counts = console.suggestions.state["counts"][console.period]
    assert counts == {"suggested": 1, "tapped": 5, "kept": 1}


async def test_a_removed_or_ignored_suggestion_is_never_suggested_again(hass, console, monkeypatch, freezer):
    fake = _sunrise(hass, monkeypatch)
    user = await _admin(hass)
    fake.handle({"op": "suggest", "config": CONFIG}, None)
    await console.suggestions.reconcile()
    sid = console.suggestions.state["items"][0]["id"]
    assert "won't suggest it again" in (await console.suggestions.dismiss(sid, user))["reply"]
    assert sid not in fake.rows
    # The same routine under another name comes back: it is removed as soon as Console sees it.
    again = fake.handle({"op": "suggest", "config": {**CONFIG, "alias": "Kitchen off late"}}, None)["id"]
    assert await console.suggestions.reconcile() == 0 and again not in fake.rows

    # Ignored for a week: removed, and remembered as not wanted.
    other = {**CONFIG, "alias": "Kitchen on at 7", "triggers": [{"trigger": "time", "at": "07:00:00"}]}
    rid = fake.handle({"op": "suggest", "config": other}, None)["id"]
    await console.suggestions.reconcile()
    freezer.tick(timedelta(days=S.EXPIRE_DAYS + 1))
    assert await console.suggestions.expire() == 1 and rid not in fake.rows
    assert [n["name"] for n in console.suggestions.state["never"]] == [CONFIG["alias"], "Kitchen on at 7"]


async def test_the_card_lists_taps_and_only_an_administrator_removes(hass, console, monkeypatch, hass_ws_client, hass_read_only_access_token):
    fake = _sunrise(hass, monkeypatch)
    fake.handle({"op": "suggest", "config": CONFIG}, None)
    await console.suggestions.reconcile()
    sid = console.suggestions.state["items"][0]["id"]
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "console/suggestions"})
    got = (await ws.receive_json())["result"]
    assert got["items"][0]["id"] == sid and "credits" in got["cost_note"] and got["on"] is False
    await ws.send_json({"id": 2, "type": "console/suggestions/tap", "suggestion_id": sid})
    tapped = await ws.receive_json()
    assert tapped["success"] and tapped["result"]["taps"] == 1
    await ws.send_json({"id": 3, "type": "console/chat/history", "limit": 5})
    said = [m["text"] for m in (await ws.receive_json())["result"]["messages"]]
    assert said[0] == "Run \u201cKitchen light off at night\u201d" and said[1].startswith("Done:")
    await ws.send_json({"id": 4, "type": "console/suggestions/set", "on": True})
    assert (await ws.receive_json())["result"] == {"on": True}

    reader = await hass_ws_client(hass, hass_read_only_access_token)
    await reader.send_json({"id": 1, "type": "console/suggestions/dismiss", "suggestion_id": sid})
    assert (await reader.receive_json())["success"] is False
    assert sid in fake.rows


async def test_the_data_wipe_takes_the_waiting_suggestions_out_of_the_automations(hass, console, monkeypatch):
    from custom_components.console import wipe

    fake = _sunrise(hass, monkeypatch)
    fake.handle({"op": "suggest", "config": CONFIG}, None)
    await console.suggestions.reconcile()
    done = await wipe.erase_data(hass, "erase my data")
    assert done["erased"]["suggestions"] == 1 and fake.rows == {}
    assert console.suggestions.state["items"] == []
