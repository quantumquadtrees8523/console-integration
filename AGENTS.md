# Agent notes

Console's Home Assistant integration (domain `console`). It builds on Sunrise and never the other way
round: everything that talks to the internet lives here; Sunrise makes no internet calls.

Three open source projects make the home lab (owner, 2026-11-28). **Console** is the harness: everything
about the agent (models, turns, schedules, what it spends). **Sunrise** is the skillset: the skills and the
tools they use. **Makaan** is the operating system on top of Home Assistant. Put a change where it belongs:
a skill's method or a tool in Sunrise, when and on which model it runs here.

- One GitHub Issue, one branch, one PR. CI is the gate. A behavior is done only when a test proves it.
- `custom_components/console/wording.py` holds every sentence a household reads. Change words there.
- What a person says never leaves the box and is never in Console's store (`.storage/console`): a turn
  leaves a route and a label there, and `test_nothing_a_person_says_is_kept` holds that line. The chat
  card's history is a file of its own on the box (`.storage/console_chat`, `history.py`), per signed-in
  person, as threads (one per chat), shown and deletable in Console settings and erased by the data wipe.
  Nothing may send it anywhere.
- What the agent is doing during a turn (`trail.py`) goes to the cards showing that chat, and its steps are
  kept with the reply in that person's thread (owner, 2026-11-28: "show each chat and agent's work within
  the thread of a chat"). Same file, same rules as the chat history: on the box only, never logged, never
  in Console's store.
- A chat turn runs on the box whoever is listening. The card never sends a message twice: it subscribes
  with `resubscribe: false`, and after a reconnect reads the thread and watches a running turn
  (`console/chat/watch`).
- The chat always offers three suggestions (`suggestions.py`), made at home with no AI unless the weekly
  run added routines. Three taps on two days makes one a quick action; four sightings on two days with no
  tap discards it. Only lights, switches, fans, helpers and scenes exposed to Assist.
- Each use of the cloud agent is an AI feature with its own switch and its cost in words (`features.py`,
  the AI features tab). A new one gets a row there. `cloud_state()` is what the relay is told: a feature
  switch never changes it.
- Usage is shown to a household in credits (one cent each, `credits.py`), never dollars. A plan's price stays in dollars.
- Usage is counted in one place, `metrics.py`, and everything reports through it: every request
  (`ConsoleData.count_turn`), every tool any agent calls, Console's own or Claude and Claude Code through the
  connector (`guard.CountedTool`, in front of every LLM API), taps and opened screens. Its `REGISTRY` is the
  single list of what can be counted. A new AI feature, tool, skill, agent, surface or screen is not done
  until it has an entry there and a plain name in `wording.METRIC_NAMES`; tests fail without (and one reads
  Sunrise's tools and skills from a checkout: `SUNRISE_REPO`, or `../sunrise`). Don't count anywhere else.
- Usage details keep to an allow-list, and that is the privacy rule: only ids from `REGISTRY` and the other
  fixed tuples in `metrics.py` are stored or sent, an unknown name lands on a catch-all (`unregistered`), a
  count is a number, a day is a UTC date. Never add a field that could hold words, a name, an entity, a room,
  a person or a time of day, and never derive a count from what was said: from the tool's name and its
  result only. The story is built from `wording.STORY` and the names alone, and `metrics.scrub` refuses any
  other word. The household is shown the exact bytes that are sent (`metrics.body`, one function for both),
  has `switch.console_usage_details`, and the data wipe erases the counts.
- The lists and the story's words are a contract: console-relay `protocol/metrics.md`, with a copy of its
  schema at `tests/metrics.schema.json`. Add to the relay's lists and release it first, then register here
  and copy the schema: a box that sends an id the relay doesn't know has its whole report refused.
- The relay's requests to the box are in `relay_api.py`, and their contract is `protocol/tunnel.md` in
  `console-relay`. Change the contract there first.
- Release: bump `version` in `manifest.json` and `VERSION` in `const.py`, merge, then tag `vX.Y.Z` or press Run workflow on `release` (main; an agent can start it through GitHub's API).
