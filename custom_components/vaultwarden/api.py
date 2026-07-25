"""
HTTP-Client für Vaultwarden.

Vaultwarden hat keine echte Monitoring-API, deshalb kombiniert der Client drei
Quellen:

* ``/api/version`` und ``/api/alive`` sind ohne Anmeldung erreichbar und liefern
  Version und Erreichbarkeit (``/api/alive`` prüft serverseitig auch die DB).
* ``/admin/users`` liefert echtes JSON, braucht aber das Admin-Backend.
* Version-Vergleich und Organisationen gibt es nur als HTML-Seite. Daraus werden
  gezielt einzelne Felder gelesen (Element-IDs bzw. Button-Marker, die
  Vaultwarden für sein eigenes JavaScript vergibt und daher stabiler sind als
  die Tabellenstruktur). Schlägt das Parsen fehl, bleibt der Wert leer, statt
  die ganze Abfrage scheitern zu lassen.

Die Anmeldung am Admin-Backend erfolgt per ``POST /admin`` mit dem Admin-Token
als Formularfeld. Vaultwarden antwortet mit einem JWT im Cookie ``VW_ADMIN``,
einen Header- oder Bearer-Zugang gibt es nicht. Das Cookie läuft ab
(``ADMIN_SESSION_LIFETIME``, Standard 20 Minuten), deshalb meldet sich der
Client bei einer 401 automatisch einmal neu an.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=20)
# Die Diagnose-Seite wartet auf GitHub und NTP, die darf länger brauchen.
DIAGNOSTICS_TIMEOUT = aiohttp.ClientTimeout(total=45)

# <span id="server-installed">1.34.3</span>
_RE_SPAN_ID = "id=\"{}\"[^>]*>([^<]*)<"
_RE_ORG_ROW = re.compile(r"vw-delete-organization")
_RE_DATETIME = re.compile(r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})(?:\.\d+)?\s*(.*)$")
_RE_UTC_OFFSET = re.compile(r"^([+-])(\d{2}):?(\d{2})$")
_RE_VERSION = re.compile(r"^\d")

# Vaultwarden schreibt "-" in die Diagnose, wenn es die neueste Version nicht
# ermitteln konnte (kein Internetzugang, GitHub-Rate-Limit).
_EMPTY_VALUES = {"", "-", "unknown", "Unknown"}


class VaultwardenError(Exception):
    """Basisfehler dieser Integration."""


class CannotConnect(VaultwardenError):
    """Server nicht erreichbar oder antwortet unerwartet."""


class InvalidAuth(VaultwardenError):
    """Admin-Token wird abgelehnt."""


class RateLimited(VaultwardenError):
    """Vaultwarden bremst die Anmeldung am Admin-Backend aus."""


class AdminDisabled(VaultwardenError):
    """Das Admin-Backend ist auf dem Server nicht aktiviert."""


@dataclass(slots=True)
class UserStats:
    """Aggregierte Zahlen aus ``/admin/users``."""

    total: int = 0
    enabled: int = 0
    disabled: int = 0
    invited: int = 0
    two_factor: int = 0
    last_active: datetime | None = None
    users: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class VersionInfo:
    """Versionsstand aus ``/admin/diagnostics``."""

    installed: str | None = None
    latest: str | None = None
    web_installed: str | None = None
    web_latest: str | None = None


def _clean(value: str | None) -> str | None:
    """Leerwerte und Vaultwardens Platzhalter zu None normalisieren."""
    if value is None:
        return None
    value = value.strip()
    return None if value in _EMPTY_VALUES else value


def parse_server_datetime(value: str | None) -> datetime | None:
    """
    Zeitstempel des Admin-Backends in ein aware datetime wandeln.

    Das Backend formatiert als ``%Y-%m-%d %H:%M:%S %Z`` in der Zeitzone des
    Servers. Steht dort eine Abkürzung wie ``CEST``, lässt sich daraus keine
    eindeutige Zone ableiten. In dem Fall wird die Zeitzone von Home Assistant
    angenommen, was bei Server und HA im selben Haushalt zutrifft.
    """
    if not value:
        return None
    match = _RE_DATETIME.match(value.strip())
    if not match:
        return None

    stamp, zone = match.group(1), match.group(2).strip()
    try:
        naive = datetime.strptime(stamp.replace("T", " "), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None

    offset = _RE_UTC_OFFSET.match(zone)
    if offset:
        sign = -1 if offset.group(1) == "-" else 1
        delta = timedelta(hours=int(offset.group(2)), minutes=int(offset.group(3)))
        return naive.replace(tzinfo=timezone(sign * delta))
    if zone.upper() in {"UTC", "GMT", "Z"}:
        return naive.replace(tzinfo=timezone.utc)

    return naive.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)


class VaultwardenClient:
    """Kapselt alle Aufrufe gegen eine Vaultwarden-Instanz."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        url: str,
        admin_token: str | None = None,
    ) -> None:
        self._session = session
        self._base = url.rstrip("/")
        self._admin_token = admin_token or None
        self._authenticated = False

    @property
    def has_admin_token(self) -> bool:
        return self._admin_token is not None

    @property
    def base_url(self) -> str:
        return self._base

    # --- Öffentliche Endpunkte ------------------------------------------

    async def async_get_version(self) -> str | None:
        """Installierte Version über ``/api/version`` (ohne Anmeldung)."""
        try:
            async with self._session.get(
                f"{self._base}/api/version", timeout=REQUEST_TIMEOUT
            ) as resp:
                if resp.status != 200:
                    return None
                return _clean(await resp.json(content_type=None))
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CannotConnect(f"{self._base} nicht erreichbar: {err}") from err
        except ValueError:
            return None

    async def async_get_server_time(self) -> datetime | None:
        """
        ``/api/alive`` abfragen.

        Der Endpunkt öffnet serverseitig eine DB-Verbindung, eine Antwort
        bedeutet also auch, dass die Datenbank erreichbar ist.
        """
        try:
            async with self._session.get(
                f"{self._base}/api/alive", timeout=REQUEST_TIMEOUT
            ) as resp:
                if resp.status != 200:
                    raise CannotConnect(f"/api/alive antwortet mit HTTP {resp.status}")
                return parse_server_datetime(await resp.json(content_type=None))
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CannotConnect(f"{self._base} nicht erreichbar: {err}") from err
        except ValueError:
            return None

    # --- Admin-Backend ---------------------------------------------------

    async def async_login(self) -> None:
        """Am Admin-Backend anmelden und das Session-Cookie einsammeln."""
        if not self._admin_token:
            raise InvalidAuth("Kein Admin-Token hinterlegt")

        try:
            async with self._session.post(
                f"{self._base}/admin",
                data={"token": self._admin_token},
                allow_redirects=False,
                timeout=REQUEST_TIMEOUT,
            ) as resp:
                if resp.status in (401, 403):
                    raise InvalidAuth("Admin-Token wurde abgelehnt")
                if resp.status == 429:
                    raise RateLimited("Zu viele Anmeldeversuche am Admin-Backend")
                if resp.status == 404:
                    raise AdminDisabled("Admin-Backend ist nicht aktiviert")
                if resp.status not in (200, 301, 302, 303, 307, 308):
                    raise CannotConnect(f"Anmeldung antwortet mit HTTP {resp.status}")
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CannotConnect(f"Anmeldung fehlgeschlagen: {err}") from err

        # Ohne Cookie im Jar bringt jede Folgeanfrage nur wieder die Loginseite.
        if not self._has_admin_cookie():
            raise InvalidAuth("Kein VW_ADMIN-Cookie erhalten")

        self._authenticated = True

    def _has_admin_cookie(self) -> bool:
        return any(cookie.key == "VW_ADMIN" for cookie in self._session.cookie_jar)

    async def _async_admin_request(
        self, path: str, timeout: aiohttp.ClientTimeout = REQUEST_TIMEOUT
    ) -> str:
        """GET auf das Admin-Backend, bei abgelaufener Session einmal neu anmelden."""
        for attempt in (1, 2):
            if not self._authenticated:
                await self.async_login()

            try:
                async with self._session.get(
                    f"{self._base}{path}", allow_redirects=False, timeout=timeout
                ) as resp:
                    # 303 landet auf der Loginseite, zählt also als abgelaufen.
                    if resp.status in (401, 403) or 300 <= resp.status < 400:
                        self._authenticated = False
                        if attempt == 2:
                            raise InvalidAuth("Admin-Session konnte nicht erneuert werden")
                        continue
                    if resp.status == 404:
                        raise AdminDisabled(f"{path} nicht vorhanden")
                    if resp.status != 200:
                        raise CannotConnect(f"{path} antwortet mit HTTP {resp.status}")
                    return await resp.text()
            except (aiohttp.ClientError, TimeoutError) as err:
                raise CannotConnect(f"{path} nicht abrufbar: {err}") from err

        raise InvalidAuth("Admin-Session konnte nicht erneuert werden")

    async def async_get_user_stats(self) -> UserStats:
        """Benutzerliste auswerten (nur Kennzahlen, keine Schlüsselfelder)."""
        raw = await self._async_admin_request("/admin/users")
        try:
            users = json.loads(raw)
        except ValueError as err:
            raise CannotConnect(f"Benutzerliste ist kein JSON: {err}") from err
        if not isinstance(users, list):
            raise CannotConnect("Benutzerliste hat ein unerwartetes Format")

        stats = UserStats(total=len(users))
        for user in users:
            if not isinstance(user, dict):
                continue
            enabled = bool(user.get("userEnabled", True))
            invited = user.get("_status") == 1
            two_factor = bool(user.get("twoFactorEnabled"))
            last_active = parse_server_datetime(user.get("lastActive"))

            stats.enabled += 1 if enabled else 0
            stats.disabled += 0 if enabled else 1
            stats.invited += 1 if invited else 0
            stats.two_factor += 1 if two_factor else 0
            if last_active and (stats.last_active is None or last_active > stats.last_active):
                stats.last_active = last_active

            # Bewusst nur unkritische Felder: die Rohantwort enthält auch
            # Schlüsselmaterial (key, privateKey, securityStamp), das nichts in
            # Home Assistant zu suchen hat.
            stats.users.append(
                {
                    "name": user.get("name"),
                    "email": user.get("email"),
                    "aktiviert": enabled,
                    "eingeladen": invited,
                    "zwei_faktor": two_factor,
                    "email_bestaetigt": bool(user.get("emailVerified")),
                    "zuletzt_aktiv": last_active.isoformat() if last_active else None,
                }
            )

        stats.users.sort(key=lambda item: (item["email"] or "").lower())
        return stats

    async def async_get_organization_count(self) -> int | None:
        """
        Anzahl Organisationen zählen.

        Vaultwarden bietet dafür kein JSON, die Übersicht ist reines HTML. Gezählt
        werden die Lösch-Buttons, die pro Organisation genau einmal gerendert
        werden. Ändert sich das Template, liefert die Methode None statt einer
        erfundenen Zahl.
        """
        try:
            html = await self._async_admin_request("/admin/organizations/overview")
        except AdminDisabled:
            return None
        if "vw-delete-organization" not in html:
            # Entweder keine Organisationen oder Template geändert – beides ist
            # ohne weiteren Anker nicht unterscheidbar.
            return 0 if "<tbody>" in html else None
        return len(_RE_ORG_ROW.findall(html))

    async def async_get_version_info(self) -> VersionInfo:
        """Installierte und neueste Version aus der Diagnose-Seite lesen."""
        html = await self._async_admin_request(
            "/admin/diagnostics", timeout=DIAGNOSTICS_TIMEOUT
        )

        def span(element_id: str) -> str | None:
            match = re.search(_RE_SPAN_ID.format(re.escape(element_id)), html)
            if not match:
                return None
            value = _clean(match.group(1))
            # "Web Vault is disabled" o.ä. sind keine Versionen.
            if value and not _RE_VERSION.match(value):
                return None
            return value

        return VersionInfo(
            installed=span("server-installed"),
            latest=span("server-latest"),
            web_installed=span("web-installed"),
            web_latest=span("web-latest"),
        )
