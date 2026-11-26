# Agent notes

Console's Home Assistant integration (domain `console`). It builds on Sunrise and never the other way
round: everything that talks to the internet lives here; Sunrise makes no internet calls.

- One GitHub Issue, one branch, one PR. CI is the gate. A behavior is done only when a test proves it.
- `custom_components/console/wording.py` holds every sentence a household reads. Change words there.
- What a person says never leaves the box and is never in Console's store (`.storage/console`): a turn
  leaves a route and a label there, and `test_nothing_a_person_says_is_kept` holds that line. The chat
  card's history is a file of its own on the box (`.storage/console_chat`, `history.py`), per signed-in
  person, shown and deletable on the Console page and erased by the data wipe. Nothing may send it anywhere.
- What the agent is doing during a turn (`trail.py`) goes to the card that asked and is not kept or logged.
- Usage is shown to a household in credits (one cent each, `credits.py`), never dollars. A plan's price stays in dollars.
- The relay's requests to the box are in `relay_api.py`, and their contract is `protocol/tunnel.md` in
  `console-relay`. Change the contract there first.
- Release: bump `version` in `manifest.json` and `VERSION` in `const.py`, merge, tag `vX.Y.Z`.
