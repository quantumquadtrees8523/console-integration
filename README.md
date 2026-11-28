# Console

Console is the opinionated way to run a home on [Home Assistant](https://www.home-assistant.io) and
[Sunrise](https://github.com/quantumquadtrees8523/sunrise). It adds:

- **Console's agent** (`conversation.console`), for Assist and for the chat card. It answers at home
  when Home Assistant's own agent knows the command (no model, no internet), and otherwise uses the
  household's cloud agent with Sunrise's tools.
- **A chat card** for your dashboards (`custom:console-chat-card`).
- **A Console page** in the sidebar: your plan, this month's usage, and exactly what is sent out.
- **Music Assistant** in the sidebar, for admins, when Home Assistant has a Music Assistant: its own app
  (music sources, speakers, library), relayed by Home Assistant so it opens at home and through the relay,
  and signed in with your Home Assistant login. The first time, sign in to Music Assistant once there and
  press **Use my Home Assistant login**.
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
2. `deepseek/deepseek-v4.1-flash` with thinking off, for a plain device command (and for suggested routines).
3. `deepseek/deepseek-v4.1-flash` with a little thinking, for everything else.
4. `deepseek/deepseek-v4-pro-0813`, only when step 2 or 3 fails or hands a hard request up.

If the cloud agent can't be used (the month's allowance is spent, the relay has been out of reach for
longer than a key lasts, or the model fails) the person is told so, and step 1 keeps working.

## Suggested routines

Console listens to the house and makes routines from what it hears. An administrator turns it on on the
Console page, under Settings. It's off unless someone turns it on, because a run that makes a routine uses
some of the month's credits (the Plan tab shows how many).

- **Every hour** Console asks Sunrise what the house heard: a door, window, motion or presence sensor
  changed (or someone came or went), and a person switched a light, switch, fan or cover by hand within
  two minutes, on at least 4 different days and 6 times in 10. Reading that uses no model, so an hour with
  nothing new uses no credits.
- **Every Monday at 3 AM** (the house's time) the cloud agent also follows Sunrise's `routines` skill to
  look at how the house is used as a whole.
- Both runs use `deepseek/deepseek-v4.1-flash` with thinking off, and are never handed to the stronger model.
- Sunrise saves each one as a real automation, **running at once** and labelled **Suggested**, limited to
  the hours it actually happens in. It never makes one with a lock, alarm, garage door, heating or sound,
  or anything not exposed to Assist.
- They show at the top of the Home dashboard, in the chat card, never as notifications. An administrator
  presses **Keep** (it's an ordinary automation from then on) or **Undo** (it's removed, and never
  suggested again). At most 3 wait for an answer at a time.
- A run is skipped only when the cloud agent can't be used (switched off, unlinked, or the month's
  allowance used up). **Suggest now** on the Console page runs Monday's look at once.
- Needs Sunrise 0.4.0 or newer (its `usage` tool's `follows`, and its `routine` tool's `suggest` with `on`).

## Where the credits went

The Console page's Plan tab has **Where it went**: a pie of this month's credits by where the requests
came from (the chat card, voice, Assist in the app, suggested routines, automations and scripts), with
a legend that also lists what spends no credits (Claude and other agents,
requests while support mode was on). It's kept on the box and isn't part of the summary that is sent out.

At 80% and at 100% of the month's credits, Home Assistant shows a notification, and each phone with the
Companion app gets a push. Each says how much is used and links to the Plan tab. Nothing is throttled;
at 100% the cloud agent pauses until the 1st, as before, and the house keeps working at home.

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
