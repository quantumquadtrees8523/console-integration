"""What the agent is doing, told to the chat card while it does it.

A turn's trail is a list of small events: a step (where the request went and why, a tool being used and
what came back, a hand-up to the stronger model), a piece of the model's thinking, a piece of its reply.
They go to the cards showing that chat, and the steps are kept with the reply in that person's chat
history on the box (history.py), so the work is still in the thread when it is opened again. Nothing
here is logged, and none of it is in Console's store or anything the relay reads.
"""

from __future__ import annotations

from collections.abc import Callable
import json
from typing import Any

DETAIL_MAX = 600
STEPS_KEPT = 40  # steps kept with one reply
THINKING_KEPT = 2000  # characters of one stretch of thinking kept with a reply


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


class Kept:
    """A turn's trail boiled down to what is kept with the reply: its steps in order, and the turn's facts."""

    def __init__(self) -> None:
        self.steps: list[dict[str, Any]] = []
        self.meta: dict[str, Any] = {}
        self._by_key: dict[Any, dict[str, Any]] = {}
        self._thinking: dict[str, Any] | None = None

    def _add(self, step: dict[str, Any]) -> dict[str, Any]:
        if len(self.steps) < STEPS_KEPT:
            self.steps.append(step)
        return step

    def feed(self, event: dict[str, Any]) -> None:
        kind = event.get("kind")
        if kind == "thinking":
            if self._thinking is None:
                self._thinking = self._add({"kind": "think", "title": "Thinking", "detail": ""})
            self._thinking["detail"] = (self._thinking["detail"] + str(event.get("text") or ""))[:THINKING_KEPT]
            return
        if kind in ("step", "said", "text"):
            self._thinking = None  # the next thinking is a new stretch
        if kind == "step":
            step = self._by_key.get(event.get("key"))
            if step is None:
                step = self._by_key[event.get("key")] = self._add({"title": event.get("title") or "Step", "detail": event.get("detail") or ""})
            if event.get("result"):
                step["result"] = str(event["result"])[:DETAIL_MAX]
            if event.get("state") == "failed":
                step["failed"] = True
        elif kind == "said":
            self._add({"title": "Said", "detail": str(event.get("text") or "")[:DETAIL_MAX]})
        elif kind == "meta":
            self.meta = {k: v for k, v in event.items() if k != "kind"}


class LiveTurn:
    """A turn in flight: what has happened so far and who is watching. A card that opens the chat while
    the turn runs (a reload, a phone waking up, a second screen) is told everything so far, then the rest.
    Held in memory for the length of the turn only."""

    def __init__(self, user_id: str) -> None:
        self.user_id = user_id
        self.kept = Kept()
        self._events: list[dict[str, Any]] = []
        self._listeners: list[Callable[[dict[str, Any]], None]] = []

    def emit(self, event: dict[str, Any]) -> None:
        self.kept.feed(event)
        last = self._events[-1] if self._events else None
        if last is not None and event.get("kind") in ("text", "thinking") and last["kind"] == event["kind"]:
            last["text"] += event.get("text") or ""  # pieces of one stretch are replayed as one
        else:
            self._events.append(dict(event))
        for listener in list(self._listeners):
            try:
                listener(event)
            except Exception:  # noqa: BLE001 (a card that went away mustn't break the turn)
                self.detach(listener)

    def attach(self, listener: Callable[[dict[str, Any]], None]) -> None:
        for event in self._events:
            listener(dict(event))
        self._listeners.append(listener)

    def detach(self, listener: Callable[[dict[str, Any]], None]) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)
