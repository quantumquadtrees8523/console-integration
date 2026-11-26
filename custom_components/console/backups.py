"""Backups and the recovery code.

Console doesn't store backups anywhere of its own. It uses Home Assistant's backups, which can be
copied off the box (Home Assistant Cloud, a network drive, and so on, under Settings → System →
Backups), and makes sure every one of them is encrypted with a key only the household holds: the
recovery code. The code is made on this box. Console's relay never keeps it: it isn't in any request
the box sends, and the relay stores nothing it carries. A backup can be restored on a new Home
Assistant with the file and the recovery code alone.
"""

from __future__ import annotations

from datetime import datetime
import secrets
from typing import Any

from homeassistant.core import HomeAssistant

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I: it gets typed from paper
LOCAL = "backup.local"


class Unavailable(ValueError):
    """Home Assistant's backups aren't loaded."""


def new_code() -> str:
    """A recovery code: seven groups of four, about 140 bits."""
    return "-".join("".join(secrets.choice(ALPHABET) for _ in range(4)) for _ in range(7))


def _manager(hass: HomeAssistant):
    from homeassistant.components.backup.const import DATA_MANAGER  # noqa: PLC0415

    manager = hass.data.get(DATA_MANAGER)
    if manager is None:
        raise Unavailable("Home Assistant's backups aren't set up on this box.")
    return manager


def status(hass: HomeAssistant) -> dict[str, Any]:
    try:
        manager = _manager(hass)
    except Unavailable:
        return {"available": False}
    config = manager.config.data
    last = config.last_completed_automatic_backup
    return {
        "available": True,
        "encrypted": bool(config.create_backup.password),
        "automatic": bool(config.automatic_backups_configured),
        "copies_go_to": list(config.create_backup.agent_ids) or [LOCAL],
        "last_automatic": last.isoformat() if last else None,
    }


async def recovery_code(hass: HomeAssistant) -> dict[str, Any]:
    """The household's recovery code. If Home Assistant's backups already have an encryption key, that
    is the code; otherwise one is made here and set as the key for every backup from now on."""
    manager = _manager(hass)
    existing = manager.config.data.create_backup.password
    if existing:
        return {"code": existing, "created": False}
    code = new_code()
    manager.config.update(create_backup={"password": code})
    await _write_now(manager)
    return {"code": code, "created": True}


async def _write_now(manager) -> None:
    """Home Assistant saves its backup settings a little after they change. A backup started in that
    gap wouldn't carry the new key, so the settings are written to disk at once."""
    try:
        store = manager.store
        await store._store.async_save(store._data_to_save())  # noqa: SLF001 (no public way to flush it)
    except Exception:  # noqa: BLE001 (it is saved a moment later either way)
        pass


async def backup_now(hass: HomeAssistant) -> dict[str, Any]:
    """An encrypted backup now, to the places the household chose (this box only, if they chose none)."""
    manager = _manager(hass)
    code = (await recovery_code(hass))["code"]
    where = list(manager.config.data.create_backup.agent_ids) or [LOCAL]
    name = f"Console backup {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    started = await manager.async_create_backup(
        agent_ids=where,
        include_addons=None,
        include_all_addons=False,
        include_database=True,
        include_folders=None,
        include_homeassistant=True,
        name=name,
        password=code,
    )
    return {"ok": True, "name": name, "job": started.backup_job_id, "copies_go_to": where}
