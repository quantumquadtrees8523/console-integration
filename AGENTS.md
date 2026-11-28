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
  person, as threads (one per conversation), shown and deletable in Console settings and erased by the data
  wipe. Nothing may send it anywhere but to the model, as the conversation it belongs to.
- The card lists conversations as collapsed comment threads and opens one whole in a drawer (owner,
  2026-11-28: "facebook comment threads", "within a drawer though. not completely visible"). Where a
  message is written is its scope: a reply stays in its conversation; a new one is told about the person's
  other recent conversations (`history.digest`, `wording.scope_all`). One conversation or all of them copy
  out as text (`console/chat/export`).
- Conversations run at once, one turn per conversation. Each has a status dot: working, error (the agent
  said why it couldn't: `ConsoleData.unfinished`) or done-and-unopened, kept as a per-thread `seen` time in
  the chat file and cleared by `console/chat/seen`. Cards hear starts and finishes on `console/chat/status`.
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
- Every chat, voice and Assist turn, and every change by hand, feeds the device-settings learner
  (`prefs.py`; owner, 2026-11-28: "this should be general. not just speakers and lights"). Any adjustable
  setting Home Assistant has an action for, per domain in `prefs.SETTINGS` (add a row, not a module). Only
  values a person chose count: never one the agent picked unasked (the person's words are checked, never
  kept), never an automation's. The agent is told them every turn and the music tool plays at them.
- Each use of the cloud agent is an AI feature with its own switch and its cost in words (`features.py`,
  the AI features tab). A new one gets a row there. `cloud_state()` is what the relay is told: a feature
  switch never changes it.
- Usage is shown to a household in credits (one cent each, `credits.py`), never dollars. A plan's price stays in dollars.
- The relay's requests to the box are in `relay_api.py`, and their contract is `protocol/tunnel.md` in
  `console-relay`. Change the contract there first.
- Release: bump `version` in `manifest.json` and `VERSION` in `const.py`, merge, tag `vX.Y.Z`.
