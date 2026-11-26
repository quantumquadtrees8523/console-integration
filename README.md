# Console

Console is the opinionated way to run a home on [Home Assistant](https://www.home-assistant.io) and
[Sunrise](https://github.com/quantumquadtrees8523/sunrise). It adds:

- **Console's agent** (`conversation.console`), for Assist and for the chat card. It answers at home
  when Home Assistant's own agent knows the command (no model, no internet), and otherwise uses the
  household's cloud agent with Sunrise's tools.
- **A chat card** for your dashboards (`custom:console-chat-card`).
- **A Console page** in the sidebar: your plan, this month's usage, and exactly what is sent out.
- **The link to Console's relay**, which hands this house its own short-lived model key and reads back
  monthly totals. No message is ever sent to the relay; the chat card's history stays on the box.

## Install

Console needs Home Assistant 2026.10 or newer. Sunrise should be installed first: without it Console's
agent falls back to Home Assistant's built-in Assist tools.

1. In HACS: ⋮ → Custom repositories → add `https://github.com/quantumquadtrees8523/console-integration`,
   type **Integration**. Download **Console**, then restart Home Assistant.
2. Settings → Devices & services → Add integration → **Console**. There is nothing to type.
3. Add the chat card to a dashboard: Edit dashboard → Add card → **Console chat**.
4. To make Console the agent behind Assist: Settings → Voice assistants → your assistant →
   Conversation agent → **Console**.

The cloud agent starts working once this house is linked at Console's site and its hub is connected.
Until then the card says the cloud agent isn't connected, and plain commands still run at home.

## How a request is answered

1. Home Assistant's own agent: built-in sentences and the household's learned ones. Free, on the home network.
2. `deepseek/deepseek-v4.1-flash` with thinking off, for a plain device command.
3. `deepseek/deepseek-v4.1-flash` with a little thinking, for everything else.
4. `deepseek/deepseek-v4-pro-0813`, only when step 2 or 3 fails or hands a hard request up.

If the cloud agent can't be used (the month's allowance is spent, the relay has been out of reach for
longer than a key lasts, or the model fails) the person is told so, and step 1 keeps working.

## What leaves the house

- To the model provider (OpenRouter): the conversation, the tool list and tool results, for requests
  that step 1 didn't answer.
- To Console's relay: once in a while, this month's totals. Requests by kind (`control`, `status`,
  `customization`, `setup`, `troubleshooting`, `other`), by route, by agent, how many were done, and
  the spend. No messages, device names, rooms or times of day. The Console page shows the exact payload.

## Claude Code plugin

This repository is also a Claude Code plugin marketplace with one plugin, `console`:

```bash
claude plugin marketplace add quantumquadtrees8523/console-integration
claude plugin install console@console
```

It adds three skills: `console:install` (put Console on a box that has Sunrise), `console:connect`
(connect Claude to the house through Console's relay) and `console:support-mode`.

## Develop

```bash
uv venv -p 3.14 .venv && . .venv/bin/activate && uv pip install -r requirements-test.txt
pytest
```

A release is a tag `vX.Y.Z` that matches `version` in `custom_components/console/manifest.json`.
