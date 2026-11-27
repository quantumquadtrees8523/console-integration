"""Music Assistant's own app in the sidebar (music_app.py): admins only, relayed at /console_music/ for a
cookie the panel gets, signed in with the Home Assistant login, and connected to Home Assistant once."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components import frontend
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.console import music_app
from custom_components.console.const import DOMAIN

MA_URL = "http://ma.test:8095"
MA_CLIENT = "http://10.0.0.5:8095"  # Music Assistant's own address: its OAuth client_id
MA_TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJzdXJ5YSJ9.c2lnbmF0dXJl"


async def _setup(hass: HomeAssistant, with_music: bool = True):
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, "conversation", {})
    if with_music:  # Home Assistant's own music_assistant entry: only its address is read
        MockConfigEntry(domain="music_assistant", title="Music Assistant", data={"url": MA_URL}).add_to_hass(hass)
    entry = MockConfigEntry(domain=DOMAIN, title="Console", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _ma(aioclient_mock, linked: bool = True):
    """Music Assistant's routes the relay uses."""
    state = {"linked": linked, "rpc": []}

    async def providers(method, url, data):
        from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse

        ids = ["builtin"] + (["homeassistant"] if state["linked"] else [])
        return AiohttpClientMockResponse(method, url, json=[{"provider_id": i} for i in ids])

    async def api(method, url, data):
        from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse

        state["rpc"].append(data)
        if data["command"] == "config/providers/setup":
            return AiohttpClientMockResponse(method, url, json={"flow_id": "f1", "step_id": "user", "type": "form"})
        state["linked"] = True
        return AiohttpClientMockResponse(method, url, json={"flow_id": "f1", "step_id": "done", "type": "finish"})

    aioclient_mock.get(f"{MA_URL}/auth/providers", side_effect=providers)
    aioclient_mock.get(f"{MA_URL}/auth/authorize", json={"authorization_url": (
        "http://127.0.0.1:8123/auth/authorize?response_type=code&client_id=http%3A%2F%2F10.0.0.5%3A8095"
        "&redirect_uri=http%3A%2F%2F10.0.0.5%3A8095%2Fauth%2Fcallback&state=st-1")})
    aioclient_mock.get(f"{MA_URL}/auth/callback", text=f'<script>const token = "{MA_TOKEN}";</script>')
    aioclient_mock.post(f"{MA_URL}/api", side_effect=api)
    aioclient_mock.get(f"{MA_URL}/", text="<html>Music Assistant</html>", headers={"Content-Type": "text/html"})
    aioclient_mock.get(f"{MA_URL}/old", status=302, headers={"Location": "/setup"})
    return state


def _calls(aioclient_mock, path: str):
    return [c for c in aioclient_mock.mock_calls if str(c[1]).split("?")[0].endswith(path)]


async def test_admins_get_a_music_assistant_entry_in_the_sidebar(hass, aioclient_mock):
    _ma(aioclient_mock)
    await _setup(hass)
    panel = hass.data[frontend.DATA_PANELS][music_app.PANEL_URL]
    assert panel.sidebar_title == "Music Assistant" and panel.require_admin
    assert panel.config["_panel_custom"]["name"] == "console-music-panel"


async def test_no_music_assistant_no_entry(hass, hass_client):
    await _setup(hass, with_music=False)
    assert music_app.PANEL_URL not in hass.data[frontend.DATA_PANELS]
    resp = await (await hass_client()).post("/api/console/music/session", json={})
    assert resp.status == 404


async def test_the_relay_opens_only_for_the_panels_cookie_and_only_for_admins(
    hass, aioclient_mock, hass_client, hass_client_no_auth, hass_read_only_access_token
):
    _ma(aioclient_mock)
    await _setup(hass)
    stranger = await hass_client_no_auth()
    assert (await stranger.get("/console_music/")).status == 401
    reader = await hass_client(hass_read_only_access_token)
    assert (await reader.post("/api/console/music/session", json={})).status == 403

    admin = await hass_client()
    resp = await admin.post("/api/console/music/session", json={})
    assert await resp.json() == {"available": True, "path": "/console_music/", "code": None, "ha_login": True, "up": True}
    cookie = resp.cookies["console_music"]
    assert cookie["httponly"] and cookie["path"] == "/console_music" and cookie["samesite"] == "Strict"

    page = await stranger.get("/console_music/", headers={"Cookie": f"console_music={cookie.value}", "X-Forwarded-Host": "relay.test"})
    assert page.status == 200 and await page.text() == "<html>Music Assistant</html>"
    sent = _calls(aioclient_mock, ":8095/")[-1][3] or {}
    assert not {k.lower() for k in sent} & {"cookie", "x-forwarded-host", "authorization"}
    moved = await stranger.get("/console_music/old", headers={"Cookie": f"console_music={cookie.value}"}, allow_redirects=False)
    assert moved.headers["Location"] == "/console_music/setup"  # its own redirects stay under the relay


async def test_the_home_assistant_login_signs_them_in_without_a_password(
    hass, aioclient_mock, hass_client, hass_client_no_auth, hass_admin_user
):
    _ma(aioclient_mock, linked=True)
    await _setup(hass)
    admin = await hass_client()
    fresh = await (await admin.post("/api/console/music/session", json={"fresh": True})).json()
    assert fresh["code"] == MA_TOKEN
    held = await (await admin.post("/api/console/music/session", json={})).json()
    assert held["code"] is None  # the app already holds a token: no new sign-in

    # What Music Assistant does with the code: trade it at Home Assistant for the same person's token.
    params = parse_qs(urlparse(str(_calls(aioclient_mock, "/auth/callback")[0][1])).query)
    assert params["state"] == ["st-1"] and params["provider_id"] == ["homeassistant"]
    traded = await (await hass_client_no_auth()).post("/auth/token", data={
        "grant_type": "authorization_code", "client_id": MA_CLIENT, "code": params["code"][0]})
    assert traded.status == 200
    token = hass.auth.async_validate_access_token((await traded.json())["access_token"])
    assert token is not None and token.user.id == hass_admin_user.id  # the admin who opened the panel


async def test_connecting_music_assistant_to_home_assistant_once(hass, aioclient_mock, hass_client):
    state = _ma(aioclient_mock, linked=False)
    await _setup(hass)
    admin = await hass_client()
    resp = await admin.post("/api/console/music/link", json={"ma_token": "ma-admin"})
    out = await resp.json()
    assert resp.status == 200 and out["ok"] and out["code"] == MA_TOKEN
    setup, submit = state["rpc"]
    assert setup["command"] == "config/providers/setup" and setup["args"] == {"provider_domain": "hass"}
    values = submit["args"]["values"]
    assert submit["args"]["flow_id"] == "f1" and values["verify_ssl"] is False
    assert values["url"].startswith("http://127.0.0.1:")
    # The plugin's token is a real long-lived Home Assistant token, named for what it's for.
    refresh = hass.auth.async_validate_access_token(values["token"])
    assert refresh is not None and refresh.client_name == "Music Assistant (Console)"
    assert refresh.token_type == "long_lived_access_token"
    headers = _calls(aioclient_mock, "/api")[0][3] or {}
    assert headers.get("Authorization") == "Bearer ma-admin"

    again = await (await admin.post("/api/console/music/link", json={"ma_token": "ma-admin"})).json()
    assert again["ok"] and again["already"] and len(state["rpc"]) == 2  # nothing set up twice


async def test_linking_needs_a_music_assistant_sign_in_first(hass, aioclient_mock, hass_client):
    _ma(aioclient_mock, linked=False)
    await _setup(hass)
    resp = await (await hass_client()).post("/api/console/music/link", json={})
    assert resp.status == 400


@pytest.mark.parametrize("view", music_app.VIEWS)
def test_no_view_answers_options_itself(view):
    """Home Assistant puts CORS on every view and aiohttp-cors refuses a route with its own OPTIONS
    handler: one would stop everything registered after it (found on 2026-11-27)."""
    assert not hasattr(view, "options")


def test_the_panels_words_are_in_wording():
    from custom_components.console import wording

    source = (Path(music_app.__file__).parent / "www/console-music-panel.js").read_text(encoding="utf-8")
    for key in wording.MUSIC_PANEL_WORDS:  # every sentence the panel shows comes from wording.py
        assert f'this._w("{key}")' in source, key
