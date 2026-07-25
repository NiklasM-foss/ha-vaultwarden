"""Diagnosedaten für den Fehlerbericht-Download in Home Assistant."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_ADMIN_TOKEN, DOMAIN
from .coordinator import VaultwardenCoordinator

# Admin-Token und Mailadressen der Benutzer gehören in keinen Fehlerbericht.
TO_REDACT = {CONF_ADMIN_TOKEN, "email", "benutzer"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator: VaultwardenCoordinator = hass.data[DOMAIN][entry.entry_id]
    data = coordinator.data

    payload: dict[str, Any] = {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "online": bool(data and data.online),
        "admin_available": bool(data and data.admin_available),
        "version": data.version if data else None,
        "versions": asdict(data.versions) if data else None,
        "org_count": data.org_count if data else None,
    }

    if data and data.stats:
        stats = asdict(data.stats)
        stats.pop("users", None)
        stats["last_active"] = (
            data.stats.last_active.isoformat() if data.stats.last_active else None
        )
        payload["stats"] = stats

    return payload
