"""Erreichbarkeit der Vaultwarden-Instanz."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import VaultwardenCoordinator
from .entity import VaultwardenEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VaultwardenCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([VaultwardenOnlineSensor(coordinator, entry)])


class VaultwardenOnlineSensor(VaultwardenEntity, BinarySensorEntity):
    """
    Meldet, ob der Server antwortet.

    Der Sensor überschreibt ``available``: er darf gerade dann nicht
    „unavailable" werden, wenn der Server weg ist – das ist ja seine Aussage.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(
        self, coordinator: VaultwardenCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator, entry, "erreichbar")

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        return None if data is None else data.online

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        data = self.coordinator.data
        if data is None:
            return None
        return {
            "server_zeit": data.server_time.isoformat() if data.server_time else None,
            "admin_backend": data.admin_available,
        }
