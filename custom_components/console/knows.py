"""What the house knows about you: everything Console, Sunrise and Home Assistant keep about the
people here, in one place, each thing editable or deletable.

- Sunrise's memory: the notes the agents keep (files under <config>/sunrise/memory).
- Presence: who Home Assistant thinks is home.
- Assist history: the last few voice requests Home Assistant keeps in memory for debugging.
- Learned sentences: the phrasings Console taught the local agent.
- The monthly usage summary: exactly what is sent to Console's relay.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .state import ConsoleData

AUTHOR = "user"
REASON = "edited on the Console page"


def sunrise_store(hass: HomeAssistant):
    for entry in hass.config_entries.async_entries("sunrise"):
        runtime = getattr(entry, "runtime_data", None)
        if runtime is not None and getattr(runtime, "store", None) is not None:
            return runtime.store
    return None


def _assist_runs(hass: HomeAssistant) -> int:
    """How many voice requests Home Assistant is holding in memory right now (it keeps the last few per
    assistant for its own debug view, and loses them on restart)."""
    data = hass.data.get("assist_pipeline")
    debug = getattr(data, "pipeline_debug", None)
    if not debug:
        return 0
    return sum(len(runs) for runs in debug.values())


def clear_assist_runs(hass: HomeAssistant) -> int:
    data = hass.data.get("assist_pipeline")
    debug = getattr(data, "pipeline_debug", None)
    if not debug:
        return 0
    cleared = sum(len(runs) for runs in debug.values())
    for runs in debug.values():
        runs.clear()
    return cleared


async def everything(hass: HomeAssistant, data: ConsoleData) -> dict[str, Any]:
    store = sunrise_store(hass)
    memory = await hass.async_add_executor_job(store.memory_list) if store else []
    presence = [
        {
            "entity_id": state.entity_id,
            "name": state.name,
            "state": state.state,
            "since": state.last_changed.isoformat(),
        }
        for state in hass.states.async_all("person")
    ]
    return {
        "sunrise": store is not None,
        "memory": memory,
        "presence": presence,
        "assist_runs": _assist_runs(hass),
        "learned": [
            {k: item.get(k) for k in ("id", "sentence", "names", "action", "learned_at", "uses")}
            for item in data.data["learned"]
        ],
        "usage": data.summary(),
    }


async def memory_read(hass: HomeAssistant, name: str) -> str | None:
    store = sunrise_store(hass)
    return await hass.async_add_executor_job(store.memory_read, name) if store else None


async def memory_write(hass: HomeAssistant, name: str, text: str) -> None:
    store = sunrise_store(hass)
    if store is None:
        raise ValueError("Sunrise isn't installed, so there's no memory to change.")
    await hass.async_add_executor_job(lambda: store.memory_write(name, text, author=AUTHOR, reason=REASON))


async def memory_delete(hass: HomeAssistant, name: str) -> None:
    store = sunrise_store(hass)
    if store is None:
        raise ValueError("Sunrise isn't installed, so there's no memory to change.")
    await hass.async_add_executor_job(lambda: store.memory_delete(name, author=AUTHOR, reason=REASON))
