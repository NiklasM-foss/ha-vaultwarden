"""
Update-Entities für Server und Web-Vault.

Installiert werden kann aus Home Assistant heraus nichts, die Entities zeigen
nur an, ob eine neuere Version verfügbar ist. Die Daten stammen aus der
Diagnose-Seite des Admin-Backends, ohne Admin-Token gibt es sie nicht.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.update import (
    UpdateEntity,
    UpdateEntityDescription,
    UpdateEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, RELEASE_URL, WEB_RELEASE_URL
from .coordinator import VaultwardenCoordinator, VaultwardenData
from .entity import VaultwardenEntity


@dataclass(frozen=True, kw_only=True)
class VaultwardenUpdateDescription(UpdateEntityDescription):
    """Beschreibt eine der beiden Update-Entities."""

    installed_fn: Callable[[VaultwardenData], str | None]
    latest_fn: Callable[[VaultwardenData], str | None]
    releases_url: str


UPDATES: tuple[VaultwardenUpdateDescription, ...] = (
    VaultwardenUpdateDescription(
        key="server",
        installed_fn=lambda data: data.versions.installed or data.version,
        latest_fn=lambda data: data.versions.latest,
        releases_url=RELEASE_URL,
    ),
    VaultwardenUpdateDescription(
        key="web_vault",
        installed_fn=lambda data: data.versions.web_installed,
        latest_fn=lambda data: data.versions.web_latest,
        releases_url=WEB_RELEASE_URL,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VaultwardenCoordinator = hass.data[DOMAIN][entry.entry_id]
    if not coordinator.client.has_admin_token:
        return

    async_add_entities(
        VaultwardenUpdate(coordinator, entry, description) for description in UPDATES
    )


class VaultwardenUpdate(VaultwardenEntity, UpdateEntity):
    """Versionsvergleich als Update-Entity."""

    entity_description: VaultwardenUpdateDescription
    _attr_supported_features = UpdateEntityFeature(0)
    _requires_admin = True

    def __init__(
        self,
        coordinator: VaultwardenCoordinator,
        entry: ConfigEntry,
        description: VaultwardenUpdateDescription,
    ) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def installed_version(self) -> str | None:
        if self.coordinator.data is None:
            return None
        return self.entity_description.installed_fn(self.coordinator.data)

    @property
    def latest_version(self) -> str | None:
        if self.coordinator.data is None:
            return None
        latest = self.entity_description.latest_fn(self.coordinator.data)
        # Ist die neueste Version unbekannt (kein Internetzugang auf dem
        # Server), lieber die installierte melden als fälschlich ein Update.
        return latest or self.installed_version

    @property
    def release_url(self) -> str | None:
        return self.entity_description.releases_url
