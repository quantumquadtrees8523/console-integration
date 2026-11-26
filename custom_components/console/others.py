"""Turns other agents take in this house (Claude, through Home Assistant's MCP server), counted from
the Sunrise tool calls they make. Console sees only which tools ran, never what was said: a burst of
calls with less than 90 seconds between them is one turn, labelled by its tools."""

from __future__ import annotations

from datetime import timedelta
import time

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval

from . import router
from .const import ROUTE_OTHER

GAP_S = 90
AGENT = "other_agents"


class OtherAgents:
    def __init__(self, hass: HomeAssistant, data) -> None:
        self.hass = hass
        self.data = data
        self.since = time.time()
        self.own: list[tuple[float, float]] = []
        self._open: list[dict] = []
        self._stop = None

    @callback
    def start(self) -> None:
        self._stop = async_track_time_interval(self.hass, self._tick, timedelta(seconds=60))

    @callback
    def stop(self) -> None:
        if self._stop:
            self._stop()

    @callback
    def mark_own(self, started: float, ended: float) -> None:
        """A stretch of time in which the tool calls were Console's own."""
        self.own = [w for w in self.own if w[1] > time.time() - 3600] + [(started - 1, ended + 1)]

    def _calls(self) -> list[dict]:
        for entry in self.hass.config_entries.async_entries("sunrise"):
            runtime = getattr(entry, "runtime_data", None)
            if runtime is not None and getattr(runtime, "calls", None) is not None:
                return list(runtime.calls)
        return []

    @callback
    def _tick(self, _now=None) -> None:
        self.scan(time.time())

    @callback
    def scan(self, now: float) -> int:
        """Count the turns that have ended since the last look. Returns how many were counted."""
        fresh = [
            c for c in self._calls()
            if c.get("ts", 0) > self.since and not any(a <= c["ts"] <= b for a, b in self.own)
        ]  # fmt: skip
        if fresh:
            self.since = max(c["ts"] for c in fresh)
            self._open += sorted(fresh, key=lambda c: c["ts"])
        counted = 0
        while self._open:
            group = [self._open[0]]
            for call in self._open[1:]:
                if call["ts"] - group[-1]["ts"] > GAP_S:
                    break
                group.append(call)
            if now - group[-1]["ts"] <= GAP_S:
                break  # this turn may still be going
            del self._open[: len(group)]
            category = router.category_for_tools([(c.get("tool", ""), c.get("args") or {}) for c in group])
            self.data.count_turn(ROUTE_OTHER, category, not any(c.get("error") for c in group), agent=AGENT)
            counted += 1
        return counted
