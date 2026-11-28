"""Suggestions and quick actions: the chat always has three, made at home for free; a tap runs one; the
ones a household keeps using become quick actions; the ones it keeps ignoring are discarded. And the
weekly run that adds routines the cloud agent suggests: its setting, a tap, keeping, expiry, removal, the wipe.

Sunrise's tools are stood in for here by small fakes with the same ops and answers (Sunrise's own tests
run the real ones against Home Assistant)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.homeassistant.exposed_entities import async_expose_entity
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, entity_registry as er, llm

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
        self.usage: list[dict[str, Any]] = []

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
            if not self.rows[rid]["suggestion"]:
                return {"error": "it was kept, so it's an ordinary routine now: remove it with op=delete"}
            self.rows.pop(rid, None)
            return {"ok": True, "dismissed": rid}
        if op == "delete":
            self.rows.pop(rid, None)
            return {"ok": True, "deleted": rid}
        return {"error": f"unknown op {op}"}


class _RoutineTool(llm.Tool):
    name = "routine"
    description = "Routines"

    def __init__(self, fake: FakeRoutines) -> None:
        self.fake = fake

    async def async_call(self, hass, tool_input, llm_context):
        user = llm_context.context.user_id if llm_context.context else None
        return llm.ToolResult(data=self.fake.handle(dict(tool_input.tool_args or {}), user), error=False)


class _UsageTool(llm.Tool):
    name = "usage"
    description = "How the house is used"

    def __init__(self, fake: FakeRoutines) -> None:
        self.fake = fake

    async def async_call(self, hass, tool_input, llm_context):
        return llm.ToolResult(data={"days": 14, "things": self.fake.usage}, error=False)


class _Sunrise(llm.API):
    def __init__(self, hass, fake):
        super().__init__(hass=hass, id="sunrise", name="Sunrise")
        self.fake = fake

    async def async_get_api_instance(self, llm_context):
        return llm.APIInstance(api=self, api_prompt="Sunrise.", llm_context=llm_context, tools=[_RoutineTool(self.fake), _UsageTool(self.fake)])


def _sunrise(hass: HomeAssistant, monkeypatch) -> FakeRoutines:
    fake = FakeRoutines()
    llm.async_register_api(hass, _Sunrise(hass, fake))
    return fake


async def _admin(hass: HomeAssistant) -> str:
    return (await hass.auth.async_create_user("Owner", group_ids=["system-admin"])).id




def _switching(hass: HomeAssistant, works: bool = True) -> list:
    """Lights and scenes that really switch, the way a device would: the call lands, then the state shows it."""
    calls = []

    async def switch(call):
        calls.append(call)
        for entity_id in call.data.get("entity_id") or []:
            if works and (state := hass.states.get(entity_id)):
                hass.states.async_set(entity_id, "on" if call.service == "turn_on" else "off", state.attributes)

    async def scene(call):
        calls.append(call)

    for domain in ("light", "switch"):
        hass.services.async_register(domain, "turn_on", switch)
        hass.services.async_register(domain, "turn_off", switch)
    hass.services.async_register("scene", "turn_on", scene)
    return calls


def _thing(hass: HomeAssistant, entity_id: str, state: str, name: str, room: str | None = None) -> None:
    """Something exposed to Assist, in a room when one is named."""
    domain, object_id = entity_id.split(".")
    entry = er.async_get(hass).async_get_or_create(domain, "test", object_id, suggested_object_id=object_id)
    if room:
        areas = ar.async_get(hass)
        area = areas.async_get_area_by_name(room) or areas.async_create(room)
        er.async_get(hass).async_update_entity(entry.entity_id, area_id=area.id)
    hass.states.async_set(entity_id, state, {"friendly_name": name})
    async_expose_entity(hass, "conversation", entity_id, True)


def names(listing: dict[str, Any], row: str = "suggested") -> list[str]:
    return [chip["name"] for chip in listing[row]]


async def test_the_chat_always_has_three_suggestions_made_at_home_for_free(hass, console, model):
    """Owner, 2026-11-28: "there should always be 3 suggestions on chat". With the weekly run off, no
    Sunrise and no cloud agent, they are made on the box from the house as it is, with no model call."""
    got = await console.suggestions.listing()
    assert names(got) == ["Turn off Kitchen light", "What's on right now?", "What routines would help here?"]
    assert got["suggested"][0] == {"id": "off:light.kitchen", "kind": "action", "name": "Turn off Kitchen light", "why": "It's on right now.", "taps": 0, "quick": False}
    assert got["suggested"][1]["kind"] == "ask" and got["suggested"][1]["ask"] == "What's on right now?"
    assert got["quick"] == [] and got["on"] is False and model.calls == []

    hass.states.async_remove("light.kitchen")  # a house with nothing to switch still has three: things to ask
    assert names(await console.suggestions.listing()) == ["What's on right now?", "What routines would help here?", "What can you do?"]


async def test_suggestions_come_from_what_is_on_how_the_house_is_used_and_its_scenes(hass, console, monkeypatch, freezer):
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to("2026-11-28 19:20:00+00:00")
    fake = _sunrise(hass, monkeypatch)
    _thing(hass, "light.den_lamp", "off", "Den lamp", "Den")
    _thing(hass, "light.hall", "on", "Hall light", "Hall")
    _thing(hass, "light.kitchen_counter", "on", "Kitchen counter", "Kitchen")
    _thing(hass, "light.kitchen_ceiling", "on", "Kitchen ceiling", "Kitchen")
    _thing(hass, "scene.movie_night", "2026-11-01T20:00:00+00:00", "Movie night")
    _thing(hass, "lock.front_door", "locked", "Front door")  # never offered: a suggestion only switches lights, switches, fans and scenes
    hass.states.async_set("light.garage", "on", {"friendly_name": "Garage light"})
    async_expose_entity(hass, "conversation", "light.garage", False)  # not exposed to Assist: never offered
    fake.usage = [{"id": "light.den_lamp", "name": "Den lamp", "changes": 40, "turned_on": 12, "days_used": 9, "common_hours": [19, 20, 7]}]
    got = await console.suggestions.listing()
    assert names(got) == ["Turn on Den lamp", "Turn off all the lights", "Turn off the Kitchen lights"]
    assert got["suggested"][0]["why"] == "Usually on around 7 PM: 9 of the last 14 days."
    assert got["suggested"][1]["why"] == "4 lights are on right now." and got["suggested"][2]["why"] == "2 lights are on there right now."
    offered = [c["id"] for c in console.suggestions._candidates(console.suggestions._things())]  # noqa: SLF001
    assert "scene:scene.movie_night" in offered and "off:light.hall" in offered
    assert not [key for key in offered if "lock" in key or "garage" in key]
    assert [op for op, _ in fake.calls] == []  # reading usage isn't a routine call, and nothing was changed


async def test_a_tap_runs_it_at_home_as_that_person_and_using_it_makes_it_a_quick_action(hass, console, model, hass_admin_user, freezer):
    """Owner, 2026-11-28: "the more the user uses them they should end up as quick actions": three taps
    on two different days, the same bar as the rest of the product."""
    freezer.move_to("2026-11-28 20:00:00+00:00")
    calls = _switching(hass)
    done = await console.suggestions.tap("off:light.kitchen", hass_admin_user.id)
    assert done["reply"] == "Done. Kitchen light is off. Use it 2 more times and it stays under the chat as a quick action."
    assert hass.states.get("light.kitchen").state == "off" and calls[0].context.user_id == hass_admin_user.id
    assert calls[0].data["entity_id"] == ["light.kitchen"] and done["things"][0]["result"] == "CHECKED"
    for _ in range(2):
        done = await console.suggestions.tap("off:light.kitchen", hass_admin_user.id)
    assert done["taps"] == 3 and done["quick"] is False  # three times in one evening is still one day
    assert done["reply"].endswith("Use it on another day and it stays under the chat as a quick action.")

    freezer.tick(timedelta(days=1))
    hass.states.async_set("light.kitchen", "on", {"friendly_name": "Kitchen light"})
    done = await console.suggestions.tap("off:light.kitchen", hass_admin_user.id)
    assert done["promoted"] and done["quick"] and "it's a quick action now: it stays under the chat" in done["reply"]
    got = await console.suggestions.listing()
    assert names(got, "quick") == ["Turn off Kitchen light"] and "Turn off Kitchen light" not in names(got)
    assert len(got["suggested"]) == 3  # its place among the suggestions is taken by the next one
    assert (await console.suggestions.tap("off:light.kitchen", hass_admin_user.id))["reply"] == "Done. Kitchen light is off."
    assert model.calls == [] and console.paths()["suggestion_taps"]["turns"] == 5  # no AI anywhere in this
    assert console.suggestions.state["counts"][console.period] == {"tapped": 5, "quick": 1}

    freezer.tick(timedelta(days=S.QUICK_IDLE_DAYS + 1))  # nobody uses it for a month: it goes back to a suggestion
    got = await console.suggestions.listing()
    assert got["quick"] == [] and got["suggested"][0]["taps"] == 0


async def test_one_seen_a_few_times_and_never_tapped_is_discarded_and_rests(hass, console, freezer):
    """Owner, 2026-11-28: "if the user sees it a few times but never clicks it then it should be
    discarded". Four sightings on two days; the chat left open, or opened again in the hour, is one."""
    freezer.move_to("2026-11-28 09:00:00+00:00")
    shown = [chip["id"] for chip in (await console.suggestions.listing())["suggested"]]
    assert (await console.suggestions.seen(shown)) == {"discarded": []}
    assert (await console.suggestions.seen(shown)) == {"discarded": []}  # a moment later: not another sighting
    assert console.suggestions.state["home"]["off:light.kitchen"]["seen"] == 1
    for _ in range(2):
        freezer.tick(S.SEEN_GAP + timedelta(minutes=1))
        assert (await console.suggestions.seen(shown)) == {"discarded": []}  # three times, but all on one day
    freezer.tick(timedelta(days=1))
    assert (await console.suggestions.seen(shown)) == {"discarded": ["off:light.kitchen"]}
    got = await console.suggestions.listing()
    assert "Turn off Kitchen light" not in names(got) and len(got["suggested"]) == 3
    assert names(got)[:2] == ["What's on right now?", "What routines would help here?"]  # things to ask are never discarded
    freezer.tick(timedelta(days=S.REST_DAYS + 1))  # made at home, so it only rests: a month on it may be offered again
    assert "Turn off Kitchen light" in names(await console.suggestions.listing())

    # One that was tapped is never discarded for being seen.
    _switching(hass)
    await console.suggestions.tap("off:light.kitchen", "someone")
    for _ in range(6):
        freezer.tick(timedelta(days=1))
        assert (await console.suggestions.seen(["off:light.kitchen"])) == {"discarded": []}


async def test_a_tap_that_changes_nothing_says_so_and_doesnt_count(hass, console, hass_admin_user, monkeypatch):
    import pytest

    monkeypatch.setattr(S, "READBACK_S", 0.2)
    _switching(hass, works=False)  # the call goes out and the light never shows the change
    with pytest.raises(S.Refused, match="didn't run. Kitchen light didn't show the change."):
        await console.suggestions.tap("off:light.kitchen", hass_admin_user.id)
    assert console.suggestions.state["home"].get("off:light.kitchen", {}).get("taps") is None
    with pytest.raises(S.Refused, match="isn't here any more"):
        await console.suggestions.tap("off:light.nowhere", hass_admin_user.id)


async def test_a_scene_and_a_rooms_lights_run_whole(hass, console, hass_admin_user):
    calls = _switching(hass)
    _thing(hass, "light.kitchen_counter", "on", "Kitchen counter", "Kitchen")
    _thing(hass, "light.kitchen_ceiling", "off", "Kitchen ceiling", "Kitchen")
    _thing(hass, "scene.movie_night", "2026-11-01T20:00:00+00:00", "Movie night")
    kitchen = ar.async_get(hass).async_get_area_by_name("Kitchen").id
    done = await console.suggestions.tap(f"off:area:{kitchen}", hass_admin_user.id)
    assert done["name"] == "Turn off the Kitchen lights" and done["reply"].startswith("Done. 2 things are off: Kitchen ceiling, Kitchen counter.")
    assert sorted(calls[0].data["entity_id"]) == ["light.kitchen_ceiling", "light.kitchen_counter"]  # the room, not only what was on
    done = await console.suggestions.tap("scene:scene.movie_night", hass_admin_user.id)
    assert done["reply"].startswith("Done: “Movie night” ran.") and calls[1].domain == "scene"


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
    assert "op=suggest" in model.calls[0]["messages"][-1]["content"]
    got = await console.suggestions.listing()
    [item] = got["items"]
    assert item["name"] == CONFIG["alias"] and item["taps"] == 0 and item["quick"] is False
    assert got["suggested"][0] == {"id": item["id"], "kind": "routine", "name": CONFIG["alias"], "why": CONFIG["description"], "taps": 0, "quick": False,
                                   "auto": False}
    assert len(got["suggested"]) == 3  # the routine the cloud agent suggested comes first, the rest are made at home
    assert ("suggest", None) in fake.calls  # saved with nobody signed in: the nightly run
    assert console.suggestions.state["last_run"]["made"] == 1


async def test_the_hourly_run_is_the_agent_following_sunrises_listening_and_what_it_saves_is_off(hass, console, model, monkeypatch):
    """Owner, 2026-11-28: "the house uses console which is guided by sunrise to properly do the task". Console
    hands the agent no routine and reads nothing itself: it asks, and the skill says how."""
    fake = _sunrise(hass, monkeypatch)
    link(console)
    console.suggestions.set_on(True)
    model.call_tool("sunrise__routine", {"op": "suggest", "config": CONFIG})
    model.say("Saved 1. [[customization]]")
    done = await console.suggestions.run(heard=True)
    assert done["ran"] and done["made"] == 1
    asked = model.calls[0]["messages"][-1]["content"]
    assert "get_skill name=routines" in asked and "Listening" in asked and "switched off" in asked
    assert "light.kitchen" not in asked and "on=true" not in asked  # how is the skill's; nothing is made live
    [item] = console.suggestions.state["items"]
    assert fake.rows[item["id"]]["on"] is False  # a suggestion: it doesn't run by itself yet

    # The house can ask for a run itself; an hour with nothing heard changes nothing.
    model.say("Saved 0: nothing new was heard. [[status]]")
    await hass.services.async_call("console", "suggest_routines", {"heard": True}, blocking=True)
    assert len(model.calls) == 3 and "Listening" in model.calls[-1]["messages"][-1]["content"] and len(fake.rows) == 1


async def test_every_suggestions_run_is_flash_with_thinking_off_and_never_the_stronger_model(hass, console, model, monkeypatch):
    """Owner, 2026-11-28: "made using the flash model never reasoning"."""
    from custom_components.console import openrouter
    from custom_components.console.const import MODEL_FLASH

    _sunrise(hass, monkeypatch)
    link(console)
    console.suggestions.set_on(True)
    model.say("Suggested 0. [[customization]]")
    assert (await console.suggestions.run())["ran"]  # Monday's
    model.fail(openrouter.ModelError("flash gave up"))  # the hourly one: Flash fails, and nothing is handed up
    assert (await console.suggestions.run(heard=True))["made"] == 0
    assert [(c["model"], c["effort"]) for c in model.calls] == [(MODEL_FLASH, "none")] * 2
    assert not any(t["function"]["name"] == "console_escalate" for c in model.calls for t in c["tools"])


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
        fake.handle({"op": "suggest", "config": {**CONFIG, "alias": f"Routine {n}", "triggers": [{"trigger": "time", "at": f"2{n}:00:00"}]}}, None)
    assert (await console.suggestions.run())["why"] == "full"
    assert len(model.calls) == 1


async def test_it_runs_on_mondays_at_three_only(hass, console, monkeypatch):
    from datetime import datetime

    ran = []

    async def run(**kw):
        ran.append(kw)
        return {}

    monkeypatch.setattr(console.suggestions, "run", run)
    await console.suggestions._weekly(datetime(2026, 11, 30, 3, 0))  # a Monday
    await console.suggestions._weekly(datetime(2026, 12, 1, 3, 0))  # a Tuesday
    assert len(ran) == 1 and S.RUN_AT == (0, 3, 0)
    await console.suggestions._hourly(datetime(2026, 12, 1, 14, S.LISTEN_MINUTE))  # and it listens every hour
    assert ran == [{}, {"heard": True}]


async def test_the_second_tap_turns_a_suggested_routine_on_and_it_stays_to_become_a_quick_action(hass, console, monkeypatch, freezer):
    """Owner, 2026-11-28: "it should not be automatic until the user clicks on it twice but they do not need to
    actively click on in order for it to turn on. commands a user accepts should continually show up there and
    eventually be made into a quick button below the chat panel"."""
    freezer.move_to("2026-11-02 20:00:00+00:00")
    fake = _sunrise(hass, monkeypatch)
    user = await _admin(hass)
    fake.handle({"op": "suggest", "config": CONFIG}, None)
    await console.suggestions.reconcile()
    sid = console.suggestions.state["items"][0]["id"]

    done = await console.suggestions.tap(sid, user)
    assert done["taps"] == 1 and done["auto"] is False and "Kitchen light is off" in done["reply"]
    assert fake.rows[sid]["on"] is False and ("keep", user) not in fake.calls  # one tap: it ran once, and is still off

    done = await console.suggestions.tap(sid, user)  # the second tap is the yes: nothing else to press
    assert done["auto"] is True and "runs by itself from now on" in done["reply"]
    assert fake.rows[sid] == {**CONFIG, "on": True, "suggestion": False} and fake.calls.count(("keep", user)) == 1
    assert console.suggestions.state["kept"][0]["change_id"] == "c1"

    # It stays in the list: an ordinary routine to Sunrise now, still a suggestion here, and taps go on counting.
    assert await console.suggestions.reconcile() == 0
    got = await console.suggestions.listing()
    assert got["suggested"][0]["id"] == sid and got["suggested"][0]["auto"] is True and got["rules"]["auto_taps"] == 2
    freezer.tick(timedelta(days=1))
    done = await console.suggestions.tap(sid, user)
    assert done["promoted"] and done["kind"] == "routine" and fake.calls.count(("keep", user)) == 1  # turned on once
    got = await console.suggestions.listing()
    assert names(got, "quick") == [CONFIG["alias"]] and CONFIG["alias"] not in names(got)

    # Accepted, so never swept out with the untapped ones, and it no longer holds one of the waiting places.
    freezer.tick(timedelta(days=S.EXPIRE_DAYS + 1))
    assert await console.suggestions.expire() == 0 and sid in fake.rows
    counts = console.suggestions.state["counts"][console.period]
    assert counts["tapped"] == 3 and counts["quick"] == 1 and counts["kept"] == 1

    # An administrator's ✕ on one that runs by itself deletes the routine, and it's never suggested again.
    assert "won't suggest it again" in (await console.suggestions.dismiss(sid, user))["reply"]
    assert sid not in fake.rows and ("delete", user) in fake.calls and console.suggestions.state["items"] == []


async def test_an_administrator_can_turn_one_on_without_waiting_for_the_taps(hass, console, monkeypatch):
    fake = _sunrise(hass, monkeypatch)
    user = await _admin(hass)
    fake.handle({"op": "suggest", "config": CONFIG}, None)
    await console.suggestions.reconcile()
    sid = console.suggestions.state["items"][0]["id"]
    kept = await console.suggestions.keep(sid, user)
    assert "runs by itself from now on" in kept["reply"] and fake.rows[sid]["on"] is True
    assert console.suggestions.state["items"][0]["auto"] is True  # it stays, on its way to a quick action
    from custom_components.console import wipe

    await wipe.erase_data(hass, "erase my data")
    assert sid in fake.rows  # the household's own routine now: the data wipe leaves it running


async def test_a_removed_or_ignored_routine_is_never_suggested_again(hass, console, monkeypatch, freezer):
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

    # Seen four times on two days and never tapped: removed from the automations, and never suggested again.
    third = {**CONFIG, "alias": "Hall off at midnight", "triggers": [{"trigger": "time", "at": "00:00:00"}]}
    tid = fake.handle({"op": "suggest", "config": third}, None)["id"]
    await console.suggestions.reconcile()
    for _ in range(3):
        assert (await console.suggestions.seen([tid]))["discarded"] == []
        freezer.tick(timedelta(hours=9))
    assert (await console.suggestions.seen([tid]))["discarded"] == [tid] and tid not in fake.rows
    assert [n["name"] for n in console.suggestions.state["never"]] == [CONFIG["alias"], "Kitchen on at 7", "Hall off at midnight"]

    # An administrator's ✕ on one made at home: gone for good, not just resting. Something to ask can't be removed.
    import pytest

    await console.suggestions.dismiss("off:light.kitchen", user)
    freezer.tick(timedelta(days=S.REST_DAYS * 3))
    assert "Turn off Kitchen light" not in names(await console.suggestions.listing())
    with pytest.raises(S.Refused):
        await console.suggestions.dismiss("ask:whats_on", user)


async def test_the_card_gets_three_and_the_quick_actions_and_only_an_administrator_removes(hass, console, monkeypatch, hass_ws_client, hass_read_only_access_token):
    fake = _sunrise(hass, monkeypatch)
    _switching(hass)
    fake.handle({"op": "suggest", "config": CONFIG}, None)
    await console.suggestions.reconcile()
    sid = console.suggestions.state["items"][0]["id"]
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "console/suggestions"})
    got = (await ws.receive_json())["result"]
    assert [c["id"] for c in got["suggested"]] == [sid, "off:light.kitchen", "ask:whats_on"] and got["quick"] == []
    assert got["items"][0]["id"] == sid and "credits" in got["cost_note"] and got["on"] is False and got["shown"] is True
    assert got["rules"]["promote_taps"] == 3 and got["rules"]["promote_days"] == 2 and got["rules"]["discard_seen"] == 4

    await ws.send_json({"id": 2, "type": "console/suggestions/tap", "suggestion_id": sid})
    tapped = (await ws.receive_json())["result"]
    assert tapped["taps"] == 1 and tapped["thread_id"].startswith("console-")
    await ws.send_json({"id": 3, "type": "console/suggestions/tap", "suggestion_id": "off:light.kitchen", "thread_id": tapped["thread_id"]})
    assert (await ws.receive_json())["result"]["thread_id"] == tapped["thread_id"]  # a tap goes into the chat that is open
    await ws.send_json({"id": 4, "type": "console/chat/history", "thread_id": tapped["thread_id"]})
    said = (await ws.receive_json())["result"]["messages"]
    assert [m["text"] for m in said][0] == "Run \u201cKitchen light off at night\u201d" and said[1]["text"].startswith("Done:")
    assert said[2]["text"] == "Run \u201cTurn off Kitchen light\u201d" and said[3]["steps"] == [{"title": "Ran at home", "detail": "A tap on a suggestion: no AI, no internet."}]
    await ws.send_json({"id": 5, "type": "console/suggestions/tap", "suggestion_id": "ask:whats_on"})
    asked = (await ws.receive_json())["result"]
    assert asked["ask"] == "What's on right now?" and "thread_id" not in asked  # the card asks it like any message
    await ws.send_json({"id": 6, "type": "console/suggestions/seen", "ids": [sid, "off:light.kitchen"]})
    assert (await ws.receive_json())["result"] == {"discarded": []}
    await ws.send_json({"id": 7, "type": "console/suggestions/set", "on": True})
    assert (await ws.receive_json())["result"] == {"on": True}

    # Someone who isn't an administrator: no suggested routines (trying one changes the house's setup), the
    # ones made at home all the same, and no removing.
    reader = await hass_ws_client(hass, hass_read_only_access_token)
    await reader.send_json({"id": 1, "type": "console/suggestions"})
    theirs = (await reader.receive_json())["result"]
    assert [c["id"] for c in theirs["suggested"]] == ["on:light.kitchen", "ask:whats_on", "ask:routines"] and theirs["is_admin"] is False  # it's off now
    await reader.send_json({"id": 2, "type": "console/suggestions/dismiss", "suggestion_id": sid})
    assert (await reader.receive_json())["success"] is False
    await reader.send_json({"id": 3, "type": "console/suggestions/keep", "suggestion_id": sid})
    assert (await reader.receive_json())["success"] is False
    assert sid in fake.rows

    # With AI switched off for the house, the routines' tools are off: the ones made at home are still there.
    console.set_switch("ai", False)
    await ws.send_json({"id": 8, "type": "console/suggestions"})
    assert [c["kind"] for c in (await ws.receive_json())["result"]["suggested"]] == ["action", "ask", "ask"]


async def test_the_data_wipe_takes_the_waiting_suggestions_out_of_the_automations(hass, console, monkeypatch):
    from custom_components.console import wipe

    fake = _sunrise(hass, monkeypatch)
    fake.handle({"op": "suggest", "config": CONFIG}, None)
    await console.suggestions.reconcile()
    done = await wipe.erase_data(hass, "erase my data")
    assert done["erased"]["suggestions"] == 1 and fake.rows == {}
    assert console.suggestions.state["items"] == []
