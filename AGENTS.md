# Agent notes

Console's Home Assistant integration (domain `console`). It builds on Sunrise and never the other way
round: everything that talks to the internet lives here; Sunrise makes no internet calls.

- One GitHub Issue, one branch, one PR. CI is the gate. A behavior is done only when a test proves it.
- `custom_components/console/wording.py` holds every sentence a household reads. Change words there.
- Nothing a person says is stored. A turn leaves a route and a label in `.storage/console`; the test
  `test_nothing_a_person_says_is_kept` holds that line.
- The relay's requests to the box are in `relay_api.py`, and their contract is `protocol/tunnel.md` in
  `console-relay`. Change the contract there first.
- Release: bump `version` in `manifest.json` and `VERSION` in `const.py`, merge, tag `vX.Y.Z`.
