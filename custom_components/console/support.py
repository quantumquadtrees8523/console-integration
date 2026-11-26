"""Support mode: the household lets Console's operator open this house for a while.

Off unless someone in the household turns it on (here, or at Console's site). It turns itself off
after seven days. While it's on there's a notification in Home Assistant and a banner on the chat card
and the Console page, and each time the operator opens or closes the house a line goes in the log the
household can read.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval

from . import wording
from .const import SUPPORT_DAYS

NOTIFICATION = "console_support"
LOG_KEPT = 100


class Support:
    def __init__(self, hass: HomeAssistant, data) -> None:
        self.hass = hass
        self.data = data
        self._stop = None

    @property
    def state(self) -> dict:
        return self.data.data["support"]

    @callback
    def start(self) -> None:
        self.check()
        self._stop = async_track_time_interval(self.hass, lambda _now: self.check(), timedelta(minutes=10))

    @callback
    def stop(self) -> None:
        if self._stop:
            self._stop()

    @callback
    def log(self, what: str) -> None:
        self.state["log"] = (self.state.get("log") or [])[-(LOG_KEPT - 1) :] + [
            {"at": self.data.now().isoformat(), "what": what}
        ]
        self.data.changed()

    def on(self) -> bool:
        return bool(self.state.get("on")) and bool(self.state.get("until")) and (
            datetime.fromisoformat(self.state["until"]) > self.data.now()
        )

    @callback
    def check(self) -> None:
        """Turn support mode off once its seven days are up."""
        if self.state.get("on") and not self.on():
            self.state.update(on=False, until=None)
            self.log(wording.SUPPORT_EXPIRED)
            self._notify(False)

    @callback
    def set(self, on: bool, by: str) -> dict:
        if on:
            until = (self.data.now().astimezone(UTC) + timedelta(days=SUPPORT_DAYS)).isoformat()
            self.state.update(on=True, until=until)
            self.log(f"Turned on by {by}. It turns itself off in {SUPPORT_DAYS} days.")
        else:
            was = bool(self.state.get("on"))
            self.state.update(on=False, until=None)
            if was:
                self.log(f"Turned off by {by}.")
        self._notify(on)
        self.data.changed()
        return {"on": self.on(), "until": self.state.get("until")}

    def _notify(self, on: bool) -> None:
        if on:
            until = datetime.fromisoformat(self.state["until"])
            self.hass.async_create_task(
                self.hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {"notification_id": NOTIFICATION, "title": wording.SUPPORT_TITLE, "message": wording.support_on(until)},
                )
            )
        else:
            self.hass.async_create_task(
                self.hass.services.async_call("persistent_notification", "dismiss", {"notification_id": NOTIFICATION})
            )
