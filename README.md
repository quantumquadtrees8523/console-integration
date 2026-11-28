# Console

Console is the opinionated way to run a home on [Home Assistant](https://www.home-assistant.io) and
[Sunrise](https://github.com/quantumquadtrees8523/sunrise). It adds:

- **Console's agent** (`conversation.console`), for Assist and for the chat card. It answers at home
  when Home Assistant's own agent knows the command (no model, no internet), and otherwise uses the
  household's cloud agent with Sunrise's tools.
- **A chat card** for your dashboards (`custom:console-chat-card`): your chats as threads, each with the
  work behind Console's replies; three suggestions to tap; and quick actions for the ones you keep using.
- **Console settings** in the sidebar: your plan, this month's usage, exactly what is sent out, and a
  switch for each AI feature with what it tends to cost.
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
2. `deepseek/deepseek-v4.1-flash` with thinking off, for a plain device command.
3. `deepseek/deepseek-v4.1-flash` with a little thinking, for everything else.
4. `deepseek/deepseek-v4-pro-0813`, only when step 2 or 3 fails or hands a hard request up.

If the cloud agent can't be used (the month's allowance is spent, the relay has been out of reach for
longer than a key lasts, or the model fails) the person is told so, and step 1 keeps working.

## Chats are threads

Each chat is its own thread. **Chats** at the top of the card lists them, newest first; open one and the
whole of it is there, ten messages at a time from the newest, with a line under each reply that opens into
the work behind it: where the request went and why, the model's thinking, each tool it used and what came
back. A chat used in the last half hour opens by itself; otherwise the card starts a new one.

- Threads are kept on the box only, per signed-in person: the newest 40 chats, 200 messages each. ✕ beside
  a chat deletes it; Console settings deletes all of yours; the data wipe erases everyone's.
- A turn runs on the box whoever is watching. If the card reloads, the phone sleeps or the connection
  drops, the reply still lands in its thread, and a card that opens the chat meanwhile picks the turn up as
  it happens. One message is always one turn: nothing is sent again when the connection comes back.

## Suggestions and quick actions

The chat always shows **three suggestions**, each a tap that runs something now and reads back what
changed. They're made on this box from the house as it is, with no AI, so they cost nothing and are there
even when the cloud agent isn't:

1. What this house usually has on at about this hour (from Sunrise's `usage`): "Turn on Den lamp".
2. What's on right now: "Turn off the Kitchen lights", "Turn off all the lights".
3. Your own scenes.
4. A light or switch the house uses most.
5. Something to ask Console, when there's nothing better, so there are always three.

They only ever turn lights, switches, fans and helpers on or off, or run a scene, and only things exposed
to Assist. Never a lock, alarm, garage door, heating or anything that makes sound.

- **Use one and it sticks.** Tapped 3 times on 2 different days, a suggestion becomes a **quick action**:
  it leaves the suggestions and stays under the chat (at most 6).
- **Ignore one and it goes.** Seen 4 times on 2 different days and never tapped, it's put away for 30 days
  and the next one takes its place. An administrator's ✕ removes one for good.
- A quick action nobody uses for 30 days goes back to being an ordinary suggestion.
- **Suggestions and quick actions in chat** under AI features turns the whole row off.

### Suggested routines

An administrator can turn on **Suggested routines** in Console settings, under AI features. It's off
unless someone turns it on, because each run uses some of the month's credits.

The house uses Console, and Console is guided by Sunrise: each run is one ordinary turn of Console's cloud
agent following Sunrise's `routines` skill, on `deepseek/deepseek-v4.1-flash` with thinking off, and never
handed to the stronger model.

- **Every hour** the agent is asked what the house heard and follows the skill's "Listening": Sunrise
  lists what followed what (a door, window, motion or presence sensor changed, or someone came or went,
  and a person switched a light, switch, fan or cover by hand within two minutes, on at least 4 different
  days and 6 times in 10), and the agent saves those as suggestions, or changes nothing.
- **Every Monday at 3 AM** (the house's time) it follows "Suggesting routines" in full, for habits by the
  clock too. Up to 3 wait at a time.
- The house can ask for a run itself with the `console.suggest_routines` service (an automation, a button).
- Sunrise saves each one as a real automation, **switched off** and labelled **Suggested**, so it can't
  fire on its own. It never suggests anything with a lock, alarm, garage door, heating or sound, or
  anything not exposed to Assist.
- They show first among the chat's suggestions, for administrators (trying one changes the house's
  setup). A tap runs one once. **The second tap lets it run by itself** from then on, with nothing else to
  press: it's an ordinary automation, which Sunrise's `undo` can still take back.
- An accepted routine stays among the suggestions, and using it makes it a quick action under the chat,
  like any other.
- One nobody taps for 7 days is removed, and so is one that's seen and ignored. A removed routine is never
  suggested again. An administrator can also let one run by itself at once, or remove any of them, under
  AI features.
- A run is skipped while 3 are waiting, or when the cloud agent can't be used. **Suggest now** runs
  Monday's look at once.
- Needs Sunrise 0.4.0 or newer (its `routines` skill's "Listening" and its `usage` tool's `follows`).

## AI features

Console settings has an **AI features** tab: each thing Console does with AI, what it's for, how expensive
it tends to be, what this house spent on it this month (counted on the box, in credits), what turning it
off means, and its own switch for administrators.

| Feature | Tends to cost | Starts |
|---|---|---|
| Cloud agent in chat, voice and Assist | Low per request, most of a month's credits in total | on |
| Stronger model for hard requests | High per request, rare | on |
| Suggested routines | Medium: a short run every hour, a long one a week | off |
| Weekly reply style | Medium, once a week per person | on |
| Suggestions and quick actions in chat | Free | on |

These are apart from the two off switches (cloud access, and AI in this house), which cut everything at
once. A feature that is off stops one use of Console's cloud agent and nothing else. Erasing Console's
data never turns one back on.

## Where the credits went

The Plan tab in Console settings has **Where it went**: a pie of this month's credits by where the requests
came from (the chat card, voice, Assist in the app, suggested routines, automations and scripts), with
a legend that also lists what spends no credits (taps on suggestions and quick actions, Claude and other agents,
requests while support mode was on). It's kept on the box and isn't part of the summary that is sent out.

At 80% and at 100% of the month's credits, Home Assistant shows a notification, and each phone with the
Companion app gets a push. Each says how much is used and links to the Plan tab. Nothing is throttled;
at 100% the cloud agent pauses until the 1st, as before, and the house keeps working at home.

## Updates

Console settings has **Update now**: it installs the latest release of each integration HACS manages
(Console, Sunrise, any other) that has an update waiting, reads each version back, then restarts Home
Assistant once. Home Assistant itself updates separately. Console's site has the same button for each
house, and one for every house, which the household allows with **Updates from Console's site**
(`switch.console_updates`, on unless they turn it off; nothing reaches the house with cloud access off).
Each run goes in the log under Support mode: who, what went from which version to which, what didn't.

## What leaves the house

- To the model provider (OpenRouter): the conversation, the tool list and tool results, for requests
  that step 1 didn't answer.
- To Console's relay: once in a while, this month's totals. Requests by kind (`control`, `status`,
  `customization`, `setup`, `troubleshooting`, `other`), by route, by agent, how many were done, and
  the spend. No messages, device names, rooms or times of day. Console settings shows the exact payload.
- To Console's relay, usage details: for each day (a UTC date), how often each AI feature, tool, skill,
  agent and screen was used, whether it worked (done, failed, not confirmed by the read-back), which model
  tier answered and how long it took in four bands; what exists on this box and was never used; and a few
  sentences that say the same in words, written on the box from the counts alone. Every name in it is from
  a fixed list that ships with Console (`metrics.py`), so nothing you say and no device, room or person
  can be in it, and there is no time of day. Unlike the labels above, the relay keeps these for this house,
  where Console's operator can read them. Console settings → What the house knows about you shows the exact
  bytes that are sent. **Usage details sent to Console** (`switch.console_usage_details`, on unless you turn
  it off) stops the counting and the sending, and the relay then deletes what it has. Erasing Console's data
  erases them here and there.
- To Console's relay, when it asks for the box's status: the versions of Console, Sunrise and Home
  Assistant, and the name, installed version and latest release of each integration HACS manages, so
  the site can show which houses have an update waiting.

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
git clone --depth 1 https://github.com/quantumquadtrees8523/sunrise ../sunrise   # or set SUNRISE_REPO
pytest
```

One test reads Sunrise's tool table and shipped skills from that checkout and fails if any has no entry in
Console's usage registry (`metrics.py`), so it fails without the checkout too.

A release is a tag `vX.Y.Z` that matches `version` in `custom_components/console/manifest.json`.
