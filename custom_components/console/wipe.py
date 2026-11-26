"""The two ways to wipe, from the Console page. Each needs its words typed exactly.

1. Erase Console and Sunrise data: Console's store (the inference key, the plan, this month's counts,
   learned sentences, support mode) and Sunrise's data folder (its memory, its history, edited skills).
   The house's link to Console's relay is cut: the relay is refused until someone connects it again.
   Home Assistant itself, its devices, dashboards and automations are untouched.
2. Factory reset Home Assistant: everything in Home Assistant's configuration folder except the
   installed custom integrations and the backups folder. Home Assistant restarts as a new install.
   It can't be undone (a backup in the backups folder can be restored by hand afterwards).
"""

from __future__ import annotations

import logging
from pathlib import Path
import shutil

from homeassistant.const import EVENT_HOMEASSISTANT_CLOSE
from homeassistant.core import HomeAssistant

from .const import DOMAIN

WORDS_DATA = "erase my data"
WORDS_FACTORY = "factory reset"
KEPT_IN_FACTORY_RESET = ("custom_components", "backups")
SUNRISE_FOLDER = "sunrise"
_LOGGER = logging.getLogger(__name__)


class Refused(ValueError):
    """The words weren't typed, or the level isn't one of the two."""


def _typed(confirm: str, words: str) -> None:
    if (confirm or "").strip().lower() != words:
        raise Refused(f"Type “{words}” exactly to go ahead. Nothing was erased.")


async def erase_data(hass: HomeAssistant, confirm: str) -> dict:
    """Level 1: Console's and Sunrise's data, and the link to the relay."""
    _typed(confirm, WORDS_DATA)
    data = hass.data[DOMAIN]
    data.learned.stop()
    learned = len(data.data["learned"])
    await data.async_erase()
    data.data["unlinked"] = True
    data.changed()
    await data.async_save_now()

    sunrise = Path(hass.config.path(SUNRISE_FOLDER))
    had_sunrise = sunrise.is_dir()
    if had_sunrise:
        await hass.async_add_executor_job(shutil.rmtree, sunrise, True)
    for entry in hass.config_entries.async_entries("sunrise"):
        await hass.config_entries.async_reload(entry.entry_id)  # it starts again with its shipped skills
    await hass.services.async_call(
        "persistent_notification", "dismiss", {"notification_id": "console_support"}, blocking=False
    )
    _LOGGER.warning("Console: Console and Sunrise data were erased from the Console page")
    return {"ok": True, "erased": {"console_store": True, "learned_sentences": learned, "sunrise_data": had_sunrise}}


def _factory_wipe(config_dir: Path) -> list[str]:
    gone = []
    for item in config_dir.iterdir():
        if item.name in KEPT_IN_FACTORY_RESET:
            continue
        try:
            if item.is_dir() and not item.is_symlink():
                shutil.rmtree(item)
            else:
                item.unlink()
            gone.append(item.name)
        except OSError:
            _LOGGER.exception("Console: factory reset couldn't remove %s", item.name)
    return gone


async def factory_reset(hass: HomeAssistant, confirm: str) -> dict:
    """Level 2: restart Home Assistant and, as the very last thing it does before exiting, remove its
    configuration. It comes back as a new install."""
    _typed(confirm, WORDS_FACTORY)
    config_dir = Path(hass.config.config_dir)

    def at_close(_event) -> None:
        # Home Assistant has written everything it was going to: whatever is removed now stays removed.
        gone = _factory_wipe(config_dir)
        _LOGGER.warning("Console: factory reset removed %d items", len(gone))

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_CLOSE, at_close)
    _LOGGER.warning("Console: a factory reset was asked for on the Console page; restarting")
    hass.async_create_task(hass.services.async_call("homeassistant", "restart"))
    return {"ok": True, "restarting": True, "kept": list(KEPT_IN_FACTORY_RESET)}
