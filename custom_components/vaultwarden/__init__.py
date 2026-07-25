"""
Einstiegspunkt der Vaultwarden-Integration.

Pro ConfigEntry wird eine eigene aiohttp-Session angelegt. Grund ist das
Session-Cookie des Admin-Backends: die geteilte HA-Session würde es global
mitschleppen, und ihr Standard-Cookie-Jar verwirft Cookies von Hosts, die nur
über eine IP-Adresse angesprochen werden. Genau das ist bei einer lokalen
Vaultwarden-Instanz aber der Normalfall.
"""

from __future__ import annotations

import logging

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_URL, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import VaultwardenClient
from .const import CONF_ADMIN_TOKEN, DOMAIN, PLATFORMS
from .coordinator import VaultwardenCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """ConfigEntry laden."""
    session = async_create_clientsession(
        hass,
        verify_ssl=entry.data.get(CONF_VERIFY_SSL, True),
        cookie_jar=aiohttp.CookieJar(unsafe=True),
    )
    client = VaultwardenClient(
        session,
        entry.data[CONF_URL],
        entry.data.get(CONF_ADMIN_TOKEN),
    )
    coordinator = VaultwardenCoordinator(hass, entry, client)

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """ConfigEntry entladen."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Neu laden, wenn Optionen geändert wurden."""
    await hass.config_entries.async_reload(entry.entry_id)
