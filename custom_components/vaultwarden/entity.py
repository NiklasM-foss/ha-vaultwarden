"""Gemeinsame Basis für alle Entities der Vaultwarden-Integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, CONF_URL
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULT_NAME, DOMAIN
from .coordinator import VaultwardenCoordinator


class VaultwardenEntity(CoordinatorEntity[VaultwardenCoordinator]):
    """Setzt Unique-ID, Geräteeintrag und Verfügbarkeit einheitlich."""

    _attr_has_entity_name = True

    # Entities, die nur mit Admin-Token Daten haben, setzen das auf True.
    _requires_admin = False

    def __init__(
        self,
        coordinator: VaultwardenCoordinator,
        entry: ConfigEntry,
        key: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data.get(CONF_NAME) or DEFAULT_NAME,
            manufacturer="dani-garcia",
            model="Vaultwarden",
            sw_version=(coordinator.data.version if coordinator.data else None),
            configuration_url=entry.data.get(CONF_URL),
        )

    @property
    def available(self) -> bool:
        """Bei offline Server nur die Sensoren zeigen, die dann noch stimmen."""
        if not super().available:
            return False
        data = self.coordinator.data
        if data is None or not data.online:
            return False
        if self._requires_admin and not data.admin_available:
            return False
        return True
