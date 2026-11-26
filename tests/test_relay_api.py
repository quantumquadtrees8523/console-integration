"""What the relay may ask of the box: administrators only, and only counts come back."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.console.const import OPENROUTER_URL, VERSION

HANDOVER = {
    "inference": {
        "base_url": OPENROUTER_URL,
        "key": "household-key",
        "expires_at": (datetime.now(UTC) + timedelta(hours=6)).isoformat(),
    },
    "plan": {"tier": "standard", "tier_name": "Standard", "cap_usd": 2.0, "next": {"name": "Plus", "price": "$10 a month"}},
    "spend": {"period": datetime.now(UTC).strftime("%Y-%m"), "usd": 0.5},
}


async def test_the_relay_hands_over_a_key_and_reads_the_usage_summary(hass, console, hass_client):
    client = await hass_client()
    answer = await client.post("/api/console/relay/config", json=HANDOVER)
    assert answer.status == 200
    report = await answer.json()
    assert report["console"] == VERSION and report["cloud_agent"] == "ok"
    assert report["usage"]["spend_usd"] == 0.5 and "household-key" not in str(report)
    assert console.key()["key"] == "household-key" and console.plan["tier_name"] == "Standard"
    assert hass.states.get("sensor.console_cloud_agent").state == "ok"


async def test_the_relay_can_say_the_month_is_spent(hass, console, hass_client):
    client = await hass_client()
    await client.post("/api/console/relay/config", json=HANDOVER | {"over": True})
    assert console.cloud_state() == "over_limit"
    await client.post("/api/console/relay/config", json=HANDOVER)
    assert console.cloud_state() == "ok"


async def test_only_an_administrator_may_hand_over_a_key(hass, console, hass_client, hass_client_no_auth, hass_read_only_access_token):
    stranger = await hass_client_no_auth()
    assert (await stranger.post("/api/console/relay/config", json=HANDOVER)).status == 401
    reader = await hass_client(hass_read_only_access_token)
    assert (await reader.post("/api/console/relay/config", json=HANDOVER)).status == 403
    assert (await reader.get("/api/console/relay/status")).status == 403
    assert console.key() is None


async def test_a_handover_without_a_key_is_refused(hass, console, hass_client):
    client = await hass_client()
    bad = await client.post("/api/console/relay/config", json={"inference": {"base_url": OPENROUTER_URL}})
    assert bad.status == 400 and console.key() is None


async def test_the_relay_can_notify_the_household(hass, console, hass_client):
    assert await __import__("homeassistant.setup", fromlist=["x"]).async_setup_component(hass, "persistent_notification", {})
    client = await hass_client()
    answer = await client.post("/api/console/relay/notify", json={"title": "From Console", "message": "Maintenance tonight."})
    assert answer.status == 200 and (await answer.json())["ok"] is True


async def test_the_card_and_the_panel_are_served(hass, console, hass_client):
    client = await hass_client()
    card = await client.get("/console_static/console-chat-card.js")
    assert card.status == 200 and 'customElements.define("console-chat-card"' in await card.text()
    panel = await client.get("/console_static/console-panel.js")
    assert panel.status == 200 and "console-panel" in await panel.text()
    assert "console" in hass.data["frontend_panels"]


async def test_the_status_command_says_what_the_card_needs(hass, console, hass_ws_client):
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "console/status"})
    result = (await ws.receive_json())["result"]
    assert result["cloud_agent"] == "not_linked" and result["banner"]["kind"] == "offline"
    assert result["plan"]["tier_name"] == "Free" and result["usage"]["turns"] == 0
