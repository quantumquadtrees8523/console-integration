---
name: connect
description: "Connect Claude Code (or Claude on the web, desktop or phone) to a house through Console's relay, so Claude can use Sunrise's tools on that house from anywhere: add the MCP server, sign in, check the tools, and verify with a harmless read. Use when the owner says \"connect Claude to my house\", \"add the Console connector\" or \"/console:connect\"."
---

# Connect Claude to the house through Console's relay

The relay is at `https://console-home.fly.dev`. Home Assistant's own MCP server sits behind it, and
Sunrise's tools are at `/api/mcp/sunrise`. Signing in is two steps the person does themselves: the
relay's sign-in (Google), which picks their house, then Home Assistant's own login, which says what
Claude may do there.

Never type, print or ask for a password or token. Every sign-in below is the owner's own.

## Claude Code

1. Add the server (user scope, so every project sees it):
   ```bash
   claude mcp add --transport http --scope user console https://console-home.fly.dev/api/mcp/sunrise
   ```
2. Sign in: inside Claude Code run `/mcp`, pick **console**, choose **Authenticate**. Or from a shell:
   ```bash
   claude mcp login console
   ```
   A browser opens at the relay.
   - If they aren't signed in there yet: **Sign in with Google**. The page then goes on by itself.
   - Home Assistant's login appears: their Home Assistant username and password. This is the
     account Claude will act as; an administrator's account lets Claude change things, any other
     account can only read.
   - The browser says it can be closed.
3. Check: `claude mcp list` shows `console: … ✔ Connected`. In a session, `/mcp` lists the tools:
   `house_map`, `act`, `audit`, `diagnose_device`, `fix_device`, `routine`, `registry_edit`, `changes`,
   `undo`, `backup`, `memory_read`, `memory_write`, `memory_list`, `memory_delete`, `get_skill`,
   `list_skills`, `skill_update`, `behavior_log`, `behavior_revert`, `network_check`, `usage`,
   `log_run`, and the date and time.
4. Verify with a read that changes nothing: ask "use the console tools to tell me how many rooms this
   house has". It should call `house_map`.

To disconnect: `claude mcp logout console`, then `claude mcp remove console`.

## Claude on the web, desktop and phone (a custom connector)

1. Open https://claude.ai/customize/connectors → **Add** → **Add custom connector**.
2. Name: `Console`. URL: `https://console-home.fly.dev/api/mcp/sunrise`. Leave the OAuth client on
   Claude's own identity. **Add**, then **Connect**.
3. Sign in exactly as above: the relay (Google), then Home Assistant.
4. In a chat: **+** → **Connectors** → turn **Console** on. The connector is saved to the account, so
   it's there on the phone too.

This link opens the dialog already filled in:
`https://claude.ai/customize/connectors?modal=add-custom-connector&connectorName=Console&connectorUrl=https%3A%2F%2Fconsole-home.fly.dev%2Fapi%2Fmcp%2Fsunrise`

## If it doesn't connect

- **"Needs authentication" again after signing in:** the Home Assistant login was closed before it
  finished, or the house's hub is offline. Open https://console-home.fly.dev : it should land in Home
  Assistant. If it says "Reaching your house…", the hub isn't connected.
- **Every tool call says AI is turned off for this house:** someone turned off **AI in this house** on
  the Console page in Home Assistant (Settings tab). Only someone in the house can turn it back on.
- **The tools list is empty or sign-in loops:** the box needs Console 0.4.0 or newer; older versions
  can't tell the relay which house a token belongs to.
