"""Sensoren der Vaultwarden-Integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import VaultwardenCoordinator, VaultwardenData
from .entity import VaultwardenEntity


@dataclass(frozen=True, kw_only=True)
class VaultwardenSensorDescription(SensorEntityDescription):
    """Sensor-Beschreibung mit Zugriff auf die Coordinator-Daten."""

    value_fn: Callable[[VaultwardenData], Any]
    attributes_fn: Callable[[VaultwardenData], dict[str, Any]] | None = None
    requires_admin: bool = True


def _stat(name: str) -> Callable[[VaultwardenData], Any]:
    def _value(data: VaultwardenData) -> Any:
        return getattr(data.stats, name) if data.stats else None

    return _value


SENSORS: tuple[VaultwardenSensorDescription, ...] = (
    VaultwardenSensorDescription(
        key="benutzer_gesamt",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_stat("total"),
        attributes_fn=lambda data: {"benutzer": data.stats.users if data.stats else []},
    ),
    VaultwardenSensorDescription(
        key="benutzer_aktiviert",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_stat("enabled"),
    ),
    VaultwardenSensorDescription(
        key="benutzer_deaktiviert",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_stat("disabled"),
    ),
    VaultwardenSensorDescription(
        key="benutzer_zwei_faktor",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_stat("two_factor"),
    ),
    VaultwardenSensorDescription(
        key="benutzer_eingeladen",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_stat("invited"),
    ),
    VaultwardenSensorDescription(
        key="organisationen",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.org_count,
    ),
    VaultwardenSensorDescription(
        key="zuletzt_aktiv",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_stat("last_active"),
    ),
    VaultwardenSensorDescription(
        key="version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.versions.installed or data.version,
        requires_admin=False,
    ),
    VaultwardenSensorDescription(
        key="neueste_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.versions.latest,
    ),
    VaultwardenSensorDescription(
        key="server_zeit",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.server_time,
        requires_admin=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Sensoren anlegen – die Admin-Sensoren nur mit hinterlegtem Token."""
    coordinator: VaultwardenCoordinator = hass.data[DOMAIN][entry.entry_id]
    has_token = coordinator.client.has_admin_token

    async_add_entities(
        VaultwardenSensor(coordinator, entry, description)
        for description in SENSORS
        if has_token or not description.requires_admin
    )


class VaultwardenSensor(VaultwardenEntity, SensorEntity):
    """Ein einzelner Messwert."""

    entity_description: VaultwardenSensorDescription

    def __init__(
        self,
        coordinator: VaultwardenCoordinator,
        entry: ConfigEntry,
        description: VaultwardenSensorDescription,
    ) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description
        self._requires_admin = description.requires_admin

    @property
    def native_value(self) -> str | int | datetime | None:
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attributes_fn is None or self.coordinator.data is None:
            return None
        return self.entity_description.attributes_fn(self.coordinator.data)
