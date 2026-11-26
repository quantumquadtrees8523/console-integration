---
name: install
description: "Install Console (the Home Assistant integration that adds Console's agent, chat card, Home dashboard and settings page) on a Home Assistant box that already has Sunrise: connect with connect-to-box, back up, add the HACS repository, download, restart once, add the integration, link the house to Console's relay, and verify on a real device. Use when the owner says \"install Console\", \"set up Console on my box\" or \"/console:install\"."
---

# Install Console

Console sits on top of Home Assistant and Sunrise. This skill puts Console's integration on a box and
proves it works. It changes the box in four places only: HACS's repository list, `custom_components/console`,
one Home Assistant restart, and one config entry. Everything else is read-only.

`scripts/ha_ws.py` beside this file sends Home Assistant websocket commands from inside the Home
Assistant container. The token is piped on stdin and never appears in a command.

## Hard rules

- Never type, print, store or ask for a password, token or key. Use `box-secret` from the
  connect-to-box skill and pipe over stdin.
- A backup before the first change, taken to the local backup location only, and confirmed listed.
- One change, then check it. Never upgrade Home Assistant as a side effect.
- Agree a test device with the owner before switching anything, and put it back as found.
- Locks, alarms and garage doors are never test devices.

## Before you start

1. Run the `connect-to-box:connect-to-box` skill (from the Sunrise marketplace:
   `claude plugin marketplace add quantumquadtrees8523/sunrise`, then
   `claude plugin install connect-to-box@sunrise`). You need its output: the shell command, the Home
   Assistant container's name, and the config path.
2. Check the floor: Home Assistant **2026.10 or newer**, a **Container** install or Home Assistant OS,
   HACS present, and **Sunrise installed and loaded**. If Sunrise is missing, stop and run
   `sunrise:install` first: without Sunrise, Console's agent falls back to Home Assistant's built-in
   Assist tools and the welcome can't run.
3. Read the baseline and write it to the box record: open repairs, the integrations logging errors,
   which dashboards exist, and the current default dashboard (`frontend/get_system_data` with
   `{"key":"core"}`). Console makes its own dashboard the default; the owner should know what it was.

## Step 1: back up

Take a backup with the local agent only, and wait until it is listed:

```
[{"type":"backup/generate","agent_ids":["backup.local"],"name":"before-console-<date>",
  "include_homeassistant":true,"include_database":true,"include_all_addons":false,"include_folders":[]}]
```

then `[{"type":"backup/info"}]` until the name appears with no `failed_agent_ids`. Never fire the
owner's default backup: it may upload somewhere they didn't expect.

## Step 2: add Console to HACS and download it

```
[{"type":"hacs/repositories/add","repository":"quantumquadtrees8523/console-integration","category":"integration"}]
[{"type":"hacs/repositories/list"}]          # filter: console-integration  -> its id and available_version
[{"type":"hacs/repository/download","repository":"<id>","version":"<available_version>"}]
```

Check: `custom_components/console/manifest.json` exists and its `version` is the one you asked for.

## Step 3: restart once, and wait properly

`docker restart <ha-container>` (or the Home Assistant OS restart). Readiness is the line
`Home Assistant initialized in Ns` in `home-assistant.log` with a timestamp after the restart; the
health check and `/manifest.json` both say yes too early.

## Step 4: add the integration

`POST /api/config/config_entries/flow {"handler":"console"}` returns a form with nothing to fill;
post `{}` to its `flow_id`. Or tell the owner: Settings → Devices & services → Add integration →
**Console**.

Check, all of these:
- `conversation.console` exists.
- `sensor.console_cloud_agent` is `not_linked` (it isn't linked yet).
- `switch.console_cloud_agent` and `switch.console_ai` are both `on`.
- A dashboard **Home** exists at `/console-home` and is the default.
- A **Console** page is in the sidebar.

## Step 5: link the house to Console's relay

The house reaches the relay through a hub that dials out; nothing in the house listens to the internet.

- **The owner's own box** already runs the hub as the container `console-hub`. Nothing to do.
- **A new box** needs the hub container and a claim. The hub's source lives in the private
  `console-relay` repository, so today only Console's operator can build it for a box:
  ```
  docker build -t console-hub <console-relay>/hub/console
  docker run -d --name console-hub --restart unless-stopped --network host \
    --env-file ~/console-hub.env -v console-hub:/data -e CONSOLE_DATA=/data console-hub
  docker logs console-hub        # shows an 8-character claim code
  ```
  `~/console-hub.env` (mode 600) holds `HA_URL=http://127.0.0.1:8123` and `HA_TOKEN=` a long-lived
  Home Assistant token of an administrator; the owner creates the token and types it into the file
  themselves. Then the owner signs in at https://console-home.fly.dev with Google and enters the claim
  code under **Claim hub**.

Within a few seconds of the hub connecting, the relay hands the box its cloud-agent key. Check:
`sensor.console_cloud_agent` becomes `ok`. If it stays `not_linked` after a minute, ask the operator
to press **Hand over a fresh key** for this household on the relay's admin page.

## Step 6: Music Assistant (optional, Container installs)

If the owner wants music and Music Assistant isn't running yet, follow
https://www.music-assistant.io/installation/ : one container, host networking, a data volume.

```
docker run -d --name music-assistant-server --restart unless-stopped --network host \
  -v <dir>:/data ghcr.io/music-assistant/server:latest
```

Then in Home Assistant: Settings → Devices & services → the discovered **Music Assistant** → Configure
(or add it by hand with the server's address and port 8095), and sign in with a Music Assistant
**admin** account. That sign-in is the owner's to do. Sunrise's `music-assistant` skill covers using it.

## Step 7: verify on a real device

With the test device the owner agreed to (read its state first):

1. In the Home dashboard's chat card, a plain command ("turn off the <device>"). It should answer in
   well under a second, and the Console page's "How they were answered" should count it under
   **Answered at home (no cloud)**. Read the device back.
2. A request the local agent can't do ("set the <device> to about half"). It should answer in a second
   or two with `Done. <device> is on at 50%.` Read the device back.
3. Put the device back exactly as it was.

## Done means

The checks in steps 4, 5 and 7 all passed and are written in the box record with the version
installed, the backup's name, the previous default dashboard, and the test device's before and after.

## Undo

Remove the Console entry (Settings → Devices & services → Console → Delete), remove Console in HACS,
restart. Console's dashboard and its default-dashboard setting are removed with the entry only if you
delete the **Home** dashboard yourself under Settings → Dashboards; say so to the owner.
