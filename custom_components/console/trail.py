"""What the agent is doing, told to the chat card while it does it.

A turn's trail is a list of small events: a step (where the request went and why, a tool being used and
what came back, a hand-up to the stronger model), a piece of the model's thinking, a piece of its reply.
They go to the one card that asked and nowhere else: nothing here is stored or logged.
"""

from __future__ import annotations

from collections.abc import Callable
import json
from typing import Any

DETAIL_MAX = 600


class Trail:
    def __init__(self, send: Callable[[dict[str, Any]], None] | None) -> None:
        self._send = send
        self._n = 0

    @property
    def live(self) -> bool:
        """Whether a chat card is listening (a voice request or another client has no trail)."""
        return self._send is not None

    def _emit(self, event: dict[str, Any]) -> None:
        if self._send is not None:
            try:
                self._send(event)
            except Exception:  # noqa: BLE001 (a card that went away mustn't break the turn)
                self._send = None

    def step(self, title: str, detail: str = "", ok: bool = True) -> None:
        """Something that happened, already finished."""
        self._n += 1
        self._emit({"kind": "step", "key": self._n, "title": title, "detail": detail[:DETAIL_MAX], "state": "done" if ok else "failed"})

    def begin(self, title: str, detail: str = "") -> int:
        """Something that has started; `end` finishes it."""
        self._n += 1
        self._emit({"kind": "step", "key": self._n, "title": title, "detail": detail[:DETAIL_MAX], "state": "running"})
        return self._n

    def end(self, key: int, result: Any, failed: bool) -> None:
        self._emit({"kind": "step", "key": key, "result": summary(result), "state": "failed" if failed else "done"})

    def thinking(self, piece: str) -> None:
        self._emit({"kind": "thinking", "text": piece})

    def text(self, piece: str) -> None:
        self._emit({"kind": "text", "text": piece})

    def said(self, words: str) -> None:
        """Words the model said before going on to use a tool: they move from the reply into the steps."""
        self._n += 1
        self._emit({"kind": "said", "key": self._n, "text": words[:DETAIL_MAX]})

    def reset(self) -> None:
        """The reply so far is void (another model is starting the request again)."""
        self._emit({"kind": "reset"})

    def meta(self, **facts: Any) -> None:
        self._emit({"kind": "meta", **facts})


class LabelGate:
    """Lets a streamed reply through while holding back its trailing [[label]], which people never see."""

    def __init__(self) -> None:
        self.text = ""
        self.sent = 0

    def feed(self, piece: str) -> str:
        self.text += piece
        end = len(self.text)
        mark = self.text.rfind("[[", self.sent)
        if mark != -1:
            close = self.text.find("]]", mark)
            if close == -1 or not self.text[close + 2 :].strip():
                end = mark  # an open label, or a closed one with nothing after it: hold it back
        elif self.text.endswith("["):
            end -= 1
        end = max(end, self.sent)
        shown, self.sent = self.text[self.sent : end], end
        return shown


_TITLES = {
    "house_map": "Looked at the house",
    "audit": "Checked the house for problems",
    "changes": "Looked at recent changes",
    "usage": "Looked at how things are used",
    "memory_list": "Looked through its notes",
    "list_skills": "Looked at its skills",
    "network_check": "Checked the network",
    "log_run": "Wrote down what it did",
    "GetDateTime": "Checked the date and time",
    "GetLiveContext": "Read what's on right now",
    "about": "Looked up Console's own facts",
}


def tool_step(name: str, args: Any) -> tuple[str, str]:
    """A tool call as a step: a plain title, and the details for whoever opens it."""
    a = args if isinstance(args, dict) else {}
    if name == "act":
        title = f"Doing {a.get('action', 'something')} on {len(a.get('entity_ids') or [])} thing(s)"
    elif name == "get_skill":
        title = f"Read the skill “{a.get('name', '')}”"
    elif name in ("memory_read", "memory_write", "memory_delete"):
        verb = {"memory_read": "Read", "memory_write": "Saved", "memory_delete": "Deleted"}[name]
        title = f"{verb} the note {a.get('name', '')}"
    elif name == "music":
        what = a.get("query") or a.get("what") or a.get("room") or ""
        title = f"Music: {a.get('op', '')} {what}".strip()
    elif name == "dashboard":
        title = f"Dashboard: {a.get('op', '')} {a.get('title', '')}".strip()
    elif name in ("routine", "registry_edit", "backup", "diagnose_device", "fix_device", "undo", "discovered"):
        title = f"{name.replace('_', ' ').capitalize()}: {a.get('op') or a.get('target') or ''}".strip(": ")
    elif name.startswith("Hass"):
        title = f"Home Assistant action {name[4:]}"
    else:
        title = _TITLES.get(name, f"Used {name.replace('_', ' ')}")
    return title, json.dumps(a, ensure_ascii=False, default=str) if a else ""


def summary(result: Any) -> str:
    """What a tool gave back, short enough to read in the card."""
    if isinstance(result, dict) and isinstance(result.get("results"), list) and result["results"]:
        rows = [f"{r.get('name') or r.get('id')}: {r.get('result')}" for r in result["results"] if isinstance(r, dict)]
        if rows:
            return "; ".join(rows)[:DETAIL_MAX]
    if isinstance(result, dict) and result.get("error"):
        return str(result["error"])[:DETAIL_MAX]
    try:
        text = json.dumps(result, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(result)
    return text if len(text) <= DETAIL_MAX else text[: DETAIL_MAX - 1] + "…"
