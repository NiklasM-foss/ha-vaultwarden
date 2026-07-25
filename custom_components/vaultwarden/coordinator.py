"""
DataUpdateCoordinator der Vaultwarden-Integration.

Zwei Besonderheiten:

* Ein nicht erreichbarer Server ist hier ein gültiger Zustand und kein
  Update-Fehler. Sonst würde ausgerechnet der Erreichbarkeits-Sensor
  „unavailable" werden, sobald er gebraucht wird.
* Die Diagnose-Seite (Versionsvergleich) wird höchstens stündlich abgerufen,
  weil Vaultwarden dafür serverseitig GitHub und einen NTP-Server kontaktiert.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .api import (
    AdminDisabled,
    CannotConnect,
    InvalidAuth,
    RateLimited,
    UserStats,
    VaultwardenClient,
    VersionInfo,
)
from .const import (
    CONF_SCAN_INTERVAL_MINUTES,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DIAGNOSTICS_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class VaultwardenData:
    """Alles, was die Entities anzeigen."""

    online: bool = False
    version: str | None = None
    server_time: datetime | None = None
    stats: UserStats | None = None
    org_count: int | None = None
    versions: VersionInfo = field(default_factory=VersionInfo)
    admin_available: bool = False


class VaultwardenCoordinator(DataUpdateCoordinator[VaultwardenData]):
    """Fragt Vaultwarden in einem festen Intervall ab."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: VaultwardenClient,
    ) -> None:
        minutes = entry.options.get(
            CONF_SCAN_INTERVAL_MINUTES, DEFAULT_SCAN_INTERVAL_MINUTES
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=minutes),
        )
        self.client = client
        self._entry = entry
        self._versions = VersionInfo()
        self._versions_fetched: datetime | None = None

    async def _async_update_data(self) -> VaultwardenData:
        previous = self.data or VaultwardenData()
        data = VaultwardenData(versions=self._versions)

        try:
            data.version = await self.client.async_get_version()
            data.server_time = await self.client.async_get_server_time()
        except CannotConnect as err:
            # Offline ist ein Messwert, kein Fehler: der Binary-Sensor soll das
            # anzeigen können, statt selbst unavailable zu werden.
            _LOGGER.debug("Vaultwarden nicht erreichbar: %s", err)
            return VaultwardenData(
                online=False,
                version=previous.version,
                versions=self._versions,
                admin_available=previous.admin_available,
            )

        data.online = True

        if not self.client.has_admin_token:
            return data

        try:
            data.stats = await self.client.async_get_user_stats()
            data.org_count = await self.client.async_get_organization_count()
            data.admin_available = True

            if self._should_fetch_versions():
                self._versions = await self.client.async_get_version_info()
                self._versions_fetched = dt_util.utcnow()
                data.versions = self._versions
        except InvalidAuth as err:
            # Löst den Reauth-Dialog aus, statt die Integration still zu brechen.
            raise ConfigEntryAuthFailed(str(err)) from err
        except AdminDisabled as err:
            _LOGGER.warning(
                "Admin-Backend von %s ist nicht aktiviert: %s",
                self.client.base_url,
                err,
            )
            data.admin_available = False
        except RateLimited as err:
            _LOGGER.debug("Anmeldung wird ausgebremst: %s", err)
            data.stats = previous.stats
            data.org_count = previous.org_count
            data.admin_available = previous.admin_available
        except CannotConnect as err:
            _LOGGER.debug("Admin-Daten nicht abrufbar: %s", err)
            data.stats = previous.stats
            data.org_count = previous.org_count
            data.admin_available = previous.admin_available

        return data

    def _should_fetch_versions(self) -> bool:
        if self._versions_fetched is None:
            return True
        return dt_util.utcnow() - self._versions_fetched >= DIAGNOSTICS_INTERVAL

    @property
    def online(self) -> bool:
        return bool(self.data and self.data.online)
