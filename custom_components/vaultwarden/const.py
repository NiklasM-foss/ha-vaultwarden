"""Konstanten der Vaultwarden-Integration."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "vaultwarden"

CONF_ADMIN_TOKEN = "admin_token"
CONF_SCAN_INTERVAL_MINUTES = "scan_interval_minutes"

DEFAULT_NAME = "Vaultwarden"
DEFAULT_SCAN_INTERVAL_MINUTES = 5
MIN_SCAN_INTERVAL_MINUTES = 1
MAX_SCAN_INTERVAL_MINUTES = 1440

# Die Diagnose-Seite fragt serverseitig GitHub (neueste Release) und einen
# NTP-Server ab. Sie wird deshalb bewusst selten abgerufen, unabhängig davon,
# wie kurz das normale Abfrageintervall eingestellt ist.
DIAGNOSTICS_INTERVAL = timedelta(hours=1)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.UPDATE,
]

RELEASE_URL = "https://github.com/dani-garcia/vaultwarden/releases"
WEB_RELEASE_URL = "https://github.com/dani-garcia/bw_web_builds/releases"
