"""Music Assistant's own app in Home Assistant's sidebar (owner, 2026-11-27: "I shouldn't have to go to
the agent or Claude Code to iterate on Music Assistant", and it must work through the relay too).

Music Assistant runs on the box with its own accounts. Home Assistant relays it at /console_music/, so it
opens wherever Home Assistant does (at home, Tailscale, the relay) with no extra port and no second
password. Its address is the one Home Assistant's own music_assistant integration uses.

- POST /api/console/music/session (an HA login, admins only) gives the browser a short-lived cookie for
  /console_music/ and, when asked (`fresh`), signs the person in to Music Assistant with their HA account:
  Music Assistant's own "Sign in with Home Assistant" (its `homeassistant` login provider), with the
  authorization code made here for the person already signed in instead of on a page the browser visits.
  Music Assistant's web app takes the token as `?code=` and keeps it.
- /console_music/<path> relays HTTP and websockets to Music Assistant, only for that cookie.
- POST /api/console/music/link connects Music Assistant to HA once (its Home Assistant plugin, which turns
  that login provider on), with the Music Assistant admin token the person has from signing in once by
  password and an HA long-lived token made here for them. That token never reaches the page.

Nothing here talks to the internet: every call is to Music Assistant on the box, or to Home Assistant.
"""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
import time
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

from aiohttp import ClientTimeout, WSMsgType, web

from homeassistant.auth.models import TOKEN_TYPE_LONG_LIVED_ACCESS_TOKEN
from homeassistant.components.auth import create_auth_code
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import wording

_LOGGER = logging.getLogger(__name__)

MA = "music_assistant"
PREFIX = "/console_music"
PANEL_URL = "console-music"
COOKIE = "console_music"
SESSION_TTL = 12 * 3600
TOKEN_NAME = "Music Assistant (Console)"
PROVIDER = "homeassistant"  # Music Assistant's login provider for Home Assistant accounts
_SESSIONS: dict[str, float] = {}  # cookie value -> expiry (epoch seconds)

# Never relayed: hop-by-hop headers, Home Assistant's cookies, and proxy hints (Music Assistant takes
# X-Forwarded-* as a reverse proxy and changes its own base URL, and trusts X-Remote-User-* from Ingress).
_DROP_REQ = {"host", "connection", "keep-alive", "upgrade", "te", "trailer", "transfer-encoding", "content-length",
             "cookie", "origin", "referer", "proxy-authorization", "x-forwarded-for", "x-forwarded-host",
             "x-forwarded-proto", "x-forwarded-port", "x-real-ip", "x-ingress-path", "x-remote-user-id",
             "x-remote-user-name", "x-remote-user-display-name", "sec-websocket-key", "sec-websocket-version",
             "sec-websocket-extensions", "sec-websocket-protocol"}
# Home Assistant's client session decompresses bodies, so length and encoding no longer hold.
_DROP_RESP = {"connection", "keep-alive", "transfer-encoding", "content-length", "content-encoding", "upgrade"}
_JWT = re.compile(r"(eyJ[\w-]+\.[\w-]+\.[\w-]+)")


def ma_url(hass: HomeAssistant) -> str:
    """Music Assistant's address, from Home Assistant's own music_assistant entry ('' when there's none)."""
    for entry in hass.config_entries.async_entries(MA):
        if url := str(entry.data.get("url") or "").rstrip("/"):
            return url
    return ""


def _ha_url_for_music(hass: HomeAssistant) -> str:
    """Where Music Assistant reaches Home Assistant from the box (its Home Assistant plugin)."""
    port = getattr(getattr(hass, "http", None), "server_port", None) or 8123
    return f"http://127.0.0.1:{port}"


def _secure(request: web.Request) -> bool:
    return request.secure or request.headers.get("X-Forwarded-Proto", "").lower() == "https"


def new_session() -> str:
    now = time.time()
    for key in [k for k, exp in _SESSIONS.items() if exp < now]:
        del _SESSIONS[key]
    value = secrets.token_urlsafe(32)
    _SESSIONS[value] = now + SESSION_TTL
    return value


def allowed(request: web.Request) -> bool:
    exp = _SESSIONS.get(request.cookies.get(COOKIE, ""))
    return bool(exp and exp > time.time())


def _admin(request: web.Request):
    user = request.get("hass_user")
    return user if user is not None and user.is_admin else None


async def _providers(hass: HomeAssistant) -> list[str]:
    session = async_get_clientsession(hass)
    async with session.get(f"{ma_url(hass)}/auth/providers", timeout=ClientTimeout(total=10)) as resp:
        if resp.status != 200:
            return []
        body = await resp.json(content_type=None)
    items = body if isinstance(body, list) else (body or {}).get("providers") or []
    return [str(p.get("provider_id")) for p in items if isinstance(p, dict)]


async def sign_in(hass: HomeAssistant, user) -> str | None:
    """A Music Assistant token for this HA user, through Music Assistant's Home Assistant login.

    Music Assistant starts the OAuth flow (its client_id and state); Home Assistant makes the authorization
    code for the person already signed in; Music Assistant trades it with Home Assistant for their token,
    links or creates its own user for them (same username: their existing account), and returns its token."""
    credential = next(iter(user.credentials), None)
    if credential is None:
        return None
    session, base, t = async_get_clientsession(hass), ma_url(hass), ClientTimeout(total=20)
    async with session.get(f"{base}/auth/authorize", params={"provider_id": PROVIDER}, timeout=t) as resp:
        if resp.status != 200:
            return None
        auth_url = (await resp.json(content_type=None) or {}).get("authorization_url") or ""
    query = parse_qs(urlparse(auth_url).query)
    client_id, state = (query.get("client_id") or [""])[0], (query.get("state") or [""])[0]
    if not client_id or not state:
        return None
    code = create_auth_code(hass, client_id, credential)
    params = {"code": code, "state": state, "provider_id": PROVIDER}
    async with session.get(f"{base}/auth/callback", params=params, timeout=t) as resp:
        page = await resp.text()
        if resp.status != 200:
            _LOGGER.warning("Music Assistant refused the Home Assistant sign-in (%s)", resp.status)
            return None
    match = _JWT.search(page)
    return match.group(1) if match else None


async def _ha_token_for(hass: HomeAssistant, user) -> str:
    """A long-lived HA token for Music Assistant's Home Assistant plugin, one per person (re-made each link)."""
    for old in [t for t in user.refresh_tokens.values() if t.client_name == TOKEN_NAME]:
        hass.auth.async_remove_refresh_token(old)
    refresh = await hass.auth.async_create_refresh_token(
        user, client_name=TOKEN_NAME, token_type=TOKEN_TYPE_LONG_LIVED_ACCESS_TOKEN,
        access_token_expiration=timedelta(days=3650))
    return hass.auth.async_create_access_token(refresh)


async def _rpc(hass: HomeAssistant, ma_token: str, command: str, **args):
    body = {"message_id": secrets.token_hex(4), "command": command, "args": args}
    async with async_get_clientsession(hass).post(
        f"{ma_url(hass)}/api", json=body, headers={"Authorization": f"Bearer {ma_token}"},
        timeout=ClientTimeout(total=30)) as resp:
        data = await resp.json(content_type=None)
        if resp.status != 200:
            raise RuntimeError((data or {}).get("error") or f"HTTP {resp.status}")
        return data


async def link(hass: HomeAssistant, user, ma_token: str) -> dict:
    """Connect Music Assistant to Home Assistant (its Home Assistant plugin) so its Home Assistant login works."""
    if PROVIDER in await _providers(hass):
        return {"ok": True, "already": True}
    step = await _rpc(hass, ma_token, "config/providers/setup", provider_domain="hass") or {}
    if step.get("type") != "form":
        return {"ok": False, "error": wording.MUSIC_NO_SETUP}
    values = {"url": _ha_url_for_music(hass), "verify_ssl": False, "token": await _ha_token_for(hass, user)}
    done = await _rpc(hass, ma_token, "config/flows/submit", flow_id=step["flow_id"], values=values) or {}
    if done.get("type") not in ("finish", "progress"):
        return {"ok": False, "error": wording.MUSIC_SETUP_REFUSED}
    for _ in range(20):  # the plugin connects, then the login provider appears
        if PROVIDER in await _providers(hass):
            return {"ok": True}
        await asyncio.sleep(0.5)
    return {"ok": False, "error": wording.MUSIC_LOGIN_OFF}


class MusicSessionView(HomeAssistantView):
    """Open the panel: the relay cookie, plus a Music Assistant token when the HA login is on and `fresh` asks."""

    url = "/api/console/music/session"
    name = "api:console:music_session"

    async def post(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        user = _admin(request)
        if user is None:
            return web.json_response({"error": wording.MUSIC_ADMINS_ONLY}, status=403)
        if not ma_url(hass):
            return web.json_response({"available": False}, status=404)
        body = await request.json() if request.can_read_body else {}
        out: dict = {"available": True, "path": f"{PREFIX}/", "code": None}
        try:
            out["ha_login"] = PROVIDER in await _providers(hass)
            out["up"] = True
            if out["ha_login"] and (body or {}).get("fresh"):
                out["code"] = await sign_in(hass, user)
        except Exception as exc:  # noqa: BLE001 (Music Assistant down is a page that says so, not an error)
            _LOGGER.warning("Music Assistant isn't answering: %s", exc)
            out.update(up=False, ha_login=False)
        resp = web.json_response(out)
        resp.set_cookie(COOKIE, new_session(), path=PREFIX, max_age=SESSION_TTL, httponly=True,
                        secure=_secure(request), samesite="Strict")
        return resp


class MusicLinkView(HomeAssistantView):
    """Connect Music Assistant to Home Assistant once, with the Music Assistant admin token the person signed in with."""

    url = "/api/console/music/link"
    name = "api:console:music_link"

    async def post(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        user = _admin(request)
        if user is None or not ma_url(hass):
            return web.json_response({"error": wording.MUSIC_ADMINS_ONLY}, status=403)
        ma_token = str((await request.json() or {}).get("ma_token") or "")
        if not ma_token:
            return web.json_response({"ok": False, "error": wording.MUSIC_PANEL_WORDS["sign_in_first"]}, status=400)
        try:
            out = await link(hass, user, ma_token)
            if out.get("ok"):
                out["code"] = await sign_in(hass, user)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("Music Assistant couldn't be connected to Home Assistant: %s", exc)
            out = {"ok": False, "error": str(exc)}
        return web.json_response(out, status=200 if out.get("ok") else 502)


class MusicProxyView(HomeAssistantView):
    """Music Assistant's web app and API at /console_music/, for the cookie MusicSessionView gave."""

    url = PREFIX + "/{path:.*}"
    name = "console:music_proxy"
    requires_auth = False

    async def _relay(self, request: web.Request, path: str) -> web.StreamResponse:
        hass: HomeAssistant = request.app["hass"]
        base = ma_url(hass)
        if not base:
            return web.Response(status=404)
        if not allowed(request):
            return web.Response(status=401, text=wording.MUSIC_OPEN_FROM_SIDEBAR)
        target = f"{base}/{path}" + (f"?{request.query_string}" if request.query_string else "")
        headers = {k: v for k, v in request.headers.items() if k.lower() not in _DROP_REQ}
        session = async_get_clientsession(hass)
        if request.headers.get("Upgrade", "").lower() == "websocket":
            return await self._websocket(request, session, target, headers)
        body = await request.read()
        try:
            async with session.request(request.method, target, data=body or None, headers=headers, allow_redirects=False,
                                       timeout=ClientTimeout(total=None, sock_connect=10, sock_read=300)) as resp:
                out_headers = {k: v for k, v in resp.headers.items() if k.lower() not in _DROP_RESP}
                if (loc := out_headers.get("Location", "")).startswith("/"):
                    out_headers["Location"] = PREFIX + loc
                out = web.StreamResponse(status=resp.status, headers=out_headers)
                await out.prepare(request)
                async for chunk in resp.content.iter_chunked(64 * 1024):
                    await out.write(chunk)
                await out.write_eof()
                return out
        except (ConnectionResetError, asyncio.CancelledError):
            raise
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("Music Assistant isn't answering: %s", exc)
            return web.Response(status=502, text=wording.MUSIC_NOT_ANSWERING)

    async def _websocket(self, request: web.Request, session, target: str, headers: dict) -> web.StreamResponse:
        protocols = tuple(p.strip() for p in request.headers.get("Sec-WebSocket-Protocol", "").split(",") if p.strip())
        url = target.replace("http://", "ws://", 1).replace("https://", "wss://", 1)
        try:
            upstream = await session.ws_connect(url, headers=headers, protocols=protocols, heartbeat=30, max_msg_size=0)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("Music Assistant's websocket isn't answering: %s", exc)
            return web.Response(status=502, text=wording.MUSIC_NOT_ANSWERING)
        ws = web.WebSocketResponse(protocols=protocols, heartbeat=30, max_msg_size=0)
        await ws.prepare(request)

        async def pump(src, dst) -> None:
            async for msg in src:
                if msg.type == WSMsgType.BINARY:
                    await dst.send_bytes(msg.data)
                elif msg.type == WSMsgType.TEXT:
                    await dst.send_str(msg.data)
                else:
                    break

        tasks = [asyncio.create_task(pump(ws, upstream)), asyncio.create_task(pump(upstream, ws))]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await upstream.close()
            await ws.close()
        return ws

    async def get(self, request: web.Request, path: str) -> web.StreamResponse:
        return await self._relay(request, path)

    async def post(self, request: web.Request, path: str) -> web.StreamResponse:
        return await self._relay(request, path)

    async def put(self, request: web.Request, path: str) -> web.StreamResponse:
        return await self._relay(request, path)

    async def patch(self, request: web.Request, path: str) -> web.StreamResponse:
        return await self._relay(request, path)

    async def delete(self, request: web.Request, path: str) -> web.StreamResponse:
        return await self._relay(request, path)

    async def head(self, request: web.Request, path: str) -> web.StreamResponse:
        return await self._relay(request, path)

    # No `options`: Home Assistant adds CORS to every view, and aiohttp-cors refuses a route that already
    # has its own OPTIONS handler, which stops everything registered after it. The app is same-origin.


VIEWS = (MusicSessionView, MusicLinkView, MusicProxyView)
