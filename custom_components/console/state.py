"""What Console keeps on the box: the inference key the relay handed it, the plan, this month's spend
and counts, learned sentences, and support mode. One file, .storage/console, readable by root only like
Home Assistant's other stores. Nothing here is a message: counts and labels only."""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar
import uuid
from datetime import UTC, datetime
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .const import (
    CATEGORIES,
    DEFAULT_PLAN,
    MONTHS_KEPT,
    ROUTES,
    STOP_AT,
    STORAGE_KEY,
    STORAGE_VERSION,
    WARN_AT,
)


# Where the request being answered came from, for the length of one turn (conversation.py sets it).
PATH: ContextVar[str | None] = ContextVar("console_path", default=None)


def period_of(now: datetime) -> str:
    """The month a turn counts toward. OpenRouter's monthly limits reset at 00:00 UTC on the 1st."""
    return now.astimezone(UTC).strftime("%Y-%m")


def next_reset(now: datetime) -> datetime:
    now = now.astimezone(UTC)
    year, month = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
    return datetime(year, month, 1, tzinfo=UTC)


def _empty_month() -> dict[str, Any]:
    return {
        "turns": 0,
        "ok": 0,
        "failed": 0,
        "spend_usd": 0.0,
        "by_route": dict.fromkeys(ROUTES, 0),
        "by_category": dict.fromkeys(CATEGORIES, 0),
        "by_agent": {},
        "by_path": {},  # path -> {"turns", "spend_usd"}: shown on the Plan tab, not sent to the relay
    }


def _fresh() -> dict[str, Any]:
    return {
        "inference": None,  # {"base_url", "key", "expires_at"}: handed over by the relay
        "plan": dict(DEFAULT_PLAN),
        "relay_spend": None,  # {"period", "usd"}: what OpenRouter had counted when the relay last looked
        "limit_hit": None,  # the period in which OpenRouter refused the key for being spent
        "months": {},
        "learned": [],
        "phrases": {},
        "support": {"on": False, "until": None, "log": []},
        "onboarding": {"offered": False, "done": False},
        "dashboard": {},
        "made": {},  # dashboards made through the agent's `dashboard` tool, by url path
        "linked_at": None,
        "switches": {"cloud": True, "ai": True},  # the off switches (cloud access, AI): on unless the household turns one off
        "site": None,  # the relay's address for this household, as the relay last gave it
        "unlinked": False,  # the household erased its data here: the relay is refused until they reconnect
        # What kind of thing each request was (topics.py), by month, not yet sent; and the batch being
        # sent, kept unchanged until the relay says it was counted.
        "topics": {"pending": {}, "sending": None},
        "suggestions": {"on": False, "items": [], "never": [], "kept": [], "last_run": None, "counts": {}},  # suggestions.py
    }


class ConsoleData:
    """The store, loaded once, saved a moment after each change."""

    def __init__(self, hass: HomeAssistant, now: Callable[[], datetime] | None = None) -> None:
        self.hass = hass
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY, private=True)
        self.data: dict[str, Any] = _fresh()
        self.now = now or (lambda: datetime.now(UTC))
        self._listeners: list[Callable[[], None]] = []
        # While a chat card waits on a turn: where to send that conversation's trail, and the earlier
        # messages it has on screen. Held in memory for the length of the turn only.
        self.streams: dict[str, Callable[[dict[str, Any]], None]] = {}
        self.earlier: dict[str, list[dict[str, Any]]] = {}
        # Requests whose path the caller knows (the chat card, the suggestions run), by context id, for one turn.
        self.via: dict[str, str] = {}

    async def async_load(self) -> None:
        stored = await self._store.async_load()
        if stored:
            self.data = _fresh() | stored

    @callback
    def changed(self) -> None:
        self._store.async_delay_save(lambda: self.data, 2)
        for listener in list(self._listeners):
            listener()

    async def async_save_now(self) -> None:
        await self._store.async_save(self.data)

    @callback
    def listen(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    async def async_erase(self) -> None:
        """Forget everything Console keeps (the wipe's first level). The kill switches stay as they
        were: erasing data must never turn AI back on."""
        switches = dict(self.data.get("switches") or {})
        self.data = _fresh()
        self.data["switches"].update(switches)
        await self._store.async_remove()
        for listener in list(self._listeners):
            listener()

    # --- this month -------------------------------------------------------------------------------

    @property
    def period(self) -> str:
        return period_of(self.now())

    def month(self, period: str | None = None) -> dict[str, Any]:
        period = period or self.period
        months = self.data["months"]
        if period not in months:
            months[period] = _empty_month()
            for old in sorted(months)[:-MONTHS_KEPT]:
                del months[old]
        return months[period]

    @property
    def plan(self) -> dict[str, Any]:
        return self.data["plan"]

    @property
    def cap_usd(self) -> float:
        return float(self.plan.get("cap_usd") or 0.0)

    @property
    def spend_usd(self) -> float:
        """This month's cloud-agent spend: what this box counted from each model call, or what the
        relay read from OpenRouter, whichever is higher."""
        counted = float(self.month()["spend_usd"])
        relay = self.data.get("relay_spend") or {}
        if relay.get("period") == self.period:
            return max(counted, float(relay.get("usd") or 0.0))
        return counted

    @property
    def used(self) -> float:
        """The share of this month's allowance that's used, 0 to 1 and beyond (rounded, so that
        $0.04 of $0.05 is 80% and not a hair under)."""
        share = round(self.spend_usd / self.cap_usd, 6) if self.cap_usd else 0.0
        if self.data.get("limit_hit") == self.period:
            return max(1.0, share)
        return share

    def key(self) -> dict[str, Any] | None:
        """The inference key if there is one and it hasn't expired."""
        inference = self.data.get("inference")
        if not inference or not inference.get("key"):
            return None
        expires = inference.get("expires_at")
        if expires and datetime.fromisoformat(expires) <= self.now():
            return None
        return inference

    def switch(self, key: str) -> bool:
        return bool((self.data.get("switches") or {}).get(key, True))

    @callback
    def set_switch(self, key: str, on: bool) -> None:
        self.data.setdefault("switches", {"cloud": True, "ai": True})[key] = bool(on)
        self.changed()

    def cloud_state(self) -> str:
        """ai_off or cloud_off (a kill switch is off), ok, near_limit, over_limit, or not_linked (no
        usable key: never linked, or the relay has been out of reach for longer than a key lasts)."""
        if not self.switch("ai"):
            return "ai_off"
        if not self.switch("cloud"):
            return "cloud_off"
        if self.data.get("unlinked"):
            return "not_linked"
        if self.used >= STOP_AT:
            return "over_limit"
        if self.key() is None:
            return "not_linked"
        if self.used >= WARN_AT:
            return "near_limit"
        return "ok"

    @callback
    def add_spend(self, usd: float, path: str | None = None) -> None:
        self.month()["spend_usd"] = round(float(self.month()["spend_usd"]) + max(usd, 0.0), 6)
        if path := path or PATH.get():
            row = self._path_row(path)
            row["spend_usd"] = round(float(row["spend_usd"]) + max(usd, 0.0), 6)
        self.changed()

    def _path_row(self, path: str) -> dict[str, Any]:
        return self.month().setdefault("by_path", {}).setdefault(path, {"turns": 0, "spend_usd": 0.0})

    @callback
    def count_path(self, path: str) -> None:
        """One request on a path that isn't an agent turn (a tap on a suggested routine)."""
        self._path_row(path)["turns"] += 1
        self.changed()

    def paths(self, period: str | None = None) -> dict[str, dict[str, Any]]:
        """This month's turns and spend by where the requests came from."""
        month = self.data["months"].get(period or self.period) or {}
        return {k: dict(v) for k, v in (month.get("by_path") or {}).items()}

    @callback
    def limit_reached(self) -> None:
        self.data["limit_hit"] = self.period
        self.changed()

    @callback
    def count_turn(
        self, route: str, category: str, ok: bool, agent: str = "console", topic: str | None = None,
        path: str | None = None,
    ) -> None:
        if path := path or PATH.get():
            self._path_row(path)["turns"] += 1
        if topic:
            waiting = self._topics()["pending"].setdefault(self.period, {})
            waiting[topic] = waiting.get(topic, 0) + 1
        month = self.month()
        month["turns"] += 1
        month["ok" if ok else "failed"] += 1
        month["by_route"][route] = month["by_route"].get(route, 0) + 1
        month["by_category"][category] = month["by_category"].get(category, 0) + 1
        month["by_agent"][agent] = month["by_agent"].get(agent, 0) + 1
        self.changed()

    def summary(self, period: str | None = None) -> dict[str, Any]:
        """The monthly usage summary: exactly what is sent to the relay, and what the household sees."""
        period = period or self.period
        month = self.data["months"].get(period) or _empty_month()
        spend = self.spend_usd if period == self.period else float(month["spend_usd"])
        return {
            "period": period,
            "spend_usd": round(spend, 4),
            "turns": month["turns"],
            "ok": month["ok"],
            "failed": month["failed"],
            "by_route": dict(month["by_route"]),
            "by_category": dict(month["by_category"]),
            "by_agent": dict(month["by_agent"]),
        }

    # --- topics: what kind of thing each request was ------------------------------------------------

    def _topics(self) -> dict[str, Any]:
        kept = self.data.get("topics")
        if not isinstance(kept, dict) or "pending" not in kept:
            kept = self.data["topics"] = {"pending": {}, "sending": None}
        return kept

    @callback
    def topics_batch(self) -> dict[str, Any] | None:
        """The batch of topic counts to send to the relay, or None. A batch is frozen the first time it
        is asked for: it goes out unchanged until the relay says it was counted (topics_counted), so
        nothing is counted twice or lost. Requests made meanwhile wait for the next batch."""
        kept = self._topics()
        if kept.get("sending") is None and any(kept["pending"].values()):
            kept["sending"] = {"batch": uuid.uuid4().hex, "counts": kept["pending"]}
            kept["pending"] = {}
            self.changed()
        return kept.get("sending")

    @callback
    def topics_counted(self, batch: str) -> None:
        kept = self._topics()
        if kept.get("sending") and kept["sending"].get("batch") == batch:
            kept["sending"] = None
            self.changed()

    def topics_waiting(self) -> dict[str, dict[str, int]]:
        """Every topic count on this box that the relay hasn't confirmed, by month: what the household
        is shown on the Console page."""
        kept = self._topics()
        out: dict[str, dict[str, int]] = {}
        for counts in (kept["pending"], (kept.get("sending") or {}).get("counts") or {}):
            for period, topics in counts.items():
                month = out.setdefault(period, {})
                for topic, n in topics.items():
                    month[topic] = month.get(topic, 0) + n
        return out

    # --- what the relay hands over ----------------------------------------------------------------

    @callback
    def apply_relay_config(self, config: dict[str, Any]) -> None:
        if "inference" in config:
            self.data["inference"] = config["inference"]
        if config.get("plan"):
            self.data["plan"] = DEFAULT_PLAN | config["plan"]
        if config.get("spend"):
            self.data["relay_spend"] = config["spend"]
        if isinstance(config.get("site"), str) and config["site"].startswith("https://"):
            self.data["site"] = config["site"].rstrip("/")
        if isinstance(config.get("topics_applied"), str):
            self.topics_counted(config["topics_applied"])
        # The relay knows what OpenRouter has counted: it says whether the month's allowance is spent.
        self.data["limit_hit"] = self.period if config.get("over") else None
        self.data["linked_at"] = self.now().isoformat()
        self.changed()
